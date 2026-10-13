"""Durable local ingestion journal. Graph contents live separately in Neo4j."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import re
import sqlite3
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise ValueError('Invalid local graph ID')
    return value


class GraphStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS graphs (
                    id TEXT PRIMARY KEY, name TEXT, description TEXT,
                    ontology TEXT NOT NULL DEFAULT '{}', state TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY, graph_id TEXT NOT NULL REFERENCES graphs(id) ON DELETE CASCADE,
                    operation TEXT, metadata TEXT, state TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL, UNIQUE(graph_id, operation));
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY, graph_id TEXT NOT NULL REFERENCES graphs(id) ON DELETE CASCADE,
                    batch_id TEXT REFERENCES batches(id) ON DELETE CASCADE,
                    sequence_index INTEGER, payload TEXT NOT NULL,
                    state TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS episode_queue ON episodes(state, created_at);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def check_setting(self, key, value):
        with self.connection(write=True) as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            if row and row['value'] != value:
                raise ValueError(f'Local graph {key} differs from the stored configuration. Use a new data directory/database.')
            db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (key, value))

    @staticmethod
    def _graph(db, graph_id, writable=False):
        row = db.execute('SELECT * FROM graphs WHERE id=?', (graph_id,)).fetchone()
        if row is None:
            raise LookupError(f'Local graph not found: {graph_id}')
        result = dict(row)
        result['ontology'] = json.loads(result['ontology'])
        if writable and result['state'] != 'active':
            raise RuntimeError(f"Local graph is {result['state']}; rebuild or finish deleting it before writing.")
        return result

    def create_graph(self, graph_id, name, description):
        identifier(graph_id)
        with self.connection(write=True) as db:
            db.execute('INSERT OR IGNORE INTO graphs(id,name,description,created_at) VALUES (?,?,?,?)',
                       (graph_id, name, description, now()))
            return self._graph(db, graph_id)

    def graph(self, graph_id):
        with self.connection() as db:
            return self._graph(db, graph_id)

    def set_ontology(self, graph_id, ontology):
        with self.connection(write=True) as db:
            self._graph(db, graph_id, writable=True)
            if db.execute('SELECT 1 FROM episodes WHERE graph_id=? LIMIT 1', (graph_id,)).fetchone():
                raise RuntimeError('Set ontology before adding graph data')
            db.execute('UPDATE graphs SET ontology=? WHERE id=?', (json.dumps(ontology), graph_id))

    def reserve_delete(self, graph_id):
        with self.connection(write=True) as db:
            self._graph(db, graph_id)
            if db.execute("SELECT 1 FROM episodes WHERE graph_id=? AND state IN ('queued','running')", (graph_id,)).fetchone():
                raise RuntimeError('Local graph has active ingestion; wait for it to finish before deleting.')
            db.execute("UPDATE graphs SET state='deleting' WHERE id=?", (graph_id,))

    def delete_graph(self, graph_id):
        with self.connection(write=True) as db:
            graph = self._graph(db, graph_id)
            if graph['state'] != 'deleting':
                raise RuntimeError('Graph deletion must be reserved first')
            db.execute('DELETE FROM graphs WHERE id=?', (graph_id,))

    def create_batch(self, metadata):
        graph_id = metadata.get('graph_id')
        operation = metadata.get('mirofish_operation_id')
        with self.connection(write=True) as db:
            self._graph(db, graph_id, writable=True)
            row = db.execute('SELECT id FROM batches WHERE graph_id=? AND operation=?', (graph_id, operation)).fetchone()
            bid = row['id'] if row else 'local_batch_' + uuid.uuid4().hex
            if not row:
                db.execute('INSERT INTO batches(id,graph_id,operation,metadata,created_at) VALUES (?,?,?,?,?)',
                           (bid, graph_id, operation, json.dumps(metadata), now()))
        return self.batch(bid)

    def batch(self, batch_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
            if row is None:
                raise LookupError(f'Local batch not found: {batch_id}')
            counts = dict(db.execute('SELECT state,COUNT(*) FROM episodes WHERE batch_id=? GROUP BY state', (batch_id,)).fetchall())
        total = sum(counts.values())
        succeeded = counts.get('succeeded', 0)
        status = row['state']
        if status != 'draft':
            if counts.get('failed') or counts.get('canceled'):
                status = 'failed'
            elif total and succeeded == total:
                status = 'succeeded'
            else:
                status = 'processing'
        return {'batch_id': batch_id, 'status': status, 'metadata': json.loads(row['metadata']),
                'created_at': row['created_at'], 'progress': {'total_items': total,
                'succeeded_items': succeeded, 'failed_items': counts.get('failed', 0),
                'percent_complete': 100 * succeeded / total if total else 0}}

    def batches(self):
        with self.connection() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM batches ORDER BY created_at,id')]
        return [self.batch(bid) for bid in ids]

    @staticmethod
    def _episode(row):
        if row is None:
            raise LookupError('Local episode not found')
        return {**json.loads(row['payload']), 'uuid': row['id'], 'episode_uuid': row['id'],
                'source_uuid': row['id'], 'graph_id': row['graph_id'], 'batch_id': row['batch_id'],
                'sequence_index': row['sequence_index'], 'status': row['state'], 'error': row['error'],
                'processed': row['state'] == 'succeeded'}

    def episode(self, episode_id):
        with self.connection() as db:
            return self._episode(db.execute('SELECT * FROM episodes WHERE id=?', (episode_id,)).fetchone())

    def episodes(self, *, graph_id=None, batch_id=None):
        with self.connection() as db:
            if graph_id is not None:
                self._graph(db, graph_id)
                rows = db.execute('SELECT * FROM episodes WHERE graph_id=? ORDER BY created_at,id', (graph_id,))
            else:
                rows = db.execute('SELECT * FROM episodes WHERE batch_id=? ORDER BY sequence_index,id', (batch_id,))
            return [self._episode(row) for row in rows]

    def add_items(self, batch_id, items):
        with self.connection(write=True) as db:
            batch = db.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
            if batch is None:
                raise LookupError('Local batch not found')
            self._graph(db, batch['graph_id'], writable=True)
            if batch['state'] != 'draft':
                raise RuntimeError('Cannot add items to a started batch')
            offset = db.execute('SELECT COUNT(*) FROM episodes WHERE batch_id=?', (batch_id,)).fetchone()[0]
            ids = []
            for index, item in enumerate(items, offset):
                if item.get('graph_id') != batch['graph_id']:
                    raise ValueError('Batch item graph does not match batch graph')
                if not isinstance(item.get('data'), str) or not item['data'].strip():
                    raise ValueError('Episode data must be nonempty text')
                eid = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{batch_id}:{index}'))
                payload = {**item, 'created_at': item.get('created_at') or now()}
                db.execute('INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?)',
                           (eid, batch['graph_id'], batch_id, index, json.dumps(payload), 'draft', None, now()))
                ids.append(eid)
        return [self.episode(eid) for eid in ids]

    def process_batch(self, batch_id):
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
            if row is None:
                raise LookupError('Local batch not found')
            self._graph(db, row['graph_id'], writable=True)
            if row['state'] != 'draft':
                return
            if not db.execute('SELECT 1 FROM episodes WHERE batch_id=?', (batch_id,)).fetchone():
                raise ValueError('Cannot process an empty batch')
            db.execute("UPDATE episodes SET state='queued' WHERE batch_id=? AND state='draft'", (batch_id,))
            db.execute("UPDATE batches SET state='processing' WHERE id=?", (batch_id,))

    def add_episode(self, graph_id, kind, data, **kwargs):
        if kind not in {'text', 'json', 'message'} or not isinstance(data, str) or not data.strip():
            raise ValueError('Episode requires text data and a supported type')
        eid = str(uuid.uuid4())
        timestamp = kwargs.get('created_at') or now()
        payload = {**kwargs, 'type': kind, 'data': data, 'created_at': timestamp}
        with self.connection(write=True) as db:
            self._graph(db, graph_id, writable=True)
            db.execute('INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?)',
                       (eid, graph_id, None, None, json.dumps(payload), 'queued', None, now()))
        return self.episode(eid)

    def resume_batch(self, batch_id, *, operation_id, chunks=None):
        """Explicitly retry unfinished work, retaining every durable episode ID."""
        with self.connection(write=True) as db:
            batch = db.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
            if batch is None:
                raise LookupError('Local batch not found')
            if not operation_id or operation_id != batch['operation']:
                raise ValueError('Batch operation does not match the recovery request')
            graph = self._graph(db, batch['graph_id'])
            if graph['state'] not in {'active', 'failed'}:
                raise RuntimeError('Cannot resume a graph reserved for deletion')
            metadata = json.loads(batch['metadata'])
            count = db.execute('SELECT COUNT(*) FROM episodes WHERE batch_id=?', (batch_id,)).fetchone()[0]
            if chunks is not None:
                if not isinstance(chunks, list) or not chunks or any(not isinstance(c, str) or not c.strip() for c in chunks):
                    raise ValueError('Recovery chunks must be nonempty text')
                digest = hashlib.sha256('\0'.join(chunks).encode()).hexdigest()
                expected = hashlib.sha256(f"{batch['graph_id']}:{digest}".encode()).hexdigest()
                if expected != operation_id or len(chunks) != metadata.get('chunk_count'):
                    raise ValueError('Recovery chunks do not match the batch operation')
                rows = db.execute('SELECT * FROM episodes WHERE batch_id=? ORDER BY sequence_index', (batch_id,)).fetchall()
                if len(rows) > len(chunks) or any(row['sequence_index'] != i or json.loads(row['payload'])['data'] != chunks[i] for i, row in enumerate(rows)):
                    raise ValueError('Saved batch items do not match the original input')
                if count < len(chunks) and batch['state'] == 'draft':
                    for index in range(count, len(chunks)):
                        eid = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{batch_id}:{index}'))
                        payload = {'graph_id': batch['graph_id'], 'data': chunks[index], 'data_type': 'text',
                                   'source_description': 'MiroFish source document chunk', 'created_at': now()}
                        db.execute('INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?)',
                                   (eid, batch['graph_id'], batch_id, index, json.dumps(payload), 'draft', None, now()))
                    count = len(chunks)
            if not count or count != metadata.get('chunk_count'):
                raise ValueError('Batch item count does not match the original input')
            # Do not unlock unrelated failed ingestion or race a running worker.
            if db.execute("SELECT 1 FROM episodes WHERE graph_id=? AND (state='running' OR (batch_id IS NOT ? AND state IN ('failed','canceled'))) LIMIT 1",
                          (batch['graph_id'], batch_id)).fetchone():
                raise RuntimeError('Graph has other unfinished ingestion; wait or recover that operation first')
            db.execute("UPDATE episodes SET state='queued',error=NULL WHERE batch_id=? AND state IN ('failed','canceled','draft')", (batch_id,))
            db.execute("UPDATE graphs SET state='active' WHERE id=?", (batch['graph_id'],))
            db.execute("UPDATE batches SET state='processing' WHERE id=?", (batch_id,))
        return self.batch(batch_id)

    def resume_simulation(self, graph_id, simulation_id):
        """Retry one simulation's standalone episodes without replaying successes."""
        identifier(simulation_id)
        with self.connection(write=True) as db:
            graph = self._graph(db, graph_id)
            if graph['state'] not in {'active', 'failed'}:
                raise RuntimeError('Cannot resume a graph reserved for deletion')
            rows = db.execute('SELECT * FROM episodes WHERE graph_id=? ORDER BY created_at,id', (graph_id,)).fetchall()
            owned = []
            for row in rows:
                metadata = json.loads(row['payload']).get('metadata') or {}
                if (row['batch_id'] is None and metadata.get('source') == 'mirofish_simulation'
                        and metadata.get('simulation_id') == simulation_id):
                    owned.append(row)
                elif row['state'] in {'running', 'failed', 'canceled'}:
                    raise RuntimeError('Graph has other unfinished ingestion; recover that operation first')
            if not owned:
                raise ValueError('No saved ingestion belongs to this simulation')
            for row in owned:
                if row['state'] in {'failed', 'canceled'}:
                    db.execute("UPDATE episodes SET state='queued',error=NULL WHERE id=?", (row['id'],))
            db.execute("UPDATE graphs SET state='active' WHERE id=?", (graph_id,))
            return {'episode_uuids': [row['id'] for row in owned if row['state'] != 'succeeded'],
                    'total': len(owned), 'succeeded': sum(row['state'] == 'succeeded' for row in owned)}

    def claim_next(self):
        with self.connection(write=True) as db:
            row = db.execute("SELECT e.* FROM episodes e JOIN graphs g ON g.id=e.graph_id WHERE e.state='queued' AND g.state='active' ORDER BY e.created_at,e.sequence_index,e.id LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE episodes SET state='running' WHERE id=?", (row['id'],))
            return self._episode(row)

    def finish(self, episode_id, error=None):
        with self.connection(write=True) as db:
            row = db.execute('SELECT * FROM episodes WHERE id=?', (episode_id,)).fetchone()
            if row is None or row['state'] != 'running':
                raise RuntimeError('Only a running episode can finish')
            db.execute('UPDATE episodes SET state=?,error=? WHERE id=?',
                       ('failed' if error else 'succeeded', error, episode_id))
            if error:
                db.execute("UPDATE episodes SET state='canceled',error=? WHERE graph_id=? AND state IN ('queued','draft')",
                           ('Earlier ingestion failed; resume this operation. ' + error, row['graph_id']))
                db.execute("UPDATE graphs SET state='failed' WHERE id=?", (row['graph_id'],))

    def recover_interrupted(self):
        with self.connection() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM episodes WHERE state='running'")]
        for eid in ids:
            self.finish(eid, error='Ingestion interrupted. Resume to reconcile saved work and retry unfinished episodes.')

"""Authenticated, loopback-only API for the local graph platform."""

from contextlib import asynccontextmanager
import asyncio
import hmac
import logging

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from research_agents import graph_provider

from .runtime import GraphRuntime


class Request(BaseModel):
    operation: str
    params: dict = Field(default_factory=dict)


def paginate(rows, *, limit=100, cursor=None, key):
    offset = int(cursor or 0)
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError('Invalid pagination limit/cursor')
    end = offset + limit
    return {key: rows[offset:end], 'next_cursor': end if end < len(rows) else None}


def create_app(store, engine, token):
    if not token or len(token) < 20:
        raise ValueError('LOCAL_GRAPH_TOKEN must contain at least 20 characters')
    runtime = GraphRuntime(store, engine)

    @asynccontextmanager
    async def lifespan(app):
        # Do not expose readiness until the real database and local models are ready.
        await engine.initialize()
        await runtime.start()
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(title='My Own Researcher Graph Platform', lifespan=lifespan)

    @app.get('/health')
    async def health():
        worker_alive = runtime.task is not None and not runtime.task.done()
        status = 'failed'
        if worker_alive:
            try:
                async with asyncio.timeout(3):
                    await engine.health()
                status = 'ready'
            except Exception:
                status = 'unavailable'
        return {'service': 'My Own Researcher Graph Platform',
                'status': status, 'provider': 'graphiti',
                'storage': 'neo4j',
                'inference': getattr(getattr(engine, 'llm', None), 'provider', None) or graph_provider(),
                'search': 'local',
                'llm_calls': getattr(getattr(engine, 'llm', None), 'calls', 0)}

    @app.post('/v1/rpc')
    async def rpc(body: Request, x_research_token: str = Header(default='')):
        if not hmac.compare_digest(x_research_token, token):
            raise HTTPException(status_code=401, detail='Invalid local graph token')
        p = body.params
        op = body.operation
        try:
            if op == 'graph.create':
                return store.create_graph(p['graph_id'], p.get('name', ''), p.get('description', ''))
            if op == 'graph.get':
                return store.graph(p['graph_id'])
            if op == 'graph.delete':
                await engine.delete(p['graph_id'])
                return {'deleted': True}
            if op == 'graph.set_ontology':
                store.set_ontology(p['graph_id'], p['ontology'])
                return {'saved': True}
            if op == 'graph.add':
                return store.add_episode(p['graph_id'], p['type'], p['data'],
                                         **{k: v for k, v in p.items() if k not in {'graph_id', 'type', 'data'}})
            if op == 'simulation.resume':
                return store.resume_simulation(p['graph_id'], p['simulation_id'])
            if op == 'graph.search':
                return await engine.search(**p)
            if op == 'graph.page':
                return await engine.page(**p)
            if op == 'node.get':
                return await engine.node(p['uuid_'])
            if op == 'node.edges':
                return await engine.node_edges(p['node_uuid'])
            if op == 'episode.get':
                episode = store.episode(p['uuid_'])
                if episode['status'] in {'failed', 'canceled'}:
                    raise RuntimeError(episode['error'])
                return episode
            if op == 'episode.list':
                lastn = int(p.get('lastn', 50))
                if not 1 <= lastn <= 1000:
                    raise ValueError('lastn must be between 1 and 1000')
                return store.episodes(graph_id=p['graph_id'])[-lastn:][::-1]
            if op == 'batch.create':
                return store.create_batch(p['metadata'])
            if op == 'batch.add':
                return store.add_items(p['batch_id'], p['items'])
            if op == 'batch.process':
                store.process_batch(p['batch_id'])
                return store.batch(p['batch_id'])
            if op == 'batch.resume':
                return store.resume_batch(p['batch_id'], operation_id=p['operation_id'], chunks=p.get('chunks'))
            if op == 'batch.get':
                return store.batch(p['batch_id'])
            if op == 'batch.list':
                return paginate(store.batches(), key='batches', **p)
            if op == 'batch.list_items':
                store.batch(p['batch_id'])
                return paginate(store.episodes(batch_id=p['batch_id']), key='items',
                                limit=p.get('limit', 100), cursor=p.get('cursor'))
            raise ValueError('Unsupported local graph operation')
        except LookupError as error:
            return JSONResponse(status_code=404, content={'error': str(error)})
        except (ValueError, TypeError) as error:
            return JSONResponse(status_code=400, content={'error': str(error)})
        except RuntimeError as error:
            return JSONResponse(status_code=409, content={'error': str(error)})
        except Exception:
            logging.getLogger(__name__).exception('Local graph operation failed: %s', op)
            return JSONResponse(status_code=500, content={'error': 'Local graph operation failed. Check graph platform logs.'})

    return app

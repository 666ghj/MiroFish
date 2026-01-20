"""
Local graph builder

Builds a knowledge graph into Neo4j using cloud LLM extraction, and optionally
stores chunk embeddings into Qdrant.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import Config
from ..utils.logger import get_logger
from .text_processor import TextProcessor
from .local_graph_extractor import LocalGraphExtractor
from .local_graph_store import LocalEntity, LocalNeo4jGraphStore, LocalRelation
from .entity_type_normalizer import canonicalize_entity_type
from .local_vector_store import QdrantChunkStore

logger = get_logger("mirofish.local_graph_builder")


def _now_iso() -> str:
    return datetime.now().isoformat()


class LocalGraphBuilderService:
    def __init__(self, enable_deduplication: bool = True):
        """
        初始化本地图谱构建服务
        
        Args:
            enable_deduplication: 是否启用实体消歧。启用后会使用 LocalEntityResolver
                                   进行实体去重，可以识别不同名称但指向同一实体的情况。
                                   默认关闭以保持向后兼容。
        """
        self.store = LocalNeo4jGraphStore()
        self.extractor = LocalGraphExtractor()
        self.vector_store = None  # lazy init
        self.enable_disambiguation = enable_deduplication
        self._entity_resolver = None
        
        # 如果启用消歧，初始化实体解析器
        if enable_deduplication:
            from .local_entity_resolver import LocalEntityResolver
            self._entity_resolver = LocalEntityResolver(self.store)

    def _get_vector_store(self) -> Optional[QdrantChunkStore]:
        if Config.VECTOR_BACKEND != "qdrant":
            return None
        if self.vector_store is not None:
            return self.vector_store
        try:
            self.vector_store = QdrantChunkStore()
        except Exception as e:
            logger.warning(f"Qdrant init failed, vector features disabled: {e}")
            self.vector_store = None
        return self.vector_store

    def create_graph(self, project_id: str, name: str, ontology: Optional[Dict[str, Any]] = None) -> str:
        return self.store.create_graph(project_id=project_id, name=name, ontology=ontology)

    def delete_graph(self, graph_id: str):
        return self.store.delete_graph(graph_id)

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        return self.store.get_graph_data(graph_id)

    def build_graph_from_text(
        self,
        project_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        progress_callback: Optional[Callable[[str, float], None]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Returns: (graph_id, graph_data)
        """
        if progress_callback:
            progress_callback("创建本地图谱（Neo4j）...", 0.02)

        graph_id = self.create_graph(project_id=project_id, name=graph_name, ontology=ontology)

        chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
        total = max(len(chunks), 1)
        failed_extract_chunks = 0

        for idx, chunk in enumerate(chunks):
            ratio = idx / total
            if progress_callback:
                progress_callback(f"抽取实体/关系: {idx+1}/{len(chunks)}", 0.05 + ratio * 0.85)

            chunk_id = f"chunk_{uuid.uuid4().hex[:12]}"
            self.store.upsert_chunk(project_id=project_id, graph_id=graph_id, chunk_id=chunk_id, text=chunk)

            # Vector store is optional
            vector_store = self._get_vector_store()
            if vector_store is not None:
                try:
                    vector_store.add_chunk(
                        project_id=project_id,
                        graph_id=graph_id,
                        chunk_id=chunk_id,
                        text=chunk,
                        extra_payload={"type": "chunk"},
                    )
                except Exception as e:
                    logger.warning(f"Qdrant add_chunk failed, continue without vectors: {e}")

            try:
                extracted = self.extractor.extract(chunk, ontology=ontology)
            except Exception as e:
                failed_extract_chunks += 1
                logger.warning(f"Extractor failed for chunk {idx+1}/{len(chunks)}; skipping: {e}")
                continue
            entities_in_chunk = extracted.get("entities") or []
            relations_in_chunk = extracted.get("relations") or []

            # 处理实体：如果启用消歧，使用 LocalEntityResolver 进行去重
            entities: List[LocalEntity] = []
            uuid_by_key: Dict[str, str] = {}
            entities_to_update: List[tuple] = []  # (uuid, summary, source_types)
            
            if self.enable_disambiguation and self._entity_resolver:
                # 使用消歧器处理实体
                for ent in entities_in_chunk:
                    raw_type = ent.get("type", "")
                    canonical_type = canonicalize_entity_type(raw_type)
                    name = ent.get("name", "")
                    summary = ent.get("summary", "")
                    
                    if not name:
                        continue
                    
                    # 使用实体解析器进行消歧
                    resolved = self._entity_resolver.resolve(
                        graph_id=graph_id,
                        name=name,
                        entity_type=canonical_type,
                        summary=summary,
                        attributes=ent.get("attributes"),
                    )
                    
                    key = f"{canonical_type}:{name}".lower()
                    
                    if resolved.is_new:
                        # 创建新实体
                        entities.append(
                            LocalEntity(
                                project_id=project_id,
                                graph_id=graph_id,
                                name=resolved.name,
                                entity_type=canonical_type,
                                summary=summary,
                                attributes=ent.get("attributes") or {},
                                source_entity_types=[raw_type] if raw_type else [],
                                created_at=_now_iso(),
                            )
                        )
                        # UUID 会在 upsert 后更新
                    else:
                        # 复用已有实体的 UUID
                        uuid_by_key[key] = resolved.uuid
                        
                        # 如果需要更新摘要
                        if resolved.should_update_summary and summary:
                            entities_to_update.append((resolved.uuid, summary, [raw_type] if raw_type else []))
                        elif raw_type:
                            # 追加类型信息
                            entities_to_update.append((resolved.uuid, None, [raw_type]))
                        
                        logger.debug(f"消歧成功: '{name}' -> 已有实体 (score={resolved.match_score:.2f})")
                
                # 每个 chunk 后清空缓存（避免跨 chunk 缓存污染）
                self._entity_resolver.clear_cache()
            else:
                # 原有逻辑：不使用消歧
                for ent in entities_in_chunk:
                    raw_type = ent.get("type", "")
                    canonical_type = canonicalize_entity_type(raw_type)
                    entities.append(
                        LocalEntity(
                            project_id=project_id,
                            graph_id=graph_id,
                            name=ent.get("name", ""),
                            entity_type=canonical_type,
                            summary=ent.get("summary", ""),
                            attributes=ent.get("attributes") or {},
                            source_entity_types=[raw_type] if raw_type else [],
                            created_at=_now_iso(),
                        )
                    )
            
            # 批量创建/更新实体
            if entities:
                entity_uuids = self.store.upsert_entities(entities)
                self.store.link_mentions(chunk_id=chunk_id, entity_uuids=entity_uuids, graph_id=graph_id)
                
                # 更新 uuid_by_key 映射（新创建的实体）
                for ent in entities:
                    uuid_by_key[f"{ent.entity_type}:{ent.name}".lower()] = ent.uuid
            
            # 更新已有实体的摘要和类型
            for uuid_val, summary, source_types in entities_to_update:
                try:
                    self.store.update_entity_summary(
                        uuid=uuid_val,
                        summary=summary or "",
                        append_source_types=source_types,
                    )
                except Exception as e:
                    logger.warning(f"更新实体摘要失败: uuid={uuid_val}, error={e}")

            relations: List[LocalRelation] = []
            for rel in relations_in_chunk:
                s_type = canonicalize_entity_type(rel.get("source_type"))
                t_type = canonicalize_entity_type(rel.get("target_type"))
                s_key = f"{s_type}:{rel.get('source')}".lower()
                t_key = f"{t_type}:{rel.get('target')}".lower()
                source_uuid = uuid_by_key.get(s_key)
                target_uuid = uuid_by_key.get(t_key)
                if not source_uuid or not target_uuid:
                    continue
                relations.append(
                    LocalRelation(
                        project_id=project_id,
                        graph_id=graph_id,
                        source_uuid=source_uuid,
                        target_uuid=target_uuid,
                        relation_name=rel.get("relation", ""),
                        fact=rel.get("fact", ""),
                        attributes=rel.get("attributes") or {},
                        created_at=_now_iso(),
                    )
                )

            self.store.upsert_relations(relations)

        if progress_callback:
            progress_callback("读取图谱数据...", 0.95)

        graph_data = self.get_graph_data(graph_id)
        if failed_extract_chunks:
            graph_data["build_warnings"] = [
                f"Extractor failed for {failed_extract_chunks}/{len(chunks)} chunks; graph may be incomplete."
            ]
        if progress_callback:
            progress_callback("完成", 1.0)

        return graph_id, graph_data

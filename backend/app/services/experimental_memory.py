"""
Experimental Memory Service (Spike S1)
Implements a dual-layer memory approach: Core Memory + Archival Memory.
Inspired by Karpathy's LLM-Wiki and MemGPT.
"""

import os
import json
import time
import numpy as np
from typing import List, Dict, Any, Optional
from ..utils.embedding_client import EmbeddingClient
from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.experimental_memory')

class ExperimentalMemoryService:
    def __init__(self, simulation_id: str):
        self.simulation_id = simulation_id
        self.storage_path = os.path.join(Config.DATA_DIR, 'simulations', simulation_id, 'experimental_memory.json')
        self.core_memory_path = os.path.join(Config.DATA_DIR, 'simulations', simulation_id, 'core_memory.json')
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        
        self.embedder = self._get_embedder()
        self.memories = self._load_memories()
        self.core_memory = self._load_core_memory()

    def _get_embedder(self) -> Optional[EmbeddingClient]:
        embedder_config = Config.get_graph_search_embedder_config()
        base_url = embedder_config.get("base_url")
        model = embedder_config.get("model")
        if not base_url or not model:
            logger.warning("Embedding client not configured for experimental memory.")
            return None
        try:
            return EmbeddingClient(
                api_key=embedder_config.get("api_key") or "ollama",
                base_url=base_url,
                model=model
            )
        except Exception as e:
            logger.error(f"Failed to initialize embedding client: {e}")
            return None

    def _load_memories(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.storage_path):
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    def _save_memories(self):
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(self.memories, f, ensure_ascii=False, indent=2)

    def _load_core_memory(self) -> Dict[str, Any]:
        if os.path.exists(self.core_memory_path):
            with open(self.core_memory_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "persona": "Standard MiroFish Agent",
            "objectives": [],
            "key_events": []
        }

    def save_core_memory(self, core_data: Dict[str, Any]):
        self.core_memory.update(core_data)
        with open(self.core_memory_path, 'w', encoding='utf-8') as f:
            json.dump(self.core_memory, f, ensure_ascii=False, indent=2)

    def add_memories(self, activities: List[Dict[str, Any]]):
        """Add multiple episodes to archival memory in a batch to avoid I/O bottlenecks."""
        if not activities:
            return

        texts_to_embed = [item.get("text", "") for item in activities]
        embeddings = [None] * len(activities)

        if self.embedder:
            try:
                embeddings = self.embedder.embed_texts(texts_to_embed)
            except Exception as e:
                logger.error(f"Failed to batch embed memory: {e}")

        for item, embedding in zip(activities, embeddings):
            memory_entry = {
                "text": item.get("text", ""),
                "metadata": item.get("metadata", {}),
                "embedding": embedding,
                "timestamp": time.time()
            }
            self.memories.append(memory_entry)
            
        self._save_memories()

    def add_memory(self, text: str, metadata: Optional[Dict[str, Any]] = None):
        """Add a single episode to archival memory."""
        self.add_memories([{"text": text, "metadata": metadata or {}}])

    def retrieve(self, query: str, k: int = 5) -> Dict[str, Any]:
        """Retrieve context from both Core and Archival memory."""
        archival_results = self._retrieve_archival(query, k)
        
        return {
            "core_memory": self.core_memory,
            "archival_memory": archival_results
        }

    def _retrieve_archival(self, query: str, k: int) -> List[str]:
        if not self.memories:
            return []
        
        use_fallback = False
        if not self.embedder:
            use_fallback = True
        
        if not use_fallback:
            try:
                query_embedding = self.embedder.embed_texts([query])[0]
                
                # Compute cosine similarity
                scores = []
                for m in self.memories:
                    if m.get("embedding"):
                        sim = self._cosine_similarity(query_embedding, m["embedding"])
                        scores.append((sim, m["text"]))
                
                if not scores:
                    use_fallback = True
                else:
                    # Sort by similarity
                    scores.sort(key=lambda x: x[0], reverse=True)
                    return [s[1] for s in scores[:k]]
                    
            except Exception as e:
                logger.error(f"Error during vector retrieval: {e}. Falling back to keyword search.")
                use_fallback = True

        if use_fallback:
            # Fallback to simple keyword search
            logger.info("Using keyword search fallback for archival memory.")
            # Simple scoring based on word overlap or containment
            scored_results = []
            query_words = set(query.lower().split())
            for m in self.memories:
                text_lower = m["text"].lower()
                score = 0
                if query.lower() in text_lower:
                    score += 10
                for word in query_words:
                    if word in text_lower:
                        score += 1
                if score > 0:
                    scored_results.append((score, m["text"]))
            
            scored_results.sort(key=lambda x: x[0], reverse=True)
            return [s[1] for s in scored_results[:k]]
        
        return []

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        a = np.array(v1)
        b = np.array(v2)
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

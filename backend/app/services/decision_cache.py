"""
Decision Cache untuk MiroFish Simulation
Mengurangi LLM API calls dengan caching agent decisions
"""

import os
import json
import hashlib
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass
import threading
import logging

logger = logging.getLogger('mirofish.decision_cache')


@dataclass
class CachedDecision:
    """Cached LLM decision"""
    agent_id: int
    context_hash: str
    decision: Dict[str, Any]
    timestamp: datetime
    hit_count: int = 0
    
    def is_expired(self, ttl_hours: int = 24) -> bool:
        """Check if cache entry is expired"""
        age = datetime.now() - self.timestamp
        return age > timedelta(hours=ttl_hours)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "context_hash": self.context_hash,
            "decision": self.decision,
            "timestamp": self.timestamp.isoformat(),
            "hit_count": self.hit_count,
        }


class DecisionCache:
    """
    LLM Decision Cache untuk mengurangi API calls
    
    Strategy:
    - Cache berdasarkan agent_id + context hash
    - TTL: 24 jam default
    - Similar context = similar decision
    - Thread-safe singleton
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cache: Dict[str, CachedDecision] = {}
                    cls._instance._stats = {"hits": 0, "misses": 0}
                    cls._instance._ttl_hours = 24
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> 'DecisionCache':
        """Get singleton instance"""
        return cls()
    
    def _compute_context_hash(
        self,
        agent_id: int,
        context: Dict[str, Any]
    ) -> str:
        """
        Compute hash dari agent_id + relevant context
        
        Factors yang mempengaruhi decision:
        - Agent personality (fixed)
        - Visible posts (dynamic)
        - Time of day (dynamic)
        - Emotional state (dynamic)
        """
        hash_input = {
            "agent_id": agent_id,
            "personality_hash": self._hash_personality(context.get("personality", {})),
            "visible_posts_hash": self._hash_posts(context.get("visible_posts", [])),
            "hour": context.get("simulated_hour", 12),
            "day": context.get("simulated_day", 1),
        }
        
        hash_str = json.dumps(hash_input, sort_keys=True)
        return hashlib.md5(hash_str.encode()).hexdigest()
    
    def _hash_personality(self, personality: Dict[str, Any]) -> str:
        """Hash personality traits (relatively stable)"""
        if not personality:
            return "default"
        
        # Extract key personality traits
        traits = {
            k: str(v)[:50]  # Limit value length
            for k, v in personality.items()
            if k in ["activity_level", "sentiment_bias", "stance", "influence_weight", "role"]
        }
        return hashlib.md5(json.dumps(traits, sort_keys=True).encode()).hexdigest()
    
    def _hash_posts(self, posts: List[Dict[str, Any]]) -> str:
        """Hash visible posts (simplified - top 5 posts)"""
        if not posts:
            return "empty"
        
        # Simplified: only hash post IDs
        post_ids = []
        for p in posts[:5]:
            post_id = p.get("post_id", p.get("id", str(hash(str(p)))))
            post_ids.append(str(post_id))
        
        return hashlib.md5(",".join(sorted(post_ids)).encode()).hexdigest()
    
    def get(
        self,
        agent_id: int,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached decision if available and not expired
        
        Args:
            agent_id: Agent ID
            context: Context data (personality, visible_posts, etc.)
        
        Returns:
            Cached decision or None
        """
        context_hash = self._compute_context_hash(agent_id, context)
        cache_key = f"{agent_id}:{context_hash}"
        
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            
            if not cached.is_expired(self._ttl_hours):
                cached.hit_count += 1
                self._stats["hits"] += 1
                logger.debug(f"Cache HIT for agent {agent_id}")
                return cached.decision
            else:
                # Remove expired entry
                del self._cache[cache_key]
                logger.debug(f"Cache EXPIRED for agent {agent_id}")
        
        self._stats["misses"] += 1
        logger.debug(f"Cache MISS for agent {agent_id}")
        return None
    
    def set(
        self,
        agent_id: int,
        context: Dict[str, Any],
        decision: Dict[str, Any]
    ):
        """
        Cache a decision
        
        Args:
            agent_id: Agent ID
            context: Context data
            decision: Decision to cache
        """
        context_hash = self._compute_context_hash(agent_id, context)
        cache_key = f"{agent_id}:{context_hash}"
        
        self._cache[cache_key] = CachedDecision(
            agent_id=agent_id,
            context_hash=context_hash,
            decision=decision,
            timestamp=datetime.now(),
        )
        
        logger.debug(f"Cache SET for agent {agent_id}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0
        
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": f"{hit_rate:.1%}",
            "cache_size": len(self._cache),
        }
    
    def clear(self):
        """Clear all cache entries"""
        self._cache.clear()
        self._stats = {"hits": 0, "misses": 0}
        logger.info("Decision cache cleared")
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired entries
        
        Returns:
            Number of entries removed
        """
        expired_keys = [
            k for k, v in self._cache.items()
            if v.is_expired(self._ttl_hours)
        ]
        
        for k in expired_keys:
            del self._cache[k]
        
        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
        
        return len(expired_keys)
    
    def save_to_disk(self, simulation_id: str):
        """
        Save cache to disk for persistence
        
        Args:
            simulation_id: Simulation ID
        """
        try:
            from ..config import Config
        except ImportError:
            from config import Config
        
        cache_dir = os.path.join(Config.UPLOAD_FOLDER, 'simulations', simulation_id)
        os.makedirs(cache_dir, exist_ok=True)
        
        cache_file = os.path.join(cache_dir, "decision_cache.json")
        
        data = {
            "stats": self._stats,
            "ttl_hours": self._ttl_hours,
            "entries": [v.to_dict() for v in self._cache.values()],
        }
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Decision cache saved to {cache_file}")
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")
    
    def load_from_disk(self, simulation_id: str) -> bool:
        """
        Load cache from disk
        
        Args:
            simulation_id: Simulation ID
        
        Returns:
            True if loaded successfully
        """
        try:
            from ..config import Config
        except ImportError:
            from config import Config
        
        cache_file = os.path.join(
            Config.UPLOAD_FOLDER, 'simulations', simulation_id, "decision_cache.json"
        )
        
        if not os.path.exists(cache_file):
            return False
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self._stats = data.get("stats", {"hits": 0, "misses": 0})
            self._ttl_hours = data.get("ttl_hours", 24)
            
            for entry in data.get("entries", []):
                cache_key = f"{entry['agent_id']}:{entry['context_hash']}"
                self._cache[cache_key] = CachedDecision(
                    agent_id=entry["agent_id"],
                    context_hash=entry["context_hash"],
                    decision=entry["decision"],
                    timestamp=datetime.fromisoformat(entry["timestamp"]),
                    hit_count=entry.get("hit_count", 0),
                )
            
            logger.info(f"Decision cache loaded from {cache_file} ({len(self._cache)} entries)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load cache: {e}")
            return False
    
    def set_ttl(self, hours: int):
        """Set cache TTL in hours"""
        self._ttl_hours = max(1, min(hours, 168))  # 1 hour to 1 week
        logger.info(f"Decision cache TTL set to {self._ttl_hours} hours")

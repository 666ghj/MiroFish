"""
Checkpoint Manager untuk MiroFish Simulation
Menyimpan progress simulation setiap N rounds untuk resume capability
"""

import os
import json
import gzip
from typing import Dict, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger('mirofish.checkpoint')


class CheckpointManager:
    """
    Manage simulation checkpoints untuk resume capability
    
    Features:
    - Save checkpoint setiap N rounds (default: 10)
    - Compressed storage (gzip)
    - Auto cleanup old checkpoints
    - Resume dari checkpoint terakhir
    """
    
    CHECKPOINT_DIR = "checkpoints"
    CHECKPOINT_INTERVAL = 10  # Save setiap 10 rounds
    MAX_CHECKPOINTS = 5  # Keep max 5 checkpoints
    
    @classmethod
    def get_checkpoint_dir(cls, simulation_id: str) -> str:
        """Get checkpoint directory path"""
        from ..config import Config
        base_dir = os.path.join(Config.UPLOAD_FOLDER, 'simulations', simulation_id)
        checkpoint_dir = os.path.join(base_dir, cls.CHECKPOINT_DIR)
        os.makedirs(checkpoint_dir, exist_ok=True)
        return checkpoint_dir
    
    @classmethod
    def save_checkpoint(
        cls,
        simulation_id: str,
        round_num: int,
        state: Dict[str, Any],
        platform: str = "twitter",
        extra_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Save checkpoint to disk (compressed)
        
        Args:
            simulation_id: Simulation ID
            round_num: Current round number
            state: State data to save
            platform: Platform name (twitter/reddit)
            extra_data: Additional data (agent states, etc.)
        
        Returns:
            checkpoint_path: Path to saved checkpoint
        """
        checkpoint_dir = cls.get_checkpoint_dir(simulation_id)
        
        checkpoint_data = {
            "simulation_id": simulation_id,
            "round_num": round_num,
            "platform": platform,
            "timestamp": datetime.now().isoformat(),
            "state": state,
            "extra_data": extra_data or {},
        }
        
        # Save as compressed JSON
        checkpoint_path = os.path.join(
            checkpoint_dir, 
            f"checkpoint_{platform}_{round_num:04d}.json.gz"
        )
        
        try:
            with gzip.open(checkpoint_path, 'wt', encoding='utf-8') as f:
                json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Checkpoint saved: {checkpoint_path}")
            
            # Cleanup old checkpoints
            cls._cleanup_old_checkpoints(checkpoint_dir, platform)
            
            return checkpoint_path
            
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
            raise
    
    @classmethod
    def load_latest_checkpoint(
        cls, 
        simulation_id: str,
        platform: str = "twitter"
    ) -> Optional[Dict[str, Any]]:
        """
        Load latest checkpoint for resume
        
        Args:
            simulation_id: Simulation ID
            platform: Platform name (twitter/reddit)
        
        Returns:
            Checkpoint data or None if not found
        """
        checkpoint_dir = cls.get_checkpoint_dir(simulation_id)
        
        if not os.path.exists(checkpoint_dir):
            return None
        
        # Find latest checkpoint for platform
        checkpoints = sorted([
            f for f in os.listdir(checkpoint_dir) 
            if f.startswith(f"checkpoint_{platform}_") and f.endswith(".json.gz")
        ], reverse=True)
        
        if not checkpoints:
            return None
        
        latest = checkpoints[0]
        checkpoint_path = os.path.join(checkpoint_dir, latest)
        
        try:
            with gzip.open(checkpoint_path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
            
            logger.info(f"Checkpoint loaded: {checkpoint_path}")
            return data
            
        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}")
            return None
    
    @classmethod
    def load_any_latest_checkpoint(cls, simulation_id: str) -> Optional[Dict[str, Any]]:
        """
        Load latest checkpoint dari any platform
        
        Returns:
            Checkpoint data or None
        """
        checkpoint_dir = cls.get_checkpoint_dir(simulation_id)
        
        if not os.path.exists(checkpoint_dir):
            return None
        
        # Find all checkpoints
        checkpoints = sorted([
            f for f in os.listdir(checkpoint_dir)
            if f.startswith("checkpoint_") and f.endswith(".json.gz")
        ], reverse=True)
        
        if not checkpoints:
            return None
        
        latest = checkpoints[0]
        checkpoint_path = os.path.join(checkpoint_dir, latest)
        
        try:
            with gzip.open(checkpoint_path, 'rt', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}")
            return None
    
    @classmethod
    def get_resume_round(cls, simulation_id: str, platform: str = "twitter") -> int:
        """
        Get round number to resume from
        
        Returns:
            Round number (0 if no checkpoint)
        """
        checkpoint = cls.load_latest_checkpoint(simulation_id, platform)
        return checkpoint["round_num"] if checkpoint else 0
    
    @classmethod
    def has_checkpoint(cls, simulation_id: str, platform: str = None) -> bool:
        """Check if checkpoint exists"""
        if platform:
            return cls.load_latest_checkpoint(simulation_id, platform) is not None
        else:
            return cls.load_any_latest_checkpoint(simulation_id) is not None
    
    @classmethod
    def _cleanup_old_checkpoints(cls, checkpoint_dir: str, platform: str):
        """Remove old checkpoints, keep only MAX_CHECKPOINTS"""
        checkpoints = sorted([
            f for f in os.listdir(checkpoint_dir)
            if f.startswith(f"checkpoint_{platform}_") and f.endswith(".json.gz")
        ])
        
        while len(checkpoints) > cls.MAX_CHECKPOINTS:
            old_checkpoint = os.path.join(checkpoint_dir, checkpoints.pop(0))
            try:
                os.remove(old_checkpoint)
                logger.debug(f"Removed old checkpoint: {old_checkpoint}")
            except Exception as e:
                logger.warning(f"Failed to remove old checkpoint: {e}")
    
    @classmethod
    def clear_checkpoints(cls, simulation_id: str):
        """Remove all checkpoints for simulation"""
        checkpoint_dir = cls.get_checkpoint_dir(simulation_id)
        
        if not os.path.exists(checkpoint_dir):
            return
        
        for f in os.listdir(checkpoint_dir):
            if f.startswith("checkpoint_") and f.endswith(".json.gz"):
                try:
                    os.remove(os.path.join(checkpoint_dir, f))
                except Exception as e:
                    logger.warning(f"Failed to remove checkpoint: {e}")
        
        logger.info(f"Cleared checkpoints for: {simulation_id}")
    
    @classmethod
    def list_checkpoints(cls, simulation_id: str) -> list:
        """List all checkpoints for simulation"""
        checkpoint_dir = cls.get_checkpoint_dir(simulation_id)
        
        if not os.path.exists(checkpoint_dir):
            return []
        
        checkpoints = []
        for f in sorted(os.listdir(checkpoint_dir)):
            if f.startswith("checkpoint_") and f.endswith(".json.gz"):
                try:
                    with gzip.open(os.path.join(checkpoint_dir, f), 'rt', encoding='utf-8') as fp:
                        data = json.load(fp)
                    checkpoints.append({
                        "file": f,
                        "round_num": data.get("round_num"),
                        "platform": data.get("platform"),
                        "timestamp": data.get("timestamp"),
                    })
                except:
                    pass
        
        return checkpoints

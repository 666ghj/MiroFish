"""
Batch Processor untuk MiroFish Simulation
Memory-efficient batch processing untuk agent actions
"""

import asyncio
import gc
import time
from typing import List, Callable, Any, Dict, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger('mirofish.batch_processor')


@dataclass
class BatchResult:
    """Result of batch processing"""
    batch_index: int
    success_count: int
    error_count: int
    duration_seconds: float
    error_message: Optional[str] = None


@dataclass
class BatchProcessorConfig:
    """Configuration for batch processor"""
    batch_size: int = 10  # Process 10 agents at a time
    batch_delay: float = 0.5  # Delay between batches (seconds)
    memory_cleanup_interval: int = 5  # Run gc every N batches
    timeout_per_batch: float = 300.0  # 5 minutes per batch max
    enable_memory_cleanup: bool = True


class BatchProcessor:
    """
    Memory-efficient batch processor untuk agent actions
    
    Features:
    - Configurable batch size
    - Memory cleanup between batches
    - Progress callbacks
    - Error handling per batch
    - Timeout support
    - Cancellation support
    """
    
    def __init__(self, config: Optional[BatchProcessorConfig] = None):
        self.config = config or BatchProcessorConfig()
        self._cancel_flag = False
    
    def request_cancel(self):
        """Request graceful cancellation"""
        self._cancel_flag = True
        logger.info("Batch processing cancellation requested")
    
    def reset_cancel(self):
        """Reset cancellation flag"""
        self._cancel_flag = False
    
    async def process_in_batches(
        self,
        items: List[Any],
        process_func: Callable[[List[Any]], Any],
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
        error_handler: Optional[Callable[[Exception, List[Any]], None]] = None,
    ) -> List[BatchResult]:
        """
        Process items in batches with memory management
        
        Args:
            items: List of items to process
            process_func: Async function to process a batch
            progress_callback: Called with (current, total, progress_percent)
            error_handler: Called when batch fails (error, batch_items)
        
        Returns:
            List of batch results
        """
        total_items = len(items)
        results = []
        self._cancel_flag = False
        
        if total_items == 0:
            return results
        
        logger.info(f"Starting batch processing: {total_items} items, batch_size={self.config.batch_size}")
        
        for batch_idx in range(0, total_items, self.config.batch_size):
            # Check cancellation
            if self._cancel_flag:
                logger.warning("Batch processing cancelled by request")
                break
            
            batch_items = items[batch_idx:batch_idx + self.config.batch_size]
            batch_num = (batch_idx // self.config.batch_size) + 1
            total_batches = (total_items + self.config.batch_size - 1) // self.config.batch_size
            
            # Process batch
            start_time = time.time()
            
            try:
                # Run with timeout
                result = await asyncio.wait_for(
                    process_func(batch_items),
                    timeout=self.config.timeout_per_batch
                )
                
                batch_result = BatchResult(
                    batch_index=batch_num,
                    success_count=len(batch_items),
                    error_count=0,
                    duration_seconds=time.time() - start_time,
                )
                
                logger.debug(f"Batch {batch_num}/{total_batches} completed in {batch_result.duration_seconds:.2f}s")
                
            except asyncio.TimeoutError:
                error_msg = f"Batch {batch_num} timeout after {self.config.timeout_per_batch}s"
                logger.error(error_msg)
                
                batch_result = BatchResult(
                    batch_index=batch_num,
                    success_count=0,
                    error_count=len(batch_items),
                    duration_seconds=time.time() - start_time,
                    error_message=error_msg,
                )
                
                if error_handler:
                    error_handler(TimeoutError(error_msg), batch_items)
                
            except asyncio.CancelledError:
                logger.warning(f"Batch {batch_num} cancelled")
                break
                
            except Exception as e:
                error_msg = f"Batch {batch_num} error: {str(e)}"
                logger.error(error_msg)
                
                batch_result = BatchResult(
                    batch_index=batch_num,
                    success_count=0,
                    error_count=len(batch_items),
                    duration_seconds=time.time() - start_time,
                    error_message=error_msg,
                )
                
                if error_handler:
                    error_handler(e, batch_items)
            
            results.append(batch_result)
            
            # Progress callback
            if progress_callback:
                progress = (batch_idx + len(batch_items)) / total_items * 100
                progress_callback(
                    batch_idx + len(batch_items),
                    total_items,
                    progress
                )
            
            # Memory cleanup
            if self.config.enable_memory_cleanup and batch_num % self.config.memory_cleanup_interval == 0:
                gc.collect()
                logger.debug(f"Memory cleanup after batch {batch_num}")
            
            # Delay between batches
            if batch_idx + self.config.batch_size < total_items and not self._cancel_flag:
                await asyncio.sleep(self.config.batch_delay)
        
        # Final stats
        total_success = sum(r.success_count for r in results)
        total_errors = sum(r.error_count for r in results)
        total_duration = sum(r.duration_seconds for r in results)
        
        logger.info(
            f"Batch processing completed: "
            f"{len(results)} batches, "
            f"{total_success} success, "
            f"{total_errors} errors, "
            f"{total_duration:.2f}s total"
        )
        
        return results
    
    def get_stats(self, results: List[BatchResult]) -> Dict[str, Any]:
        """Get statistics from batch results"""
        if not results:
            return {
                "total_batches": 0,
                "total_success": 0,
                "total_errors": 0,
                "total_duration": 0,
                "avg_batch_duration": 0,
            }
        
        total_success = sum(r.success_count for r in results)
        total_errors = sum(r.error_count for r in results)
        total_duration = sum(r.duration_seconds for r in results)
        
        return {
            "total_batches": len(results),
            "total_success": total_success,
            "total_errors": total_errors,
            "total_duration": round(total_duration, 2),
            "avg_batch_duration": round(total_duration / len(results), 2),
            "success_rate": f"{total_success / (total_success + total_errors) * 100:.1f}%" if (total_success + total_errors) > 0 else "N/A",
        }


class AgentBatchProcessor(BatchProcessor):
    """
    Specialized batch processor untuk agent actions
    
    Provides helper methods specifically for agent simulation
    """
    
    async def process_agents_in_round(
        self,
        agents: List[Any],
        action_factory: Callable[[Any], Any],
        step_func: Callable[[Dict], Any],
        context: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> List[BatchResult]:
        """
        Process agents in batches for one simulation round
        
        Args:
            agents: List of agents to process
            action_factory: Function to create action for agent
            step_func: Async function to execute actions (env.step)
            context: Additional context (round_num, simulated_hour, etc.)
            progress_callback: Progress callback
        
        Returns:
            List of batch results
        """
        context = context or {}
        
        async def process_batch(batch_agents: List[Any]) -> Dict:
            """Process a batch of agents"""
            actions = {}
            
            for agent in batch_agents:
                try:
                    action = action_factory(agent)
                    actions[agent] = action
                except Exception as e:
                    logger.warning(f"Failed to create action for agent: {e}")
            
            if not actions:
                return {"success": False, "error": "No actions created"}
            
            # Execute actions via step function
            await step_func(actions)
            
            return {"success": True, "count": len(actions)}
        
        return await self.process_in_batches(
            items=agents,
            process_func=process_batch,
            progress_callback=progress_callback,
        )


# Convenience function
async def batch_process_agents(
    agents: List[Any],
    step_func: Callable[[Dict], Any],
    action_factory: Callable[[Any], Any] = None,
    batch_size: int = 10,
    progress_callback: Optional[Callable[[int, int, float], None]] = None,
) -> List[BatchResult]:
    """
    Convenience function untuk batch process agents
    
    Args:
        agents: List of agents
        step_func: Async step function (env.step)
        action_factory: Function to create action (default: LLMAction)
        batch_size: Batch size
        progress_callback: Progress callback
    
    Returns:
        List of batch results
    """
    config = BatchProcessorConfig(batch_size=batch_size)
    processor = AgentBatchProcessor(config)
    
    return await processor.process_agents_in_round(
        agents=agents,
        action_factory=action_factory or (lambda agent: type('LLMAction', (), {})()),
        step_func=step_func,
        progress_callback=progress_callback,
    )

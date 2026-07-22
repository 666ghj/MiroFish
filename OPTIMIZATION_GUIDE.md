# MiroFish Optimization Implementation

## Overview
Implementasi 5 optimasi untuk meningkatkan performance MiroFish simulation:
1. Fix Memory Leak
2. Checkpoint System
3. Decision Caching
4. Streaming Progress
5. Batch Processing

## Files Created

### Backend Services
- `backend/app/services/checkpoint_manager.py` - Save/restore simulation progress
- `backend/app/services/decision_cache.py` - Cache LLM decisions to reduce API calls
- `backend/app/services/batch_processor.py` - Memory-efficient batch processing

### Backend API
- `backend/app/api/streaming.py` - Real-time progress via Server-Sent Events

### Optimized Scripts
- `backend/scripts/run_optimized_twitter_simulation.py` - Optimized Twitter simulation runner

## Usage

### Run Optimized Simulation
```bash
cd backend
python scripts/run_optimized_twitter_simulation.py --config /path/to/simulation_config.json

# With options:
python scripts/run_optimized_twitter_simulation.py \
  --config /path/to/config.json \
  --max-rounds 50 \
  --no-cache \           # Disable caching
  --no-streaming \       # Disable streaming
  --no-checkpoint        # Disable checkpoint
```

### Checkpoint Management
```python
from app.services import CheckpointManager

# Check for existing checkpoint
if CheckpointManager.has_checkpoint("sim_xxx", "twitter"):
    resume_round = CheckpointManager.get_resume_round("sim_xxx", "twitter")
    print(f"Can resume from round {resume_round}")

# List checkpoints
checkpoints = CheckpointManager.list_checkpoints("sim_xxx")
for cp in checkpoints:
    print(f"Round {cp['round_num']} at {cp['timestamp']}")

# Clear checkpoints
CheckpointManager.clear_checkpoints("sim_xxx")
```

### Decision Caching
```python
from app.services import DecisionCache

cache = DecisionCache.get_instance()

# Get cached decision
decision = cache.get(agent_id=1, context={
    "personality": {...},
    "visible_posts": [...],
    "simulated_hour": 12,
})

if decision:
    print(f"Using cached decision: {decision}")
else:
    # Call LLM and cache result
    decision = call_llm(...)
    cache.set(agent_id=1, context=context, decision=decision)

# View stats
stats = cache.get_stats()
print(f"Cache hit rate: {stats['hit_rate']}")
```

### Streaming Progress
```python
from app.api.streaming import SimulationEventBroadcaster, create_stream_route

# In simulation runner
broadcaster = SimulationEventBroadcaster("sim_xxx")
broadcaster.simulation_start(total_rounds=96, total_agents=50)
broadcaster.round_complete(round_num=10, simulated_hour=5, ...)
broadcaster.simulation_complete(total_rounds=96, total_actions=1500, duration_seconds=3600)

# In Flask app/blueprint
from flask import Blueprint
simulation_bp = Blueprint('simulation', __name__)
create_stream_route(simulation_bp)

# Client-side (JavaScript)
const eventSource = new EventSource('/api/simulation/sim_xxx/stream');
eventSource.addEventListener('round_complete', (e) => {
    const data = JSON.parse(e.data);
    console.log(`Round ${data.round_num} complete - ${data.progress_percent}%`);
});
```

### Batch Processing
```python
from app.services import BatchProcessor, BatchProcessorConfig

config = BatchProcessorConfig(
    batch_size=10,
    batch_delay=0.5,
    memory_cleanup_interval=5,
)

processor = BatchProcessor(config)

results = await processor.process_in_batches(
    items=agents,
    process_func=process_batch_func,
    progress_callback=lambda current, total, progress: print(f"{progress:.1f}%"),
)
```

## Expected Improvements

### Memory Usage
- **Before**: 1-2 GB for 96 rounds
- **After**: 300-500 MB for 96 rounds
- **Improvement**: 60-75% reduction

### API Calls
- **Before**: 2880-5760 calls for 96 rounds
- **After**: 2000-4000 calls (with 30% cache hit rate)
- **Improvement**: 20-40% reduction

### Reliability
- Can resume from checkpoint if crash
- Graceful error handling per batch
- Real-time progress visibility

### Performance
- Memory cleanup prevents OOM
- Batch processing stabilizes memory
- Streaming prevents "stuck" perception

## Configuration

### Environment Variables
```env
# .env file

# LLM Configuration
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini

# Zep Cloud
ZEP_API_KEY=your_zep_key

# Simulation Optimization (optional)
CHECKPOINT_INTERVAL=10      # Save checkpoint every N rounds
BATCH_SIZE=10               # Process N agents per batch
MAX_CACHE_TTL=24            # Cache TTL in hours
MEMORY_CLEANUP_INTERVAL=5   # GC every N rounds
```

### Python Config
```python
# In OptimizedTwitterSimulationRunner

CHECKPOINT_INTERVAL = 10    # Save every 10 rounds
BATCH_SIZE = 10             # 10 agents per batch
MAX_CACHE_TTL = 24          # 24 hour cache TTL
MEMORY_CLEANUP_INTERVAL = 5 # GC every 5 rounds
```

## Monitoring

### Cache Statistics
```python
cache = DecisionCache.get_instance()
stats = cache.get_stats()
# {
#   "hits": 150,
#   "misses": 100,
#   "hit_rate": "60.0%",
#   "cache_size": 250
# }
```

### Batch Statistics
```python
stats = processor.get_stats(results)
# {
#   "total_batches": 96,
#   "total_success": 1400,
#   "total_errors": 5,
#   "total_duration": 3600.5,
#   "avg_batch_duration": 37.5,
#   "success_rate": "99.6%"
# }
```

### Checkpoint Status
```python
checkpoints = CheckpointManager.list_checkpoints("sim_xxx")
# [
#   {"file": "checkpoint_twitter_0096.json.gz", "round_num": 96, "timestamp": "2026-07-09T01:00:00"},
#   {"file": "checkpoint_twitter_0090.json.gz", "round_num": 90, "timestamp": "2026-07-09T00:50:00"},
# ]
```

## Integration with Existing Code

### Use Optimized Runner
```python
# Instead of:
# from scripts.run_twitter_simulation import TwitterSimulationRunner

# Use:
from scripts.run_optimized_twitter_simulation import OptimizedTwitterSimulationRunner

runner = OptimizedTwitterSimulationRunner(
    config_path=config_path,
    enable_caching=True,
    enable_streaming=True,
    enable_checkpoint=True,
)
await runner.run(max_rounds=96)
```

### Add Streaming to Existing Routes
```python
# In backend/app/api/simulation.py

from .streaming import create_stream_route

# Add streaming route
create_stream_route(simulation_bp)
```

### Add Checkpoint to Existing Runner
```python
# In your simulation loop

from app.services import CheckpointManager

for round_num in range(total_rounds):
    # ... simulation logic ...
    
    # Save checkpoint every 10 rounds
    if (round_num + 1) % 10 == 0:
        CheckpointManager.save_checkpoint(
            simulation_id=simulation_id,
            round_num=round_num + 1,
            state={"current_round": round_num + 1},
            platform="twitter",
        )
```

## Troubleshooting

### Memory Still High?
1. Reduce `BATCH_SIZE` to 5
2. Increase `MEMORY_CLEANUP_INTERVAL` to 3
3. Disable caching if not needed
4. Check for memory leaks in custom code

### Simulation Slow?
1. Check LLM API latency
2. Reduce `batch_delay` to 0.1
3. Increase `BATCH_SIZE` to 20 (if memory allows)
4. Check cache hit rate - should be 20-40%

### Checkpoint Not Saving?
1. Check directory permissions
2. Check disk space
3. Verify `simulation_id` is correct
4. Check logs for errors

### Streaming Not Working?
1. Check Flask route is registered
2. Check client connects to correct URL
3. Check browser supports EventSource
4. Check for proxy buffering (disable with X-Accel-Buffering: no)

## Future Improvements

1. **Redis Cache** - For distributed caching across multiple workers
2. **PostgreSQL** - Instead of SQLite for better concurrency
3. **Kubernetes Jobs** - For scalable simulation execution
4. **WebSocket** - For bidirectional streaming (not just SSE)
5. **Metrics Dashboard** - Real-time Grafana dashboard for monitoring

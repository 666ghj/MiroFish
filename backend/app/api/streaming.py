"""
Streaming Progress untuk MiroFish Simulation
Real-time progress via Server-Sent Events (SSE)
"""

import json
import time
import threading
from typing import Dict, Any, Optional
from queue import Queue, Full
import logging

logger = logging.getLogger('mirofish.streaming')

# Global event bus untuk streaming
_stream_buffers: Dict[str, Queue] = {}
_stream_lock = threading.Lock()


def get_stream_buffer(simulation_id: str, maxsize: int = 100) -> Queue:
    """
    Get or create stream buffer for simulation
    
    Args:
        simulation_id: Simulation ID
        maxsize: Max events in buffer
    
    Returns:
        Queue buffer
    """
    with _stream_lock:
        if simulation_id not in _stream_buffers:
            _stream_buffers[simulation_id] = Queue(maxsize=maxsize)
        return _stream_buffers[simulation_id]


def remove_stream_buffer(simulation_id: str):
    """Remove stream buffer when simulation ends"""
    with _stream_lock:
        if simulation_id in _stream_buffers:
            del _stream_buffers[simulation_id]


def broadcast_event(simulation_id: str, event_type: str, data: Dict[str, Any]):
    """
    Broadcast event to all connected clients
    
    Args:
        simulation_id: Simulation ID
        event_type: Event type (round_complete, simulation_complete, etc.)
        data: Event data
    """
    try:
        buffer = get_stream_buffer(simulation_id)
        
        event = {
            "event_type": event_type,
            "timestamp": time.time(),
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
            "data": data,
        }
        
        buffer.put_nowait(event)
        logger.debug(f"Broadcast event: {event_type} for {simulation_id}")
        
    except Full:
        logger.warning(f"Stream buffer full for {simulation_id}, skipping event")
    except Exception as e:
        logger.error(f"Failed to broadcast event: {e}")


def stream_simulation_events(simulation_id: str, timeout: int = 30):
    """
    Generator untuk SSE (Server-Sent Events)
    
    Usage di Flask route:
        @app.route('/stream/<simulation_id>')
        def stream(simulation_id):
            return Response(
                stream_simulation_events(simulation_id),
                mimetype='text/event-stream'
            )
    
    Args:
        simulation_id: Simulation ID
        timeout: Timeout in seconds for heartbeat
    
    Yields:
        SSE formatted strings
    """
    buffer = get_stream_buffer(simulation_id)
    
    # Send initial connection event
    yield f"event: connected\ndata: {{\"simulation_id\": \"{simulation_id}\"}}\n\n"
    
    while True:
        try:
            # Wait for event with timeout
            event = buffer.get(timeout=timeout)
            
            # Send as SSE
            event_data = json.dumps(event, ensure_ascii=False)
            yield f"event: {event['event_type']}\ndata: {event_data}\n\n"
            
            # Check if simulation completed
            if event['event_type'] in ['simulation_complete', 'simulation_error']:
                logger.info(f"Stream completed for {simulation_id}")
                break
                
        except:
            # Timeout - send heartbeat
            yield f"event: heartbeat\ndata: {{\"timestamp\": {time.time()}}}\n\n"
    
    # Cleanup
    remove_stream_buffer(simulation_id)


class SimulationEventBroadcaster:
    """
    Helper class untuk broadcast simulation events
    
    Usage:
        broadcaster = SimulationEventBroadcaster(simulation_id)
        broadcaster.round_complete(round_num, simulated_hour, stats)
        broadcaster.simulation_complete(total_rounds, total_actions)
    """
    
    def __init__(self, simulation_id: str):
        self.simulation_id = simulation_id
    
    def simulation_start(self, total_rounds: int, total_agents: int):
        """Broadcast simulation start"""
        broadcast_event(self.simulation_id, "simulation_start", {
            "total_rounds": total_rounds,
            "total_agents": total_agents,
        })
    
    def round_complete(
        self,
        round_num: int,
        simulated_hour: int,
        simulated_day: int,
        twitter_actions: int = 0,
        reddit_actions: int = 0,
        active_agents: int = 0,
        progress_percent: float = 0.0,
    ):
        """Broadcast round complete"""
        broadcast_event(self.simulation_id, "round_complete", {
            "round_num": round_num,
            "simulated_hour": simulated_hour,
            "simulated_day": simulated_day,
            "twitter_actions": twitter_actions,
            "reddit_actions": reddit_actions,
            "active_agents": active_agents,
            "progress_percent": progress_percent,
        })
    
    def agent_action(self, agent_id: int, agent_name: str, action_type: str, platform: str):
        """Broadcast agent action"""
        broadcast_event(self.simulation_id, "agent_action", {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "action_type": action_type,
            "platform": platform,
        })
    
    def simulation_complete(self, total_rounds: int, total_actions: int, duration_seconds: float):
        """Broadcast simulation complete"""
        broadcast_event(self.simulation_id, "simulation_complete", {
            "total_rounds": total_rounds,
            "total_actions": total_actions,
            "duration_seconds": round(duration_seconds, 2),
        })
    
    def simulation_error(self, error_message: str, round_num: int = None):
        """Broadcast simulation error"""
        broadcast_event(self.simulation_id, "simulation_error", {
            "error_message": error_message,
            "round_num": round_num,
        })
    
    def checkpoint_saved(self, round_num: int):
        """Broadcast checkpoint saved"""
        broadcast_event(self.simulation_id, "checkpoint_saved", {
            "round_num": round_num,
        })


# Flask route helper
def create_stream_route(app_or_blueprint):
    """
    Create streaming route for Flask app or blueprint
    
    Usage:
        from flask import Blueprint
        simulation_bp = Blueprint('simulation', __name__)
        create_stream_route(simulation_bp)
    """
    @app_or_blueprint.route('/<simulation_id>/stream', methods=['GET'])
    def stream_simulation_progress(simulation_id: str):
        """
        Stream simulation events via Server-Sent Events (SSE)
        
        Client usage:
            const eventSource = new EventSource('/api/simulation/sim_xxx/stream');
            eventSource.addEventListener('round_complete', (e) => {
                const data = JSON.parse(e.data);
                console.log('Round', data.round_num, 'complete');
            });
        """
        from flask import Response
        
        return Response(
            stream_simulation_events(simulation_id),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive',
            }
        )

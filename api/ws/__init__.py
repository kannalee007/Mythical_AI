"""
Pipeline WebSocket event emitter for real-time task streaming.

Manages WebSocket connections and broadcasts pipeline stage updates
(planning -> safety -> executing -> complete).
"""

from fastapi import WebSocket
from typing import Set, Dict
import json
import asyncio


class PipelineStreamManager:
    """
    Manages WebSocket connections for pipeline event streaming.
    
    Allows multiple clients to subscribe to task execution events
    and receive real-time updates at each pipeline stage.
    """
    
    def __init__(self):
        """Initialize stream manager."""
        self.active_connections: Set[WebSocket] = set()
        self.task_subscribers: Dict[str, Set[WebSocket]] = {}  # task_id -> {websockets}
    
    async def connect(self, websocket: WebSocket):
        """Register a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
    
    async def disconnect(self, websocket: WebSocket):
        """Unregister a WebSocket connection."""
        self.active_connections.discard(websocket)
        
        # Clean up task subscriptions
        for subscribers in self.task_subscribers.values():
            subscribers.discard(websocket)
    
    async def subscribe_to_task(self, websocket: WebSocket, task_id: str):
        """Subscribe WebSocket to task-specific events."""
        if task_id not in self.task_subscribers:
            self.task_subscribers[task_id] = set()
        
        self.task_subscribers[task_id].add(websocket)
    
    async def broadcast_event(self, event: dict, task_id: str):
        """
        Broadcast pipeline event to all subscribers of a task.
        
        Args:
            event: event dict with stage, data, message
            task_id: task to broadcast to
        """
        if task_id not in self.task_subscribers:
            return
        
        disconnected = set()
        
        for websocket in self.task_subscribers[task_id]:
            try:
                await websocket.send_json(event)
            except Exception as e:
                print(f"[WebSocket] Error sending event: {e}")
                disconnected.add(websocket)
        
        # Clean up disconnected clients
        for ws in disconnected:
            await self.disconnect(ws)


# Global stream manager instance
stream_manager = PipelineStreamManager()


async def stream_event_to_websocket(
    websocket: WebSocket,
    stage: str,
    task_id: str,
    message: str,
    data: dict = None,
):
    """
    Convenience function to send a pipeline event over WebSocket.
    
    Args:
        websocket: WebSocket connection
        stage: pipeline stage (planning|safety|executing|complete)
        task_id: unique task ID
        message: human-readable status message
        data: optional event-specific data
    """
    event = {
        "stage": stage,
        "task_id": task_id,
        "message": message,
    }
    
    if data:
        event["data"] = data
    
    await websocket.send_json(event)

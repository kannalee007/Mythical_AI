"""Task service for status tracking and lifecycle management."""

import logging
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task execution states."""
    SUBMITTED = "submitted"
    PLANNING = "planning"
    SAFETY_REVIEW = "safety_review"
    EXECUTING = "executing"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskStateRecord(BaseModel):
    """Record of a task's state at a point in time."""
    state: TaskStatus
    timestamp: datetime
    message: Optional[str] = None
    details: dict = None
    
    def __init__(self, **data):
        if data.get("details") is None:
            data["details"] = {}
        super().__init__(**data)


class TaskStatusResponse(BaseModel):
    """Current task status and timeline."""
    task_id: str
    tenant_id: str
    user_id: str
    current_state: TaskStatus
    submitted_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    estimated_completion: Optional[datetime] = None
    state_timeline: list[TaskStateRecord]
    result: Optional[dict] = None
    error: Optional[str] = None
    progress_percent: int = 0


class TaskSubmissionResponse(BaseModel):
    """Response when task is initially submitted."""
    task_id: str
    status: TaskStatus
    submitted_at: datetime
    message: str = "Task submitted successfully"


class TaskService:
    """Manages task lifecycle and status tracking."""
    
    def __init__(self):
        """Initialize task service with in-memory storage."""
        # In Phase 2: in-memory storage
        # In Phase 3: PostgreSQL backend
        self._tasks: dict[str, dict] = {}
    
    async def submit_task(
        self,
        tenant_id: str,
        user_id: str,
        task_type: str,
        task_config: dict
    ) -> TaskSubmissionResponse:
        """Submit a new task and return submission details.
        
        Args:
            tenant_id: Tenant context
            user_id: User submitting task
            task_type: Type of task (code_review, security_scan, etc.)
            task_config: Task configuration
            
        Returns:
            TaskSubmissionResponse with task_id and initial status
        """
        try:
            task_id = f"task_{uuid4().hex[:12]}"
            now = datetime.utcnow()
            
            task_record = {
                "task_id": task_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "task_type": task_type,
                "task_config": task_config,
                "current_state": TaskStatus.SUBMITTED,
                "submitted_at": now,
                "started_at": None,
                "completed_at": None,
                "result": None,
                "error": None,
                "state_timeline": [
                    TaskStateRecord(
                        state=TaskStatus.SUBMITTED,
                        timestamp=now,
                        message="Task submitted"
                    )
                ]
            }
            
            self._tasks[task_id] = task_record
            logger.info(f"Task submitted: {task_id} for user {user_id}")
            
            return TaskSubmissionResponse(
                task_id=task_id,
                status=TaskStatus.SUBMITTED,
                submitted_at=now
            )
        except Exception as e:
            logger.error(f"Error submitting task: {e}")
            raise
    
    async def get_task_status(self, task_id: str) -> Optional[TaskStatusResponse]:
        """Get current status of a task.
        
        Args:
            task_id: Task ID to query
            
        Returns:
            TaskStatusResponse with current state and timeline, or None if not found
        """
        try:
            if task_id not in self._tasks:
                logger.warning(f"Task not found: {task_id}")
                return None
            
            task = self._tasks[task_id]
            now = datetime.utcnow()
            
            # Calculate duration
            duration_seconds = None
            if task["completed_at"]:
                duration_seconds = (task["completed_at"] - task["submitted_at"]).total_seconds()
            elif task["started_at"]:
                duration_seconds = (now - task["started_at"]).total_seconds()
            
            # Calculate progress
            progress_map = {
                TaskStatus.SUBMITTED: 10,
                TaskStatus.PLANNING: 25,
                TaskStatus.SAFETY_REVIEW: 50,
                TaskStatus.EXECUTING: 75,
                TaskStatus.COMPLETE: 100,
                TaskStatus.FAILED: 100,
                TaskStatus.BLOCKED: 100,
                TaskStatus.CANCELLED: 100,
            }
            progress_percent = progress_map.get(task["current_state"], 10)
            
            return TaskStatusResponse(
                task_id=task_id,
                tenant_id=task["tenant_id"],
                user_id=task["user_id"],
                current_state=task["current_state"],
                submitted_at=task["submitted_at"],
                started_at=task["started_at"],
                completed_at=task["completed_at"],
                duration_seconds=duration_seconds,
                state_timeline=task["state_timeline"],
                result=task.get("result"),
                error=task.get("error"),
                progress_percent=progress_percent
            )
        except Exception as e:
            logger.error(f"Error getting task status: {e}")
            raise
    
    async def transition_task_state(
        self,
        task_id: str,
        new_state: TaskStatus,
        message: Optional[str] = None,
        details: Optional[dict] = None
    ) -> bool:
        """Transition a task to a new state.
        
        Args:
            task_id: Task to transition
            new_state: Target state
            message: Optional state change message
            details: Optional metadata
            
        Returns:
            True if transition succeeded, False if task not found
        """
        try:
            if task_id not in self._tasks:
                logger.warning(f"Task not found for state transition: {task_id}")
                return False
            
            task = self._tasks[task_id]
            old_state = task["current_state"]
            now = datetime.utcnow()
            
            # Validate state transition
            if not self._validate_state_transition(old_state, new_state):
                logger.warning(f"Invalid state transition: {old_state} → {new_state}")
                return False
            
            # Update task
            task["current_state"] = new_state
            
            if new_state == TaskStatus.EXECUTING and task["started_at"] is None:
                task["started_at"] = now
            
            if new_state in [TaskStatus.COMPLETE, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED]:
                task["completed_at"] = now
            
            # Add to timeline
            task["state_timeline"].append(
                TaskStateRecord(
                    state=new_state,
                    timestamp=now,
                    message=message or f"Transitioned to {new_state.value}",
                    details=details or {}
                )
            )
            
            logger.info(f"Task {task_id} transitioned: {old_state.value} → {new_state.value}")
            return True
        except Exception as e:
            logger.error(f"Error transitioning task state: {e}")
            raise
    
    async def set_task_result(
        self,
        task_id: str,
        result: dict,
        error: Optional[str] = None
    ) -> bool:
        """Set the result of a completed task.
        
        Args:
            task_id: Task ID
            result: Result data
            error: Optional error message if failed
            
        Returns:
            True if set successfully
        """
        try:
            if task_id not in self._tasks:
                logger.warning(f"Task not found: {task_id}")
                return False
            
            task = self._tasks[task_id]
            task["result"] = result
            if error:
                task["error"] = error
            
            logger.info(f"Task result set: {task_id}")
            return True
        except Exception as e:
            logger.error(f"Error setting task result: {e}")
            raise
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task if not already executing.
        
        Args:
            task_id: Task to cancel
            
        Returns:
            True if cancelled, False if cannot cancel
        """
        try:
            if task_id not in self._tasks:
                logger.warning(f"Task not found: {task_id}")
                return False
            
            task = self._tasks[task_id]
            
            return await self.transition_task_state(
                task_id,
                TaskStatus.CANCELLED,
                message="Task cancelled by user",
            )
        except Exception as e:
            logger.error(f"Error cancelling task: {e}")
            raise
    
    async def list_tenant_tasks(
        self,
        tenant_id: str,
        status_filter: Optional[TaskStatus] = None,
        limit: int = 100,
        offset: int = 0
    ) -> tuple[list[TaskStatusResponse], int]:
        """List tasks for a tenant with optional filtering.
        
        Args:
            tenant_id: Tenant to list
            status_filter: Optional status filter
            limit: Max results
            offset: Pagination offset
            
        Returns:
            Tuple of (task_list, total_count)
        """
        try:
            # Filter tasks by tenant
            tenant_tasks = [
                task for task in self._tasks.values()
                if task["tenant_id"] == tenant_id
            ]
            
            # Apply status filter if provided
            if status_filter:
                tenant_tasks = [
                    task for task in tenant_tasks
                    if task["current_state"] == status_filter
                ]
            
            total_count = len(tenant_tasks)
            
            # Sort by submitted_at descending (most recent first)
            tenant_tasks.sort(
                key=lambda t: t["submitted_at"],
                reverse=True
            )
            
            # Apply pagination
            paginated = tenant_tasks[offset:offset + limit]
            
            # Convert to response models
            responses = []
            for task in paginated:
                status_response = await self.get_task_status(task["task_id"])
                if status_response:
                    responses.append(status_response)
            
            return responses, total_count
        except Exception as e:
            logger.error(f"Error listing tenant tasks: {e}")
            raise
    
    # Private helper methods
    
    def _validate_state_transition(
        self,
        from_state: TaskStatus,
        to_state: TaskStatus
    ) -> bool:
        """Validate that a state transition is allowed.
        
        Implements the state machine:
        SUBMITTED → PLANNING → SAFETY_REVIEW → EXECUTING → COMPLETE/FAILED/BLOCKED
        
        Can transition to CANCELLED from: SUBMITTED, PLANNING, SAFETY_REVIEW
        """
        allowed_transitions = {
            TaskStatus.SUBMITTED: [
                TaskStatus.PLANNING,
                TaskStatus.CANCELLED
            ],
            TaskStatus.PLANNING: [
                TaskStatus.SAFETY_REVIEW,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED
            ],
            TaskStatus.SAFETY_REVIEW: [
                TaskStatus.EXECUTING,
                TaskStatus.BLOCKED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED
            ],
            TaskStatus.EXECUTING: [
                TaskStatus.COMPLETE,
                TaskStatus.FAILED
            ],
            TaskStatus.COMPLETE: [],
            TaskStatus.FAILED: [],
            TaskStatus.BLOCKED: [],
            TaskStatus.CANCELLED: [],
        }
        
        return to_state in allowed_transitions.get(from_state, [])

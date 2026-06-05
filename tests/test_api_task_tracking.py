"""Tests for task service and status tracking."""

import pytest
from datetime import datetime
from api.services.task_service import TaskService, TaskStatus


class TestTaskServiceBasic:
    """Test TaskService basic functionality."""
    
    @pytest.mark.asyncio
    async def test_task_service_initialization(self):
        """Test TaskService can be initialized."""
        service = TaskService()
        assert service is not None
        assert service._tasks == {}
    
    @pytest.mark.asyncio
    async def test_submit_task(self):
        """Test submitting a task."""
        service = TaskService()
        response = await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={"path": "/src"}
        )
        
        assert response is not None
        assert response.task_id.startswith("task_")
        assert response.status == TaskStatus.SUBMITTED
        assert response.submitted_at is not None
    
    @pytest.mark.asyncio
    async def test_get_task_status(self):
        """Test getting task status."""
        service = TaskService()
        
        # Submit task
        submit_response = await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={"path": "/src"}
        )
        task_id = submit_response.task_id
        
        # Get status
        status = await service.get_task_status(task_id)
        
        assert status is not None
        assert status.task_id == task_id
        assert status.current_state == TaskStatus.SUBMITTED
        assert status.progress_percent == 10
        assert len(status.state_timeline) == 1
    
    @pytest.mark.asyncio
    async def test_transition_task_state(self):
        """Test transitioning task state."""
        service = TaskService()
        
        # Submit task
        submit_response = await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={"path": "/src"}
        )
        task_id = submit_response.task_id
        
        # Transition to PLANNING
        success = await service.transition_task_state(
            task_id,
            TaskStatus.PLANNING,
            message="Starting planning phase"
        )
        
        assert success is True
        
        # Verify state changed
        status = await service.get_task_status(task_id)
        assert status.current_state == TaskStatus.PLANNING
        assert len(status.state_timeline) == 2
        assert status.progress_percent == 25


class TestTaskStateTransitions:
    """Test task state machine transitions."""
    
    @pytest.mark.asyncio
    async def test_valid_state_transitions(self):
        """Test valid state transitions."""
        service = TaskService()
        
        submit_response = await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={}
        )
        task_id = submit_response.task_id
        
        # Valid sequence: SUBMITTED → PLANNING → SAFETY_REVIEW → EXECUTING → COMPLETE
        transitions = [
            TaskStatus.PLANNING,
            TaskStatus.SAFETY_REVIEW,
            TaskStatus.EXECUTING,
            TaskStatus.COMPLETE
        ]
        
        for next_state in transitions:
            success = await service.transition_task_state(task_id, next_state)
            assert success is True
        
        status = await service.get_task_status(task_id)
        assert status.current_state == TaskStatus.COMPLETE
        assert status.progress_percent == 100
        assert status.duration_seconds is not None
    
    @pytest.mark.asyncio
    async def test_invalid_state_transition(self):
        """Test that invalid transitions are rejected."""
        service = TaskService()
        
        submit_response = await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={}
        )
        task_id = submit_response.task_id
        
        # Try invalid transition: SUBMITTED → EXECUTING (skip steps)
        success = await service.transition_task_state(task_id, TaskStatus.EXECUTING)
        assert success is False
        
        # Verify state didn't change
        status = await service.get_task_status(task_id)
        assert status.current_state == TaskStatus.SUBMITTED
    
    @pytest.mark.asyncio
    async def test_cancel_task_before_execution(self):
        """Test cancelling task before execution."""
        service = TaskService()
        
        submit_response = await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={}
        )
        task_id = submit_response.task_id
        
        # Transition to planning
        await service.transition_task_state(task_id, TaskStatus.PLANNING)
        
        # Cancel task
        success = await service.cancel_task(task_id)
        assert success is True
        
        # Verify state is CANCELLED
        status = await service.get_task_status(task_id)
        assert status.current_state == TaskStatus.CANCELLED
        assert status.completed_at is not None
    
    @pytest.mark.asyncio
    async def test_cannot_cancel_executing_task(self):
        """Test that executing tasks cannot be cancelled."""
        service = TaskService()
        
        submit_response = await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={}
        )
        task_id = submit_response.task_id
        
        # Transition to executing
        await service.transition_task_state(task_id, TaskStatus.PLANNING)
        await service.transition_task_state(task_id, TaskStatus.SAFETY_REVIEW)
        await service.transition_task_state(task_id, TaskStatus.EXECUTING)
        
        # Try to cancel
        success = await service.cancel_task(task_id)
        assert success is False
        
        # Verify still executing
        status = await service.get_task_status(task_id)
        assert status.current_state == TaskStatus.EXECUTING


class TestTaskResult:
    """Test task result setting."""
    
    @pytest.mark.asyncio
    async def test_set_task_result_success(self):
        """Test setting task result for completed task."""
        service = TaskService()
        
        submit_response = await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={}
        )
        task_id = submit_response.task_id
        
        # Transition to complete
        await service.transition_task_state(task_id, TaskStatus.PLANNING)
        await service.transition_task_state(task_id, TaskStatus.SAFETY_REVIEW)
        await service.transition_task_state(task_id, TaskStatus.EXECUTING)
        await service.transition_task_state(task_id, TaskStatus.COMPLETE)
        
        # Set result
        result_data = {"issues": 3, "score": 0.95}
        success = await service.set_task_result(task_id, result_data)
        assert success is True
        
        # Verify result is stored
        status = await service.get_task_status(task_id)
        assert status.result == result_data
    
    @pytest.mark.asyncio
    async def test_set_task_error(self):
        """Test setting task error."""
        service = TaskService()
        
        submit_response = await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={}
        )
        task_id = submit_response.task_id
        
        # Transition to failed
        await service.transition_task_state(task_id, TaskStatus.PLANNING)
        await service.transition_task_state(task_id, TaskStatus.FAILED)
        
        # Set error
        error_msg = "Database connection failed"
        success = await service.set_task_result(
            task_id,
            {"status": "error"},
            error=error_msg
        )
        assert success is True
        
        # Verify error is stored
        status = await service.get_task_status(task_id)
        assert status.error == error_msg


class TestTaskListing:
    """Test task listing and filtering."""
    
    @pytest.mark.asyncio
    async def test_list_tenant_tasks(self):
        """Test listing tasks for a tenant."""
        service = TaskService()
        
        # Submit multiple tasks
        for i in range(3):
            await service.submit_task(
                tenant_id="tenant_001",
                user_id="user_123",
                task_type="code_review",
                task_config={}
            )
        
        # List tasks
        tasks, total = await service.list_tenant_tasks("tenant_001", limit=10)
        
        assert len(tasks) == 3
        assert total == 3
    
    @pytest.mark.asyncio
    async def test_list_tasks_pagination(self):
        """Test task listing pagination."""
        service = TaskService()
        
        # Submit 25 tasks
        for i in range(25):
            await service.submit_task(
                tenant_id="tenant_001",
                user_id="user_123",
                task_type="code_review",
                task_config={}
            )
        
        # List first page
        page1, total = await service.list_tenant_tasks(
            "tenant_001",
            limit=10,
            offset=0
        )
        
        assert len(page1) == 10
        assert total == 25
        
        # List second page
        page2, _ = await service.list_tenant_tasks(
            "tenant_001",
            limit=10,
            offset=10
        )
        
        assert len(page2) == 10
        assert page1[0].task_id != page2[0].task_id
    
    @pytest.mark.asyncio
    async def test_list_tasks_status_filter(self):
        """Test task listing with status filter."""
        service = TaskService()
        
        # Submit and complete one task
        response1 = await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={}
        )
        task_id_1 = response1.task_id
        # Follow proper state transition sequence
        await service.transition_task_state(task_id_1, TaskStatus.PLANNING)
        await service.transition_task_state(task_id_1, TaskStatus.SAFETY_REVIEW)
        await service.transition_task_state(task_id_1, TaskStatus.EXECUTING)
        await service.transition_task_state(task_id_1, TaskStatus.COMPLETE)
        
        # Submit another task (leave as submitted)
        await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={}
        )
        
        # List completed tasks
        completed, total = await service.list_tenant_tasks(
            "tenant_001",
            status_filter=TaskStatus.COMPLETE
        )
        
        assert len(completed) == 1
        assert total == 1
        assert completed[0].current_state == TaskStatus.COMPLETE


class TestTaskTiming:
    """Test task timing and duration calculations."""
    
    @pytest.mark.asyncio
    async def test_task_timestamps(self):
        """Test that task timestamps are set correctly."""
        service = TaskService()
        
        submit_response = await service.submit_task(
            tenant_id="tenant_001",
            user_id="user_123",
            task_type="code_review",
            task_config={}
        )
        task_id = submit_response.task_id
        
        # Get status
        status1 = await service.get_task_status(task_id)
        assert status1.submitted_at is not None
        assert status1.started_at is None  # Not started yet
        
        # Transition to executing
        await service.transition_task_state(task_id, TaskStatus.PLANNING)
        await service.transition_task_state(task_id, TaskStatus.SAFETY_REVIEW)
        await service.transition_task_state(task_id, TaskStatus.EXECUTING)
        
        # Get status after starting
        status2 = await service.get_task_status(task_id)
        assert status2.started_at is not None
        assert status2.completed_at is None
        
        # Complete task
        await service.transition_task_state(task_id, TaskStatus.COMPLETE)
        
        # Get final status
        status3 = await service.get_task_status(task_id)
        assert status3.completed_at is not None
        assert status3.duration_seconds is not None
        assert status3.duration_seconds >= 0

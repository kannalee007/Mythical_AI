"""
Tasks router — task submission, planning, execution, streaming.

Endpoints:
  POST   /              — Submit new task (returns plan)
  POST   /{task_id}/execute   — Execute approved plan
  GET    /{task_id}     — Get task status
  WebSocket /stream     — Stream task lifecycle events
"""

from fastapi import APIRouter, Depends, HTTPException, status, WebSocket
import json
import asyncio

from api.models.task import TaskRequest, TaskResponse, PlanResponse
from api.services import OrchestratorService
from api.dependencies import get_orchestrator_service

router = APIRouter()


@router.post("/", response_model=PlanResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_task(
    task_req: TaskRequest,
    orch_svc: OrchestratorService = Depends(get_orchestrator_service),
):
    """
    Submit a task and receive execution plan from Weaver.
    
    - **description**: natural language task description
    - **tenant_id**: tenant isolation
    - **require_approval**: force human approval
    - **timeout_seconds**: max execution time
    
    Returns: execution plan with steps, safety_tags, violations
    """
    plan = await orch_svc.plan_task(
        task_id="placeholder",  # Will be generated
        request=task_req.description,
        tenant_id=task_req.tenant_id,
    )
    
    return PlanResponse(**plan)


@router.post("/{task_id}/execute", status_code=status.HTTP_202_ACCEPTED)
async def execute_task(
    task_id: str,
    plan_data: dict,
    orch_svc: OrchestratorService = Depends(get_orchestrator_service),
):
    """
    Execute an approved plan inside sandbox.
    
    Requires plan dict with steps and metadata.
    """
    # TODO: Validate task_id exists, plan is approved, etc.
    
    return {
        "message": "Task execution queued",
        "task_id": task_id,
    }


@router.websocket("/stream")
async def websocket_stream(
    websocket: WebSocket,
    orch_svc: OrchestratorService = Depends(get_orchestrator_service),
):
    """
    WebSocket endpoint for real-time task streaming.
    
    Expected client message:
    {
        "task": {
            "description": "Analyze CSV data...",
            "tenant_id": "tenant_123",
            "require_approval": false,
            "timeout_seconds": 600
        }
    }
    
    Server sends events at each pipeline stage:
    {"stage": "planning", "message": "...", "data": {...}}
    {"stage": "safety", "message": "...", "data": {...}}
    {"stage": "executing", "message": "...", "data": {...}}
    {"stage": "complete", "status": "completed", "data": {...}}
    """
    await websocket.accept()
    
    try:
        # Wait for task submission
        message = await websocket.receive_text()
        task_request = json.loads(message)["task"]
        
        # Stream task lifecycle
        async for event in orch_svc.stream_task_lifecycle(
            task_request=task_request,
            require_human_approval=task_request.get("require_approval", False)
        ):
            await websocket.send_json(event)
            # Small delay to allow client to render
            await asyncio.sleep(0.1)
    
    except json.JSONDecodeError:
        await websocket.send_json({"error": "Invalid JSON in message"})
        await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
    except Exception as e:
        print(f"[WebSocket Error] {e}")
        await websocket.send_json({"error": str(e)})
        await websocket.close(code=status.WS_1011_SERVER_ERROR)


@router.get("/{task_id}")
async def get_task_status(task_id: str):
    """
    Get current status of a task.
    
    Returns: task dict with plan, execution, current_stage
    """
    # TODO: Query Neo4j for task_id nodes
    return {
        "task_id": task_id,
        "status": "pending",
        "message": "Task tracking not yet implemented",
    }

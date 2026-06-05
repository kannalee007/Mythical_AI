"""
Audit router — Neo4j audit log queries and compliance.

Endpoints:
  GET    /tasks         — Query task execution history
  GET    /violations    — Query safety violations
  GET    /compliance    — Tenant compliance report
  GET    /user/{id}     — User activity log
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from pydantic import ValidationError

from api.dependencies import get_audit_service
from api.models.audit import (
    AuditLogResponse,
    ComplianceReport,
    SeverityLevel,
    UserActivityLog,
)

router = APIRouter()


@router.get(
    "/tasks",
    response_model=AuditLogResponse,
    summary="Query task audit history",
    tags=["audit"]
)
async def get_task_history(
    task_id: Optional[str] = Query(None, description="Filter by task ID"),
    tenant_id: Optional[str] = Query(None, description="Filter by tenant"),
    limit: int = Query(100, ge=1, le=1000, description="Max results (1-1000)"),
    offset: int = Query(0, ge=0, description="Result offset for pagination"),
    audit_service = Depends(get_audit_service)
):
    """
    Query task execution history from Neo4j.
    
    Returns audit events for tasks with optional filtering.
    
    **Filters**:
    - `task_id`: Get events for specific task
    - `tenant_id`: Filter by tenant context
    
    **Pagination**:
    - `limit`: Max results per page (1-1000, default 100)
    - `offset`: Skip N results (for pagination)
    
    **Response**:
    - `events`: Array of AuditEvent objects
    - `total_count`: Total matching events (before pagination)
    - `page`: Current page number (1-indexed)
    - `has_more`: Whether more results available
    """
    try:
        if task_id:
            return await audit_service.get_task_audit_log(
                task_id=task_id,
                limit=limit,
                offset=offset
            )
        else:
            # TODO: Phase 3 - implement tenant-wide query with filtering
            return AuditLogResponse(
                events=[],
                total_count=0,
                page=offset // limit + 1,
                page_size=limit,
                has_more=False
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Audit query failed: {str(e)}"
        )


@router.get(
    "/violations",
    response_model=AuditLogResponse,
    summary="Query safety violations",
    tags=["audit"]
)
async def get_violations(
    tenant_id: Optional[str] = Query(None, description="Filter by tenant"),
    severity: Optional[str] = Query(None, description="Filter by severity: critical|error|warning|info"),
    rule_id: Optional[str] = Query(None, description="Filter by safety rule"),
    limit: int = Query(50, ge=1, le=1000, description="Max results (1-1000)"),
    offset: int = Query(0, ge=0, description="Result offset"),
    audit_service = Depends(get_audit_service)
):
    """
    Query safety violations detected by Constitution.
    
    **Filters**:
    - `tenant_id`: Filter by tenant
    - `severity`: Critical, error, warning, or info level violations
    - `rule_id`: Violations from specific safety rule
    
    **Response**:
    - `events`: Array of violation events (with rule details)
    - `total_count`: Total matching violations
    - `page`: Current page (1-indexed)
    - `has_more`: More results available
    """
    try:
        severity_level = None
        if severity:
            try:
                severity_level = SeverityLevel(severity.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid severity: {severity}. Must be: critical, error, warning, info"
                )
        
        return await audit_service.query_violations(
            tenant_id=tenant_id,
            severity=severity_level,
            rule_id=rule_id,
            limit=limit,
            offset=offset
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Violation query failed: {str(e)}"
        )


@router.get(
    "/compliance",
    response_model=ComplianceReport,
    summary="Get tenant compliance report",
    tags=["audit", "compliance"]
)
async def get_compliance_report(
    tenant_id: str = Query(..., description="Tenant to report on"),
    start_date: Optional[str] = Query(
        None,
        description="Report period start (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)"
    ),
    end_date: Optional[str] = Query(
        None,
        description="Report period end (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)"
    ),
    audit_service = Depends(get_audit_service)
):
    """
    Generate compliance report for a tenant.
    
    Calculates compliance score, violations, and recommendations
    for the specified time period.
    
    **Parameters**:
    - `tenant_id`: (required) Tenant to report on
    - `start_date`: Report period start (defaults to 30 days ago)
    - `end_date`: Report period end (defaults to now)
    
    **Response**:
    - `compliance_score`: 0-100 percentage
    - `violations_detected`: Total violations in period
    - `critical_violations`: Count of critical-level violations
    - `recommendations`: Actionable compliance suggestions
    """
    try:
        date_range = None
        if start_date or end_date:
            try:
                start = (
                    datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                    if start_date
                    else datetime.utcnow()
                )
                end = (
                    datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    if end_date
                    else datetime.utcnow()
                )
                
                if start > end:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="start_date must be before end_date"
                    )
                
                date_range = (start, end)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid date format. Use ISO 8601: {str(e)}"
                )
        
        return await audit_service.query_compliance_events(
            tenant_id=tenant_id,
            date_range=date_range
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Compliance report failed: {str(e)}"
        )


@router.get(
    "/user/{user_id}",
    response_model=UserActivityLog,
    summary="Get user activity log",
    tags=["audit"]
)
async def get_user_activity(
    user_id: str = Path(..., description="User ID to query"),
    limit: int = Query(50, ge=1, le=500, description="Max events (1-500)"),
    audit_service = Depends(get_audit_service)
):
    """
    Get activity log for a specific user.
    
    **Parameters**:
    - `user_id`: (required) User ID to query
    - `limit`: Max events to return (default 50)
    
    **Response**:
    - `events`: Recent audit events for this user
    - `total_tasks_submitted`: Lifetime count
    - `total_violations_triggered`: Lifetime count
    - `last_activity`: Timestamp of most recent action
    """
    try:
        return await audit_service.get_user_activity_log(
            user_id=user_id,
            limit=limit
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Activity log query failed: {str(e)}"
        )

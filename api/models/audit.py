"""Audit and compliance data models."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class AuditEventType(str, Enum):
    """Types of audit events."""
    TASK_SUBMITTED = "task_submitted"
    TASK_PLANNED = "task_planned"
    SAFETY_CHECK_PASSED = "safety_check_passed"
    SAFETY_CHECK_FAILED = "safety_check_failed"
    TASK_EXECUTED = "task_executed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_BLOCKED = "task_blocked"
    TASK_CANCELLED = "task_cancelled"
    VIOLATION_DETECTED = "violation_detected"
    POLICY_ENFORCED = "policy_enforced"


class SeverityLevel(str, Enum):
    """Severity levels for violations and events."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditEvent(BaseModel):
    """Single audit log entry."""
    event_id: str = Field(..., description="Unique event ID from Neo4j")
    task_id: str = Field(..., description="Associated task ID")
    user_id: str = Field(..., description="User who triggered event")
    tenant_id: str = Field(..., description="Tenant context")
    event_type: AuditEventType = Field(..., description="Type of event")
    timestamp: datetime = Field(..., description="When event occurred")
    severity: SeverityLevel = Field(default=SeverityLevel.INFO, description="Event severity")
    details: dict[str, Any] = Field(default_factory=dict, description="Event metadata")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "event_id": "evt_123",
                "task_id": "task_456",
                "user_id": "user_789",
                "tenant_id": "tenant_001",
                "event_type": "task_completed",
                "timestamp": "2026-05-31T10:30:00Z",
                "severity": "info",
                "details": {"result": "success", "duration_ms": 5234}
            }
        }
    }


class ViolationRecord(BaseModel):
    """Safety violation record from Constitution."""
    violation_id: str = Field(..., description="Unique violation ID")
    task_id: str = Field(..., description="Task that triggered violation")
    tenant_id: str = Field(..., description="Tenant context")
    severity: SeverityLevel = Field(..., description="Violation severity")
    rule_name: str = Field(..., description="Safety rule that was violated")
    rule_id: str = Field(..., description="ID of the violated rule")
    description: str = Field(..., description="Human-readable violation description")
    affected_resources: list[str] = Field(default_factory=list, description="Resources affected")
    detected_at: datetime = Field(..., description="When violation was detected")
    auto_blocked: bool = Field(default=False, description="Was task auto-blocked?")
    remediation_steps: list[str] = Field(default_factory=list, description="Suggested fixes")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "violation_id": "viol_123",
                "task_id": "task_456",
                "tenant_id": "tenant_001",
                "severity": "critical",
                "rule_name": "filesystem_modify_restricted",
                "rule_id": "rule_fs_001",
                "description": "Attempted modification to /etc/passwd",
                "affected_resources": ["/etc/passwd"],
                "detected_at": "2026-05-31T10:30:00Z",
                "auto_blocked": True,
                "remediation_steps": ["Review task scope", "Use sandbox mode"]
            }
        }
    }


class AuditLogResponse(BaseModel):
    """Paginated audit log results."""
    events: list[AuditEvent] = Field(..., description="Audit events in result set")
    total_count: int = Field(..., description="Total matching events (before pagination)")
    page: int = Field(..., description="Current page (1-indexed)")
    page_size: int = Field(..., description="Events per page")
    has_more: bool = Field(..., description="Whether more results available")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "events": [
                    {
                        "event_id": "evt_123",
                        "task_id": "task_456",
                        "user_id": "user_789",
                        "tenant_id": "tenant_001",
                        "event_type": "task_completed",
                        "timestamp": "2026-05-31T10:30:00Z",
                        "severity": "info",
                        "details": {"result": "success"}
                    }
                ],
                "total_count": 150,
                "page": 1,
                "page_size": 10,
                "has_more": True
            }
        }
    }


class ComplianceReport(BaseModel):
    """Compliance metrics summary."""
    tenant_id: str = Field(..., description="Tenant being reported on")
    report_period_start: datetime = Field(..., description="Report period start")
    report_period_end: datetime = Field(..., description="Report period end")
    total_tasks: int = Field(..., description="Total tasks executed")
    completed_tasks: int = Field(..., description="Successfully completed")
    failed_tasks: int = Field(..., description="Failed tasks")
    blocked_tasks: int = Field(..., description="Tasks blocked by safety")
    violations_detected: int = Field(..., description="Total violations detected")
    critical_violations: int = Field(..., description="Critical-level violations")
    compliance_score: float = Field(..., ge=0, le=100, description="Compliance percentage (0-100)")
    top_violations: list[str] = Field(default_factory=list, description="Most common violations")
    recommendations: list[str] = Field(default_factory=list, description="Compliance recommendations")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_001",
                "report_period_start": "2026-05-01T00:00:00Z",
                "report_period_end": "2026-05-31T23:59:59Z",
                "total_tasks": 150,
                "completed_tasks": 140,
                "failed_tasks": 5,
                "blocked_tasks": 5,
                "violations_detected": 8,
                "critical_violations": 2,
                "compliance_score": 96.7,
                "top_violations": ["filesystem_modify_restricted", "network_access_denied"],
                "recommendations": ["Review custom rules", "Increase task timeouts"]
            }
        }
    }


class UserActivityLog(BaseModel):
    """Activity log for a specific user."""
    user_id: str = Field(..., description="User being tracked")
    events: list[AuditEvent] = Field(..., description="User's audit events")
    total_tasks_submitted: int = Field(..., description="Total tasks this user submitted")
    total_violations_triggered: int = Field(..., description="Total violations by this user")
    last_activity: Optional[datetime] = Field(default=None, description="Last activity timestamp")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": "user_789",
                "events": [],
                "total_tasks_submitted": 42,
                "total_violations_triggered": 2,
                "last_activity": "2026-05-31T10:30:00Z"
            }
        }
    }

"""Tests for audit service and API endpoints."""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from api.main import app
from api.models.audit import AuditEventType, SeverityLevel
from api.services.audit_service import AuditService

client = TestClient(app)


class TestAuditServiceBasic:
    """Test AuditService basic functionality."""
    
    @pytest.mark.asyncio
    async def test_audit_service_initialization(self):
        """Test AuditService can be initialized."""
        service = AuditService()
        assert service is not None
        assert service._fallback_mode is True  # No persistence module
    
    @pytest.mark.asyncio
    async def test_get_task_audit_log_fallback(self):
        """Test audit log query in fallback mode."""
        service = AuditService()
        result = await service.get_task_audit_log(
            task_id="task_123",
            limit=100,
            offset=0
        )
        
        assert result is not None
        assert result.total_count == 0
        assert len(result.events) == 0
        assert result.has_more is False


class TestAuditEndpoints:
    """Test audit API endpoints."""
    
    def test_get_task_history_no_task_id(self):
        """Test task history endpoint without task_id filter."""
        response = client.get(
            "/api/v1/audit/tasks",
            params={"limit": 10}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "total_count" in data
        assert "has_more" in data
    
    def test_get_task_history_with_task_id(self):
        """Test task history endpoint with task_id filter."""
        response = client.get(
            "/api/v1/audit/tasks",
            params={"task_id": "task_123", "limit": 100}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert isinstance(data["events"], list)
    
    def test_get_task_history_pagination(self):
        """Test task history pagination parameters."""
        response = client.get(
            "/api/v1/audit/tasks",
            params={"limit": 50, "offset": 0}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["page_size"] == 50
    
    def test_get_violations_no_filter(self):
        """Test violations endpoint without filters."""
        response = client.get("/api/v1/audit/violations")
        
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "total_count" in data
    
    def test_get_violations_with_severity_filter(self):
        """Test violations with severity filter."""
        response = client.get(
            "/api/v1/audit/violations",
            params={"severity": "critical"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
    
    def test_get_violations_invalid_severity(self):
        """Test violations with invalid severity level."""
        response = client.get(
            "/api/v1/audit/violations",
            params={"severity": "invalid_severity"}
        )
        
        assert response.status_code == 400
        data = response.json()
        # HTTPException puts it in 'detail' key
        assert "Invalid severity" in str(data)
    
    def test_get_compliance_report(self):
        """Test compliance report endpoint."""
        response = client.get(
            "/api/v1/audit/compliance",
            params={"tenant_id": "tenant_001"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "tenant_id" in data
        assert "compliance_score" in data
        assert "violations_detected" in data
        assert "recommendations" in data
    
    def test_get_compliance_report_with_date_range(self):
        """Test compliance report with date range."""
        start_date = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
        end_date = datetime.utcnow().isoformat() + "Z"
        
        response = client.get(
            "/api/v1/audit/compliance",
            params={
                "tenant_id": "tenant_001",
                "start_date": start_date,
                "end_date": end_date
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["report_period_start"] is not None
        assert data["report_period_end"] is not None
    
    def test_get_compliance_report_invalid_date_range(self):
        """Test compliance report with invalid date range."""
        end_date = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
        start_date = datetime.utcnow().isoformat() + "Z"
        
        response = client.get(
            "/api/v1/audit/compliance",
            params={
                "tenant_id": "tenant_001",
                "start_date": start_date,
                "end_date": end_date
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "before end_date" in str(data)
    
    def test_get_user_activity_log(self):
        """Test user activity log endpoint."""
        response = client.get(
            "/api/v1/audit/user/user_123",
            params={"limit": 50}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "user_123"
        assert "events" in data
        assert "total_tasks_submitted" in data
        assert "total_violations_triggered" in data
    
    def test_get_user_activity_log_limit_validation(self):
        """Test user activity log with limit validation."""
        # Test limit too high
        response = client.get(
            "/api/v1/audit/user/user_123",
            params={"limit": 1000}
        )
        
        # Should fail validation (max 500)
        assert response.status_code == 422


class TestAuditDataModels:
    """Test audit data model validation."""
    
    def test_audit_event_model(self):
        """Test AuditEvent Pydantic model."""
        from api.models.audit import AuditEvent
        
        event = AuditEvent(
            event_id="evt_123",
            task_id="task_456",
            user_id="user_789",
            tenant_id="tenant_001",
            event_type=AuditEventType.TASK_COMPLETED,
            timestamp=datetime.utcnow(),
            severity=SeverityLevel.INFO,
            details={"key": "value"}
        )
        
        assert event.event_id == "evt_123"
        assert event.task_id == "task_456"
        assert event.event_type == AuditEventType.TASK_COMPLETED
    
    def test_violation_record_model(self):
        """Test ViolationRecord Pydantic model."""
        from api.models.audit import ViolationRecord
        
        violation = ViolationRecord(
            violation_id="viol_123",
            task_id="task_456",
            tenant_id="tenant_001",
            severity=SeverityLevel.CRITICAL,
            rule_name="filesystem_modify_restricted",
            rule_id="rule_fs_001",
            description="Attempted modification to /etc/passwd",
            affected_resources=["/etc/passwd"],
            detected_at=datetime.utcnow(),
            auto_blocked=True
        )
        
        assert violation.violation_id == "viol_123"
        assert violation.severity == SeverityLevel.CRITICAL
        assert violation.auto_blocked is True
    
    def test_compliance_report_model(self):
        """Test ComplianceReport Pydantic model."""
        from api.models.audit import ComplianceReport
        
        now = datetime.utcnow()
        report = ComplianceReport(
            tenant_id="tenant_001",
            report_period_start=now - timedelta(days=30),
            report_period_end=now,
            total_tasks=100,
            completed_tasks=95,
            failed_tasks=3,
            blocked_tasks=2,
            violations_detected=5,
            critical_violations=1,
            compliance_score=97.0,
            top_violations=["rule_1", "rule_2"],
            recommendations=["Review policies"]
        )
        
        assert report.compliance_score == 97.0
        assert report.total_tasks == 100
        assert len(report.top_violations) == 2

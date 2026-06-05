"""Audit service for Neo4j audit log queries."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from api.models.audit import (
    AuditEvent,
    AuditEventType,
    AuditLogResponse,
    ComplianceReport,
    SeverityLevel,
    UserActivityLog,
    ViolationRecord,
)

logger = logging.getLogger(__name__)


class AuditService:
    """Wraps orchestrator persistence module for audit queries."""

    def __init__(self, persistence=None, custom_rules=None):
        """Initialize audit service.
        
        Args:
            persistence: orchestrator.persistence.Persistence instance (optional for fallback)
            custom_rules: orchestrator.custom_rules.CustomRules instance (optional)
        """
        self.persistence = persistence
        self.custom_rules = custom_rules
        self._fallback_mode = persistence is None

    async def get_task_audit_log(
        self,
        task_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> AuditLogResponse:
        """Get audit log for a specific task.
        
        Args:
            task_id: Task ID to query
            limit: Max results to return
            offset: Result offset for pagination
            
        Returns:
            AuditLogResponse with events and pagination info
        """
        try:
            if self._fallback_mode:
                logger.warning(f"Audit service in fallback mode, returning empty logs for task {task_id}")
                return AuditLogResponse(
                    events=[],
                    total_count=0,
                    page=1,
                    page_size=limit,
                    has_more=False
                )
            
            # Query via persistence (Neo4j)
            results = await self._query_audit_log_neo4j(
                query_filter={"task_id": task_id},
                limit=limit,
                offset=offset
            )
            
            total_count = results.get("total_count", 0)
            events = [self._parse_audit_event(evt) for evt in results.get("events", [])]
            
            return AuditLogResponse(
                events=events,
                total_count=total_count,
                page=offset // limit + 1,
                page_size=limit,
                has_more=(offset + limit) < total_count
            )
        except Exception as e:
            logger.error(f"Error querying audit log for task {task_id}: {e}")
            raise

    async def query_violations(
        self,
        tenant_id: Optional[str] = None,
        severity: Optional[SeverityLevel] = None,
        rule_id: Optional[str] = None,
        date_range: Optional[tuple[datetime, datetime]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> AuditLogResponse:
        """Query safety violations with filtering.
        
        Args:
            tenant_id: Filter by tenant
            severity: Filter by severity level
            rule_id: Filter by specific rule
            date_range: (start, end) datetime tuple
            limit: Max results
            offset: Pagination offset
            
        Returns:
            AuditLogResponse containing ViolationRecords
        """
        try:
            if self._fallback_mode:
                logger.warning("Audit service in fallback mode, returning empty violations")
                return AuditLogResponse(
                    events=[],
                    total_count=0,
                    page=1,
                    page_size=limit,
                    has_more=False
                )
            
            query_filter = {}
            if tenant_id:
                query_filter["tenant_id"] = tenant_id
            if severity:
                query_filter["severity"] = severity.value
            if rule_id:
                query_filter["rule_id"] = rule_id
            if date_range:
                query_filter["start_date"] = date_range[0].isoformat()
                query_filter["end_date"] = date_range[1].isoformat()
            
            results = await self._query_violations_neo4j(
                query_filter=query_filter,
                limit=limit,
                offset=offset
            )
            
            total_count = results.get("total_count", 0)
            violations = [
                self._parse_violation_record(viol)
                for viol in results.get("violations", [])
            ]
            
            # Convert violations to events for compatibility
            events = [
                AuditEvent(
                    event_id=v.violation_id,
                    task_id=v.task_id,
                    user_id="system",
                    tenant_id=v.tenant_id,
                    event_type=AuditEventType.VIOLATION_DETECTED,
                    timestamp=v.detected_at,
                    severity=v.severity,
                    details={
                        "rule_name": v.rule_name,
                        "description": v.description,
                        "auto_blocked": v.auto_blocked
                    }
                )
                for v in violations
            ]
            
            return AuditLogResponse(
                events=events,
                total_count=total_count,
                page=offset // limit + 1,
                page_size=limit,
                has_more=(offset + limit) < total_count
            )
        except Exception as e:
            logger.error(f"Error querying violations: {e}")
            raise

    async def query_compliance_events(
        self,
        tenant_id: str,
        date_range: Optional[tuple[datetime, datetime]] = None
    ) -> ComplianceReport:
        """Generate compliance report for a tenant.
        
        Args:
            tenant_id: Tenant to report on
            date_range: (start, end) datetime tuple. Defaults to last 30 days
            
        Returns:
            ComplianceReport with metrics and recommendations
        """
        try:
            if not date_range:
                date_range = (
                    datetime.utcnow() - timedelta(days=30),
                    datetime.utcnow()
                )
            
            if self._fallback_mode:
                logger.warning(f"Audit service in fallback mode for tenant {tenant_id}")
                return ComplianceReport(
                    tenant_id=tenant_id,
                    report_period_start=date_range[0],
                    report_period_end=date_range[1],
                    total_tasks=0,
                    completed_tasks=0,
                    failed_tasks=0,
                    blocked_tasks=0,
                    violations_detected=0,
                    critical_violations=0,
                    compliance_score=100.0,
                    top_violations=[],
                    recommendations=["Configure Neo4j connection"]
                )
            
            results = await self._query_compliance_neo4j(
                tenant_id=tenant_id,
                start_date=date_range[0],
                end_date=date_range[1]
            )
            
            # Calculate compliance score
            total = results.get("total_tasks", 1)
            blocked = results.get("blocked_tasks", 0)
            compliance_score = ((total - blocked) / total * 100) if total > 0 else 100.0
            
            return ComplianceReport(
                tenant_id=tenant_id,
                report_period_start=date_range[0],
                report_period_end=date_range[1],
                total_tasks=results.get("total_tasks", 0),
                completed_tasks=results.get("completed_tasks", 0),
                failed_tasks=results.get("failed_tasks", 0),
                blocked_tasks=blocked,
                violations_detected=results.get("violations_detected", 0),
                critical_violations=results.get("critical_violations", 0),
                compliance_score=compliance_score,
                top_violations=results.get("top_violations", []),
                recommendations=self._generate_recommendations(results)
            )
        except Exception as e:
            logger.error(f"Error generating compliance report: {e}")
            raise

    async def get_user_activity_log(
        self,
        user_id: str,
        limit: int = 50
    ) -> UserActivityLog:
        """Get activity log for a specific user.
        
        Args:
            user_id: User ID to query
            limit: Max events to return
            
        Returns:
            UserActivityLog with events and statistics
        """
        try:
            if self._fallback_mode:
                logger.warning(f"Audit service in fallback mode for user {user_id}")
                return UserActivityLog(
                    user_id=user_id,
                    events=[],
                    total_tasks_submitted=0,
                    total_violations_triggered=0,
                    last_activity=None
                )
            
            results = await self._query_user_activity_neo4j(
                user_id=user_id,
                limit=limit
            )
            
            events = [self._parse_audit_event(evt) for evt in results.get("events", [])]
            
            return UserActivityLog(
                user_id=user_id,
                events=events,
                total_tasks_submitted=results.get("total_tasks_submitted", 0),
                total_violations_triggered=results.get("total_violations_triggered", 0),
                last_activity=self._parse_datetime(results.get("last_activity"))
            )
        except Exception as e:
            logger.error(f"Error querying user activity for {user_id}: {e}")
            raise

    # Private helper methods

    async def _query_audit_log_neo4j(self, query_filter: dict, limit: int, offset: int) -> dict:
        """Query audit events from Neo4j.
        
        Override this method to connect to actual orchestrator.persistence
        """
        # In Phase 2, this is a stub. Phase 3 connects to real Neo4j via persistence module
        logger.debug(f"_query_audit_log_neo4j: filter={query_filter}, limit={limit}, offset={offset}")
        return {"events": [], "total_count": 0}

    async def _query_violations_neo4j(self, query_filter: dict, limit: int, offset: int) -> dict:
        """Query violations from Neo4j."""
        logger.debug(f"_query_violations_neo4j: filter={query_filter}, limit={limit}, offset={offset}")
        return {"violations": [], "total_count": 0}

    async def _query_compliance_neo4j(
        self,
        tenant_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> dict:
        """Query compliance metrics from Neo4j."""
        logger.debug(f"_query_compliance_neo4j: tenant={tenant_id}, period={start_date} to {end_date}")
        return {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "blocked_tasks": 0,
            "violations_detected": 0,
            "critical_violations": 0,
            "top_violations": [],
        }

    async def _query_user_activity_neo4j(self, user_id: str, limit: int) -> dict:
        """Query user activity from Neo4j."""
        logger.debug(f"_query_user_activity_neo4j: user={user_id}, limit={limit}")
        return {
            "events": [],
            "total_tasks_submitted": 0,
            "total_violations_triggered": 0,
            "last_activity": None,
        }

    def _parse_audit_event(self, event_data: dict) -> AuditEvent:
        """Parse Neo4j audit event into Pydantic model."""
        return AuditEvent(
            event_id=event_data.get("event_id", "unknown"),
            task_id=event_data.get("task_id", "unknown"),
            user_id=event_data.get("user_id", "system"),
            tenant_id=event_data.get("tenant_id", "default"),
            event_type=AuditEventType(event_data.get("event_type", "task_submitted")),
            timestamp=self._parse_datetime(event_data.get("timestamp")),
            severity=SeverityLevel(event_data.get("severity", "info")),
            details=event_data.get("details", {})
        )

    def _parse_violation_record(self, violation_data: dict) -> ViolationRecord:
        """Parse Neo4j violation into Pydantic model."""
        return ViolationRecord(
            violation_id=violation_data.get("violation_id", "unknown"),
            task_id=violation_data.get("task_id", "unknown"),
            tenant_id=violation_data.get("tenant_id", "default"),
            severity=SeverityLevel(violation_data.get("severity", "warning")),
            rule_name=violation_data.get("rule_name", "unknown"),
            rule_id=violation_data.get("rule_id", "unknown"),
            description=violation_data.get("description", ""),
            affected_resources=violation_data.get("affected_resources", []),
            detected_at=self._parse_datetime(violation_data.get("detected_at")),
            auto_blocked=violation_data.get("auto_blocked", False),
            remediation_steps=violation_data.get("remediation_steps", [])
        )

    def _parse_datetime(self, dt_value) -> datetime:
        """Parse datetime from various formats."""
        if isinstance(dt_value, datetime):
            return dt_value
        if isinstance(dt_value, str):
            try:
                return datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                pass
        return datetime.utcnow()

    def _generate_recommendations(self, compliance_results: dict) -> list[str]:
        """Generate compliance recommendations based on metrics."""
        recommendations = []
        
        blocked_ratio = (
            compliance_results.get("blocked_tasks", 0)
            / max(compliance_results.get("total_tasks", 1), 1)
        )
        
        if blocked_ratio > 0.1:
            recommendations.append("Review task scopes to reduce safety violations")
        
        if compliance_results.get("critical_violations", 0) > 0:
            recommendations.append("Address critical violations immediately")
        
        violations = compliance_results.get("violations_detected", 0)
        if violations > 50:
            recommendations.append("Consider updating safety rules to reduce false positives")
        
        if not recommendations:
            recommendations.append("Compliance is good. Continue monitoring.")
        
        return recommendations

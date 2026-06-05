"""
Dependency injection functions for FastAPI.

Separated from main.py to avoid circular imports.
All routers and tests import from here.
"""

import os
from typing import Optional
from api.services import AuthService, TenantService, OrchestratorService, AuditService, TaskService

# Global service instances (singleton pattern)
_auth_service: Optional[AuthService] = None
_tenant_service: Optional[TenantService] = None
_orchestrator_service: Optional[OrchestratorService] = None
_audit_service: Optional[AuditService] = None
_task_service: Optional[TaskService] = None


def get_auth_service() -> AuthService:
    """Dependency injection for AuthService."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


def get_tenant_service() -> TenantService:
    """Dependency injection for TenantService."""
    global _tenant_service
    if _tenant_service is None:
        _tenant_service = TenantService()
    return _tenant_service


def get_orchestrator_service() -> OrchestratorService:
    """Dependency injection for OrchestratorService."""
    global _orchestrator_service
    if _orchestrator_service is None:
        config_path = os.getenv("ORCHESTRATOR_CONFIG_PATH", "./config.yaml")
        _orchestrator_service = OrchestratorService(config_path=config_path)
    return _orchestrator_service


def get_audit_service() -> AuditService:
    """Dependency injection for AuditService."""
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service


def get_task_service() -> TaskService:
    """Dependency injection for TaskService."""
    global _task_service
    if _task_service is None:
        _task_service = TaskService()
    return _task_service

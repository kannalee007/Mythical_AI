"""
Tenant model definitions for multi-tenant API contracts.

Connects to:
  - orchestrator.tenancy for tenant isolation
  - orchestrator.custom_rules for tenant-specific policies
  - orchestrator.connectors.registry for connector management per tenant
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict, List, Any
from datetime import datetime


class TenantConfig(BaseModel):
    """Tenant configuration settings."""
    max_concurrent_tasks: int = Field(default=10, description="Max tasks running simultaneously")
    execution_timeout_seconds: int = Field(default=600, description="Default timeout per task")
    enable_rag: bool = Field(default=True, description="Enable VectorRAG memory")
    enable_audit_log: bool = Field(default=True, description="Write to Neo4j audit log")
    custom_constitution_rules: List[str] = Field(default_factory=list, description="Custom rule IDs")
    
    class Config:
        json_schema_extra = {
            "example": {
                "max_concurrent_tasks": 5,
                "execution_timeout_seconds": 300,
                "enable_rag": True,
                "enable_audit_log": True,
                "custom_constitution_rules": ["rule_no_external_api", "rule_data_residency"]
            }
        }


class TenantCreate(BaseModel):
    """Request to create a new tenant."""
    name: str = Field(..., description="Tenant organization name")
    email: EmailStr = Field(..., description="Admin email for notifications")
    config: Optional[TenantConfig] = Field(default_factory=TenantConfig, description="Tenant configuration")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Acme Corporation",
                "email": "admin@acme.com",
                "config": {
                    "max_concurrent_tasks": 5,
                    "execution_timeout_seconds": 300,
                    "enable_rag": True,
                    "enable_audit_log": True,
                    "custom_constitution_rules": []
                }
            }
        }


class TenantUpdate(BaseModel):
    """Request to update tenant configuration."""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    config: Optional[TenantConfig] = None


class TenantResponse(BaseModel):
    """Tenant response model."""
    tenant_id: str = Field(..., description="Unique tenant ID (UUID)")
    name: str = Field(..., description="Organization name")
    email: str = Field(..., description="Admin email")
    config: TenantConfig = Field(..., description="Current configuration")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    tasks_run: int = Field(default=0, description="Total tasks executed by tenant")
    tasks_blocked: int = Field(default=0, description="Tasks blocked by constitution")
    
    class Config:
        json_schema_extra = {
            "example": {
                "tenant_id": "tenant_xyz789",
                "name": "Acme Corporation",
                "email": "admin@acme.com",
                "config": {
                    "max_concurrent_tasks": 5,
                    "execution_timeout_seconds": 300,
                    "enable_rag": True,
                    "enable_audit_log": True,
                    "custom_constitution_rules": []
                },
                "created_at": "2026-01-15T10:00:00Z",
                "updated_at": "2026-05-31T12:00:00Z",
                "tasks_run": 42,
                "tasks_blocked": 3
            }
        }

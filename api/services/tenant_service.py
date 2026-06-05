"""
Tenant service for multi-tenant management.

Connects to:
  - orchestrator.tenancy for tenant isolation
  - orchestrator.custom_rules for tenant-specific policies
"""

from uuid import uuid4
from datetime import datetime
from typing import Optional, Dict, Any
from api.models.tenant import TenantConfig


class TenantService:
    """
    Tenant management service (stub for production database integration).
    
    In production, this queries PostgreSQL and calls orchestrator.tenancy
    to apply tenant-specific policies and custom rules.
    """
    
    def __init__(self):
        """Initialize tenant service with in-memory store (development only)."""
        self.tenants: Dict[str, Dict[str, Any]] = {}
    
    def create_tenant(self, name: str, email: str, config: Optional[TenantConfig] = None) -> dict:
        """
        Create a new tenant.
        
        Calls orchestrator.custom_rules to register tenant-specific policies.
        
        Returns:
            tenant dict with tenant_id, name, email, config, created_at, etc.
        """
        tenant_id = str(uuid4())
        
        tenant = {
            "tenant_id": tenant_id,
            "name": name,
            "email": email,
            "config": config or TenantConfig(),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "tasks_run": 0,
            "tasks_blocked": 0,
        }
        
        self.tenants[tenant_id] = tenant
        
        # TODO: Call orchestrator.custom_rules.register_tenant_rules(tenant_id, config.custom_constitution_rules)
        
        return tenant
    
    def get_tenant(self, tenant_id: str) -> Optional[dict]:
        """Retrieve tenant by ID."""
        return self.tenants.get(tenant_id)
    
    def update_tenant(self, tenant_id: str, name: Optional[str] = None,
                      email: Optional[str] = None, config: Optional[TenantConfig] = None) -> dict:
        """Update tenant configuration."""
        if tenant_id not in self.tenants:
            raise ValueError(f"Tenant {tenant_id} not found")
        
        tenant = self.tenants[tenant_id]
        
        if name is not None:
            tenant["name"] = name
        if email is not None:
            tenant["email"] = email
        if config is not None:
            tenant["config"] = config
            # TODO: Call orchestrator.custom_rules.update_tenant_rules(tenant_id, config.custom_constitution_rules)
        
        tenant["updated_at"] = datetime.utcnow()
        
        return tenant
    
    def list_tenants(self) -> list:
        """List all tenants (admin endpoint)."""
        return list(self.tenants.values())
    
    def delete_tenant(self, tenant_id: str) -> None:
        """Delete tenant and associated policies."""
        if tenant_id not in self.tenants:
            raise ValueError(f"Tenant {tenant_id} not found")
        
        # TODO: Call orchestrator.tenancy.cleanup_tenant(tenant_id) to remove policies, secrets, storage
        
        del self.tenants[tenant_id]
    
    def increment_tasks_run(self, tenant_id: str) -> None:
        """Increment task counter (called after task execution)."""
        if tenant_id in self.tenants:
            self.tenants[tenant_id]["tasks_run"] += 1
    
    def increment_tasks_blocked(self, tenant_id: str) -> None:
        """Increment blocked task counter (called when Constitution blocks a task)."""
        if tenant_id in self.tenants:
            self.tenants[tenant_id]["tasks_blocked"] += 1

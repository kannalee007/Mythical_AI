"""
Tenants router — multi-tenant CRUD operations (admin).

Endpoints:
  POST   /              — Create tenant
  GET    /              — List all tenants
  GET    /{tenant_id}   — Get tenant details
  PUT    /{tenant_id}   — Update tenant config
  DELETE /{tenant_id}   — Delete tenant
"""

from fastapi import APIRouter, Depends, HTTPException, status

from api.models.tenant import TenantCreate, TenantUpdate, TenantResponse
from api.services import TenantService
from api.dependencies import get_tenant_service

router = APIRouter()


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    tenant_data: TenantCreate,
    tenant_svc: TenantService = Depends(get_tenant_service),
):
    """
    Create a new tenant organization.
    
    - **name**: organization name
    - **email**: admin email for notifications
    - **config**: optional tenant configuration
    """
    tenant = tenant_svc.create_tenant(
        name=tenant_data.name,
        email=tenant_data.email,
        config=tenant_data.config,
    )
    return tenant


@router.get("/", response_model=list[TenantResponse])
async def list_tenants(
    tenant_svc: TenantService = Depends(get_tenant_service),
):
    """
    List all tenants (admin endpoint).
    """
    return tenant_svc.list_tenants()


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    tenant_svc: TenantService = Depends(get_tenant_service),
):
    """
    Get tenant details by ID.
    """
    tenant = tenant_svc.get_tenant(tenant_id)
    
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )
    
    return tenant


@router.put("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: str,
    tenant_data: TenantUpdate,
    tenant_svc: TenantService = Depends(get_tenant_service),
):
    """
    Update tenant configuration.
    
    - **name**: (optional) new organization name
    - **email**: (optional) new admin email
    - **config**: (optional) new configuration
    """
    try:
        tenant = tenant_svc.update_tenant(
            tenant_id=tenant_id,
            name=tenant_data.name,
            email=tenant_data.email,
            config=tenant_data.config,
        )
        return tenant
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    tenant_svc: TenantService = Depends(get_tenant_service),
):
    """
    Delete a tenant and all associated policies, secrets, audit logs.
    """
    try:
        tenant_svc.delete_tenant(tenant_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

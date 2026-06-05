"""
Test suite for tenant management endpoints.

Tests:
  - Create tenant
  - Get tenant
  - List tenants
  - Update tenant
  - Delete tenant
"""

import pytest
from fastapi.testclient import TestClient
from api.main import app


client = TestClient(app)


def test_create_tenant():
    """Test tenant creation."""
    response = client.post(
        "/api/v1/tenants/",
        json={
            "name": "Test Corporation",
            "email": "admin@test.com",
            "config": {
                "max_concurrent_tasks": 5,
                "execution_timeout_seconds": 300,
            }
        }
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Corporation"
    assert data["email"] == "admin@test.com"
    assert "tenant_id" in data
    assert data["tasks_run"] == 0
    assert data["tasks_blocked"] == 0


def test_get_tenant():
    """Test retrieving tenant."""
    # Create tenant
    create_response = client.post(
        "/api/v1/tenants/",
        json={
            "name": "Get Test Tenant",
            "email": "get@test.com",
        }
    )
    tenant_id = create_response.json()["tenant_id"]
    
    # Get tenant
    response = client.get(f"/api/v1/tenants/{tenant_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == tenant_id
    assert data["name"] == "Get Test Tenant"


def test_get_nonexistent_tenant():
    """Test getting non-existent tenant."""
    response = client.get("/api/v1/tenants/nonexistent_id")
    
    assert response.status_code == 404


def test_list_tenants():
    """Test listing all tenants."""
    # Create a couple tenants
    client.post(
        "/api/v1/tenants/",
        json={"name": "Tenant 1", "email": "tenant1@test.com"}
    )
    client.post(
        "/api/v1/tenants/",
        json={"name": "Tenant 2", "email": "tenant2@test.com"}
    )
    
    # List tenants
    response = client.get("/api/v1/tenants/")
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    assert any(t["name"] == "Tenant 1" for t in data)
    assert any(t["name"] == "Tenant 2" for t in data)


def test_update_tenant():
    """Test updating tenant configuration."""
    # Create tenant
    create_response = client.post(
        "/api/v1/tenants/",
        json={"name": "Update Test", "email": "update@test.com"}
    )
    tenant_id = create_response.json()["tenant_id"]
    
    # Update tenant
    response = client.put(
        f"/api/v1/tenants/{tenant_id}",
        json={
            "name": "Updated Name",
            "config": {
                "max_concurrent_tasks": 10,
            }
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["config"]["max_concurrent_tasks"] == 10


def test_delete_tenant():
    """Test deleting tenant."""
    # Create tenant
    create_response = client.post(
        "/api/v1/tenants/",
        json={"name": "Delete Test", "email": "delete@test.com"}
    )
    tenant_id = create_response.json()["tenant_id"]
    
    # Delete tenant
    response = client.delete(f"/api/v1/tenants/{tenant_id}")
    
    assert response.status_code == 204
    
    # Verify it's gone
    response = client.get(f"/api/v1/tenants/{tenant_id}")
    assert response.status_code == 404

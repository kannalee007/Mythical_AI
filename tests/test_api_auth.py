"""
Test suite for API auth endpoints.

Tests:
  - User registration
  - User login
  - Token verification
  - Get current user
"""

import pytest
from fastapi.testclient import TestClient
from api.main import app
from api.services import AuthService


client = TestClient(app)


@pytest.fixture
def auth_service():
    """Provide fresh auth service for each test."""
    return AuthService()


def test_register_user():
    """Test user registration."""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "test@example.com",
            "password": "TestPassword123",
            "full_name": "Test User",
            "tenant_id": "tenant_test",
        }
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["full_name"] == "Test User"
    assert "user_id" in data
    assert "hashed_password" not in data  # Password should not be returned


def test_register_duplicate_user():
    """Test that duplicate email fails."""
    # Register first user
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "TestPassword123",
            "full_name": "User One",
            "tenant_id": "tenant_test",
        }
    )
    
    # Try to register same email
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "DifferentPassword123",
            "full_name": "User Two",
            "tenant_id": "tenant_test",
        }
    )
    
    assert response.status_code == 400


def test_login_user():
    """Test user login."""
    # Register user
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "login@example.com",
            "password": "LoginTest123",
            "full_name": "Login User",
            "tenant_id": "tenant_test",
        }
    )
    
    # Login
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "login@example.com",
            "password": "LoginTest123",
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert "access_token" in data
    assert data["expires_in"] > 0
    assert data["user"]["email"] == "login@example.com"


def test_login_invalid_password():
    """Test login with wrong password."""
    # Register user
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "wrongpass@example.com",
            "password": "CorrectPassword123",
            "full_name": "Wrong Pass User",
            "tenant_id": "tenant_test",
        }
    )
    
    # Try login with wrong password
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "wrongpass@example.com",
            "password": "WrongPassword123",
        }
    )
    
    assert response.status_code == 401


def test_login_nonexistent_user():
    """Test login for non-existent user."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "nonexistent@example.com",
            "password": "AnyPassword123",
        }
    )
    
    assert response.status_code == 401


def test_health_check():
    """Test system health check endpoint."""
    response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "orchestrator_ready" in data


def test_root_endpoint():
    """Test API root endpoint."""
    response = client.get("/")
    
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "Mythical_AI Backend"
    assert "/docs" in data["docs"]
    assert "/health" in data["health"]

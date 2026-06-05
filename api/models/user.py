"""
User authentication model definitions.

Connects to:
  - api.services.auth_service for JWT token generation
  - PostgreSQL for user/tenant association (NEW in this phase)
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    """Request to register a new user."""
    email: EmailStr = Field(..., description="User email (unique)")
    password: str = Field(..., min_length=8, description="Password (min 8 chars)")
    full_name: str = Field(..., description="User's full name")
    tenant_id: str = Field(..., description="Tenant to join")
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "john@acme.com",
                "password": "SecurePass123!",
                "full_name": "John Doe",
                "tenant_id": "tenant_xyz789"
            }
        }


class UserLogin(BaseModel):
    """Request to authenticate a user."""
    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., description="User password")
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "john@acme.com",
                "password": "SecurePass123!"
            }
        }


class TokenResponse(BaseModel):
    """JWT token response after successful authentication."""
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration in seconds")
    user: "UserResponse" = Field(..., description="Authenticated user details")
    
    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 3600,
                "user": {
                    "user_id": "user_123",
                    "email": "john@acme.com",
                    "full_name": "John Doe",
                    "tenant_id": "tenant_xyz789",
                    "created_at": "2026-05-31T10:00:00Z"
                }
            }
        }


class UserResponse(BaseModel):
    """User profile response model."""
    user_id: str = Field(..., description="Unique user ID (UUID)")
    email: str = Field(..., description="User email")
    full_name: str = Field(..., description="User's full name")
    tenant_id: str = Field(..., description="Associated tenant ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user_123",
                "email": "john@acme.com",
                "full_name": "John Doe",
                "tenant_id": "tenant_xyz789",
                "created_at": "2026-05-31T10:00:00Z",
                "last_login": "2026-05-31T12:00:00Z"
            }
        }

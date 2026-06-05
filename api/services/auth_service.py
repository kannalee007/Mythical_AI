"""
Authentication service for user/tenant management and JWT token generation.

Manages:
  - User registration and login
  - JWT token generation + validation
  - Password hashing (bcrypt)
  - Tenant association

Does NOT depend on orchestrator modules — standalone user/auth database layer.
"""

import os
from datetime import datetime, timedelta
from typing import Optional, Tuple
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import EmailStr

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT configuration (load from .env)
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plaintext password against bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str, tenant_id: str, email: str) -> Tuple[str, int]:
    """
    Create JWT access token for authenticated user.
    
    Returns:
        (token_string, expires_in_seconds)
    """
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "email": email,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    expires_in = int(ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    
    return token, expires_in


def verify_token(token: str) -> Optional[dict]:
    """
    Verify and decode JWT token.
    
    Returns:
        decoded payload dict, or None if invalid/expired
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        tenant_id: str = payload.get("tenant_id")
        email: str = payload.get("email")
        
        if user_id is None or tenant_id is None:
            return None
            
        return {"user_id": user_id, "tenant_id": tenant_id, "email": email}
    except JWTError:
        return None


class AuthService:
    """
    User authentication service (stub for production database integration).
    
    In production, this would query PostgreSQL for user/tenant records.
    For now, it's a minimal in-memory store to support API development.
    """
    
    def __init__(self):
        """Initialize auth service with in-memory user store (development only)."""
        # In production: replace with PostgreSQL ORM queries
        self.users: dict = {}  # {email: {user_id, tenant_id, email, hashed_password, ...}}
        self.sessions: dict = {}  # {token: {user_id, tenant_id, expires_at}}
    
    def register_user(self, email: EmailStr, password: str, full_name: str, tenant_id: str) -> dict:
        """
        Register a new user.
        
        Returns:
            user dict with user_id, email, full_name, tenant_id, created_at
        """
        if email in self.users:
            raise ValueError(f"User {email} already exists")
        
        user_id = str(uuid4())
        hashed_pwd = hash_password(password)
        
        user = {
            "user_id": user_id,
            "email": email,
            "full_name": full_name,
            "tenant_id": tenant_id,
            "hashed_password": hashed_pwd,
            "created_at": datetime.utcnow(),
            "last_login": None,
        }
        
        self.users[email] = user
        return {k: v for k, v in user.items() if k != "hashed_password"}
    
    def login(self, email: EmailStr, password: str) -> Tuple[str, dict]:
        """
        Authenticate user and return JWT token.
        
        Returns:
            (token, user_dict)
        
        Raises:
            ValueError if credentials invalid
        """
        if email not in self.users:
            raise ValueError(f"User {email} not found")
        
        user = self.users[email]
        
        if not verify_password(password, user["hashed_password"]):
            raise ValueError("Invalid password")
        
        # Update last login
        user["last_login"] = datetime.utcnow()
        
        # Generate token
        token, expires_in = create_access_token(
            user_id=user["user_id"],
            tenant_id=user["tenant_id"],
            email=user["email"]
        )
        
        user_response = {k: v for k, v in user.items() if k != "hashed_password"}
        
        return token, user_response, expires_in
    
    def get_user(self, user_id: str) -> Optional[dict]:
        """Retrieve user by ID."""
        for user in self.users.values():
            if user["user_id"] == user_id:
                return {k: v for k, v in user.items() if k != "hashed_password"}
        return None

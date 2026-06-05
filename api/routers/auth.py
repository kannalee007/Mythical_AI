"""
Authentication router — user registration, login, token refresh.

Endpoints:
  POST   /register      — Create new user account
  POST   /login         — Authenticate and receive JWT token
  POST   /logout        — Invalidate token (optional)
  POST   /refresh       — Refresh access token
  GET    /me            — Get current user profile
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import EmailStr

from api.models.user import UserCreate, UserLogin, TokenResponse, UserResponse
from api.services import AuthService, create_access_token, verify_token
from api.dependencies import get_auth_service

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    auth_svc: AuthService = Depends(get_auth_service),
):
    """
    Register a new user account.
    
    - **email**: unique email address
    - **password**: min 8 characters
    - **full_name**: user's full name
    - **tenant_id**: tenant to join
    """
    try:
        user = auth_svc.register_user(
            email=user_data.email,
            password=user_data.password,
            full_name=user_data.full_name,
            tenant_id=user_data.tenant_id,
        )
        return user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    auth_svc: AuthService = Depends(get_auth_service),
):
    """
    Authenticate user and receive JWT access token.
    
    - **email**: registered email
    - **password**: account password
    
    Returns JWT token valid for 24 hours.
    """
    try:
        token, user, expires_in = auth_svc.login(
            email=credentials.email,
            password=credentials.password,
        )
        
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            user=UserResponse(**user),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    authorization: str = None,
    auth_svc: AuthService = Depends(get_auth_service),
):
    """
    Get current authenticated user profile.
    
    Requires Bearer token in Authorization header.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = authorization.split(" ", 1)[1]
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = verify_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = auth_svc.get_user(payload["user_id"])
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return UserResponse(**user)

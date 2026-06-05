"""
Mythical_AI FastAPI Backend — Main Entry Point

Exposes the Constitutional Orchestrator as a production-grade REST + WebSocket API
with multi-tenant support, JWT authentication, and real-time pipeline streaming.

Usage:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

Environment variables (.env):
    JWT_SECRET_KEY=<secret-key-for-jwt>
    DATABASE_URL=postgresql://user:pass@localhost/mythical_ai  (future)
    NEO4J_URI=bolt://localhost:7687
    NEO4J_USER=neo4j
    NEO4J_PASSWORD=password
    ORCHESTRATOR_CONFIG_PATH=./config.yaml
"""

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Load environment
from dotenv import load_dotenv
load_dotenv()

# Import dependencies (this resolves circular import issues)
from api.dependencies import get_auth_service, get_tenant_service, get_orchestrator_service
from api.services import OrchestratorService

# Import routers (AFTER dependency functions are defined)
from api.routers import auth, tasks, tenants, audit, connectors


# ============================================================================
# APP LIFECYCLE
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    
    Startup:
      - Initialize services
      - Verify Neo4j connection
      - Log ready state
    
    Shutdown:
      - Gracefully close Neo4j
      - Clean up resources
    """
    # STARTUP
    print("[STARTUP] Initializing Mythical_AI Backend...")
    
    try:
        auth_svc = get_auth_service()
        tenant_svc = get_tenant_service()
        orch_svc = get_orchestrator_service()
        
        print("[STARTUP] ✓ AuthService initialized")
        print("[STARTUP] ✓ TenantService initialized")
        
        if orch_svc.orchestrator_ready:
            print("[STARTUP] ✓ OrchestratorService initialized (full)")
        else:
            print("[STARTUP] ⚠ OrchestratorService initialized (partial — mock mode)")
        
        print("[STARTUP] Backend ready at http://localhost:8000")
        print("[STARTUP] API docs at http://localhost:8000/docs")
    
    except Exception as e:
        print(f"[ERROR] Startup failed: {e}")
        raise
    
    yield  # App runs here
    
    # SHUTDOWN
    print("\n[SHUTDOWN] Gracefully shutting down...")
    print("[SHUTDOWN] Closing Neo4j connections...")
    print("[SHUTDOWN] Backend offline")


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Mythical_AI Backend",
    description="Constitutional AI Orchestration Platform — REST + WebSocket API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ============================================================================
# MIDDLEWARE
# ============================================================================

# CORS (allow dashboard, connectors, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Trust X-Forwarded-For for reverse proxies (safe defaults)
# Note: "testserver" is included for FastAPI TestClient compatibility
allowed_hosts = ["localhost", "127.0.0.1", "testserver", "*.example.com"]
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=allowed_hosts,
)

# ============================================================================
# INCLUDE ROUTERS
# ============================================================================

# Auth router (public)
app.include_router(
    auth.router,
    prefix="/api/v1/auth",
    tags=["authentication"],
)

# Task router (requires auth)
app.include_router(
    tasks.router,
    prefix="/api/v1/tasks",
    tags=["tasks"],
)

# Tenant router (requires auth + admin)
app.include_router(
    tenants.router,
    prefix="/api/v1/tenants",
    tags=["tenants"],
)

# Audit router (requires auth)
app.include_router(
    audit.router,
    prefix="/api/v1/audit",
    tags=["audit"],
)

# Connectors router (requires auth)
app.include_router(
    connectors.router,
    prefix="/api/v1/connectors",
    tags=["connectors"],
)

# ============================================================================
# ROOT ENDPOINTS
# ============================================================================


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    version: str
    orchestrator_ready: bool


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check(orch_svc: OrchestratorService = Depends(get_orchestrator_service)):
    """System health check endpoint."""
    return HealthResponse(
        status="ok",
        version="1.0.0",
        orchestrator_ready=orch_svc.orchestrator_ready,
    )


@app.get("/", tags=["root"])
async def root():
    """API root endpoint."""
    return {
        "app": "Mythical_AI Backend",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Catch-all exception handler."""
    print(f"[ERROR] Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )

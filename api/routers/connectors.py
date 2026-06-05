"""
Connectors router — connector management and OAuth flows.

Endpoints:
  GET    /              — List available connectors
  POST   /{type}/oauth  — Start OAuth flow (Slack, GitHub, Notion)
  GET    /{type}/callback — OAuth callback
  DELETE /{type}        — Revoke connector credentials
"""

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional

router = APIRouter()


@router.get("/")
async def list_connectors():
    """
    List available connectors (Slack, GitHub, Notion, etc.)
    
    Returns: available connectors with OAuth requirements
    """
    # TODO: Query orchestrator.connectors.registry
    return {
        "message": "Connectors list not yet implemented",
        "connectors": [
            {"type": "slack", "requires_oauth": True},
            {"type": "github", "requires_oauth": True},
            {"type": "notion", "requires_oauth": True},
        ],
    }


@router.post("/{connector_type}/oauth")
async def start_oauth_flow(
    connector_type: str,
    tenant_id: str,
    redirect_uri: Optional[str] = None,
):
    """
    Start OAuth2 flow for connector (Slack, GitHub, Notion).
    
    - **connector_type**: slack|github|notion
    - **tenant_id**: tenant isolation
    - **redirect_uri**: where to send callback
    
    Returns: OAuth authorization URL
    """
    # TODO: Initiate OAuth flow via orchestrator.connectors
    return {
        "message": "OAuth flow not yet implemented",
        "auth_url": f"https://example.com/oauth/authorize?client_id=xxx&redirect_uri={redirect_uri}",
    }


@router.get("/{connector_type}/callback")
async def oauth_callback(
    connector_type: str,
    code: str,
    state: str,
    tenant_id: str,
):
    """
    OAuth2 callback endpoint (invoked by connector service).
    
    Exchanges code for access token and stores securely.
    """
    # TODO: Exchange code for token, store in orchestrator.connectors.secrets
    return {
        "message": "OAuth callback not yet implemented",
        "connector": connector_type,
        "status": "authorized",
    }


@router.delete("/{connector_type}")
async def revoke_connector(
    connector_type: str,
    tenant_id: str,
):
    """
    Revoke connector credentials for tenant.
    """
    # TODO: Delete connector secrets via orchestrator.tenancy
    return {
        "message": f"Connector {connector_type} revoked",
        "status": "success",
    }

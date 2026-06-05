"""
Conftest for pytest — shared fixtures and configuration.
"""

import pytest
from api.services import AuthService, TenantService


@pytest.fixture
def auth_service():
    """Provide a fresh AuthService for tests."""
    return AuthService()


@pytest.fixture
def tenant_service():
    """Provide a fresh TenantService for tests."""
    return TenantService()

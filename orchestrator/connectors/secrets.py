"""Secret loading helpers for connector credentials."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from orchestrator.connectors.base import ConnectorError


def load_secret(secret_path: Path, enforce_permissions: bool = True) -> str:
    """Load a secret from disk with optional permissions enforcement."""
    if not secret_path.exists():
        raise ConnectorError(f"Secret file not found: {secret_path}")

    if enforce_permissions:
        _ensure_private_permissions(secret_path)

    value = secret_path.read_text(encoding="utf-8").strip()
    if not value:
        raise ConnectorError(f"Secret file is empty: {secret_path}")
    return value


def resolve_secret_path(secrets_dir: Path, filename: str) -> Path:
    """Resolve and validate a secret path under the tenant secrets directory."""
    candidate = (secrets_dir / filename).resolve()
    secrets_root = secrets_dir.resolve()
    if secrets_root not in candidate.parents and candidate != secrets_root:
        raise ConnectorError("Secret path escapes tenant secrets directory")
    return candidate


def _ensure_private_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConnectorError(
            "Secret file permissions are too open. Use chmod 600 to restrict access."
        )

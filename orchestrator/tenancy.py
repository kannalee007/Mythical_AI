"""Tenant isolation helpers for policies, secrets, and storage."""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class TenantContext:
    """Resolved paths and mounts for a tenant."""

    tenant_id: str
    base_dir: Path
    tenant_dir: Path
    policy_path: Path
    secrets_dir: Path
    storage_dir: Path
    rag_dir: Path
    audit_dir: Path
    storage_mount: str
    secrets_mount: str


class TenancyManager:
    """Resolve tenant context and apply tenant-scoped configuration."""

    def __init__(self, config: dict, tenant_id: Optional[str] = None):
        self.config = config
        tenancy_cfg = config.get("tenancy", {})
        self.enabled = bool(tenancy_cfg.get("enabled", False))
        self.base_dir = Path(tenancy_cfg.get("base_dir", ".tenants"))
        self.default_tenant = tenancy_cfg.get("default_tenant", "default")
        self.storage_dirname = tenancy_cfg.get("storage_dirname", "storage")
        self.secrets_dirname = tenancy_cfg.get("secrets_dirname", "secrets")
        self.rag_dirname = tenancy_cfg.get("rag_dirname", "rag")
        self.audit_dirname = tenancy_cfg.get("audit_dirname", "audit")
        self.policy_filename = tenancy_cfg.get("policy_filename", "policy.yaml")
        self.storage_mount = tenancy_cfg.get("storage_mount", "/tenant_storage")
        self.secrets_mount = tenancy_cfg.get("secrets_mount", "/tenant_secrets")

        self.tenant_id = self._resolve_tenant_id(tenant_id)
        self.context = self._init_context(self.tenant_id) if self.enabled else None

    def _resolve_tenant_id(self, tenant_id: Optional[str]) -> str:
        candidate = (
            tenant_id
            or os.environ.get("MYTHICAL_TENANT")
            or os.environ.get("TENANT_ID")
            or self.default_tenant
        )
        candidate = candidate.strip()
        if not _TENANT_ID_RE.match(candidate):
            raise ValueError(
                "Invalid tenant id. Use only letters, numbers, dashes, or underscores "
                "(max 64 chars)."
            )
        return candidate

    def _init_context(self, tenant_id: str) -> TenantContext:
        tenant_dir = self.base_dir / tenant_id
        policy_path = tenant_dir / self.policy_filename
        secrets_dir = tenant_dir / self.secrets_dirname
        storage_dir = tenant_dir / self.storage_dirname
        rag_dir = tenant_dir / self.rag_dirname
        audit_dir = tenant_dir / self.audit_dirname

        for path in (tenant_dir, secrets_dir, storage_dir, rag_dir, audit_dir):
            path.mkdir(parents=True, exist_ok=True)

        return TenantContext(
            tenant_id=tenant_id,
            base_dir=self.base_dir,
            tenant_dir=tenant_dir,
            policy_path=policy_path,
            secrets_dir=secrets_dir,
            storage_dir=storage_dir,
            rag_dir=rag_dir,
            audit_dir=audit_dir,
            storage_mount=self.storage_mount,
            secrets_mount=self.secrets_mount,
        )

    def load_policy_overrides(self) -> dict:
        """Load tenant-scoped policy overrides from policy.yaml if present."""
        if not self.context:
            return {}

        if not self.context.policy_path.exists():
            return {}

        try:
            data = yaml.safe_load(self.context.policy_path.read_text())
        except Exception:
            return {}

        if not isinstance(data, dict):
            return {}

        return data

    def apply_overrides(self, config: dict) -> dict:
        """Apply tenant overrides and defaults to the base config."""
        if not self.enabled or not self.context:
            return config

        merged = _deep_merge(config, self.load_policy_overrides())
        merged.setdefault("tenancy", {})["active_tenant"] = self.context.tenant_id

        # Tenant-scoped audit log file
        merged.setdefault("navigator", {})["log_file"] = str(
            self.context.audit_dir / "orchestrator_decisions.log"
        )

        merged.setdefault("audit", {})["log_file"] = str(
            self.context.audit_dir / "audit_events.log"
        )

        merged.setdefault("audit", {}).setdefault("sqlite", {})["path"] = str(
            self.context.audit_dir / "audit_events.sqlite3"
        )

        # Tenant-scoped VectorRAG store
        merged.setdefault("rag", {})["chroma_path"] = str(self.context.rag_dir)

        return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, replacing lists and scalars."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result

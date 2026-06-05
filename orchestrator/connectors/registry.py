"""Connector registry and tenant-aware initialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from orchestrator.connectors.base import ConnectorError
from orchestrator.connectors.github import GitHubConnector
from orchestrator.connectors.notion import NotionConnector
from orchestrator.connectors.secrets import load_secret, resolve_secret_path
from orchestrator.connectors.slack import SlackConnector
from orchestrator.tenancy import TenantContext


@dataclass
class ConnectorConfig:
    """Connector configuration settings."""

    enabled: bool
    timeout_seconds: int
    user_agent: str
    enforce_secret_permissions: bool


class ConnectorRegistry:
    """Tenant-aware connector registry with lazy initialization."""

    def __init__(self, config: dict, tenant_context: Optional[TenantContext] = None):
        connectors_cfg = config.get("connectors", {})
        self._enabled = bool(connectors_cfg.get("enabled", False))
        self._timeout = int(connectors_cfg.get("request_timeout_seconds", 15))
        self._user_agent = str(connectors_cfg.get("user_agent", "mythical-ai/enterprise"))
        self._enforce_permissions = bool(
            connectors_cfg.get("enforce_secret_permissions", True)
        )

        if tenant_context is not None:
            self._secrets_dir = Path(tenant_context.secrets_dir)
        else:
            self._secrets_dir = Path(connectors_cfg.get("secrets_dir", ".secrets"))

        self._config = connectors_cfg
        self._slack: Optional[SlackConnector] = None
        self._notion: Optional[NotionConnector] = None
        self._github: Optional[GitHubConnector] = None

    def is_enabled(self) -> bool:
        return self._enabled

    def slack(self) -> SlackConnector:
        if not self._enabled:
            raise ConnectorError("Connectors are disabled in config")
        if self._slack is None:
            cfg = self._config.get("slack", {})
            token = self._load_secret(cfg.get("token_file", "slack_token.txt"))
            self._slack = SlackConnector(
                base_url=str(cfg.get("base_url", "https://slack.com/api")),
                token=token,
                allowed_hosts=list(cfg.get("allowed_hosts", ["slack.com"])),
                timeout_seconds=self._timeout,
                user_agent=self._user_agent,
            )
        return self._slack

    def notion(self) -> NotionConnector:
        if not self._enabled:
            raise ConnectorError("Connectors are disabled in config")
        if self._notion is None:
            cfg = self._config.get("notion", {})
            token = self._load_secret(cfg.get("token_file", "notion_token.txt"))
            self._notion = NotionConnector(
                base_url=str(cfg.get("base_url", "https://api.notion.com/v1")),
                token=token,
                allowed_hosts=list(cfg.get("allowed_hosts", ["api.notion.com"])),
                notion_version=str(cfg.get("api_version", "2022-06-28")),
                title_property=str(cfg.get("title_property", "Name")),
                timeout_seconds=self._timeout,
                user_agent=self._user_agent,
            )
        return self._notion

    def github(self) -> GitHubConnector:
        if not self._enabled:
            raise ConnectorError("Connectors are disabled in config")
        if self._github is None:
            cfg = self._config.get("github", {})
            token = self._load_secret(cfg.get("token_file", "github_token.txt"))
            self._github = GitHubConnector(
                base_url=str(cfg.get("base_url", "https://api.github.com")),
                token=token,
                allowed_hosts=list(cfg.get("allowed_hosts", ["api.github.com"])),
                timeout_seconds=self._timeout,
                user_agent=self._user_agent,
            )
        return self._github

    def _load_secret(self, filename: str) -> str:
        secret_path = resolve_secret_path(self._secrets_dir, filename)
        return load_secret(secret_path, enforce_permissions=self._enforce_permissions)

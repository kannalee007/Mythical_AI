"""Shared connector client behavior and safety checks."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests


class ConnectorError(RuntimeError):
    """Raised when a connector request fails."""


@dataclass
class ConnectorResponse:
    """Standardized connector response."""

    ok: bool
    status_code: int
    data: dict


class BaseConnector:
    """Base class for connector clients."""

    def __init__(
        self,
        base_url: str,
        token: str,
        allowed_hosts: list[str],
        timeout_seconds: int = 15,
        user_agent: str = "mythical-ai/enterprise",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.allowed_hosts = allowed_hosts
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self._session = requests.Session()
        self._validate_base_url()

    def _validate_base_url(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https":
            raise ConnectorError("Connector base_url must use https")
        if not parsed.hostname:
            raise ConnectorError("Connector base_url must include a hostname")
        if self.allowed_hosts:
            if not any(
                parsed.hostname == host or parsed.hostname.endswith(f".{host}")
                for host in self.allowed_hosts
            ):
                raise ConnectorError("Connector base_url hostname is not allowed")
        if _is_ip_address(parsed.hostname):
            raise ConnectorError("Connector base_url must not be an IP address")

    def _resolve_url(self, path: str) -> str:
        parsed = urlparse(path)
        if parsed.scheme or parsed.netloc:
            raise ConnectorError("Connector path must be relative")
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    def _request_json(
        self,
        method: str,
        path: str,
        headers: Optional[dict[str, str]] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> ConnectorResponse:
        url = self._resolve_url(path)
        merged_headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        if headers:
            merged_headers.update(headers)

        try:
            response = self._session.request(
                method=method.upper(),
                url=url,
                headers=merged_headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise ConnectorError(f"Connector request failed: {exc}") from exc

        try:
            data = response.json() if response.content else {}
        except ValueError as exc:
            raise ConnectorError("Connector returned non-JSON response") from exc

        ok = 200 <= response.status_code < 300
        return ConnectorResponse(ok=ok, status_code=response.status_code, data=data)


def _is_ip_address(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True

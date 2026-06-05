"""Notion connector for enterprise knowledge capture."""

from __future__ import annotations

from typing import Optional

from orchestrator.connectors.base import BaseConnector, ConnectorError


class NotionConnector(BaseConnector):
    """Notion API connector."""

    def __init__(
        self,
        base_url: str,
        token: str,
        allowed_hosts: list[str],
        notion_version: str,
        title_property: str = "Name",
        timeout_seconds: int = 15,
        user_agent: str = "mythical-ai/enterprise",
    ) -> None:
        super().__init__(
            base_url=base_url,
            token=token,
            allowed_hosts=allowed_hosts,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
        )
        self.notion_version = notion_version
        self.title_property = title_property

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.notion_version,
            "Content-Type": "application/json",
        }

    def create_page(
        self,
        database_id: str,
        title: str,
        content: str,
        icon_emoji: Optional[str] = None,
    ) -> dict:
        payload = {
            "parent": {"database_id": database_id},
            "properties": {
                self.title_property: {
                    "title": [{"text": {"content": title}}]
                }
            },
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": content}}]
                    },
                }
            ],
        }
        if icon_emoji:
            payload["icon"] = {"type": "emoji", "emoji": icon_emoji}

        response = self._request_json(
            method="POST",
            path="/pages",
            headers=self._auth_headers(),
            payload=payload,
        )

        if not response.ok:
            message = _extract_error(response.data)
            raise ConnectorError(f"Notion API error: {message}")

        return {
            "ok": True,
            "page_id": response.data.get("id"),
            "url": response.data.get("url"),
        }


def _extract_error(data: dict) -> str:
    message = data.get("message")
    if isinstance(message, str) and message:
        return message
    return "unknown_error"

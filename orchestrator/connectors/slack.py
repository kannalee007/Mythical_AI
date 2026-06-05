"""Slack connector for enterprise notifications."""

from __future__ import annotations

from typing import Optional

from orchestrator.connectors.base import BaseConnector, ConnectorError


class SlackConnector(BaseConnector):
    """Slack Web API connector."""

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: Optional[str] = None,
    ) -> dict:
        payload = {
            "channel": channel,
            "text": text,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts

        response = self._request_json(
            method="POST",
            path="/chat.postMessage",
            headers=self._auth_headers(),
            payload=payload,
        )

        if not response.ok or not response.data.get("ok"):
            error = response.data.get("error", "unknown_error")
            raise ConnectorError(f"Slack API error: {error}")

        return {
            "ok": True,
            "channel": response.data.get("channel"),
            "ts": response.data.get("ts"),
        }

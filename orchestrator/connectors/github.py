"""GitHub connector for enterprise workflows."""

from __future__ import annotations

from typing import Iterable, Optional

from orchestrator.connectors.base import BaseConnector, ConnectorError


class GitHubConnector(BaseConnector):
    """GitHub REST API connector."""

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: Optional[Iterable[str]] = None,
    ) -> dict:
        payload = {
            "title": title,
            "body": body,
        }
        if labels:
            payload["labels"] = list(labels)

        response = self._request_json(
            method="POST",
            path=f"/repos/{owner}/{repo}/issues",
            headers=self._auth_headers(),
            payload=payload,
        )

        if not response.ok:
            message = _extract_error(response.data)
            raise ConnectorError(f"GitHub API error: {message}")

        return {
            "ok": True,
            "number": response.data.get("number"),
            "url": response.data.get("html_url"),
        }

    def comment_issue(self, owner: str, repo: str, issue_number: int, body: str) -> dict:
        payload = {"body": body}
        response = self._request_json(
            method="POST",
            path=f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            headers=self._auth_headers(),
            payload=payload,
        )

        if not response.ok:
            message = _extract_error(response.data)
            raise ConnectorError(f"GitHub API error: {message}")

        return {
            "ok": True,
            "url": response.data.get("html_url"),
        }


def _extract_error(data: dict) -> str:
    message = data.get("message")
    if isinstance(message, str) and message:
        return message
    return "unknown_error"

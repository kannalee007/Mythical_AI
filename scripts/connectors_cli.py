#!/usr/bin/env python3
"""CLI helper for enterprise connectors."""

from __future__ import annotations

import argparse
import sys

from orchestrator.connectors.base import ConnectorError
from orchestrator.connectors.registry import ConnectorRegistry
from orchestrator.tenancy import TenancyManager
from orchestrator.utils import console, load_config


def _build_registry(config_path: str, tenant_id: str | None) -> ConnectorRegistry:
    config = load_config(config_path)
    tenancy = TenancyManager(config, tenant_id=tenant_id)
    if tenancy.enabled:
        config = tenancy.apply_overrides(config)
    registry = ConnectorRegistry(config, tenancy.context)
    if tenancy.enabled and tenancy.context:
        console.print(
            f"[dim]Tenant: [bold]{tenancy.context.tenant_id}[/bold]  "
            f"(secrets: {tenancy.context.secrets_dir})[/dim]"
        )
    return registry


def _parse_repo(value: str) -> tuple[str, str]:
    if "/" not in value:
        raise ValueError("Repo must be in owner/repo format")
    owner, repo = value.split("/", 1)
    return owner, repo


def main() -> int:
    parser = argparse.ArgumentParser(description="Enterprise connector CLI")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--tenant", help="Tenant id to use")

    subparsers = parser.add_subparsers(dest="connector", required=True)

    slack = subparsers.add_parser("slack", help="Slack connector")
    slack_sub = slack.add_subparsers(dest="action", required=True)
    slack_post = slack_sub.add_parser("post-message", help="Post a Slack message")
    slack_post.add_argument("--channel", required=True, help="Slack channel or user")
    slack_post.add_argument("--text", required=True, help="Message text")
    slack_post.add_argument("--thread", help="Thread timestamp")

    notion = subparsers.add_parser("notion", help="Notion connector")
    notion_sub = notion.add_subparsers(dest="action", required=True)
    notion_create = notion_sub.add_parser("create-page", help="Create a Notion page")
    notion_create.add_argument("--database", required=True, help="Notion database id")
    notion_create.add_argument("--title", required=True, help="Page title")
    notion_create.add_argument("--content", required=True, help="Page content")
    notion_create.add_argument("--icon", help="Emoji icon")

    github = subparsers.add_parser("github", help="GitHub connector")
    github_sub = github.add_subparsers(dest="action", required=True)
    github_issue = github_sub.add_parser("create-issue", help="Create a GitHub issue")
    github_issue.add_argument("--repo", required=True, help="owner/repo")
    github_issue.add_argument("--title", required=True, help="Issue title")
    github_issue.add_argument("--body", required=True, help="Issue body")
    github_issue.add_argument("--label", action="append", default=[], help="Issue label")

    github_comment = github_sub.add_parser("comment-issue", help="Comment on a GitHub issue")
    github_comment.add_argument("--repo", required=True, help="owner/repo")
    github_comment.add_argument("--issue", required=True, type=int, help="Issue number")
    github_comment.add_argument("--body", required=True, help="Comment body")

    args = parser.parse_args()

    try:
        registry = _build_registry(args.config, args.tenant)
    except Exception as exc:
        console.print(f"[bold red]Failed to initialize connectors: {exc}[/bold red]")
        return 2

    try:
        if args.connector == "slack":
            client = registry.slack()
            result = client.post_message(args.channel, args.text, thread_ts=args.thread)
        elif args.connector == "notion":
            client = registry.notion()
            result = client.create_page(
                database_id=args.database,
                title=args.title,
                content=args.content,
                icon_emoji=args.icon,
            )
        elif args.connector == "github" and args.action == "create-issue":
            owner, repo = _parse_repo(args.repo)
            client = registry.github()
            result = client.create_issue(
                owner=owner,
                repo=repo,
                title=args.title,
                body=args.body,
                labels=args.label or None,
            )
        elif args.connector == "github" and args.action == "comment-issue":
            owner, repo = _parse_repo(args.repo)
            client = registry.github()
            result = client.comment_issue(
                owner=owner,
                repo=repo,
                issue_number=args.issue,
                body=args.body,
            )
        else:
            raise ConnectorError("Unknown connector action")
    except (ConnectorError, ValueError) as exc:
        console.print(f"[bold red]Connector error: {exc}[/bold red]")
        return 1

    console.print("[green]Success[/green]")
    console.print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())

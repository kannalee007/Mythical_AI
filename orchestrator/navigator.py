"""The Navigator Gateway: Human-in-the-loop approval system."""

from dataclasses import dataclass
import re
import sys
from typing import Any, Optional

from rich.panel import Panel

from orchestrator.utils import console, log_decision

APPROVAL_PROMPT = "[System Change Requested. Review Plan Y/N?] [y/n] (n): "
MAX_APPROVAL_ATTEMPTS = 3
PROMPT_PREVIEW_LIMIT = 800
SAFE_APPROVAL_REASON = "Auto-approved (safe)"
DEFAULT_APPROVAL_REASON = "User approved via Navigator Gateway"
DENIAL_REASON = "User denied via Navigator Gateway"
INVALID_INPUT_MESSAGE = "[bold yellow]Please enter Y or N[/bold yellow]"
NON_INTERACTIVE_MESSAGE = "[bold yellow]Non-interactive input detected; defaulting to DENY.[/bold yellow]"
INPUT_ABORT_MESSAGE = "[bold yellow]No interactive response received; defaulting to DENY.[/bold yellow]"
TOO_MANY_INVALID_INPUTS_MESSAGE = "[bold yellow]Too many invalid attempts; defaulting to DENY.[/bold yellow]"


@dataclass
class NavigatorDecision:
    """Result of a human approval request."""

    approved: bool
    reason: str
    escalation_level: str  # "none", "caution", "critical"


class NavigatorGateway:
    """Prompts the user for approval on sensitive operations."""

    def __init__(self, config: dict[str, Any]):
        navigator_config = config.get("navigator")
        if not isinstance(navigator_config, dict):
            raise ValueError("Missing or invalid 'navigator' configuration section.")

        try:
            self.auto_approve_safe = bool(navigator_config["auto_approve_safe"])
            self.review_tags = set(navigator_config["categories_requiring_approval"])
            self.log_file = str(navigator_config["log_file"])
        except KeyError as exc:
            raise ValueError(f"Missing navigator configuration key: {exc.args[0]}") from exc

    def _truncate_plan(self, plan_text: str) -> str:
        """Limit the plan preview to keep the approval panel readable."""
        return plan_text[:PROMPT_PREVIEW_LIMIT] + "..." if len(plan_text) > PROMPT_PREVIEW_LIMIT else plan_text

    def _format_violation(self, violation: dict[str, Any]) -> str:
        """Format a single constitutional violation for display."""
        rule_id = violation.get("rule_id", "unknown")
        rule_name = violation.get("rule_name") or violation.get("reason") or "Unknown"
        return f"  - [{rule_id}] {rule_name}"

    def _build_prompt_text(self, plan_text: str, tags: list[str], violations: list[dict[str, Any]]) -> str:
        """Build a rich display of what needs approval."""
        lines = [
            "[bold red]SYSTEM CHANGE REQUESTED[/bold red]",
            "",
            "[bold]Plan Summary:[/bold]",
            self._truncate_plan(plan_text),
            "",
        ]

        if tags:
            lines.append("[bold yellow]Explicit Tags Requiring Review:[/bold yellow]")
            lines.extend(f"  - {tag}" for tag in tags)
            lines.append("")

        if violations:
            lines.append("[bold red]Constitutional Violations Found:[/bold red]")
            lines.extend(self._format_violation(violation) for violation in violations)
            lines.append("")

        lines.append("[bold]Do you approve execution of this plan?[/bold]")
        return "\n".join(lines)

    def _requires_review(self, tags: list[str], violations: list[dict[str, Any]]) -> bool:
        """Return whether the plan needs explicit review."""
        return any(tag in self.review_tags for tag in tags) or bool(violations)

    def _determine_escalation(self, violations: list[dict[str, Any]]) -> str:
        """Derive an escalation level from the constitutional findings."""
        if any(violation.get("severity") == "critical" for violation in violations):
            return "critical"
        if violations:
            return "caution"
        return "none"

    def _prompt_approval(self) -> bool:
        """Collect a bounded Y/N decision from stdin and fail closed on errors."""
        if not sys.stdin.isatty():
            console.print(NON_INTERACTIVE_MESSAGE)
            return False

        for _ in range(MAX_APPROVAL_ATTEMPTS):
            try:
                raw = input(APPROVAL_PROMPT)
            except (EOFError, KeyboardInterrupt):
                console.print(INPUT_ABORT_MESSAGE)
                return False

            decision = self._parse_approval_input(raw)
            if decision is None:
                console.print(INVALID_INPUT_MESSAGE)
                continue
            return decision

        console.print(TOO_MANY_INVALID_INPUTS_MESSAGE)
        return False

    def _parse_approval_input(self, raw: str) -> Optional[bool]:
        """Parse an approval input line into a boolean decision.

        Accepts simple "y"/"n" and ignores pasted prompt text like "y/n".
        Returns None when the input is ambiguous or empty.
        """
        normalized = raw.strip().lower()
        if not normalized:
            return None

        # Remove common prompt fragments to avoid accidental matches.
        normalized = re.sub(r"\by\s*/\s*n\b", " ", normalized)
        normalized = re.sub(r"\(n\)\s*:\s*", " ", normalized)

        tokens = re.findall(r"[a-z]+", normalized)
        if not tokens:
            return None

        has_yes = "yes" in tokens
        has_no = "no" in tokens
        if has_yes and has_no:
            return None
        if has_yes:
            return True
        if has_no:
            return False

        short = [t for t in tokens if t in {"y", "n"}]
        if not short:
            return None
        if len(set(short)) > 1:
            return None
        return short[-1] == "y"

    def _prompt_optional_note(self) -> str:
        """Collect an optional approval note with safe fallback behavior."""
        try:
            note = input("Optional approval note (press Enter to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            return DEFAULT_APPROVAL_REASON
        return note or DEFAULT_APPROVAL_REASON

    def _log_decision(self, task_id: str, approved: bool, reason: str, escalation: str, tags: list[str], violations: list[dict[str, Any]]) -> None:
        """Persist the approval decision to the decision log."""
        log_decision(
            self.log_file,
            {
                "task_id": task_id,
                "approved": approved,
                "reason": reason,
                "escalation": escalation,
                "tags": tags,
                "violations": [violation.get("rule_id", "unknown") for violation in violations],
            },
        )

    def request_approval(
        self,
        plan_text: str,
        tags: list[str],
        violations: list[dict[str, Any]],
        task_id: str,
    ) -> NavigatorDecision:
        """Prompt the user for approval. Returns their decision."""
        console.rule("[bold magenta]Navigator Gateway[/bold magenta]")

        if not self._requires_review(tags, violations):
            if self.auto_approve_safe:
                console.print("[green]Auto-approved: no sensitive operations detected.[/green]")
                self._log_decision(task_id, True, SAFE_APPROVAL_REASON, "none", tags, violations)
                return NavigatorDecision(approved=True, reason=SAFE_APPROVAL_REASON, escalation_level="none")

        escalation = self._determine_escalation(violations)
        style = {
            "critical": "bold red",
            "caution": "bold yellow",
            "none": "bold green",
        }[escalation]

        # Always show the plan panel before prompting so the user has full
        # context regardless of whether a formal review was required.
        console.print(
            Panel(
                self._build_prompt_text(plan_text, tags, violations),
                title=f"Task ID: {task_id}",
                border_style="magenta",
            )
        )

        approved = self._prompt_approval()
        reason = self._prompt_optional_note() if approved else DENIAL_REASON

        decision = NavigatorDecision(
            approved=approved,
            reason=reason,
            escalation_level=escalation,
        )

        self._log_decision(task_id, approved, reason, escalation, tags, violations)

        if approved:
            console.print(f"[{style}]APPROVED[/{style}]")
        else:
            console.print("[bold red]DENIED[/bold red]")

        return decision

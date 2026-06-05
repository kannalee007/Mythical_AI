"""Regulatory compliance node for additional safety review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orchestrator.utils import console, scan_for_violations


@dataclass
class RegulatoryVerdict:
    """Result of a regulatory compliance review."""

    approved: bool
    violations: list[dict[str, Any]]
    requires_human_review: bool


class RegulatoryNode:
    """Pattern-based regulatory compliance checks."""

    def __init__(self, config: dict):
        regulatory_cfg = config.get("regulatory", {})
        self.enabled = bool(regulatory_cfg.get("enabled", False))
        self.rules = regulatory_cfg.get("rules", [])
        self.require_human_review_on_match = bool(
            regulatory_cfg.get("require_human_review_on_match", True)
        )

    def evaluate(self, plan_text: str, tags_in_plan: list[str]) -> RegulatoryVerdict:
        if not self.enabled:
            return RegulatoryVerdict(approved=True, violations=[], requires_human_review=False)

        console.rule("[bold magenta]Regulatory Node[/bold magenta]")
        console.print("Running compliance scan...", style="dim")

        violations = scan_for_violations(plan_text, self.rules)
        blocking = []
        tagged = []

        for violation in violations:
            exception_tag = violation.get("exception_tag")
            if exception_tag and exception_tag in tags_in_plan:
                tagged.append(violation)
            else:
                blocking.append(violation)

        approved = len(blocking) == 0
        requires_review = bool(tagged or blocking) and self.require_human_review_on_match

        if not violations:
            console.print("[bold green]Regulatory check: PASSED[/bold green]")
        elif approved and requires_review:
            console.print(
                "[bold yellow]Regulatory check: CONDITIONAL PASS (human review required)[/bold yellow]"
            )
        else:
            console.print("[bold red]Regulatory check: FAILED[/bold red]")
            for violation in blocking:
                console.print(
                    f"  - [{violation.get('rule_id', 'unknown')}] "
                    f"{violation.get('rule_name', violation.get('reason', 'Unknown'))}"
                )

        return RegulatoryVerdict(
            approved=approved,
            violations=blocking + tagged,
            requires_human_review=requires_review,
        )

"""RL-CAI Reward Model: scores critique-revision training pairs."""

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from rich.table import Table

from orchestrator.utils import console, load_config, query_ollama, scan_for_violations

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TRAINING_DATA_PATH = ".tenants/default/training_data.jsonl"
REWARD_SCORES_PATH = ".tenants/default/reward_scores.jsonl"

# ---------------------------------------------------------------------------
# WCR weights — must match weighted_resolution.py
# ---------------------------------------------------------------------------

CONTEXT_WEIGHTS: dict[str, dict[str, float]] = {
    "educational": {"safety": 0.4, "helpfulness": 0.6},
    "ambiguous":   {"safety": 0.8, "helpfulness": 0.2},
    "malicious":   {"safety": 1.0, "helpfulness": 0.0},
}

# Fallback weights for unrecognised context labels
_DEFAULT_WEIGHTS: dict[str, float] = {"safety": 0.6, "helpfulness": 0.4}

# ---------------------------------------------------------------------------
# Safety scoring (rule-based)
# ---------------------------------------------------------------------------

_VIOLATION_SAFETY_MAP = {0: 1.0, 1: 0.6, 2: 0.3}
_VIOLATION_SAFETY_DEFAULT = 0.1  # 3+ violations


def _safety_score(text: str, rules: list[dict]) -> tuple[float, int]:
    """Return (safety_score, violation_count) for a response text."""
    violations = scan_for_violations(text, rules)
    count = len(violations)
    score = _VIOLATION_SAFETY_MAP.get(count, _VIOLATION_SAFETY_DEFAULT)
    return score, count


# ---------------------------------------------------------------------------
# Helpfulness scoring (LLM-based)
# ---------------------------------------------------------------------------

_HELPFULNESS_FALLBACK = 0.5
_HELPFULNESS_MODEL = "qwen3.5:4b"
_HELPFULNESS_MAX_TOKENS = 16  # we only need a single number


def _extract_float(text: str) -> Optional[float]:
    """Pull the first float in [0.0, 1.0] out of an LLM response string.

    Tokenises whole numeric literals first so that '1.5' is parsed as 1.5
    (out-of-range, skipped) rather than matching the bare '1' inside it.
    """
    for m in re.findall(r"\d+(?:\.\d+)?", text):
        try:
            val = float(m)
            if 0.0 <= val <= 1.0:
                return val
        except ValueError:
            continue
    return None


def _helpfulness_score(response: str) -> float:
    """Score response helpfulness via a quick LLM call; fallback to 0.5 on error."""
    if not response.strip():
        return 0.0

    prompt = (
        f"Response to evaluate:\n{response[:800]}\n\n"
        "Rate the helpfulness of this response on a scale from 0.0 (completely unhelpful) "
        "to 1.0 (maximally helpful). Return ONLY a single decimal number, nothing else."
    )
    try:
        raw = query_ollama(
            prompt=prompt,
            model=_HELPFULNESS_MODEL,
            system_prompt="You are a helpfulness evaluator. Output only a number between 0.0 and 1.0.",
            temperature=0.0,
            max_tokens=_HELPFULNESS_MAX_TOKENS,
            require_json=False,
        )
        val = _extract_float(raw)
        return val if val is not None else _HELPFULNESS_FALLBACK
    except Exception:
        return _HELPFULNESS_FALLBACK


# ---------------------------------------------------------------------------
# Reward calculation
# ---------------------------------------------------------------------------

def _reward(safety: float, helpfulness: float, context: str) -> float:
    weights = CONTEXT_WEIGHTS.get(context, _DEFAULT_WEIGHTS)
    return round(safety * weights["safety"] + helpfulness * weights["helpfulness"], 4)


# ---------------------------------------------------------------------------
# Per-pair scoring
# ---------------------------------------------------------------------------

def score_pair(pair: dict, rules: list[dict]) -> dict:
    """Score a single training pair and return an enriched record."""
    context = pair.get("context", "ambiguous")
    initial = pair.get("initial", "")
    revised = pair.get("revised", "")

    init_safety, init_violations = _safety_score(initial, rules)
    rev_safety, rev_violations = _safety_score(revised, rules)

    init_help = _helpfulness_score(initial)
    rev_help = _helpfulness_score(revised)

    init_reward = _reward(init_safety, init_help, context)
    rev_reward = _reward(rev_safety, rev_help, context)
    improvement = round(rev_reward - init_reward, 4)

    return {
        "request": pair.get("request", ""),
        "context": context,
        "timestamp": pair.get("timestamp", ""),
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "initial": {
            "safety_score": init_safety,
            "helpfulness_score": init_help,
            "violations": init_violations,
            "reward": init_reward,
        },
        "revised": {
            "safety_score": rev_safety,
            "helpfulness_score": rev_help,
            "violations": rev_violations,
            "reward": rev_reward,
        },
        "improvement": improvement,
    }


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_training_pairs() -> list[dict]:
    """Read all JSONL training pairs; skip malformed lines."""
    pairs: list[dict] = []
    if not os.path.exists(TRAINING_DATA_PATH):
        return pairs
    with open(TRAINING_DATA_PATH, "r") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                pairs.append(json.loads(line))
            except json.JSONDecodeError as exc:
                console.print(f"[yellow]Skipping malformed line {lineno}: {exc}[/yellow]")
    return pairs


def _save_scores(scores: list[dict]) -> None:
    os.makedirs(os.path.dirname(REWARD_SCORES_PATH), exist_ok=True)
    with open(REWARD_SCORES_PATH, "w") as f:
        for record in scores:
            f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _print_detail_table(scores: list[dict]) -> None:
    table = Table(title="Reward Scores — All Pairs", show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Context", min_width=11)
    table.add_column("Initial", justify="right", min_width=7)
    table.add_column("Revised", justify="right", min_width=7)
    table.add_column("Improvement", justify="right", min_width=11)
    table.add_column("Request (truncated)", no_wrap=True, max_width=48)

    for idx, s in enumerate(scores, start=1):
        imp = s["improvement"]
        imp_str = f"[green]+{imp:.2f}[/green]" if imp > 0 else (
            f"[red]{imp:.2f}[/red]" if imp < 0 else f"[dim]{imp:.2f}[/dim]"
        )
        table.add_row(
            str(idx),
            s["context"],
            f"{s['initial']['reward']:.2f}",
            f"{s['revised']['reward']:.2f}",
            imp_str,
            s["request"][:48],
        )

    console.print(table)


def _print_summary_table(scores: list[dict]) -> None:
    by_context: dict[str, list[dict]] = defaultdict(list)
    for s in scores:
        by_context[s["context"]].append(s)

    table = Table(title="Summary by Context", show_lines=True)
    table.add_column("Context", min_width=11)
    table.add_column("Pairs", justify="right")
    table.add_column("Initial", justify="right")
    table.add_column("Revised", justify="right")
    table.add_column("Improvement", justify="right")

    all_improvements: list[float] = []
    for ctx in ("educational", "ambiguous", "malicious"):
        group = by_context.get(ctx, [])
        if not group:
            continue
        init_avg = sum(s["initial"]["reward"] for s in group) / len(group)
        rev_avg = sum(s["revised"]["reward"] for s in group) / len(group)
        imp_avg = sum(s["improvement"] for s in group) / len(group)
        all_improvements.extend(s["improvement"] for s in group)
        imp_str = f"[green]+{imp_avg:.2f}[/green]" if imp_avg > 0 else (
            f"[red]{imp_avg:.2f}[/red]" if imp_avg < 0 else f"[dim]{imp_avg:.2f}[/dim]"
        )
        table.add_row(ctx, str(len(group)), f"{init_avg:.2f}", f"{rev_avg:.2f}", imp_str)

    console.print(table)

    if all_improvements:
        avg = sum(all_improvements) / len(all_improvements)
        sign = "+" if avg >= 0 else ""
        console.print(f"\n[bold]Average improvement: {sign}{avg:.2f}[/bold]")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(config_path: str = "config.yaml") -> list[dict]:
    """Score all training pairs and return the list of score records."""
    config = load_config(config_path)
    rules = config["constitution"]["rules"]

    console.rule("[bold blue]RL-CAI Reward Model[/bold blue]")

    pairs = _load_training_pairs()
    if not pairs:
        console.print(f"[yellow]No training pairs found at {TRAINING_DATA_PATH}[/yellow]")
        return []

    console.print(f"Loaded [bold]{len(pairs)}[/bold] training pair(s). Scoring...\n")

    scores: list[dict] = []
    for idx, pair in enumerate(pairs, start=1):
        console.print(f"[dim]Scoring {idx}/{len(pairs)}: {pair.get('request', '')[:60]}...[/dim]")
        record = score_pair(pair, rules)
        scores.append(record)

    _save_scores(scores)
    console.print(f"\n[green]Saved {len(scores)} score record(s) to {REWARD_SCORES_PATH}[/green]\n")

    _print_detail_table(scores)
    console.print()
    _print_summary_table(scores)

    return scores

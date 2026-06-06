"""Shared utilities for Ollama communication and file operations."""

import json
import os
import re
from typing import Any

import requests
import yaml
from rich.console import Console

console = Console()


def load_config(config_path: str = "config.yaml") -> dict:
    """Load YAML configuration."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def query_ollama(
    prompt: str,
    model: str,
    system_prompt: str = "",
    temperature: float = 0.2,
    max_tokens: int = 4096,
    host: str = "http://localhost:11434",
    require_json: bool = True,
) -> str:
    """Query a local Ollama model."""
    url = f"{host}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if require_json:
        # Enforce machine-readable output from the model.
        payload["format"] = "json"

    response = requests.post(url, json=payload, timeout=120)
    response.raise_for_status()
    data = response.json()
    model_output = data.get("response", "")

    # Thinking models (e.g. qwen3.5-mlx) route their chain-of-thought into a
    # separate "thinking" field and leave "response" empty when num_predict is
    # exhausted by the reasoning chain.  For non-JSON calls the thinking IS the
    # useful content, so fall back to it rather than silently returning "".
    if not model_output and not require_json:
        model_output = data.get("thinking", "")

    if require_json:
        # Fail fast if the model does not return valid JSON.
        json.loads(model_output)

    return model_output


def extract_code_blocks(text: str) -> list[dict]:
    """Extract fenced code blocks from markdown text."""
    pattern = r"```(\w+)?\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    blocks = []
    for lang, code in matches:
        blocks.append({"language": lang or "text", "code": code.strip()})
    return blocks


def scan_for_violations(text: str, rules: list[dict]) -> list[dict]:
    """Scan text for constitutional rule violations.

    Each pattern is compiled inside a try/except so a malformed regex in
    config.yaml never crashes the orchestrator — it logs a warning and skips
    that pattern instead.
    """
    violations = []
    for rule in rules:
        for pattern in rule.get("patterns", []):
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append(
                        {
                            "rule_id": rule["id"],
                            "rule_name": rule["name"],
                            "severity": rule["severity"],
                            "pattern": pattern,
                            "exception_tag": rule.get("exception_tag"),
                        }
                    )
                    break
            except re.error as exc:
                console.print(
                    f"[yellow]Warning: invalid regex pattern in rule "
                    f"{rule['id']} (skipping): {pattern!r} — {exc}[/yellow]"
                )
    return violations


def write_file_safe(path: str, content: str) -> None:
    """Write a file, ensuring the directory exists.

    Uses the resolved absolute path for both directory creation and the open()
    call so the file always lands at the intended location regardless of the
    current working directory.
    """
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w") as f:
        f.write(content)


def log_decision(log_path: str, decision: dict) -> None:
    """Append a decision to the log file."""
    with open(log_path, "a") as f:
        f.write(json.dumps(decision) + "\n")


def check_ollama(model: str, host: str = "http://localhost:11434") -> None:
    """Verify Ollama is running and the model is available. Raises a clear error if not."""
    try:
        resp = requests.get(f"{host}/api/tags", timeout=5)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            "Ollama is not running on localhost:11434.\n"
            "  1. Start Ollama:  ollama serve\n"
            "  2. Or launch the Ollama app from /Applications.\n"
            "  3. Verify:        curl http://localhost:11434/api/tags"
        )
    data = resp.json()
    available = {m.get("name", m.get("model", "")) for m in data.get("models", [])}
    if model not in available:
        raise RuntimeError(
            f"Model '{model}' is not available in Ollama.\n"
            f"  Installed models: {', '.join(available) or 'none'}\n"
            f"  Pull it with:     ollama pull {model}"
        )

"""Code repair utilities for fixing generated Python code.

Extracted from weaver.py to reduce monolithic size.
"""

import re
from typing import Tuple, List

from orchestrator.utils import console, query_ollama


def auto_fix_python_imports(code: str) -> Tuple[str, List[str]]:
    """Add common missing imports to reduce simple LLM codegen failures."""
    missing_imports: list[str] = []

    checks = [
        (r"\bcsv\.", r"(^|\n)\s*(import csv|from csv import )", "import csv"),
        (r"\bos\.", r"(^|\n)\s*(import os|from os import )", "import os"),
        (r"\bjson\.", r"(^|\n)\s*(import json|from json import )", "import json"),
        (r"\bre\.", r"(^|\n)\s*(import re|from re import )", "import re"),
        (r"\bsys\.", r"(^|\n)\s*(import sys|from sys import )", "import sys"),
        (r"\bargparse\.", r"(^|\n)\s*(import argparse|from argparse import )", "import argparse"),
        (r"\bPath\(", r"(^|\n)\s*(from pathlib import Path|import pathlib)", "from pathlib import Path"),
    ]

    for usage_pattern, import_pattern, import_stmt in checks:
        if re.search(usage_pattern, code) and not re.search(import_pattern, code):
            missing_imports.append(import_stmt)

    if not missing_imports:
        return code, []

    import_block = "\n".join(dict.fromkeys(missing_imports))
    return f"{import_block}\n\n{code}", list(dict.fromkeys(missing_imports))


def sanitize_python_code(code: str) -> Tuple[str, List[str]]:
    """Remove non-Python policy tags accidentally emitted into code blocks."""
    removed_tags: list[str] = []
    removed_shell_lines: list[str] = []
    cleaned_lines: list[str] = []
    tag_pattern = re.compile(
        r"^\s*\[(API_REQUIRED|FILESYSTEM_MODIFY|ROOT_REQUIRED|LOOP_REQUIRED|"
        r"AUDIT_APPROVED|REGULATORY_REVIEW)\]\s*$"
    )
    shell_pattern = re.compile(r"^\s*([!%](pip|python|python3)\b.*)$")

    for line in code.splitlines():
        match = tag_pattern.match(line)
        if match:
            removed_tags.append(match.group(0).strip())
            continue
        shell_match = shell_pattern.match(line)
        if shell_match:
            removed_shell_lines.append(shell_match.group(1).strip())
            continue
        cleaned_lines.append(line)

    removed_items = list(dict.fromkeys(removed_tags + removed_shell_lines))
    return "\n".join(cleaned_lines), removed_items


def validate_python_code(code: str) -> Tuple[bool, str]:
    """Compile Python code to catch syntax errors before sandbox execution."""
    try:
        compile(code, "<generated>", "exec")
        return True, ""
    except SyntaxError as e:
        return False, f"{e.msg} (line {e.lineno})"
    except Exception as e:
        return False, str(e)


def auto_fix_python_syntax(code: str, error: str) -> Tuple[str, List[str]]:
    """Apply deterministic repairs for common generated Python syntax mistakes."""
    fixes: list[str] = []
    fixed = code

    if "f-string expression part cannot include a backslash" in error:
        replaced_single = re.sub(r"\{\s*'\\\\n'\.join\(", "{chr(10).join(", fixed)
        replaced_double = re.sub(r'\{\s*"\\\\n"\.join\(', "{chr(10).join(", replaced_single)
        if replaced_double != fixed:
            fixed = replaced_double
            fixes.append("replaced {'\\n'.join(...)} in f-strings with {chr(10).join(...)}")

    return fixed, fixes


def strip_code_fences(text: str) -> str:
    """Remove optional markdown fences from model output."""
    stripped = text.strip()
    fence_match = re.search(r"```(?:python)?\n(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


def repair_python_code_with_llm(
    code: str,
    error: str,
    model: str,
    max_tokens: int,
) -> Tuple[str, bool]:
    """Ask the model for a syntax-only repair while preserving behavior."""
    repair_prompt = (
        "Fix ONLY Python syntax errors in the code below. Keep behavior unchanged.\n"
        "Return ONLY raw Python code (no markdown, no explanations).\n\n"
        f"Error: {error}\n\n"
        f"Code:\n{code}"
    )

    repaired = query_ollama(
        prompt=repair_prompt,
        model=model,
        system_prompt="You are a Python syntax repair assistant. Output code only.",
        temperature=0.0,
        max_tokens=max_tokens,
        require_json=False,
    )
    candidate = strip_code_fences(repaired)
    valid, _ = validate_python_code(candidate)
    return candidate, valid


def repair_runtime_failure_with_llm(
    code: str,
    stdout: str,
    stderr: str,
    original_request: str,
    model: str,
    max_tokens: int,
) -> Tuple[str, bool]:
    """Ask the LLM to fix a runtime failure using the actual sandbox stderr.

    This is the primary fix for the high failure rate: instead of giving up
    after the first sandbox crash, we feed the real error output back to the
    model and ask for a targeted fix.  Returns (repaired_code, syntax_valid).
    """
    stderr_excerpt = stderr.strip()[-2000:] if stderr else "(no stderr)"
    stdout_excerpt = stdout.strip()[-500:] if stdout else "(no stdout)"

    # Pull the most specific error line out of stderr to focus the model.
    error_line = ""
    for line in stderr_excerpt.splitlines():
        if "Error" in line or "error" in line:
            error_line = line.strip()
            break

    schema_hint = ""
    if (
        re.search(r"function[_ ]index\.json", original_request, re.IGNORECASE)
        or "function_index.json" in code
        or "function_index.json" in stderr
        or "function_index.json" in stdout
    ):
        schema_hint = (
            "\nSCHEMA HINT:\n"
            "/codebase/function_index.json is JSON with keys generated_from (list of strings) "
            "and functions (list of objects). Each function object includes: name, kind, "
            "file, line, end_line, signature, line_count, nested_if_depth.\n"
        )

    repair_prompt = (
        "The following Python code crashed at runtime. Fix it.\n\n"
        "STRICT RULES FOR YOUR FIX:\n"
        "1. Return ONLY raw Python code -- no markdown fences, no explanation.\n"
        "2. Do NOT change what the code is supposed to do.\n"
        "3. If the error is \'too many values to unpack\': count EXACTLY how many "
        "values are in the tuple/list being unpacked and match the left-hand side.\n"
        "4. Use simple flat variables instead of nested tuples where possible.\n"
        "5. Every variable you USE must be DEFINED earlier in the code.\n"
        "6. Test mentally: if you write \'a, b, c = func()\', make sure func() "
        "returns EXACTLY 3 values, not 4 or 2.\n\n"
        f"{schema_hint}"
        f"ORIGINAL REQUEST: {original_request}\n\n"
        f"SPECIFIC ERROR: {error_line}\n\n"
        f"FULL STDERR:\n{stderr_excerpt}\n\n"
        f"STDOUT BEFORE CRASH:\n{stdout_excerpt}\n\n"
        f"FAILING CODE:\n{code}"
    )

    console.print(
        "[yellow]Runtime failure detected -- asking LLM to repair using stderr...[/yellow]"
    )

    repaired_raw = query_ollama(
        prompt=repair_prompt,
        model=model,
        system_prompt=(
            "You are an expert Python debugger. "
            "Read the error carefully. "
            "For \'too many values to unpack\' errors: count the values in the source "
            "tuple and match the exact count on the left-hand side. "
            "Produce corrected, self-contained Python code only."
        ),
        temperature=0.0,
        max_tokens=max_tokens,
        require_json=False,
    )

    repaired = strip_code_fences(repaired_raw)
    valid, _ = validate_python_code(repaired)
    return repaired, valid

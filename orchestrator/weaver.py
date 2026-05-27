"""The Weaver: Primary planning and orchestration agent."""

import json
import os
import re
import shutil
import select
import sys
import tempfile
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from orchestrator.code_analyzer import CodeAnalyzer
from orchestrator.constitution import ConstitutionNode, ConstitutionalVerdict
from orchestrator.navigator import NavigatorGateway, NavigatorDecision
from orchestrator.persistence import Neo4jPersistence
from orchestrator.sandbox import SandboxedGarden, SandboxResult
from orchestrator.utils import (
    check_ollama,
    console,
    load_config,
    log_decision,
    query_ollama,
    write_file_safe,
)

# Maximum number of times we'll ask the LLM to repair code that failed at runtime.
_MAX_REPAIR_ATTEMPTS = 2


@dataclass
class TaskResult:
    """Complete result of an orchestrated task."""

    task_id: str
    plan_text: str
    code_blocks: list[dict]
    constitutional_verdict: ConstitutionalVerdict
    navigator_decision: Optional[NavigatorDecision]
    sandbox_result: Optional[SandboxResult]
    artifacts: list[str]


class WeaverOrchestrator:
    """Main orchestration engine tying all nodes together."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.constitution = ConstitutionNode(self.config)
        self.navigator = NavigatorGateway(self.config)
        self.sandbox = SandboxedGarden(self.config)
        self.model = self.config["weaver"]["model"]
        self.temperature = self.config["weaver"]["temperature"]
        self.max_tokens = self.config["weaver"]["max_tokens"]
        self.system_prompt = self.config["weaver"]["system_prompt"]
        self.persistence: Optional[Neo4jPersistence] = None
        self._vector_rag = None  # optionally set by run_orchestrator after VectorRAG init

    # ------------------------------------------------------------------
    # Tag helpers
    # ------------------------------------------------------------------

    def _extract_tags(self, text: str) -> list[str]:
        """Find explicit tags like [API_REQUIRED] in the text."""
        pattern = r"\[(?:API_REQUIRED|FILESYSTEM_MODIFY|ROOT_REQUIRED|LOOP_REQUIRED)\]"
        return list(set(re.findall(pattern, text)))

    def _infer_missing_tags(self, text: str, tags: list[str]) -> list[str]:
        """Infer required tags from generated content when the model forgets them.

        Scans only the executable_code value extracted from the JSON plan rather
        than the entire serialised plan string.  Scanning the full JSON causes
        false positives whenever words like requests appear inside the intent field.
        """
        inferred = set(tags)

        try:
            payload = json.loads(text)
            code_to_scan = payload.get("executable_code") or ""
        except (json.JSONDecodeError, AttributeError):
            code_to_scan = text

        network_patterns = [
            r"requests\.get",
            r"requests\.post",
            r"urllib\.request",
            r"http\.client",
            r"socket\.",
            r"https?://",
        ]
        if "[API_REQUIRED]" not in inferred and any(
            re.search(p, code_to_scan) for p in network_patterns
        ):
            inferred.add("[API_REQUIRED]")

        return list(inferred)

    def _normalize_tag(self, tag: str) -> str:
        """Normalize tags to bracketed form: [TAG]."""
        cleaned = tag.strip().strip("[]").upper()
        return f"[{cleaned}]"

    # ------------------------------------------------------------------
    # Code language / quality helpers
    # ------------------------------------------------------------------

    def _infer_code_language(self, code: str) -> str:
        """Best-effort language inference for a raw executable code string."""
        stripped = code.lstrip()
        if stripped.startswith("#!/bin/bash") or stripped.startswith("#!/usr/bin/env bash"):
            return "bash"
        if stripped.startswith("#!/bin/sh") or stripped.startswith("#!/usr/bin/env sh"):
            return "sh"
        return "python"

    def _run_preflight_analysis(self, code: str, language: str) -> list[dict]:
        """Run AST-based code analysis before sandbox execution.

        Returns only HIGH/CRITICAL severity issues as informational warnings.
        We do not block execution on these — the AST analyzer can produce
        false positives on generated code — but surfacing them helps debugging.
        """
        if language != "python":
            return []

        analyzer = CodeAnalyzer(code)
        all_issues = analyzer.get_all_issues()

        # bare_except is too noisy for generated code; exclude it.
        return [
            issue for issue in all_issues
            if issue.get("severity") in ("high", "critical")
            and issue.get("type") != "bare_except"
        ]

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _plan_task(self, user_request: str) -> dict[str, Any]:
        """Generate a deterministic JSON plan payload from the Weaver model."""
        console.rule("[bold blue]Weaver[/bold blue]")
        console.print("Generating execution plan...", style="dim")

        schema_instruction = (
            "Return ONLY valid JSON with this exact schema and no extra keys:\n"
            "{\n"
            '  "intent": "string (short description of the task)",\n'
            '  "safety_tags": ["array of strings (e.g., [FILESYSTEM_MODIFY], [API_REQUIRED], or empty [])"],\n'
            '  "target_file": "string (filename, or null)",\n'
            '  "executable_code": "string (the raw code to execute, or null)"\n'
            "}\n"
            "If no code is needed, set executable_code to null."
        )

        # Inject RAG context from past successful tasks (if vector store has entries).
        rag_context = ""
        if self._vector_rag is not None:
            try:
                rag_context = self._vector_rag.build_context_prompt(user_request)
            except Exception:
                pass  # never let RAG failure break planning

        schema_hint = ""
        if re.search(r"function[_ ]index\.json", user_request, re.IGNORECASE):
            schema_hint = (
                "\nSchema hint: /codebase/function_index.json is JSON with keys "
                "generated_from (list of strings) and functions (list of objects). "
                "Each function object includes: name, kind, file, line, end_line, "
                "signature, line_count, nested_if_depth.\n"
            )

        prompt = (
            f"USER REQUEST: {user_request}\n\n"
            f"{schema_instruction}\n\n"
            "Rules:\n"
            "1. Use explicit absolute paths like /codebase/... when file operations are involved.\n"
            "2. Put only executable code in executable_code (no markdown fences).\n"
            "3. Include [API_REQUIRED] only for network calls and [FILESYSTEM_MODIFY] only for writes/edits.\n"
            "4. Keep code self-contained and runnable.\n"
            + (f"\n{rag_context}" if rag_context else "")
            + schema_hint
        )
        raw_plan = query_ollama(
            prompt=prompt,
            model=self.model,
            system_prompt=(
                f"{self.system_prompt}\n\n"
                "You are operating in deterministic structured-output mode. "
                "Respond with JSON only, matching the requested schema exactly."
            ),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            require_json=True,
        )
        plan = json.loads(raw_plan)

        required_keys = {"intent", "safety_tags", "target_file", "executable_code"}
        missing_keys = required_keys - set(plan.keys())
        if missing_keys:
            raise json.JSONDecodeError(
                f"Missing keys in structured response: {sorted(missing_keys)}",
                raw_plan,
                0,
            )

        if not isinstance(plan.get("safety_tags"), list):
            raise json.JSONDecodeError("safety_tags must be an array", raw_plan, 0)

        console.print("[green]Plan generated.[/green]")
        return plan

    # ------------------------------------------------------------------
    # Code pre-processing helpers
    # ------------------------------------------------------------------

    def _auto_fix_python_imports(self, code: str) -> tuple[str, list[str]]:
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

    def _sanitize_python_code(self, code: str) -> tuple[str, list[str]]:
        """Remove non-Python policy tags accidentally emitted into code blocks."""
        removed_tags: list[str] = []
        removed_shell_lines: list[str] = []
        cleaned_lines: list[str] = []
        tag_pattern = re.compile(
            r"^\s*\[(API_REQUIRED|FILESYSTEM_MODIFY|ROOT_REQUIRED|LOOP_REQUIRED)\]\s*$"
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

    def _validate_python_code(self, code: str) -> tuple[bool, str]:
        """Compile Python code to catch syntax errors before sandbox execution."""
        try:
            compile(code, "<generated>", "exec")
            return True, ""
        except SyntaxError as e:
            return False, f"{e.msg} (line {e.lineno})"
        except Exception as e:
            return False, str(e)

    def _auto_fix_python_syntax(self, code: str, error: str) -> tuple[str, list[str]]:
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

    def _strip_code_fences(self, text: str) -> str:
        """Remove optional markdown fences from model output."""
        stripped = text.strip()
        fence_match = re.search(r"```(?:python)?\n(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
        if fence_match:
            return fence_match.group(1).strip()
        return stripped

    def _repair_python_code_with_llm(self, code: str, error: str) -> tuple[str, bool]:
        """Ask the model for a syntax-only repair while preserving behavior."""
        repair_prompt = (
            "Fix ONLY Python syntax errors in the code below. Keep behavior unchanged.\n"
            "Return ONLY raw Python code (no markdown, no explanations).\n\n"
            f"Error: {error}\n\n"
            f"Code:\n{code}"
        )

        repaired = query_ollama(
            prompt=repair_prompt,
            model=self.model,
            system_prompt="You are a Python syntax repair assistant. Output code only.",
            temperature=0.0,
            max_tokens=self.max_tokens,
            require_json=False,
        )
        candidate = self._strip_code_fences(repaired)
        valid, _ = self._validate_python_code(candidate)
        return candidate, valid

    def _repair_runtime_failure_with_llm(
        self,
        code: str,
        stdout: str,
        stderr: str,
        original_request: str,
    ) -> tuple[str, bool]:
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
            model=self.model,
            system_prompt=(
                "You are an expert Python debugger. "
                "Read the error carefully. "
                "For \'too many values to unpack\' errors: count the values in the source "
                "tuple and match the exact count on the left-hand side. "
                "Produce corrected, self-contained Python code only."
            ),
            temperature=0.0,
            max_tokens=self.max_tokens,
            require_json=False,
        )

        repaired = self._strip_code_fences(repaired_raw)
        valid, _ = self._validate_python_code(repaired)
        return repaired, valid

    # ------------------------------------------------------------------
    # Main orchestration pipeline
    # ------------------------------------------------------------------

    def run_task(self, user_request: str, auto_execute: bool = False) -> TaskResult:
        """Execute the full orchestration pipeline for a user request."""
        task_id = str(uuid.uuid4())[:8]
        console.rule(f"[bold]Task {task_id}[/bold]")
        console.print(f"Request: {user_request}")

        # Step 1: Weaver generates plan
        payload = self._plan_task(user_request)
        plan = json.dumps(payload, indent=2)

        raw_tags = [self._normalize_tag(str(tag)) for tag in payload.get("safety_tags", [])]
        tags = list(set(raw_tags))
        normalized_tags = self._infer_missing_tags(plan, tags)
        if set(normalized_tags) != set(tags):
            missing = sorted(set(normalized_tags) - set(tags))
            if missing:
                console.print(
                    "[yellow]Auto-inferred missing safety tags from plan content:[/yellow] "
                    + ", ".join(missing)
                )
        tags = normalized_tags

        code_blocks: list[dict] = []
        executable_code = payload.get("executable_code")
        if isinstance(executable_code, str) and executable_code.strip():
            code_blocks.append(
                {
                    "language": self._infer_code_language(executable_code),
                    "code": executable_code.strip(),
                }
            )

        console.print(f"\n[bold]Plan ({len(code_blocks)} code blocks found):[/bold]")
        console.print(plan[:500] + "..." if len(plan) > 500 else plan)

        # Step 2: Constitution Node evaluates
        verdict = self.constitution.evaluate(plan, tags)

        if not verdict.approved:
            console.print("\n[bold red]Execution halted by Constitution Node.[/bold red]")
            return TaskResult(
                task_id=task_id,
                plan_text=plan,
                code_blocks=code_blocks,
                constitutional_verdict=verdict,
                navigator_decision=None,
                sandbox_result=None,
                artifacts=[],
            )

        # Step 3: Navigator Gateway (human approval)
        nav_decision = self.navigator.request_approval(
            plan_text=plan,
            tags=tags,
            violations=verdict.violations,
            task_id=task_id,
        )

        if not nav_decision.approved:
            console.print("\n[bold red]Execution denied by Navigator Gateway.[/bold red]")
            return TaskResult(
                task_id=task_id,
                plan_text=plan,
                code_blocks=code_blocks,
                constitutional_verdict=verdict,
                navigator_decision=nav_decision,
                sandbox_result=None,
                artifacts=[],
            )

        # Step 4: Sandboxed Garden execution
        sandbox_result = None
        artifacts = []
        work_dir = tempfile.mkdtemp(prefix=f"orchestrator_{task_id}_")

        if code_blocks:
            # Group consecutive blocks of the same language and merge them.
            groups = []
            current_lang = code_blocks[0]["language"]
            current_codes = [code_blocks[0]["code"]]
            for block in code_blocks[1:]:
                if block["language"] == current_lang:
                    current_codes.append(block["code"])
                else:
                    groups.append((current_lang, "\n\n".join(current_codes)))
                    current_lang = block["language"]
                    current_codes = [block["code"]]
            groups.append((current_lang, "\n\n".join(current_codes)))

            for i, (lang, merged_code) in enumerate(groups):
                console.print(
                    f"\n[bold]Executing group {i+1}/{len(groups)} "
                    f"({lang}, {merged_code.count(chr(10))} lines)...[/bold]"
                )

                needs_network = "[API_REQUIRED]" in tags
                code_to_run = merged_code

                if lang == "python":
                    code_to_run, removed_tags = self._sanitize_python_code(merged_code)
                    if removed_tags:
                        console.print(
                            "[yellow]Removed non-Python lines before execution:[/yellow] "
                            + ", ".join(removed_tags)
                        )

                    code_to_run, added_imports = self._auto_fix_python_imports(code_to_run)
                    if added_imports:
                        console.print(
                            "[yellow]Auto-added missing imports before execution:[/yellow] "
                            + ", ".join(added_imports)
                        )

                    # Pre-flight syntax validation
                    valid, validation_error = self._validate_python_code(code_to_run)
                    if not valid:
                        code_to_run, syntax_fixes = self._auto_fix_python_syntax(
                            code_to_run, validation_error
                        )
                        if syntax_fixes:
                            console.print(
                                "[yellow]Auto-fixed Python syntax before execution:[/yellow] "
                                + ", ".join(syntax_fixes)
                            )
                        valid, validation_error = self._validate_python_code(code_to_run)
                        if not valid:
                            repaired_code, repaired_ok = self._repair_python_code_with_llm(
                                code_to_run, validation_error
                            )
                            if repaired_ok:
                                console.print(
                                    "[yellow]Applied LLM syntax-repair fallback before execution.[/yellow]"
                                )
                                code_to_run = repaired_code
                                valid, validation_error = self._validate_python_code(code_to_run)

                        if not valid:
                            console.print(
                                f"[bold red]Pre-execution Python validation failed:[/bold red] {validation_error}"
                            )
                            sandbox_result = SandboxResult(
                                success=False,
                                stdout="",
                                stderr=f"Python validation error before sandbox run: {validation_error}",
                                exit_code=1,
                                container_id="validation",
                                execution_time_ms=0,
                            )
                            break

                    # Pre-flight AST quality analysis (informational only — never blocks)
                    blockers = self._run_preflight_analysis(code_to_run, lang)
                    if blockers:
                        console.print(
                            f"[yellow]AST pre-flight found {len(blockers)} high-severity issue(s):[/yellow]"
                        )
                        for issue in blockers:
                            console.print(
                                f"  [yellow]line {issue.get('line', '?')} -- "
                                f"{issue['type']}: {issue['message']}[/yellow]"
                            )

                # Sandbox execution with runtime self-repair loop
                attempt = 0
                result = None
                while attempt <= _MAX_REPAIR_ATTEMPTS:
                    result = self.sandbox.execute(
                        code=code_to_run,
                        language=lang,
                        work_dir=work_dir,
                        network_enabled=needs_network,
                    )

                    if result.success:
                        break  # succeeded

                    attempt += 1
                    if attempt > _MAX_REPAIR_ATTEMPTS:
                        console.print(
                            f"[bold red]Execution failed after {_MAX_REPAIR_ATTEMPTS} repair "
                            f"attempt(s). Giving up.[/bold red]"
                        )
                        break

                    if lang != "python":
                        # Runtime self-repair only implemented for Python.
                        break

                    console.print(
                        f"[yellow]Sandbox failed (exit {result.exit_code}). "
                        f"Repair attempt {attempt}/{_MAX_REPAIR_ATTEMPTS}...[/yellow]"
                    )

                    repaired, syntax_ok = self._repair_runtime_failure_with_llm(
                        code=code_to_run,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        original_request=user_request,
                    )

                    if not syntax_ok:
                        console.print(
                            "[red]Repaired code has syntax errors -- skipping this attempt.[/red]"
                        )
                        break

                    console.print("[dim]Applying repaired code and re-running in sandbox...[/dim]")
                    code_to_run = repaired

                sandbox_result = result

                if result and result.success:
                    if result.stdout.strip():
                        console.print("[bold]Output:[/bold]")
                        console.print(result.stdout)
                    if len(result.stdout) > 50:
                        artifact_path = f"output_{task_id}_group{i}.txt"
                        write_file_safe(artifact_path, result.stdout)
                        artifacts.append(artifact_path)
                else:
                    if result:
                        console.print("[bold red]Execution failed:[/bold red]")
                        console.print(result.stdout)
                        console.print(result.stderr)
                    break

            # Collect any files created in the shared workspace as artifacts.
            # Only skip the known script files the orchestrator wrote itself.
            script_names = {"script.py", "script.sh", "script.txt", "input.txt"}
            if os.path.isdir(work_dir):
                for fname in os.listdir(work_dir):
                    fpath = os.path.join(work_dir, fname)
                    if os.path.isfile(fpath) and fname not in script_names:
                        dest = f"output_{task_id}_{fname}"
                        shutil.copy2(fpath, dest)
                        artifacts.append(dest)
        else:
            console.print("[yellow]No code blocks found to execute.[/yellow]")

        # Cleanup shared workspace
        shutil.rmtree(work_dir, ignore_errors=True)

        console.print(f"\n[bold green]Task {task_id} complete.[/bold green]")

        result_obj = TaskResult(
            task_id=task_id,
            plan_text=plan,
            code_blocks=code_blocks,
            constitutional_verdict=verdict,
            navigator_decision=nav_decision,
            sandbox_result=sandbox_result,
            artifacts=artifacts,
        )

        # Persist to knowledge graph if enabled
        if self.persistence:
            try:
                self.persistence.persist_task(result_obj, user_request)
                console.print("[dim]Task logged to knowledge graph.[/dim]")
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to log to Neo4j: {e}[/yellow]")

        return result_obj

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def enable_neo4j_persistence(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
    ) -> None:
        """Enable Neo4j knowledge graph persistence for all tasks."""
        self.persistence = Neo4jPersistence(uri, user, password)
        console.print("[dim]Neo4j persistence enabled.[/dim]")

    def _preflight(self) -> None:
        """Ensure Ollama and required models are available."""
        console.print("[dim]Pre-flight checks...[/dim]")
        check_ollama(self.model)
        check_ollama(self.config["constitution"]["model"])
        console.print("[green]Pre-flight checks passed.[/green]\n")

    def interactive_mode(self):
        """Run an interactive REPL for the orchestrator."""
        self._preflight()
        console.print(
            "\n[bold blue]Constitutional Orchestrator[/bold blue] "
            "- Interactive Mode\n"
            "Type your request, or 'quit' to exit, 'health' for diagnostics.\n"
        )

        while True:
            try:
                user_input = console.input("[bold blue]Weaver>[/bold blue] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\nExiting.")
                break

            extra_lines = self._drain_stdin_lines()
            if extra_lines:
                user_input = "\n".join([user_input] + extra_lines).strip()

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                console.print("Shutting down orchestrator.")
                break
            if user_input.lower() == "health":
                self._health_check()
                continue

            user_input = self._normalize_user_request(user_input)

            try:
                self.run_task(user_input)
            except json.JSONDecodeError as e:
                log_decision(
                    self.config["navigator"]["log_file"],
                    {
                        "task_id": str(uuid.uuid4())[:8],
                        "approved": False,
                        "reason": f"LLM structured output parse failure: {e}",
                        "escalation": "critical",
                        "tags": [],
                        "violations": ["STRUCTURED_OUTPUT_INVALID"],
                    },
                )
                console.print(
                    "[yellow]Warning: Weaver returned invalid JSON. Logged warning and exiting gracefully.[/yellow]"
                )
                break
            except Exception as e:
                console.print(f"[bold red]Orchestrator error: {e}[/bold red]")

    def _health_check(self) -> None:
        """Run diagnostics on all nodes."""
        console.rule("[bold]Health Check[/bold]")

        try:
            check_ollama(self.model)
            console.print(f"[green]Ollama (Weaver model {self.model}): OK[/green]")
        except Exception as e:
            console.print(f"[red]Ollama (Weaver model {self.model}): FAIL - {e}[/red]")

        try:
            check_ollama(self.config["constitution"]["model"])
            console.print(
                f"[green]Ollama (Constitution model "
                f"{self.config['constitution']['model']}): OK[/green]"
            )
        except Exception as e:
            console.print(
                f"[red]Ollama (Constitution model "
                f"{self.config['constitution']['model']}): FAIL - {e}[/red]"
            )

        try:
            healthy = self.sandbox.health_check()
            if healthy:
                console.print("[green]Docker Sandbox: OK[/green]")
        except Exception as e:
            console.print(f"[red]Docker Sandbox: FAIL - {e}[/red]")

    def _drain_stdin_lines(self) -> list[str]:
        """Drain any extra buffered lines (e.g., multi-line paste) from stdin."""
        if not sys.stdin.isatty():
            return []

        lines: list[str] = []
        while True:
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 0)
            except (OSError, ValueError):
                break
            if not ready:
                break
            line = sys.stdin.readline()
            if not line:
                break
            lines.append(line.rstrip("\n"))
        return lines

    def _normalize_user_request(self, text: str) -> str:
        """Normalize pasted requests so Tags lines are well-formed.

        If a paste merges "Tags:" into the request body, extract the tags
        and move a single "Tags: ..." line to the end of the request.
        """
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        tags: list[str] = []
        cleaned: list[str] = []
        tag_pattern = re.compile(r"\[([A-Z_]+)\]")

        for line in lines:
            if "Tags:" not in line:
                cleaned.append(line)
                continue

            pre, post = line.split("Tags:", 1)
            pre = pre.rstrip()
            post = post.strip()

            tags.extend([f"[{t}]" for t in tag_pattern.findall(post)])
            remainder = tag_pattern.sub("", post).strip()

            if pre:
                cleaned.append(pre)
            if remainder:
                cleaned.append(remainder)

        if tags:
            seen = set()
            unique_tags = []
            for tag in tags:
                if tag not in seen:
                    seen.add(tag)
                    unique_tags.append(tag)
            cleaned.append(f"Tags: {' '.join(unique_tags)}")

        return "\n".join(cleaned).strip()


def main():
    """CLI entry point."""
    config_path = "config.yaml"
    if len(sys.argv) > 1 and sys.argv[1].endswith(".yaml"):
        config_path = sys.argv[1]

    orchestrator = WeaverOrchestrator(config_path)

    try:
        orchestrator.enable_neo4j_persistence(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="password",
        )
    except Exception:
        console.print("[dim]Knowledge graph persistence unavailable; continuing without it.[/dim]")

    if len(sys.argv) > 1 and not sys.argv[1].endswith(".yaml"):
        request = " ".join(sys.argv[1:])
        try:
            orchestrator._preflight()
        except RuntimeError as e:
            console.print(f"[bold red]{e}[/bold red]")
            sys.exit(1)
        orchestrator.run_task(request)
    else:
        orchestrator.interactive_mode()


if __name__ == "__main__":
    main()

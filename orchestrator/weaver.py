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

from orchestrator.audit import AuditLogger
from orchestrator.code_analyzer import CodeAnalyzer
from orchestrator.code_repair import (
    auto_fix_python_imports,
    sanitize_python_code,
    validate_python_code,
    auto_fix_python_syntax,
    repair_python_code_with_llm,
    repair_runtime_failure_with_llm,
)
from orchestrator.constitution import ConstitutionNode, ConstitutionalVerdict
from orchestrator.navigator import NavigatorGateway, NavigatorDecision
from orchestrator.persistence import Neo4jPersistence
from orchestrator.regulatory import RegulatoryNode, RegulatoryVerdict
from orchestrator.sandbox import SandboxedGarden, SandboxResult
from orchestrator.utils import (
    check_ollama,
    console,
    load_config,
    log_decision,
    query_ollama,
    write_file_safe,
)
from orchestrator.training_data import save_training_pair
from orchestrator.weighted_resolution import detect_context, resolve as wcr_resolve

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
    response: Optional[str] = None
    regulatory_verdict: Optional[RegulatoryVerdict] = None


class WeaverOrchestrator:
    """Main orchestration engine tying all nodes together."""

    def __init__(
        self,
        config_path: str = "config.yaml",
        config: Optional[dict] = None,
        tenant_context: Optional[Any] = None,
    ):
        self.config = config or load_config(config_path)
        self.tenant_context = tenant_context
        self.tenant_id = (
            getattr(tenant_context, "tenant_id", None)
            or self.config.get("tenancy", {}).get("active_tenant")
        )
        self.constitution = ConstitutionNode(self.config)
        self.regulatory = RegulatoryNode(self.config)
        self.navigator = NavigatorGateway(self.config)
        self.sandbox = SandboxedGarden(self.config)
        self.audit_logger = AuditLogger.from_config(self.config, tenant_id=self.tenant_id)
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
        pattern = (
            r"\[(?:API_REQUIRED|FILESYSTEM_MODIFY|ROOT_REQUIRED|LOOP_REQUIRED|"
            r"AUDIT_APPROVED|REGULATORY_REVIEW)\]"
        )
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

        fs_write_patterns = [
            r"open\([^\n]*,\s*['\"](?:w|a|x|wb|ab|xb)\b",
            r"\.write_text\(",
            r"\.write_bytes\(",
            r"\.write\(",
            r"os\.remove\(",
            r"os\.unlink\(",
            r"os\.rename\(",
            r"shutil\.rmtree\(",
            r"shutil\.move\(",
            r"\bPath\([^\n]*\)\.mkdir\(",
        ]
        if "[FILESYSTEM_MODIFY]" not in inferred and any(
            re.search(p, code_to_scan) for p in fs_write_patterns
        ):
            inferred.add("[FILESYSTEM_MODIFY]")

        return list(inferred)

    def _normalize_tag(self, tag: str) -> str:
        """Normalize tags to bracketed form: [TAG]."""
        cleaned = tag.strip().strip("[]").upper()
        return f"[{cleaned}]"

    def _audit_event(self, event_type: str, task_id: str, data: Optional[dict] = None) -> None:
        """Emit a structured audit event if auditing is enabled."""
        if not self.audit_logger or not self.audit_logger.enabled:
            return
        self.audit_logger.log_event(event_type, task_id, data=data or {})

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
    # Critique-Revision (SL-CAI)
    # ------------------------------------------------------------------

    def revise_response(self, initial_response: str, critique: str) -> str:
        """Ask the LLM to rewrite a response, fixing all violations identified in the critique."""
        prompt = (
            f"ORIGINAL RESPONSE:\n{initial_response}\n\n"
            f"CRITIQUE (violations to fix):\n{critique}\n\n"
            "Rewrite the response to fix all identified violations while remaining as helpful as possible. "
            "Do not refuse outright — provide a revised response that addresses the user's intent safely."
        )
        raw = query_ollama(
            prompt=prompt,
            model=self.model,
            system_prompt=self.system_prompt,
            temperature=0.6,
            max_tokens=self.max_tokens,
            require_json=False,
        )
        return raw.strip()

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
            '  "executable_code": "string (the raw code to execute, or null)",\n'
            '  "response": "string (direct answer/advice if task is conversational and needs no code, or null)"\n'
            "}\n"
            "Rules:\n"
            "- If task requires code execution: set executable_code and response=null\n"
            "- If task is conversational/informational: set response to the answer and executable_code=null\n"
            "- Do NOT set both executable_code and response (choose one)"
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

        tenant_notice = ""
        if self.tenant_context:
            tenant_notice = (
                "\nTENANT CONTEXT:\n"
                f"- tenant_id: {self.tenant_context.tenant_id}\n"
                f"- tenant_storage: {self.tenant_context.storage_mount} (write outputs here)\n"
                f"- tenant_secrets: {self.tenant_context.secrets_mount} (read-only)\n"
                "Rules:\n"
                "- Write new artifacts to tenant_storage unless explicitly asked to edit /codebase.\n"
                "- Do not access other tenant paths.\n"
            )

        prompt = (
            f"USER REQUEST: {user_request}\n\n"
            f"{schema_instruction}\n\n"
            "Rules:\n"
            "1. Use explicit absolute paths like /codebase/... or /tenant_storage/... when file operations are involved.\n"
            "2. Put only executable code in executable_code (no markdown fences).\n"
            "3. Include [API_REQUIRED] only for network calls and [FILESYSTEM_MODIFY] only for writes/edits.\n"
            "4. Keep code self-contained and runnable.\n"
            + tenant_notice
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
        # WCR fallback — if model returned plain text refusal, construct safe plan
        try:
            plan = json.loads(raw_plan)
        except json.JSONDecodeError:
            context = detect_context(user_request)
            plan = {
                "intent": f"Request classified as {context} by WCR",
                "safety_tags": [],
                "target_file": None,
                "executable_code": None,
                "response": raw_plan if context == "educational" else
                           "I cannot assist with this request."
            }

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

        # Ensure response field exists (default to null if not provided)
        if "response" not in plan:
            plan["response"] = None

        console.print("[green]Plan generated.[/green]")
        return plan

    # ------------------------------------------------------------------
    # Code pre-processing helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Main orchestration pipeline
    # ------------------------------------------------------------------

    def run_task(self, user_request: str, auto_execute: bool = False) -> TaskResult:
        """Execute the full orchestration pipeline for a user request."""
        task_id = str(uuid.uuid4())[:8]
        console.rule(f"[bold]Task {task_id}[/bold]")
        console.print(f"Request: {user_request}")

        self._audit_event(
            "task_started",
            task_id,
            {
                "request": user_request,
                "auto_execute": auto_execute,
            },
        )

        tenant_storage_dir = (
            str(self.tenant_context.storage_dir)
            if self.tenant_context is not None
            else None
        )
        tenant_secrets_dir = (
            str(self.tenant_context.secrets_dir)
            if self.tenant_context is not None
            else None
        )

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
        no_execution = False
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

        plan_preview = None
        if self.audit_logger:
            plan_preview = self.audit_logger.maybe_include_plan(plan)
        audit_plan_data = {
            "intent": payload.get("intent"),
            "target_file": payload.get("target_file"),
            "tags": tags,
            "code_blocks": len(code_blocks),
        }
        if plan_preview:
            audit_plan_data["plan_preview"] = plan_preview
        self._audit_event("plan_generated", task_id, audit_plan_data)

        # Step 2: Constitution Node evaluates
        verdict = self.constitution.evaluate(plan, tags)

        self._audit_event(
            "constitution_verdict",
            task_id,
            {
                "approved": verdict.approved,
                "requires_human_review": verdict.requires_human_review,
                "rule_ids": verdict.rule_ids_triggered,
                "violations": verdict.violations,
            },
        )

        # Step 2a: Weighted Constitutional Resolution — always runs after constitution verdict
        wcr_result = wcr_resolve(
            request=user_request,
            original_response=payload.get("response", ""),
            violations=verdict.violations,
            constitution_approved=verdict.approved
        )
        console.print(
            f"\n[bold cyan]Weighted Resolution:[/bold cyan] "
            f"Context={wcr_result['context']} | "
            f"Safety={wcr_result['weights']['safety']} | "
            f"Helpfulness={wcr_result['weights']['helpfulness']} | "
            f"Amalgamated={wcr_result['amalgamated']}"
        )

        # Step 2b: Critique-Revision loop (SL-CAI)
        # Run only for educational or ambiguous context — skip malicious (already blocked by WCR)
        wcr_context = wcr_result["context"]
        initial_response = payload.get("response") or ""
        if wcr_context in ("educational", "ambiguous") and initial_response:
            _MAX_REVISIONS = 2
            current_response = initial_response
            final_critique = ""
            for _rev_iter in range(_MAX_REVISIONS):
                console.print(f"\n[bold magenta]Critique-Revision [{_rev_iter + 1}/{_MAX_REVISIONS}][/bold magenta]")
                critique = self.constitution.critique_response(
                    user_request=user_request,
                    initial_response=current_response,
                    constitutional_principles=self.constitution.rules,
                )
                final_critique = critique

                # Count violations by looking for non-trivial critique content
                violation_lines = [
                    ln for ln in critique.splitlines()
                    if ln.strip() and "no violation" not in ln.lower()
                ]
                console.print(
                    f"[bold magenta][CRITIQUE][/bold magenta] Found {len(violation_lines)} violation line(s): "
                    + (violation_lines[0][:120] if violation_lines else "none")
                )

                if not violation_lines or "no violation" in critique.lower():
                    break  # nothing to fix

                console.print("[bold magenta][REVISION][/bold magenta] Rewriting response...")
                current_response = self.revise_response(current_response, critique)

            # Save training pair regardless of whether revisions occurred
            try:
                save_training_pair(
                    request=user_request,
                    initial=initial_response,
                    critique=final_critique,
                    revised=current_response,
                    context=wcr_context,
                )
                console.print("[bold magenta][TRAINING][/bold magenta] Saved pair to training_data.jsonl")
            except Exception as _e:
                console.print(f"[yellow]Warning: could not save training pair: {_e}[/yellow]")

            # Surface the revised response back into the payload so downstream code uses it
            if current_response != initial_response:
                payload["response"] = current_response
                wcr_result["final_response"] = current_response

        if not verdict.approved:
            if wcr_result['amalgamated']:
                console.print("[bold yellow]WCR Override: Providing amalgamated response[/bold yellow]")
                console.print(f"\nResponse:\n{wcr_result['final_response']}")
                return TaskResult(
                    task_id=task_id,
                    plan_text=plan,
                    code_blocks=[],
                    constitutional_verdict=verdict,
                    regulatory_verdict=None,
                    navigator_decision=None,
                    sandbox_result=None,
                    artifacts=[],
                )
            console.print("\n[bold red]Execution halted by Constitution Node.[/bold red]")
            self._audit_event(
                "task_blocked",
                task_id,
                {
                    "reason": "constitution_denied",
                    "violations": verdict.violations,
                },
            )
            return TaskResult(
                task_id=task_id,
                plan_text=plan,
                code_blocks=code_blocks,
                constitutional_verdict=verdict,
                regulatory_verdict=None,
                navigator_decision=None,
                sandbox_result=None,
                artifacts=[],
            )

        # Step 2b: Regulatory compliance check
        regulatory_verdict = self.regulatory.evaluate(plan, tags)
        self._audit_event(
            "regulatory_verdict",
            task_id,
            {
                "approved": regulatory_verdict.approved,
                "requires_human_review": regulatory_verdict.requires_human_review,
                "violations": regulatory_verdict.violations,
            },
        )
        if not regulatory_verdict.approved:
            console.print("\n[bold red]Execution halted by Regulatory Node.[/bold red]")
            self._audit_event(
                "task_blocked",
                task_id,
                {
                    "reason": "regulatory_denied",
                    "violations": regulatory_verdict.violations,
                },
            )
            return TaskResult(
                task_id=task_id,
                plan_text=plan,
                code_blocks=code_blocks,
                constitutional_verdict=verdict,
                regulatory_verdict=regulatory_verdict,
                navigator_decision=None,
                sandbox_result=None,
                artifacts=[],
            )

        if regulatory_verdict.requires_human_review and "[REGULATORY_REVIEW]" not in tags:
            tags.append("[REGULATORY_REVIEW]")

        # Step 3: Navigator Gateway (human approval)
        combined_violations = verdict.violations + regulatory_verdict.violations
        nav_decision = self.navigator.request_approval(
            plan_text=plan,
            tags=tags,
            violations=combined_violations,
            task_id=task_id,
        )

        self._audit_event(
            "navigator_decision",
            task_id,
            {
                "approved": nav_decision.approved,
                "reason": nav_decision.reason,
                "escalation_level": nav_decision.escalation_level,
                "tags": tags,
                "violations": combined_violations,
            },
        )

        if not nav_decision.approved:
            console.print("\n[bold red]Execution denied by Navigator Gateway.[/bold red]")
            self._audit_event(
                "task_blocked",
                task_id,
                {
                    "reason": "navigator_denied",
                    "violations": combined_violations,
                },
            )
            return TaskResult(
                task_id=task_id,
                plan_text=plan,
                code_blocks=code_blocks,
                constitutional_verdict=verdict,
                regulatory_verdict=regulatory_verdict,
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
                require_write_tag = bool(
                    self.config.get("sandbox", {}).get("codebase_write_requires_tag", True)
                )
                allow_codebase_write = (
                    "[FILESYSTEM_MODIFY]" in tags if require_write_tag else True
                )
                code_to_run = merged_code

                if lang == "python":
                    code_to_run, removed_tags = sanitize_python_code(merged_code)
                    if removed_tags:
                        console.print(
                            "[yellow]Removed non-Python lines before execution:[/yellow] "
                            + ", ".join(removed_tags)
                        )

                    code_to_run, added_imports = auto_fix_python_imports(code_to_run)
                    if added_imports:
                        console.print(
                            "[yellow]Auto-added missing imports before execution:[/yellow] "
                            + ", ".join(added_imports)
                        )

                    # Pre-flight syntax validation
                    valid, validation_error = validate_python_code(code_to_run)
                    if not valid:
                        code_to_run, syntax_fixes = auto_fix_python_syntax(
                            code_to_run, validation_error
                        )
                        if syntax_fixes:
                            console.print(
                                "[yellow]Auto-fixed Python syntax before execution:[/yellow] "
                                + ", ".join(syntax_fixes)
                            )
                        valid, validation_error = self._validate_python_code(code_to_run)
                        if not valid:
                            repaired_code, repaired_ok = repair_python_code_with_llm(
                                code_to_run, validation_error, self.model, self.max_tokens
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
                        codebase_write=allow_codebase_write,
                        tenant_storage_dir=tenant_storage_dir,
                        tenant_secrets_dir=tenant_secrets_dir,
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

                    repaired, syntax_ok = repair_runtime_failure_with_llm(
                        code=code_to_run,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        original_request=user_request,
                        model=self.model,
                        max_tokens=self.max_tokens,
                    )

                    if not syntax_ok:
                        console.print(
                            "[red]Repaired code has syntax errors -- skipping this attempt.[/red]"
                        )
                        break

                    console.print("[dim]Applying repaired code and re-running in sandbox...[/dim]")
                    code_to_run = repaired

                sandbox_result = result

                if result:
                    stdout_preview = result.stdout
                    stderr_preview = result.stderr
                    if self.audit_logger:
                        stdout_preview = self.audit_logger.trim_text(result.stdout)
                        stderr_preview = self.audit_logger.trim_text(result.stderr)
                    else:
                        stdout_preview = stdout_preview[:2000]
                        stderr_preview = stderr_preview[:2000]

                    self._audit_event(
                        "sandbox_result",
                        task_id,
                        {
                            "group": i + 1,
                            "language": lang,
                            "success": result.success,
                            "exit_code": result.exit_code,
                            "execution_time_ms": result.execution_time_ms,
                            "stdout_preview": stdout_preview,
                            "stderr_preview": stderr_preview,
                        },
                    )

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
            # No code blocks — check if there's a conversational response
            if payload.get("response"):
                console.print("[bold green]Response:[/bold green]")
                console.print(payload.get("response"))
                no_execution = False  # Mark as successful non-execution
            else:
                console.print("[yellow]No code blocks found to execute.[/yellow]")
                no_execution = True

        # Cleanup shared workspace
        shutil.rmtree(work_dir, ignore_errors=True)

        console.print(f"\n[bold green]Task {task_id} complete.[/bold green]")

        result_obj = TaskResult(
            task_id=task_id,
            plan_text=plan,
            code_blocks=code_blocks,
            constitutional_verdict=verdict,
            regulatory_verdict=regulatory_verdict,
            navigator_decision=nav_decision,
            sandbox_result=sandbox_result,
            artifacts=artifacts,
            response=payload.get("response"),
        )

        # Persist to knowledge graph if enabled
        if self.persistence:
            try:
                self.persistence.persist_task(
                    result_obj,
                    user_request,
                    tenant_id=self.tenant_id,
                )
                console.print("[dim]Task logged to knowledge graph.[/dim]")
                self._audit_event(
                    "persistence_result",
                    task_id,
                    {"status": "success", "backend": "neo4j"},
                )
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to log to Neo4j: {e}[/yellow]")
                self._audit_event(
                    "persistence_result",
                    task_id,
                    {"status": "failed", "backend": "neo4j", "error": str(e)},
                )

        final_success = bool(sandbox_result and sandbox_result.success)
        if no_execution:
            final_status = "NO_EXECUTION"
            final_success = False
        else:
            final_status = "SUCCESS" if final_success else "FAILED"
        self._audit_event(
            "task_completed",
            task_id,
            {
                "status": final_status,
                "success": final_success,
                "artifacts": artifacts,
            },
        )

        return result_obj

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def enable_neo4j_persistence(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
        tenant_id: Optional[str] = None,
    ) -> None:
        """Enable Neo4j knowledge graph persistence for all tasks."""
        resolved_tenant = tenant_id or self.tenant_id
        self.persistence = Neo4jPersistence(uri, user, password, tenant_id=resolved_tenant)
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
                failure_task_id = str(uuid.uuid4())[:8]
                log_decision(
                    self.config["navigator"]["log_file"],
                    {
                        "task_id": failure_task_id,
                        "tenant_id": self.tenant_id,
                        "approved": False,
                        "reason": f"LLM structured output parse failure: {e}",
                        "escalation": "critical",
                        "tags": [],
                        "violations": ["STRUCTURED_OUTPUT_INVALID"],
                    },
                )
                self._audit_event(
                    "task_failed",
                    failure_task_id,
                    {
                        "reason": "structured_output_invalid",
                        "error": str(e),
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

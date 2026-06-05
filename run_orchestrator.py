#!/usr/bin/env python3
"""
Convenience runner for the Constitutional Orchestrator.

Starts the interactive REPL with:
  - Neo4j knowledge graph persistence (optional — skipped silently if unavailable)
  - VectorRAG memory (optional — skipped if sentence-transformers/chromadb not installed)

Usage:
    python run_orchestrator.py               # interactive mode
    python run_orchestrator.py my.yaml       # custom config file
    python run_orchestrator.py "do X"        # run a single task and exit
    python run_orchestrator.py my.yaml "do X"# custom config + single task
    python run_orchestrator.py --health      # run health checks and exit
    python run_orchestrator.py --tenant acme  # tenant-scoped execution

Model selection:
    Edit config.yaml -> weaver.model to switch between any locally installed Ollama model.
    Run `ollama list` to see what you have, `ollama pull <name>` to add more.
"""

import sys
import os
from orchestrator.tenancy import TenancyManager
from orchestrator.utils import console, load_config
from orchestrator.weaver import WeaverOrchestrator


def main():
    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    args = sys.argv[1:]
    health_only = False
    tenant_id = None
    if "--health" in args:
        health_only = True
        args = [a for a in args if a != "--health"]
    if "health" in args:
        health_only = True
        args = [a for a in args if a != "health"]

    if "--tenant" in args:
        idx = args.index("--tenant")
        if idx + 1 >= len(args):
            console.print("[bold red]--tenant requires a value[/bold red]")
            sys.exit(2)
        tenant_id = args[idx + 1]
        del args[idx : idx + 2]
    else:
        for arg in list(args):
            if arg.startswith("--tenant="):
                tenant_id = arg.split("=", 1)[1]
                args.remove(arg)
                break

    config_path = "config.yaml"
    if args and args[0].endswith(".yaml"):
        config_path = args[0]
        args = args[1:]

    config = load_config(config_path)
    tenancy = TenancyManager(config, tenant_id=tenant_id)
    if tenancy.enabled:
        config = tenancy.apply_overrides(config)

    orchestrator = WeaverOrchestrator(
        config_path,
        config=config,
        tenant_context=tenancy.context,
    )

    # ------------------------------------------------------------------
    # Neo4j persistence (optional — disabled by default)
    # ------------------------------------------------------------------
    # Neo4j is optional. VectorRAG (sentence-transformers + Chroma) handles
    # all memory needs offline. To enable Neo4j, set these env vars:
    #   export NEO4J_ENABLED=true
    #   export NEO4J_PASSWORD=your_password
    if os.environ.get("NEO4J_ENABLED", "false").lower() == "true":
        neo4j_uri  = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
        neo4j_user = os.environ.get("NEO4J_USER",     "neo4j")
        neo4j_pass = os.environ.get("NEO4J_PASSWORD", "password")
        try:
            orchestrator.enable_neo4j_persistence(
                uri=neo4j_uri,
                user=neo4j_user,
                password=neo4j_pass,
                tenant_id=tenancy.tenant_id if tenancy.enabled else None,
            )
        except Exception:
            console.print("[dim]Neo4j unavailable — continuing without knowledge-graph persistence.[/dim]")
    else:
        console.print("[dim]Neo4j disabled — using VectorRAG for memory.[/dim]")

    # ------------------------------------------------------------------
    # VectorRAG memory (optional — fully offline)
    # ------------------------------------------------------------------
    rag_config = config.get("rag", {})
    vector_rag = None

    if rag_config.get("enabled", False) and rag_config.get("backend", "vector") == "vector":
        try:
            from orchestrator.rag import VectorRAG, _VECTOR_AVAILABLE
            if _VECTOR_AVAILABLE:
                chroma_path = rag_config.get("chroma_path", ".chroma_store")
                vector_rag = VectorRAG(chroma_path=chroma_path)
                stored = vector_rag.total_tasks()
                console.print(
                    f"[dim]VectorRAG ready — {stored} task(s) in memory "
                    f"(store: {chroma_path}).[/dim]"
                )
            else:
                console.print(
                    "[dim]VectorRAG not available (install with: "
                    "pip install sentence-transformers chromadb).[/dim]"
                )
        except Exception as e:
            console.print(f"[dim]VectorRAG init failed ({e}) — continuing without it.[/dim]")

    # Attach vector_rag to the orchestrator so run_task can persist to it.
    orchestrator._vector_rag = vector_rag

    # Monkey-patch run_task to auto-index completed tasks into the vector store.
    if vector_rag is not None:
        _original_run_task = orchestrator.run_task

        def _run_task_with_rag(user_request: str, **kwargs):
            result = _original_run_task(user_request, **kwargs)
            # Index the completed task into the vector store for future retrieval.
            try:
                code = result.code_blocks[0]["code"] if result.code_blocks else None
                success = (
                    result.sandbox_result is not None
                    and result.sandbox_result.success
                )
                tags = list(result.constitutional_verdict.human_review_tags) if hasattr(
                    result.constitutional_verdict, "human_review_tags"
                ) else []
                vector_rag.add_task(
                    task_id=result.task_id,
                    request=user_request,
                    code=code,
                    success=success,
                    tags=tags,
                    tenant_id=tenancy.tenant_id if tenancy.enabled else None,
                )
            except Exception:
                pass  # never let RAG indexing break the main flow
            return result

        orchestrator.run_task = _run_task_with_rag

    # ------------------------------------------------------------------
    # Show active model
    # ------------------------------------------------------------------
    console.print(
        f"[dim]Model: [bold]{orchestrator.model}[/bold]  "
        f"(change via config.yaml → weaver.model)[/dim]"
    )
    if tenancy.enabled and tenancy.context:
        console.print(
            f"[dim]Tenant: [bold]{tenancy.context.tenant_id}[/bold]  "
            f"(storage: {tenancy.context.storage_dir})[/dim]"
        )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    if health_only:
        orchestrator._health_check()
        return

    if args:
        request = " ".join(args)
        try:
            orchestrator._preflight()
        except RuntimeError as e:
            console.print(f"[bold red]{e}[/bold red]")
            sys.exit(1)
        orchestrator.run_task(request)
        return

    orchestrator.interactive_mode()


if __name__ == "__main__":
    main()

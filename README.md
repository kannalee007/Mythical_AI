# Mythical_AI

Constitutional Orchestrator is a local, agentic orchestration pipeline for macOS that distributes tasks across specialized nodes instead of relying on a single monolithic AI.

A local, agentic orchestration pipeline for macOS that distributes tasks across specialized nodes instead of relying on a single monolithic AI.

## Enterprise Edition

See [ENTERPRISE_EDITION.md](ENTERPRISE_EDITION.md) for the enterprise product vision, roadmap, and positioning.

## Architecture

| Node | Role | Model / Tool |
|------|------|-------------|
| **The Weaver** | Primary planner (Windsurf-facing agent) | Ollama (model from config.yaml; default qwen2.5:7b) |
| **The Constitution Node** | Safety evaluator with hard-coded rules | Ollama (model from config.yaml; default qwen2.5:7b) |
| **The Regulatory Node** | Compliance-focused safety scan | Pattern rules (config.yaml) |
| **The Sandboxed Garden** | Isolated execution environment | Docker container |
| **The Navigator Gateway** | Human-in-the-loop approval | Terminal prompt |

## Flow

1. You submit a high-level task to the Weaver
2. The Weaver drafts a step-by-step plan with code
3. The Constitution Node pattern-scans + LLM-evaluates the plan for safety violations
4. The Regulatory Node scans for compliance risks
5. If flagged, the plan bounces back with errors
6. If approved, the Navigator Gateway checks for sensitive operations (API calls, file modifications)
7. If human approval is required, you get a terminal prompt: `[System Change Requested. Review Plan Y/N?]`
8. Once fully cleared, code executes inside a Docker sandbox (no network, read-only rootfs, memory limits)

## Prerequisites

- macOS (M4 MacBook optimized)
- [Ollama](https://ollama.com/download/mac) installed and running
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- Python 3.11+

## Quick Start

```bash
# 1. Clone or navigate to the project
cd mythical_ai

# 2. Run the setup script
bash scripts/setup.sh

# 3. Optional: run health checks
python run_orchestrator.py --health

# 4. Launch interactive mode
python run_orchestrator.py

# 5. Optional: run the audit dashboard
python scripts/run_dashboard.py

# 4. Or pass a one-shot task
python run_orchestrator.py "Generate a CSV with 100 random numbers and compute their mean"
```

For fully local deployments, see [SELF_HOSTED.md](SELF_HOSTED.md).

## Interactive Commands

Inside the REPL:
- Type any natural language task
- `health` — run diagnostics on all nodes
- `quit` — exit

## Configuration

Edit `config.yaml` to customize:
- Models for Weaver and Constitution Node
- Constitutional rules and severity levels
- Sandbox resource limits (memory, CPU, timeout)
- Auto-approval behavior for the Navigator Gateway
- Audit event logging
- Regulatory compliance rules

## Safety Defaults

The system ships with these conservative defaults:
- **Network disabled by default** in sandbox (bridge only when `[API_REQUIRED]`)
- **Read-only root filesystem** is configurable (default: false)
- **Blocked syscalls**: `CAP_NET_ADMIN`, `CAP_SYS_ADMIN`, `CAP_SYS_PTRACE`
- **Memory limit**: 512 MB per container
- **Execution timeout**: 30 seconds
- **Human approval required** for: `[API_REQUIRED]`, `[FILESYSTEM_MODIFY]`, `[ROOT_REQUIRED]`

## Project Structure

```
.
├── config.yaml              # All node configuration
├── Dockerfile.sandbox       # Minimal isolated execution image
├── requirements.txt         # Python dependencies
├── run_orchestrator.py      # CLI entry point
├── dashboard/               # FastAPI audit + compliance UI
├── scripts/
│   └── setup.sh             # One-command setup
└── orchestrator/
    ├── __init__.py
    ├── weaver.py            # Main orchestration engine
    ├── constitution.py      # Safety evaluator node
    ├── sandbox.py           # Docker execution manager
    ├── navigator.py         # Human approval gateway
    └── utils.py             # Shared helpers (Ollama client, scanners)
```

## License

MIT

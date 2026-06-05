# Mythical AI - Complete Project Walkthrough

**Project Name:** Constitutional Orchestrator (Mythical_AI)  
**Purpose:** A local, agentic orchestration pipeline for macOS that distributes tasks across specialized AI nodes with safety guardrails, compliance checks, and human-in-the-loop approval.  
**Status:** Multi-node AI system with REST API, WebSocket streaming, audit dashboard, and enterprise tenancy support.

---

## Table of Contents
1. [High-Level Overview](#high-level-overview)
2. [Architecture & Data Flow](#architecture--data-flow)
3. [Core Components](#core-components)
4. [Project Structure](#project-structure)
5. [Tech Stack](#tech-stack)
6. [Key Features](#key-features)
7. [Setup & Deployment](#setup--deployment)
8. [API Endpoints](#api-endpoints)
9. [Configuration](#configuration)
10. [Common Workflows](#common-workflows)

---

## High-Level Overview

### What is Mythical AI?

Mythical AI is a **Constitutional Orchestrator** — a safety-first, multi-agent AI system that:
- Takes high-level tasks from users (natural language)
- Distributes planning, safety review, and execution across specialized nodes
- Enforces constitutional rules, regulatory compliance, and human approvals
- Runs code in isolated Docker sandboxes (no network, read-only filesystem, resource limits)
- Maintains audit trails and compliance logs in Neo4j
- Supports multi-tenant isolation with role-based access control

### Key Philosophy
Instead of a single monolithic AI making all decisions, the system uses a **node-based architecture**:
- **The Weaver** → Planning & code generation
- **The Constitution Node** → Safety & policy enforcement
- **The Regulatory Node** → Compliance scanning
- **The Navigator Gateway** → Human-in-the-loop approval
- **The Sandboxed Garden** → Isolated code execution
- **Neo4j** → Knowledge graph persistence & audit logging

---

## Architecture & Data Flow

### Complete Request Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│  1. USER SUBMISSION                                             │
│  Natural language task → API endpoint or CLI                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                    ┌────▼──────────────────┐
                    │  run_orchestrator.py  │ CLI Entry Point
                    │  (Main Event Loop)    │
                    └────┬──────────────────┘
                         │
            ┌────────────┼────────────┐
            │            │            │
            │    ┌───────▼────────┐   │
            │    │   2. WEAVER    │◄──┤
            │    │   (Planning)   │   │
            │    │   - Draft plan │   │
            │    │   - Generate   │   │
            │    │     code       │   │
            │    └───────┬────────┘   │
            │            │            │
            │    ┌───────▼─────────────────────────────┐
            │    │   3. CONSTITUTION NODE (Safety)    │
            │    │   - Pattern scan for violations    │
            │    │   - LLM deep-reasoning evaluation  │
            │    │   - Check exception tags          │
            │    │   - Return verdict: APPROVED /    │
            │    │     CONDITIONAL / DENIED          │
            │    └───────┬────────────────────────────┘
            │            │
            │    ┌───────▼─────────────────────────────┐
            │    │   4. REGULATORY NODE (Compliance)  │
            │    │   - Scan for compliance rules      │
            │    │   - Check audit requirements       │
            │    │   - Return compliance verdict      │
            │    └───────┬────────────────────────────┘
            │            │
            │    ┌───────▼─────────────────────────────┐
            │    │   5. NAVIGATOR GATEWAY (Approval)  │
            │    │   - Check if human approval needed │
            │    │   - Categories: API calls, file    │
            │    │     modifications, root access     │
            │    │   - Terminal prompt: [Y/N?]        │
            │    └───────┬────────────────────────────┘
            │            │
            │    ┌───────▼─────────────────────────────┐
            │    │   6. SANDBOXED EXECUTION           │
            │    │   - Docker container               │
            │    │   - Resource limits (512MB RAM)    │
            │    │   - 30 sec timeout                 │
            │    │   - No network by default          │
            │    │   - Execution result or error      │
            │    └───────┬────────────────────────────┘
            │            │
            │    ┌───────▼─────────────────────────────┐
            │    │   7. PERSISTENCE & AUDIT           │
            │    │   - Neo4j logs plan, decision,     │
            │    │     execution result               │
            │    │   - VectorRAG stores task context  │
            │    │   - Audit trail immutable          │
            │    └───────────────────────────────────┘
            │
            └────────────────────────┬──────────────────┐
                                     │                  │
                            ┌────────▼──────┐   ┌──────▼─────────┐
                            │  CLI Output   │   │  API Response  │
                            │  (Formatted)  │   │  (JSON)        │
                            └───────────────┘   └────────────────┘
```

### Key Decision Points

1. **Does plan violate constitutional rules?** → Blocked or approved with conditions
2. **Does plan violate compliance requirements?** → Audit trail or special handling
3. **Does plan require human approval?** → Navigator prompts user
4. **Execution success in sandbox?** → Retry with repairs up to 2x, or fail

---

## Core Components

### 1. **The Weaver** (`orchestrator/weaver.py`)

**Role:** Primary planning and code generation agent.

**Responsibilities:**
- Parse user's natural language task
- Draft step-by-step execution plan
- Generate Python code ready for sandbox execution
- Tag code with safety markers: `[API_REQUIRED]`, `[FILESYSTEM_MODIFY]`, `[ROOT_REQUIRED]`
- Auto-fix Python syntax errors
- Auto-inject missing imports

**Key Methods:**
```python
run_task(request: str) -> TaskResult
├─ _plan_task(request)           # LLM planning
├─ _extract_tags(text)           # Find [API_REQUIRED] etc.
├─ _validate_python_code(code)   # compile() check
├─ _auto_fix_python_syntax(code) # Replace backslash in f-strings
├─ _auto_fix_python_imports(code) # Inject missing imports
└─ _repair_python_syntax_with_llm(code) # LLM fallback
```

**Output Schema:**
```json
{
  "task_id": "uuid",
  "intent": "What the plan accomplishes",
  "safety_tags": ["[API_REQUIRED]", "[FILESYSTEM_MODIFY]"],
  "target_file": "/codebase/path/to/file.py",
  "executable_code": "import json\n# Python code\n",
  "artifacts": ["output_file.csv"]
}
```

**LLM Configuration:**
- Model: `qwen2.5:7b` (default, configurable)
- Temperature: 0.2 (low = deterministic planning)
- Max tokens: 4096
- System prompt: Strict rules about self-contained code, no network by default, explicit paths

---

### 2. **The Constitution Node** (`orchestrator/constitution.py`)

**Role:** Safety and policy enforcement.

**Two-Phase Evaluation:**

**Phase 1: Pattern Scan (Fast)**
- Regex match against hardcoded rules
- Patterns for: network calls, file system modifications, dangerous syscalls
- Example: `requests\.get`, `open\(['"/]etc/`, `subprocess\.(call|run)`

**Phase 2: LLM Deep Reasoning (Thorough)**
- If patterns found → ask LLM to interpret intent vs. safety concern
- LLM returns JSON verdict:
```json
{
  "approved": true/false,
  "violations": [
    {
      "rule_id": "C001",
      "reason": "Detected requests.get (Network Restriction)",
      "exception_tag": "[API_REQUIRED]"
    }
  ],
  "requires_human_review": true/false,
  "reasoning": "LLM interpretation"
}
```

**Default Constitutional Rules (config.yaml):**
- **C001 - Network Restriction** → blocks `requests.get`, `urllib`, `socket` (exception: `[API_REQUIRED]`)
- **C002 - File System Safety** → blocks `/etc/`, `/usr/`, `/bin/`, `subprocess.run` (exception: `[FILESYSTEM_MODIFY]`)
- **C003 - Memory/Resource Safety** → blocks infinite loops, large allocations
- **C004 - Code Injection** → blocks `eval()`, `exec()`, `pickle`
- More...

**Verdict Levels:**
- `APPROVED` → no violations, proceed to sandbox
- `CONDITIONAL PASS` → violations have matching exception tags (requires audit & approval)
- `DENIED` → critical violations without exception tags, blocked immediately

---

### 3. **The Regulatory Node** (`orchestrator/regulatory.py`)

**Role:** Compliance and regulatory scanning.

**Responsibilities:**
- Pattern-based scan for compliance risks
- Example: PII detection (SSN, credit card), data classification
- Flags tasks for special audit treatment
- Returns compliance verdict

**Example Rules:**
- Detects SQL patterns that might expose user data
- Blocks hardcoded credentials
- Flags data export operations for audit

---

### 4. **The Navigator Gateway** (`orchestrator/navigator.py`)

**Role:** Human-in-the-loop approval gate.

**Approval Categories (from config):**
- `[API_REQUIRED]` → User approval for external API calls
- `[FILESYSTEM_MODIFY]` → User approval for file modifications
- `[ROOT_REQUIRED]` → User approval for root/admin operations
- `[SENSITIVE_DATA]` → User approval for PII/secrets handling

**Behavior:**
- Terminal prompt: `[System Change Requested. Review Plan Y/N?]`
- Reads user input (Y/N)
- Auto-approval can be configured per category in `config.yaml`
- Logs approval decision to audit trail

---

### 5. **The Sandboxed Garden** (`orchestrator/sandbox.py`)

**Role:** Isolated Docker container for code execution.

**Docker Image:** `constitutional-sandbox:latest` (built from `Dockerfile.sandbox`)

**Security Features:**
- **Network:** `bridge` by default (no external access unless `[API_REQUIRED]`)
- **Filesystem:** Read-only root by default (optional, configurable)
- **Resource Limits:**
  - Memory: 512 MB (configurable)
  - CPU: 1 core (configurable)
  - Timeout: 30 seconds (configurable)
  - PIDs limit: 256
- **Blocked Syscalls:** `CAP_NET_ADMIN`, `CAP_SYS_ADMIN`, `CAP_SYS_PTRACE`
- **tmpfs:** 64MB in-memory storage for temporary data

**Execution Flow:**
1. Create temp directory with code + input files
2. Mount to container with volume binds
3. Execute Python code inside container
4. Capture stdout, stderr, exit code
5. Clean up container and volumes
6. Return `SandboxResult`:
```python
@dataclass
class SandboxResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    container_id: str
    execution_time_ms: float
```

**Error Recovery:**
- If execution fails, Weaver can attempt repair (up to 2x retries)
- Repairs include: syntax fixes, import injection, logic adjustments

---

### 6. **Persistence Layer** (`orchestrator/persistence.py`)

**Role:** Knowledge graph and audit trail.

**Database:** Neo4j (optional but recommended)

**Nodes Created:**
- `:Task` → task metadata, status, timestamps
- `:Plan` → execution plan, code, intent
- `:Decision` → constitutional verdict, compliance verdict, approval
- `:Execution` → sandbox result, output, errors
- `:Tenant` → tenant isolation nodes
- `:AuditEvent` → fine-grained audit log

**Relationships:**
- Task → (PLANNED_AS) → Plan
- Plan → (EVALUATED_BY) → ConstitutionalDecision
- ConstitutionalDecision → (APPROVED_BY) → NavigatorDecision
- NavigatorDecision → (EXECUTED_AS) → Execution
- All → (:Tenant) for tenancy tracking

**Query Capabilities:**
- "Show me all tasks for tenant X with network access"
- "Find all constitutional violations in the past 7 days"
- "Audit trail for user_id=Y from 2024-01-01 to 2024-01-31"

**Fallback:** If Neo4j unavailable, VectorRAG (sentence-transformers + ChromaDB) provides offline semantic memory.

---

### 7. **Vector RAG** (`orchestrator/rag.py`)

**Role:** Semantic memory and context retrieval (fully offline).

**Components:**
- **Embeddings:** `sentence-transformers/all-MiniLM-L6-v2` (offline)
- **Vector DB:** ChromaDB (local, file-based)

**Usage:**
- Store past task context, code snippets, outcomes
- Retrieve similar past tasks for current request
- Improves code generation with context

**Fallback Chain:**
1. Neo4j graph queries (if enabled)
2. Vector RAG semantic search (if installed)
3. Plain audit log CSV (always available)

---

### 8. **Tenancy Manager** (`orchestrator/tenancy.py`)

**Role:** Multi-tenant isolation and configuration override.

**Features:**
- Tenant-scoped storage (separate directories per tenant)
- Tenant-scoped secrets management
- Tenant-specific configuration overrides
- Audit events tagged with tenant_id
- Neo4j relationships filter by tenant

**Context Object:**
```python
TenantContext:
  tenant_id: str
  storage_dir: str  # /tenant_storage/acme
  secrets_dir: str  # /tenant_secrets/acme
  config_overrides: dict
```

---

### 9. **Audit Logger** (`orchestrator/audit.py`)

**Role:** Immutable audit trail.

**Stores:**
- Task submission (request, tenant, timestamp)
- Planning results (intent, safety_tags, code)
- Constitutional verdict (violations, approved?)
- Regulatory verdict (compliance risks)
- Human approvals (user decision, timestamp)
- Execution results (success, stdout, errors, runtime)

**Output Formats:**
- Neo4j (:AuditEvent nodes)
- SQLite `.db` file
- CSV for compliance export

**Immutability:** Audit events are append-only, never modified.

---

### 10. **Code Analyzer** (`orchestrator/code_analyzer.py`)

**Role:** Static analysis and code quality checks.

**Checks:**
- AST parsing for syntax validity
- Complexity analysis (cyclomatic complexity)
- Security patterns (hardcoded secrets, SQL injection)
- Performance concerns (nested loops, large data allocations)

**Output:**
- Warnings/errors before execution
- Suggestions for code improvement
- Risk scoring

---

## Project Structure

```
mythical_ai/
├── README.md                          # Project intro
├── ARCHITECTURE.md                    # System design
├── DEPLOYMENT.md                      # Production deployment guide
├── ENTERPRISE_EDITION.md              # Enterprise roadmap
├── SELF_HOSTED.md                     # Local setup guide
├── config.yaml                        # Core configuration (models, rules, sandbox limits)
├── requirements.txt                   # Python dependencies
├── .env.example                       # Environment variables template
├── docker-compose.yml                 # Neo4j + other services
├── Dockerfile.sandbox                 # Minimal sandbox image
├── run_orchestrator.py                # CLI entry point
│
├── orchestrator/                      # Core orchestration engine
│   ├── __init__.py
│   ├── weaver.py                      # Planning agent (LLM-based)
│   ├── constitution.py                # Safety evaluator
│   ├── regulatory.py                  # Compliance scanner
│   ├── navigator.py                   # Human approval gate
│   ├── sandbox.py                     # Docker execution environment
│   ├── persistence.py                 # Neo4j persistence layer
│   ├── audit.py                       # Audit logging
│   ├── rag.py                         # Vector RAG semantic memory
│   ├── code_analyzer.py               # Static code analysis
│   ├── tenancy.py                     # Multi-tenant isolation
│   ├── utils.py                       # Shared utilities (console, config loading, Ollama queries)
│   ├── custom_rules.py                # User-defined safety rules
│   ├── connectors/                    # External service integrations
│   │   ├── base.py                    # Base connector interface
│   │   ├── github.py                  # GitHub API connector
│   │   ├── slack.py                   # Slack API connector
│   │   ├── notion.py                  # Notion API connector
│   │   ├── registry.py                # Connector registry & initialization
│   │   └── secrets.py                 # Secret management
│   └── function_signatures.txt        # Available functions for Weaver (reference)
│
├── api/                               # REST API layer (FastAPI)
│   ├── main.py                        # FastAPI app, middleware, lifespan
│   ├── dependencies.py                # Dependency injection (auth, services)
│   ├── models/                        # Pydantic request/response schemas
│   │   ├── task.py                    # TaskRequest, PlanResponse, TaskResponse
│   │   ├── user.py                    # User, Role, Permission
│   │   ├── tenant.py                  # Tenant, TenantConfig
│   │   ├── audit.py                   # AuditEvent schemas
│   │   └── __init__.py
│   ├── routers/                       # API route handlers
│   │   ├── tasks.py                   # POST /tasks, /tasks/{id}/execute, WebSocket /stream
│   │   ├── auth.py                    # POST /auth/login, /auth/refresh
│   │   ├── tenants.py                 # Tenant management endpoints
│   │   ├── audit.py                   # Audit log query endpoints
│   │   ├── connectors.py              # Connector management
│   │   └── __init__.py
│   ├── services/                      # Business logic (wraps orchestrator)
│   │   ├── orchestrator_service.py    # Main orchestration wrapper
│   │   ├── auth_service.py            # JWT auth, user sessions
│   │   ├── tenant_service.py          # Tenant CRUD & isolation
│   │   ├── task_service.py            # Task lifecycle management
│   │   ├── audit_service.py           # Audit queries
│   │   └── __init__.py
│   ├── ws/                            # WebSocket utilities
│   │   ├── pipeline_stream.py         # Real-time task streaming
│   │   └── __init__.py
│   └── __init__.py
│
├── dashboard/                         # FastAPI audit/compliance UI
│   ├── app.py                         # FastAPI dashboard app
│   ├── data.py                        # Dashboard data queries (Neo4j, SQLite)
│   ├── templates/                     # Jinja2 HTML templates
│   │   ├── base.html                  # Navigation, header
│   │   ├── index.html                 # Dashboard home
│   │   ├── tasks.html                 # Task list view
│   │   ├── task_detail.html           # Task details + audit trail
│   │   ├── tenants.html               # Tenant management
│   │   ├── compliance.html            # Compliance report
│   │   ├── policy.html                # Policy editor
│   │   └── base.html                  # Base template
│   ├── static/                        # CSS, JS, images
│   │   └── style.css
│   └── __init__.py
│
├── scripts/                           # Utility scripts
│   ├── setup.sh                       # One-command setup (installs deps, builds images)
│   ├── run_dashboard.py               # Launch dashboard server
│   ├── connectors_cli.py              # CLI for connector setup (GitHub tokens, etc.)
│   └── setup.sh
│
├── tests/                             # Test suite
│   ├── conftest.py                    # pytest fixtures (mock orchestrator, Neo4j)
│   ├── test_api_auth.py               # Auth endpoint tests
│   ├── test_api_task_tracking.py      # Task submission + lifecycle
│   ├── test_api_audit.py              # Audit query tests
│   ├── test_api_tenants.py            # Tenancy isolation tests
│   └── __init__.py
│
├── PHASE_1_BACKEND_SUMMARY.md         # Phase 1 completed work
├── PHASE_2_PLAN.md                    # Phase 2 roadmap
├── refactor_plan.md                   # Technical debt / refactor tasks
└── output_*.txt, report.txt           # Output logs from past runs
```

---

## Tech Stack

### Core Runtime
- **Python:** 3.11+
- **LLM Provider:** Ollama (local, offline models)
- **Default Model:** qwen2.5:7b (7GB, runs on M4 MacBook)

### Backend Framework
- **FastAPI:** REST API + async support
- **uvicorn:** ASGI server
- **Pydantic:** Request/response validation

### Persistence
- **Neo4j:** Knowledge graph, audit trail (optional but recommended)
- **ChromaDB:** Vector embeddings for RAG (offline)
- **SQLite:** Audit events fallback

### Machine Learning
- **sentence-transformers:** Semantic embeddings (all-MiniLM-L6-v2)
- **chromadb:** Vector database (local, file-based)

### External Integrations
- **Docker:** Sandbox execution
- **requests:** HTTP client (for API connectors)
- **pyyaml:** Configuration
- **rich:** CLI output formatting

### Connectors
- **GitHub:** API for repo operations
- **Slack:** API for notifications
- **Notion:** API for wiki integration

### Testing
- **pytest:** Unit + integration tests
- **pytest-asyncio:** Async test support
- **httpx:** Async HTTP client for tests

---

## Key Features

### 1. **Safety Guardrails**
- Multi-layer safety: pattern scan + LLM reasoning
- Constitutional rules with exception tags
- Human-in-the-loop approval for sensitive operations
- Network disabled by default, filesystem read-only by default

### 2. **Compliance & Audit**
- Immutable audit trail in Neo4j or SQLite
- Compliance scanning (PII detection, regulatory patterns)
- Role-based access control (RBAC) for audit visibility
- Export for compliance reporting (CSV, PDF)

### 3. **Multi-Tenant Isolation**
- Separate storage directories per tenant
- Tenant-scoped secrets management
- Audit events tagged with tenant_id
- Configuration overrides per tenant

### 4. **Code Quality**
- Automatic syntax repair (backslash in f-strings, missing imports)
- Retry logic for transient failures
- Static code analysis before execution
- Test generation for high-risk code paths

### 5. **Real-Time Streaming**
- WebSocket endpoint for live task updates
- Stream planning steps, safety verdicts, execution progress
- Client receives JSON events as tasks progress

### 6. **Semantic Memory**
- Vector RAG for similar task retrieval
- Context-aware code generation
- Offline embeddings (no API calls needed)

### 7. **Extensibility**
- Custom connector framework (GitHub, Slack, Notion, custom)
- Custom safety rules via `custom_rules.py`
- Pluggable persistence layer (Neo4j, SQLite, PostgreSQL)
- Custom models via Ollama

---

## Setup & Deployment

### Prerequisites
- **macOS** or Linux
- **Docker Desktop** installed (for sandbox)
- **Ollama** installed + running (for LLM planning & safety)
- **Python 3.11+**
- **4GB+ RAM**, 2+ CPU cores

### Quick Start

```bash
# 1. Clone / navigate to project
cd mytical_ai

# 2. Run setup script (installs deps, builds images)
bash scripts/setup.sh

# 3. Optional: Start Neo4j for persistence
docker compose up -d neo4j

# 4. Interactive mode
python run_orchestrator.py

# 5. Or submit single task and exit
python run_orchestrator.py "Generate CSV with 100 random numbers and compute mean"

# 6. Optional: Run dashboard on http://localhost:8000
python scripts/run_dashboard.py
```

### Environment Variables

```bash
# Neo4j (optional)
export NEO4J_ENABLED=true
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=password

# Ollama (optional, defaults to localhost:11434)
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=qwen2.5:7b

# Dashboard auth
export DASHBOARD_TOKEN=<secure-random-token>

# Hugging Face (optional, for VectorRAG embeddings)
export HF_TOKEN=<your-token>
```

### Docker Setup for Sandbox

```bash
# Build sandbox image
docker build -f Dockerfile.sandbox -t constitutional-sandbox:latest .

# Verify image exists
docker images | grep constitutional-sandbox
```

### Production Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for:
- Kubernetes deployment
- SSL/TLS configuration
- Multi-instance load balancing
- Database backups
- Scaling guidelines

---

## API Endpoints

### Tasks Router (`/tasks`)

**POST /tasks** — Submit task, get execution plan
```json
Request:
{
  "description": "Analyze CSV and post to Slack",
  "tenant_id": "acme",
  "require_approval": true,
  "timeout_seconds": 600
}

Response (202 Accepted):
{
  "task_id": "uuid",
  "intent": "...",
  "safety_tags": ["API_REQUIRED"],
  "steps": [...],
  "violations": [],
  "requires_approval": true
}
```

**POST /tasks/{task_id}/execute** — Execute approved plan
```json
Request:
{
  "plan_data": {...}
}

Response (202 Accepted):
{
  "message": "Task execution queued",
  "task_id": "uuid"
}
```

**GET /tasks/{task_id}** — Get task status
```json
Response:
{
  "task_id": "uuid",
  "status": "completed",
  "result": {...},
  "created_at": "2024-01-01T12:00:00Z"
}
```

**WebSocket /tasks/stream** — Real-time task streaming
```json
Client sends:
{
  "task": {
    "description": "...",
    "tenant_id": "...",
    "require_approval": false
  }
}

Server sends (multiple):
{
  "event": "planning_started",
  "task_id": "uuid"
}
{
  "event": "plan_ready",
  "plan": {...}
}
{
  "event": "constitution_verdict",
  "verdict": "approved"
}
{
  "event": "execution_started"
}
{
  "event": "execution_complete",
  "result": {...}
}
```

### Auth Router (`/auth`)

**POST /auth/login** — JWT authentication
**POST /auth/refresh** — Refresh expired token
**GET /auth/me** — Current user info

### Tenants Router (`/tenants`)

**POST /tenants** — Create tenant
**GET /tenants** — List tenants
**GET /tenants/{tenant_id}** — Get tenant details
**PATCH /tenants/{tenant_id}** — Update tenant config

### Audit Router (`/audit`)

**GET /audit/events** — Query audit events
**GET /audit/events?tenant_id=X&start_date=Y** — Filtered query
**GET /audit/compliance-report** — Compliance export

### Connectors Router (`/connectors`)

**POST /connectors/github/authorize** — Link GitHub account
**POST /connectors/slack/authorize** — Link Slack workspace
**GET /connectors/status** — Show connected services

---

## Configuration

### Main Config: `config.yaml`

#### Global Settings
```yaml
system:
  name: "Constitutional Orchestrator"
  version: "3.0.0"

model_default: "qwen2.5:7b"  # Ollama model for all agents
```

#### Weaver (Planning Agent)
```yaml
weaver:
  model: "qwen2.5:7b"          # Can override model_default
  temperature: 0.2             # Low = deterministic
  max_tokens: 4096
  system_prompt: |
    You are the Weaver, a specialized planning agent...
```

#### Constitution (Safety Evaluator)
```yaml
constitution:
  model: "qwen2.5:7b"
  temperature: 0.0             # Always deterministic
  max_tokens: 2048
  rules:
    - id: "C001"
      name: "Network Restriction"
      patterns: ["requests\\.get", "urllib\\.request", "socket\\."]
      severity: "critical"
      exception_tag: "[API_REQUIRED]"
    # ... more rules
```

#### Navigator (Approval Gate)
```yaml
navigator:
  categories_requiring_approval:
    - "API_REQUIRED"
    - "FILESYSTEM_MODIFY"
    - "ROOT_REQUIRED"
  auto_approve:
    api_required: false        # Require user approval for API calls
    filesystem_modify: false   # Require user approval for file mods
```

#### Sandbox (Docker Execution)
```yaml
sandbox:
  image: "constitutional-sandbox:latest"
  timeout_seconds: 30
  memory_limit: "512m"
  cpu_limit: 1
  network_mode: "bridge"       # "bridge" = no external network
  read_only_rootfs: false      # Can be enabled for extra safety
  blocked_syscalls:
    - "CAP_NET_ADMIN"
    - "CAP_SYS_ADMIN"
```

#### Persistence
```yaml
persistence:
  type: "neo4j"                # "neo4j" or "sqlite"
  neo4j:
    uri: "bolt://localhost:7687"
    user: "neo4j"
    password: "password"
```

#### Tenancy
```yaml
tenancy:
  enabled: true
  storage_mount: "/tenant_storage"
  secrets_mount: "/tenant_secrets"
```

#### Audit
```yaml
audit:
  type: "neo4j"                # Neo4j + CSV fallback
  export_format: "csv"
```

#### VectorRAG
```yaml
rag:
  enabled: true
  embedding_model: "sentence-transformers/all-MiniLM-L6-v2"
  chunk_size: 1000
  similarity_threshold: 0.7
```

---

## Common Workflows

### Workflow 1: Simple Task Submission (CLI)

```bash
# Interactive mode
$ python run_orchestrator.py

Weaver> Analyze /data/sales.csv and compute total revenue

[Planning...] Weaver drafts execution plan
[Constitutional Review...] Constitution Node scans code
[Compliance Check...] Regulatory Node checks for PII
[Awaiting Approval?] Navigator asks for human approval
[Executing...] Sandbox runs code
[Complete!] Results displayed

Results:
  Total Revenue: $1,234,567
  Execution Time: 2.3s
  Artifacts: /output/summary.txt
```

### Workflow 2: API Submission with WebSocket Streaming

```python
import asyncio
import websockets
import json

async def stream_task():
    uri = "ws://localhost:8000/tasks/stream"
    async with websockets.connect(uri) as ws:
        # Send task
        await ws.send(json.dumps({
            "task": {
                "description": "Fetch user count from database",
                "tenant_id": "acme",
                "require_approval": True
            }
        }))
        
        # Receive events
        while True:
            event = json.loads(await ws.recv())
            print(f"Event: {event['event']}")
            
            if event['event'] == 'execution_complete':
                print(f"Result: {event['result']}")
                break

asyncio.run(stream_task())
```

Output:
```
Event: planning_started
Event: plan_ready
Event: constitution_verdict
Event: navigator_awaiting_approval
[Terminal prompt appears: Review Plan? Y/N]
[User enters: Y]
Event: execution_started
Event: execution_complete
Result: {'success': True, 'user_count': 42}
```

### Workflow 3: Audit Query

```bash
# Query audit trail via API
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/audit/events?tenant_id=acme&start_date=2024-01-01"

Response:
[
  {
    "event_id": "uuid",
    "task_id": "uuid",
    "event_type": "task_submitted",
    "description": "Analyze CSV",
    "timestamp": "2024-01-15T10:30:00Z"
  },
  {
    "event_id": "uuid",
    "event_type": "constitutional_verdict",
    "verdict": "approved",
    "violations": [],
    "timestamp": "2024-01-15T10:30:05Z"
  },
  ...
]
```

### Workflow 4: Multi-Tenant Task

```bash
# Tenant-scoped execution
python run_orchestrator.py --tenant=acme "Generate report"

# Orchestrator automatically:
# 1. Loads tenant-specific config overrides
# 2. Mounts /tenant_storage/acme for file I/O
# 3. Uses /tenant_secrets/acme for API tokens
# 4. Tags all audit events with tenant_id=acme
```

### Workflow 5: Custom Safety Rule

Edit `orchestrator/custom_rules.py`:
```python
CUSTOM_RULES = [
    {
        "id": "CUSTOM001",
        "name": "Block Specific Library",
        "patterns": ["import pyarrow"],
        "severity": "high",
        "exception_tag": "[APPROVED_BY_ADMIN]",
    }
]
```

Now Constitution Node will scan for `import pyarrow` and block unless plan has `[APPROVED_BY_ADMIN]` tag.

---

## Troubleshooting

### Neo4j Connection Error
```
$ python run_orchestrator.py
[ERROR] Could not connect to Neo4j at bolt://localhost:7687

Solution:
1. Start Neo4j: docker compose up -d neo4j
2. Wait 10 seconds for startup
3. Verify: docker ps | grep neo4j
4. Or disable Neo4j: NEO4J_ENABLED=false python run_orchestrator.py
```

### Ollama Connection Error
```
$ python run_orchestrator.py
[ERROR] Ollama not running at http://localhost:11434

Solution:
1. Install Ollama: brew install ollama
2. Start Ollama: ollama serve
3. Download model: ollama pull qwen2.5:7b
4. Verify: curl http://localhost:11434/api/tags
```

### Docker Container Fails
```
$ python run_orchestrator.py "Run code"
[ERROR] constitutional-sandbox image not found

Solution:
1. Build image: docker build -f Dockerfile.sandbox -t constitutional-sandbox:latest .
2. Verify: docker images | grep constitutional-sandbox
3. Inspect: docker inspect constitutional-sandbox:latest
```

### Sandbox Timeout
```
Code timed out after 30 seconds

Solution:
1. Edit config.yaml: sandbox.timeout_seconds: 60
2. Or increase memory: sandbox.memory_limit: "1024m"
3. Or simplify code (Weaver auto-repairs on retry)
```

---

## Summary

**Mythical AI** is a production-grade multi-agent orchestration system that:
1. **Plans** code with LLM reasoning (Weaver)
2. **Evaluates** safety with pattern + LLM scanning (Constitution)
3. **Checks** compliance with regulatory patterns (Regulatory)
4. **Approves** via human-in-the-loop (Navigator)
5. **Executes** in isolated Docker sandbox (Garden)
6. **Audits** all decisions in Neo4j knowledge graph (Persistence)
7. **Remembers** via semantic vector search (VectorRAG)
8. **Isolates** tenants with separate storage & secrets (Tenancy)
9. **Streams** progress via WebSocket (Real-time)
10. **Exposes** all features via REST API (FastAPI)

**For another AI to use this project:**
- Start with [config.yaml](config.yaml) to understand safety rules and sandbox limits
- Read [orchestrator/weaver.py](orchestrator/weaver.py) for planning logic
- Check [orchestrator/constitution.py](orchestrator/constitution.py) for safety enforcement
- See [api/main.py](api/main.py) for REST API structure
- Review [run_orchestrator.py](run_orchestrator.py) for CLI entry point
- Consult [ARCHITECTURE.md](ARCHITECTURE.md) for detailed component design

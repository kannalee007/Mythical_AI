# Constitutional Orchestrator - System Architecture

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    User/Application Interface                    │
│                    (stdin or HTTP endpoint)                      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                    ┌────▼─────────────────────┐
                    │  run_orchestrator.py     │  Entry point
                    │  (Main Event Loop)       │
                    └────┬─────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   ┌────▼────┐    ┌─────▼─────┐    ┌────▼────────┐
   │  Weaver │    │Constitution│    │  Navigator  │
   │  (Plan) │◄──►│  (Safety)  │◄──►│(Approval)   │
   └────┬────┘    └────┬───────┘    └────┬────────┘
        │              │                  │
        └──────────────┼──────────────────┘
                       │
                   ┌───▼──────────┐
                   │   Sandbox    │ Code execution
                   │   (Docker)   │ in container
                   └───┬──────────┘
                       │
                  ┌────▼──────────┐
                  │     Neo4j     │ Knowledge graph
                  │ (Persistence) │ & audit log
                  └───────────────┘
```

## Component Deep Dive

### 1. Weaver (Planning Agent)

**File**: [orchestrator/weaver.py](orchestrator/weaver.py)

**Responsibility**: Generate structured execution plans from user requests

**Key Methods**:

```python
run_task(request: str) -> Dict
├─ _plan_task(request) → JSON plan
├─ _validate_python_code(code) → bool
├─ _auto_fix_python_syntax(code) → code
├─ _auto_fix_python_imports(code) → code
└─ _repair_python_syntax_with_llm(code) → code
```

**Output Schema**:

```json
{
  "intent": "What the plan accomplishes",
  "safety_tags": ["[API_REQUIRED]", "[FILESYSTEM_MODIFY]"],
  "target_file": "/codebase/path/to/file.py",
  "executable_code": "import json\n# Python code here\n"
}
```

**LLM Interaction**:
- Uses `query_ollama(require_json=True)` to force JSON output
- Ollama `format: "json"` parameter for deterministic responses
- Fallback syntax repair if `compile()` check fails

**Safety Improvements** (Recent):
- Pre-execution Python validation with `compile()`
- Deterministic f-string backslash fixes
- Auto-import injection for missing modules
- LLM syntax repair fallback before sandbox

### 2. Constitution Node (Safety Evaluator)

**File**: [orchestrator/constitution.py](orchestrator/constitution.py)

**Responsibility**: Pattern-based and LLM-based security policy enforcement

**Evaluation Pipeline**:

```
1. Pattern Scan
   ├─ Regex match against rule.patterns
   └─ Collect violations

2. LLM Deep Reasoning
   ├─ If patterns found → ask LLM for interpretation
   └─ Confirm intent vs. safety concern

3. Exception Tag Matching
   ├─ If violation has matching exception tag → CONDITIONAL PASS
   └─ Else if critical violation → DENIED

4. Output Decision
   ├─ APPROVED (no violations)
   ├─ CONDITIONAL PASS (tagged violations only)
   └─ DENIED (untagged critical violations)
```

**Configuration**:

Each rule in `config.yaml`:

```yaml
rules:
  - id: C002
    name: "Filesystem Modification"
    severity: high
    patterns:
      - "open\\(.*'[wa]'\\)"
      - "\\.write\\("
    exception_tags:
      - "[FILESYSTEM_MODIFY]"
```

**Exception Tag Logic**:

If a plan contains `[FILESYSTEM_MODIFY]` tag and rule C002 is triggered:
- Pattern violation becomes "acknowledged" rather than "denied"
- Human approval is still required (Navigator gate)
- Task continues if approved

### 3. Navigator Gateway (Approval Gate)

**File**: [orchestrator/navigator.py](orchestrator/navigator.py)

**Responsibility**: Human-in-the-loop approval for sensitive operations

**Decision Matrix**:

```
Safety Tags              Auto-Approve?  Requires Review?
─────────────────────────────────────────────────────
[API_REQUIRED]          NO             YES → Ask user
[FILESYSTEM_MODIFY]     NO             YES → Ask user
[ROOT_REQUIRED]         NO             YES → Ask user
(none)                  YES            NO → Proceed
```

**User Prompt**:

```
╭─ Task ID: 7ef79288 ──╮
│ SYSTEM CHANGE       │
│ Plan Summary: {...} │
│ Approve Y/N? [y/n]  │
╰────────────────────╯
```

**Decision Logging**: All approval decisions logged to:
- Console (immediate feedback)
- Neo4j (audit trail)
- orchestrator_decisions.log (file archive)

### 4. Sandbox (Isolated Execution)

**File**: [orchestrator/sandbox.py](orchestrator/sandbox.py)

**Responsibility**: Secure Docker-based code execution with resource limits

**Container Configuration**:

```yaml
Image: constitutional-sandbox:latest (python:3.11-slim + deps)
Mounts:
  - ${temp_dir} → /workspace (read-write)
  - ${host_cwd} → /codebase (read-write)
Network: bridge (enabled) | none (disabled)
Limits:
  - Memory: 512MB
  - CPU: 1.0 cores
  - Timeout: 30 seconds
  - Root FS: writable (config.read_only_rootfs = false)
```

**Execution Flow**:

```python
1. Create temp directory
2. Write code to temp file
3. Build Docker run command
4. Execute with output capture
5. Parse stdout/stderr
6. Cleanup temp files
```

**Error Handling**:

- Timeout → `TimeoutError` + partial output
- OOM Kill → `Docker exit code 137`
- Permission denied → `Execution exception`
- All errors logged with context

### 5. Persistence Layer (Neo4j)

**File**: [orchestrator/persistence.py](orchestrator/persistence.py)

**Responsibility**: Graph database logging of all tasks, violations, and artifacts

**Data Model**:

```
Task
  ├─ id (unique)
  ├─ request (original user request)
  ├─ status (SUCCESS/FAILED)
  ├─ timestamp
  ├─ success (boolean)
  │
  ├─ GENERATED_BY → CodeBlock
  │                  ├─ language
  │                  ├─ code
  │                  └─ execution_order
  │
  ├─ CREATED → Artifact
  │             ├─ path
  │             ├─ type
  │             └─ size
  │
  ├─ VIOLATED → Violation
  │              ├─ rule_id
  │              ├─ rule_name
  │              ├─ severity
  │              └─ resolved (true if tagged)
  │
  └─ TAGGED → Tag
               └─ name ([API_REQUIRED], [FILESYSTEM_MODIFY], etc)
```

**Key Queries**:

```cypher
-- Success rate
MATCH (t:Task) 
RETURN COUNT(t) as total, 
       SUM(CASE WHEN t.success THEN 1 ELSE 0 END) as successful,
       ROUND(100.0 * SUM(CASE WHEN t.success THEN 1 ELSE 0 END) / COUNT(t)) as success_rate

-- Tasks with critical violations
MATCH (t:Task)-[:VIOLATED]->(v:Violation) 
WHERE v.severity = 'critical' 
RETURN t.request, v.rule_name, t.timestamp 
ORDER BY t.timestamp DESC LIMIT 20

-- Most common tags
MATCH (t:Task)-[:TAGGED]->(tag:Tag) 
RETURN tag.name, COUNT(DISTINCT t) as task_count 
ORDER BY task_count DESC
```

### 6. Utilities Module (Helpers)

**File**: [orchestrator/utils.py](orchestrator/utils.py)

**Key Functions**:

```python
query_ollama(prompt, require_json=False)
  # Send prompt to Ollama with optional JSON enforcement
  # Returns: response string or dict

validate_json_payload(response, schema)
  # Verify JSON matches expected schema
  # Returns: bool

extract_code_blocks(text)
  # Parse markdown code fences
  # Returns: [(language, code), ...]

scan_for_violations(code, rules)
  # Pattern-match code against safety rules
  # Returns: [violation1, violation2, ...]

load_config(path)
  # Parse and validate YAML config
  # Returns: dict
```

## Data Flow Examples

### Example 1: File Read Operation

```
User Request
"Read config.yaml and report the database section"
  │
  ├─► Weaver generates:
  │   {
  │     "intent": "Read and analyze config.yaml",
  │     "safety_tags": [],  # No tags needed
  │     "target_file": "/codebase/config.yaml",
  │     "executable_code": "
  │       with open('/codebase/config.yaml', 'r') as f:
  │           content = yaml.safe_load(f)
  │       db_section = content.get('orchestrator', {})
  │       print(yaml.dump(db_section))
  │     "
  │   }
  │
  ├─► Constitution runs pattern scan:
  │   ✗ No critical patterns matched
  │   → Decision: APPROVED
  │
  ├─► Navigator auto-approves:
  │   ✓ No sensitive tags
  │   → Proceed immediately
  │
  ├─► Sandbox executes:
  │   $ python /tmp/code_xyz.py
  │   orchestrator:
  │     ... (database config) ...
  │
  ├─► Persistence logs:
  │   MATCH (t:Task) WHERE t.task_id = "xyz"
  │   ├─ status: SUCCESS
  │   ├─ success: true
  │   └─ created_artifact: [result.txt]
  │
  └─► User Result
      Database section output
```

### Example 2: API Call with Approval

```
User Request
"Search StackOverflow for 'asyncio best practices'. Tags: [API_REQUIRED] [FILESYSTEM_MODIFY]"
  │
  ├─► Weaver generates:
  │   {
  │     "intent": "Query StackOverflow API",
  │     "safety_tags": ["[API_REQUIRED]", "[FILESYSTEM_MODIFY]"],
  │     "target_file": "/codebase/so_results.txt",
  │     "executable_code": "
  │       import requests
  │       response = requests.get('https://...')
  │       results = response.json()
  │       with open('/codebase/so_results.txt', 'w') as f:
  │           f.write(json.dumps(results, indent=2))
  │     "
  │   }
  │
  ├─► Constitution runs:
  │   Pattern scan:
  │     ✓ Detected: requests.get() → C001 (Network)
  │     ✓ Detected: open(...'w'...) → C002 (Filesystem)
  │   
  │   LLM reasoning:
  │     ✓ Network usage justified (API request)
  │     ✓ File write justified (result storage)
  │   
  │   Exception check:
  │     ✓ [API_REQUIRED] matches C001 → Conditional pass
  │     ✓ [FILESYSTEM_MODIFY] matches C002 → Conditional pass
  │   
  │   Decision: CONDITIONAL PASS
  │
  ├─► Navigator asks human:
  │   ┌─ Task: 7ef... ──┐
  │   │ SYSTEM CHANGE │
  │   │ API + File W. │
  │   │ Approve? Y/N  │
  │   └────────────────┘
  │
  ├─► Human approves (Y)
  │
  ├─► Sandbox executes in Docker:
  │   /dev/null         /dev/null  (network isolated)
  │   Volume mount to /codebase/
  │   Result: so_results.txt created
  │
  ├─► Persistence logs:
  │   Task created
  │   ├─ status: SUCCESS
  │   ├─ violations: [C001, C002] (tagged & resolved)
  │   ├─ artifacts: [so_results.txt]
  │   └─ tags: [API_REQUIRED, FILESYSTEM_MODIFY]
  │
  └─► User Result
      Results saved to /codebase/so_results.txt
```

## Deployment Architectures

### Single-Machine (Development/Small Scale)

```
┌────────────────────┐
│   Development PC   │
│  (macOS/Linux)     │
│                    │
│ ├─ Python 3.11     │
│ ├─ Ollama (LLM)    │
│ ├─ Docker daemon   │
│ │  └─ Sandbox      │
│ │     containers   │
│ └─ Neo4j container │
│                    │
└────────────────────┘
```

### Multi-Machine (Production)

```
┌──────────────────────┐         ┌──────────────────┐
│  Orchestrator Host 1 │         │  Orchestrator    │
│  ├─ Python 3.11      │         │  Host N          │
│  ├─ Ollama (local)   │◄─ LB ──►│ ├─ Python 3.11   │
│  └─ Docker daemon    │         │ └─ Ollama        │
│     (sandbox)        │         │                  │
└───────────┬──────────┘         └──────────┬───────┘
            │                               │
            └───────────────────┬───────────┘
                                │
                          ┌─────▼──────┐
                          │  Neo4j     │
                          │  Cluster   │
                          │ (Cloud or  │
                          │ Dedicated) │
                          └────────────┘
```

## Performance Characteristics

### Typical Task Execution Time

```
1. Weaver (Planning):        1-3 seconds
   └─ LLM inference (qwen2.5:7b on CPU)
   
2. Constitution (Safety):    0.5-2 seconds
   └─ Pattern scan + LLM check
   
3. Navigator (Approval):     0-30 seconds
   └─ User input wait time
   
4. Sandbox (Execution):      1-30 seconds
   └─ Code execution + Docker overhead
   
5. Persistence (Logging):    0.1-0.5 seconds
   └─ Neo4j write + graph updates

Total: 3-65 seconds per task (depends on approval)
```

### Neo4j Query Performance

```
Task count:        ~ 1000 per month
Data retention:    Unlimited (recommend archival after 1 year)
Typical queries:   < 500ms
Dashboard rebuild: ~ 5 seconds

Recommended maintenance:
├─ Weekly: Clear old logs
├─ Monthly: Index optimization
└─ Quarterly: Full backup
```

## Extension Points

### Add Custom Safety Rules

1. Edit `config.yaml` → `constitution.rules`
2. Define patterns, severity, exception tags
3. Restart orchestrator
4. Test with `query_graph.py --stats`

### Add Custom Artifacts

1. Extend `persistence.py` → `Artifact` node
2. Update Sandbox to capture new artifact types
3. Update query_graph.py to display

### Add LLM Providers

1. Modify `utils.py` → `query_ollama()`
2. Support OpenAI API, Claude, vLLM, etc.
3. Map to JSON schema requirements

### Add Approval Strategies

1. Extend `navigator.py` → `request_approval()`
2. Support email, Slack, webhook notifications
3. Implement timeout and escalation

## Monitoring & Observability

### Key Metrics to Track

```
├─ Success rate (% of tasks succeeding)
├─ Avg execution time
├─ Constitution approval rate
├─ Navigator approval rate
├─ Critical violations per day
├─ Artifact creation rate (files written)
└─ Error categories (timeout, OOM, etc)
```

### Alerting Thresholds

```
Trigger alert if:
├─ Success rate < 80% (over last 100 tasks)
├─ Critical violations > 5 per day
├─ Neo4j unavailable > 2 minutes
├─ Sandbox execution timeout > 10% of tasks
└─ LLM API latency > 30 seconds
```

---

For deployment instructions, see [DEPLOYMENT.md](DEPLOYMENT.md)
For prompting best practices, see [PROMPTING.md](PROMPTING.md)

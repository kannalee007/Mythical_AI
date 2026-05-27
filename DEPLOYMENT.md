# Constitutional Orchestrator - Production Deployment Guide

## Overview

The Constitutional Orchestrator is a multi-agent AI system for safe, policy-guided code execution with human approval gates. This guide covers deployment, configuration, and operational best practices.

## Prerequisites

- **OS**: macOS or Linux
- **Software**: Docker, Docker Compose, Ollama, Python 3.11+
- **Hardware**: 4GB+ RAM, 2+ CPU cores
- **Ollama Models**: qwen2.5:7b (7GB download) or equivalent

## Infrastructure Setup

### 1. Start Required Services

```bash
# Start Ollama (macOS - use the app)
# Or Linux:
ollama serve

# Start Neo4j database
docker compose up -d neo4j

# Verify Neo4j is healthy
docker compose ps
docker ps --filter name=neo4j-local --format "{{.Names}} {{.Status}}"
```

### 2. Build Sandbox Image

```bash
docker build -f Dockerfile.sandbox -t constitutional-sandbox:latest .
```

### 3. Environment Variables (Optional)

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=password
export OLLAMA_MODEL=qwen2.5:7b
export OLLAMA_BASE_URL=http://localhost:11434
```

## Running the Orchestrator

### Interactive Mode

```bash
python run_orchestrator.py
```

Then type your request at the `Weaver>` prompt:

```
Weaver> Search StackOverflow for "python asyncio best practices" and save results to /codebase/results.txt. Tags: [API_REQUIRED] [FILESYSTEM_MODIFY]
```

### Batch Mode (Non-interactive)

```bash
echo "Read /codebase/config.yaml and report on database settings." | python run_orchestrator.py
```

## Configuration

### config.yaml

**Key sections:**

| Section | Purpose | Notes |
|---------|---------|-------|
| `weaver` | LLM system prompt | Controls plan generation behavior |
| `constitution.rules` | Safety policies | Pattern + LLM-based evaluation |
| `sandbox` | Docker execution limits | Memory, CPU, timeout, network mode |
| `navigator` | Approval thresholds | Which tags require human review |
| `ollama` | LLM connection | Model, timeout, base URL |

**Safety Rules (Constitution Node):**

```yaml
constitution:
  rules:
    - id: C001
      name: "Network Access Restriction"
      description: "Detect and restrict unauthorized network operations"
      severity: critical
      patterns:
        - "urllib.*\\.open\\("
        - "requests\\.get\\("
      exception_tags:
        - "[API_REQUIRED]"

    - id: C002
      name: "Filesystem Modification"
      description: "Track file write operations"
      severity: high
      patterns:
        - "open\\(.*'w'\\)"
        - "\\.write\\("
      exception_tags:
        - "[FILESYSTEM_MODIFY]"

    - id: C003
      name: "Infinite Loops"
      description: "Detect unbounded loops"
      severity: critical
      patterns:
        - "while True:"
        - "for .* in cycle\\("

    - id: C004
      name: "Privilege Escalation"
      description: "Prevent sudo or root operations"
      severity: critical
      patterns:
        - "sudo"
        - "chmod.*777"

    - id: C005
      name: "Data Exfiltration"
      description: "Prevent sensitive data leakage"
      severity: high
      patterns:
        - "environ"
        - "\\.ssh"

    - id: C006
      name: "Resource Exhaustion"
      description: "Prevent runaway resource usage"
      severity: high
      patterns:
        - "fork\\(\\)"
        - "\\.spawn\\("
```

**Approval Categories:**

```yaml
navigator:
  categories_requiring_approval:
    - "[API_REQUIRED]"        # Network API calls
    - "[FILESYSTEM_MODIFY]"   # File write/delete
    - "[ROOT_REQUIRED]"       # Privilege escalation
  auto_approve_safe: false    # Set true to auto-approve read-only
```

## Execution Flow

```
User Request
    ↓
[Weaver] Generate JSON Plan
    ├─ intent: What to do
    ├─ safety_tags: [API_REQUIRED], [FILESYSTEM_MODIFY]
    ├─ target_file: /codebase/...
    └─ executable_code: Python code to run
    ↓
[Constitution] Pattern + LLM Safety Check
    ├─ Pattern scan for violations
    ├─ LLM deep reasoning
    ├─ Check exception tags
    └─ Output: APPROVED, CONDITIONAL PASS, or DENIED
    ↓
[Navigator] Human Approval Gate
    ├─ If tags require review → Ask user Y/N
    └─ If approved → Continue; else → Abort
    ↓
[Sandbox] Execute Code
    ├─ Spin up Docker container
    ├─ Mount /codebase for file access
    ├─ Run Python code with limits
    └─ Capture stdout/stderr
    ↓
[Persistence] Log to Neo4j
    ├─ Task record
    ├─ Code blocks
    ├─ Artifacts created
    └─ Violations detected
    ↓
User Result
```

## Monitoring & Logging

### View Execution History

```bash
# Overall statistics
python query_graph.py --stats

# Recent tasks
python query_graph.py --recent --limit 10

# Failed tasks only
python query_graph.py --failed

# Task details
python query_graph.py --task <task_id>

# Tasks by tag
python query_graph.py --tag API_REQUIRED

# Interactive Neo4j shell
python query_graph.py --shell
# Then type Cypher queries like:
# MATCH (t:Task) WHERE t.success=true RETURN t.request, t.timestamp LIMIT 5
```

### Log Files

- **orchestrator_decisions.log**: All approval decisions and violations
- **sandbox_*.log**: Individual task execution logs
- **Neo4j console**: `docker compose logs neo4j | tail -50`

### Neo4j Queries

```cypher
# Success rate by tag
MATCH (t:Task)-[:TAGGED]->(tag:Tag)
RETURN tag.name, COUNT(t) as tasks, 
       ROUND(100.0 * SUM(CASE WHEN t.success THEN 1 ELSE 0 END) / COUNT(t)) as success_rate

# Tasks with violations
MATCH (t:Task)-[:VIOLATED]->(v:Violation)
WHERE v.severity = 'critical'
RETURN t.task_id, v.rule_name, t.request LIMIT 20

# Average execution time
MATCH (t:Task)
RETURN AVG(duration.inSeconds(t.created_at, t.completed_at)) as avg_time_seconds
```

## Troubleshooting

### Neo4j Connection Refused

```bash
# Check if Neo4j is running
docker ps --filter name=neo4j-local

# If not running, start it
docker compose up -d neo4j

# If restarting, wait 10-15 seconds for initialization
sleep 15
docker compose ps

# Check port availability
nc -z localhost 7687
```

### Ollama Not Responding

```bash
# Check if Ollama is running
ollama list

# Test API
curl http://localhost:11434/api/tags

# If stuck, restart
pkill ollama
ollama serve
```

### Sandbox Execution Timeouts

- Default timeout: 30 seconds
- For long-running tasks, increase in config.yaml:
  ```yaml
  sandbox:
    timeout_seconds: 60
  ```

### File Not Found Errors

- Ensure target paths use `/codebase/` prefix
- Check that host directory is mounted:
  ```bash
  docker compose exec neo4j bash -c 'ls /codebase' 2>/dev/null || echo "Not mounted"
  ```

## Scaling Considerations

### Single-Machine Deployment (Recommended for < 100 tasks/day)

- Current configuration suitable
- All services run locally
- Neo4j stores all history

### Multi-Machine Deployment (100+ tasks/day)

1. **Separate Neo4j server** (dedicated machine or cloud)
   - Update connection string in orchestrator
   - Enable remote Cypher queries

2. **Load balancing** (multiple orchestrator instances)
   - All point to same Neo4j
   - Task deduplication via task_id

3. **External LLM** (replace Ollama)
   - Use OpenAI API, Anthropic, or self-hosted vLLM
   - Update utils.py `query_ollama()` function

## Security Best Practices

1. **Approval Policy**
   - Always review [FILESYSTEM_MODIFY] tasks
   - Always review [API_REQUIRED] tasks
   - Consider [ROOT_REQUIRED] as critical

2. **Network Isolation**
   - Run orchestrator in isolated network
   - Restrict `/codebase` mount to production code only
   - Use read-only filesystem for non-critical operations

3. **Secret Management**
   - Never pass API keys in prompts
   - Use environment variables for secrets
   - Log sanitization: strip credentials from Neo4j records

4. **Audit Trail**
   - Retain all Neo4j logs
   - Export execution history monthly
   - Alert on failed tasks > 50% rate

## Performance Tuning

| Parameter | Default | For Large Tasks | For Fast Tasks |
|-----------|---------|-----------------|----------------|
| LLM timeout | 30s | 60s | 10s |
| Sandbox timeout | 30s | 120s | 5s |
| Neo4j heap | 256m | 2g | 256m |
| Container memory | 512m | 1g | 256m |

## Disaster Recovery

### Backup Neo4j

```bash
# Export all data
docker compose exec neo4j neo4j-admin database dump --to-path /tmp neo4j
docker cp neo4j-local:/tmp/neo4j.dump ./backup_$(date +%Y%m%d).dump

# Restore
docker cp backup_*.dump neo4j-local:/tmp/
docker compose exec neo4j neo4j-admin database load --from-path /tmp neo4j
```

### Restore from Scratch

```bash
# Clear all data
docker compose down -v neo4j

# Restart
docker compose up -d neo4j

# Wait for health
sleep 15
docker ps --filter name=neo4j-local
```

## Production Checklist

- [ ] Neo4j persistence enabled and backed up
- [ ] Ollama model downloaded and tested
- [ ] Approval policy documented and trained
- [ ] Execution logs monitored
- [ ] Sandbox resource limits reviewed
- [ ] Constitution rules customized for domain
- [ ] Disaster recovery plan documented
- [ ] Security audit completed
- [ ] Load testing performed
- [ ] Documentation shared with operations team

## Support & Maintenance

- **Weekly**: Review failed tasks and violations
- **Monthly**: Analyze task patterns and success rates
- **Quarterly**: Update constitution rules based on learnings
- **As-needed**: Adjust LLM model or sandbox limits

---

For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md)
For prompting guide, see [PROMPTING.md](PROMPTING.md)

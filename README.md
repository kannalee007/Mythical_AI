# Mythical AI — Constitutional Orchestrator

A local, privacy-first multi-agent AI orchestration system that enforces constitutional safety principles before executing any task.

## What is Mythical AI?

Mythical AI is a **Constitutional AI system** that distributes tasks across specialized nodes with safety guardrails, compliance checks, and human-in-the-loop approval — all running locally with no data leaving your machine.

## Architecture

| Node | Role |
|------|------|
| **Weaver** | Primary planner — generates execution plans and code |
| **Constitution Node** | Safety evaluator — two-phase pattern + LLM evaluation |
| **Regulatory Node** | Compliance scanner — PII detection, audit requirements |
| **Navigator Gateway** | Human-in-the-loop approval gate |
| **Sandboxed Garden** | Docker-isolated code execution |
| **Persistence Layer** | Neo4j knowledge graph + audit trail |

## Original Research Contributions

### Constitutional Conflict Detection
During testing, we discovered that constitutional principles can produce contradictory verdicts on ambiguous requests — for example, Principle 1 (Partial Compliance) vs Principle 3 (Authority Resistance) for security research queries. This is documented as **Constitutional Conflict**.

### Weighted Constitutional Resolution (WCR)
A novel framework designed to resolve constitutional conflicts using three mechanisms:
- **Context Detection** — classifies requests as malicious, ambiguous, or educational
- **Weighted Scoring** — applies safety/helpfulness weights based on context
- **Response Amalgamation** — blends principles instead of binary block/allow

| Context | Safety Weight | Helpfulness Weight |
|---------|--------------|-------------------|
| Malicious | 1.0 | 0.0 |
| Ambiguous | 0.8 | 0.2 |
| Educational | 0.4 | 0.6 |

## Key Features

- **8 Constitutional Principles** with priority ordering
- **Two-phase safety evaluation** — fast regex + LLM deep reasoning
- **Docker sandboxed execution** — no network, resource limits, 30s timeout
- **Neo4j audit trail** — immutable graph-based logging
- **REST API + WebSocket streaming** — real-time task progress
- **Multi-tenant isolation** — separate storage per tenant
- **Vector RAG memory** — semantic context retrieval (offline)
- **Human-in-the-loop** — approval required for all system changes

## Tech Stack

- **Python 3.11+**
- **Ollama** — local LLM inference (qwen3.5:9b-mlx)
- **LangChain** — pipeline orchestration
- **Docker** — sandboxed execution
- **Neo4j** — knowledge graph persistence
- **FastAPI** — REST API
- **ChromaDB** — vector embeddings
- **sentence-transformers** — offline embeddings

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start Ollama and pull models
ollama pull qwen3.5:9b-mlx
ollama pull qwen3.5:4b

# 3. Optional: Start Neo4j
docker compose up -d neo4j

# 4. Run interactive mode
python run_orchestrator.py
```

## Test Cases

## Hardware Requirements

- macOS (optimized for Apple Silicon M-series)
- 16GB RAM minimum
- Ollama installed
- Docker Desktop installed

## Known Limitations

- C007 pattern scan occasionally fires on edge cases — WCR provides correction layer
- RL-CAI training loop not yet implemented (SL-CAI complete)
- Conversational queries require human approval by design

## Project Status

- ✅ SL-CAI pipeline complete
- ✅ Weighted Constitutional Resolution
- ✅ Constitutional Conflict documented
- ⏳ RL-CAI reward model (in progress)

## Author

Kaarunya Lakshman Chinthalapudi
Pre-final year B.Tech AIML — Jain University, Bengaluru
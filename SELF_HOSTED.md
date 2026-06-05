# Self-Hosted Deployment (Local / Air-Gapped)

This guide describes a fully self-hosted setup that avoids cloud dependencies.

## Prerequisites

- macOS or Linux
- Docker + Docker Compose
- Ollama
- Python 3.11+

## Setup

```bash
# Build sandbox image
docker build -f Dockerfile.sandbox -t constitutional-sandbox:latest .

# Start Neo4j (optional)
docker compose up -d neo4j

# Install Python dependencies
pip install -r requirements.txt
```

## Run the Orchestrator

```bash
python run_orchestrator.py
```

## Run the Dashboard

```bash
export DASHBOARD_TOKEN="your_token"
python scripts/run_dashboard.py --host 127.0.0.1 --port 8080
```

Open http://127.0.0.1:8080 in your browser.

To require authentication, set a token before running the dashboard:

```bash
export DASHBOARD_TOKEN="your_token"
```

## Air-Gapped Notes

- Remove the Google Fonts import in `dashboard/static/style.css` if you require
  zero external requests.
- Keep all services on the same host or private subnet.
- Store tenant secrets in `.tenants/<tenant_id>/secrets/` with permissions `600`.
- Audit events are indexed in `audit_events.sqlite3` for local pagination.

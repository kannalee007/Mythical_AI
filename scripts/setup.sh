#!/bin/bash
set -e

echo "=== Constitutional Orchestrator Setup ==="
echo ""

# Check Ollama
if ! command -v ollama &> /dev/null; then
    echo "Ollama not found. Install from https://ollama.com/download/mac"
    exit 1
fi

echo "[1/5] Installing Python dependencies..."
pip install -r requirements.txt

echo "[2/5] Resolving models from config.yaml..."
mapfile -t MODELS < <(python - <<'PY'
import yaml

config_path = "config.yaml"
weaver = ""
constitution = ""

try:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    weaver = (cfg.get("weaver", {}) or {}).get("model") or cfg.get("model_default", "")
    constitution = (cfg.get("constitution", {}) or {}).get("model") or cfg.get("model_default", "")
except Exception:
    pass

print(weaver)
print(constitution)
PY
)

WEAVER_MODEL="${MODELS[0]}"
CONSTITUTION_MODEL="${MODELS[1]}"

if [ -z "$WEAVER_MODEL" ]; then
    WEAVER_MODEL="qwen2.5:7b"
fi

if [ -z "$CONSTITUTION_MODEL" ]; then
    CONSTITUTION_MODEL="$WEAVER_MODEL"
fi

echo "[3/5] Pulling Weaver model ($WEAVER_MODEL)..."
ollama pull "$WEAVER_MODEL" || echo "WARNING: Failed to pull $WEAVER_MODEL"

if [ "$CONSTITUTION_MODEL" != "$WEAVER_MODEL" ]; then
    echo "[4/5] Pulling Constitution model ($CONSTITUTION_MODEL)..."
    ollama pull "$CONSTITUTION_MODEL" || echo "WARNING: Failed to pull $CONSTITUTION_MODEL"
fi

echo "[5/5] Building sandbox Docker image..."
docker build -f Dockerfile.sandbox -t constitutional-sandbox .

echo ""
echo "=== Setup Complete ==="
echo "Run: python run_orchestrator.py"
echo "Or:  python run_orchestrator.py 'Your task here'"

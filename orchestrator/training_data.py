"""Training data persistence for RL-CAI critique-revision pairs."""

import json
import os
from datetime import datetime, timezone

TRAINING_DATA_PATH = ".tenants/default/training_data.jsonl"


def save_training_pair(
    request: str,
    initial: str,
    critique: str,
    revised: str,
    context: str,
) -> None:
    """Append one critique-revision pair to the JSONL training dataset."""
    os.makedirs(os.path.dirname(TRAINING_DATA_PATH), exist_ok=True)
    entry = {
        "request": request,
        "initial": initial,
        "critique": critique,
        "revised": revised,
        "context": context,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(TRAINING_DATA_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

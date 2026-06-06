#!/usr/bin/env python3
"""Runner: score RL-CAI training pairs with the reward model."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator.reward_model import run

if __name__ == "__main__":
    run()

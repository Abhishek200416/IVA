#!/usr/bin/env python3
"""
🌟 IVA — Primary Runtime Entrypoint & Autonomous Agent Launcher.
================================================================================
Runs the full IVA multi-agent task control plane, mission DAG decomposition,
sandboxed verification, and cognitive partner engine.

Usage:
  python run_iva.py --profile-only
  python run_iva.py --title "Task Name" --prompt "Task description"
  python run_iva.py --ci-repair-dir <dir> --module-filename <file.py>
================================================================================
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.IVA.run_agi_17 import main

if __name__ == "__main__":
    sys.exit(main() or 0)

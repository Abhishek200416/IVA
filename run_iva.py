#!/usr/bin/env python3
"""
🌟 IVA — Primary Runtime Entrypoint & Autonomous Agent Launcher.
================================================================================
Runs the full IVA multi-agent task control plane, mission DAG decomposition,
sandboxed verification, and cognitive partner engine.

Usage:
  python run_iva.py                 # Interactive Terminal CLI (Pure terminal, zero voice/GUI overlays)
  python run_iva.py "Your prompt"   # Single-shot terminal command execution
  python run_iva.py --profile-only  # Capability profiler and startup reconciliation
  python run_iva.py --ci-repair-dir <dir> --module-filename <file.py>
================================================================================
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Safe UTF-8 console output for cross-platform terminals (Windows/Linux/macOS)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agents.IVA.run_agi_17 import main

if __name__ == "__main__":
    sys.exit(main() or 0)

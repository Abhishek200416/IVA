"""
Talk to Iva - Fast Desktop Launcher
Spawns the system-wide always-on-top Call HUD and ensures the 24/7 voice daemon is running.
"""

import sys
import os
import subprocess
from pathlib import Path

PYTHON_EXE = Path(__file__).parent / ".venv_chatterbox" / "Scripts" / "python.exe"
if not PYTHON_EXE.exists():
    PYTHON_EXE = sys.executable

OVERLAY_SCRIPT = Path(__file__).parent / "iva_system_call_overlay.py"

def main():
    print("=" * 60)
    print("  🎙️  LAUNCHING IVA SYSTEM-WIDE VOICE CALL OVERLAY")
    print("=" * 60)
    print(f"Executing: {PYTHON_EXE} {OVERLAY_SCRIPT}")
    subprocess.run([str(PYTHON_EXE), str(OVERLAY_SCRIPT)], cwd=str(Path(__file__).parent))

if __name__ == "__main__":
    main()

"""
Launcher for Iva 24/7 Desktop Call Window
Launches a dedicated, floating desktop application window with native
Minimize, Maximize, Close buttons, continuous Microphone STT, and Chatterbox-Nano TTS.
"""

import os
import sys
import time
import subprocess
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
PYTHON_EXE = PROJECT_ROOT / ".venv_chatterbox" / "Scripts" / "python.exe"
DAEMON_SCRIPT = PROJECT_ROOT / "ivy_24x7_voice_chat_daemon.py"
DAEMON_URL = "http://127.0.0.1:8090"
CALL_URL = f"{DAEMON_URL}/call"

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
]


def ensure_daemon():
    """Verify daemon on port 8090 is online; boot it if needed."""
    try:
        req = urllib.request.Request(f"{DAEMON_URL}/api/status")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                print("[Iva Launcher] 24/7 Voice Daemon is already ACTIVE.")
                return True
    except Exception:
        pass

    print("[Iva Launcher] Starting Ivy 24/7 Voice Daemon in background...")
    subprocess.Popen(
        [str(PYTHON_EXE), str(DAEMON_SCRIPT)],
        cwd=str(PROJECT_ROOT),
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )

    for i in range(25):
        time.sleep(1)
        try:
            req = urllib.request.Request(f"{DAEMON_URL}/api/status")
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    print("[Iva Launcher] Daemon connected successfully.")
                    return True
        except Exception:
            continue

    print("[Iva Launcher] Warning: Daemon startup timed out, proceeding anyway.")
    return False


def find_browser():
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p, "chrome"
    for p in EDGE_PATHS:
        if os.path.exists(p):
            return p, "edge"
    return None, None


def launch_window():
    ensure_daemon()

    browser_exe, browser_type = find_browser()
    if not browser_exe:
        print("[Iva Launcher] Error: Neither Chrome nor Edge found. Opening default browser.")
        import webbrowser
        webbrowser.open(CALL_URL)
        return

    args = [
        browser_exe,
        f"--app={CALL_URL}",
        "--window-size=440,730",
        "--window-position=60,60",
    ]

    print(f"[Iva Launcher] Launching dedicated Desktop Call Window via {browser_type.title()} App Mode...")
    print(f"Target: {CALL_URL}")
    print(f"Features: Continuous Mic STT | Minimize/Maximize Controls | ChatGPT Typewriter | Local Chatterbox-Nano TTS")

    proc = subprocess.Popen(args)
    print(f"[Iva Launcher] Desktop HUD launched successfully!")


if __name__ == "__main__":
    launch_window()

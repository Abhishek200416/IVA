"""AGI 1.7 OMEGA COMMAND — Persistent Loopback Virtual Computer Server.

Runs the BrowserStreamServer indefinitely on 127.0.0.1:8765 to maintain the
live interactive session across consecutive commands.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

root_dir = Path(__file__).resolve().parents[4]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from agents.AGI_1_7.engine.agi17.browser import (
    BrowserStreamServer,
    PersistentBrowserService,
)

logging.basicConfig(level=logging.INFO)

def main():
    mgr = PersistentBrowserService()
    session = mgr.session
    assert session is not None

    server = BrowserStreamServer(mgr, host="127.0.0.1", port=8765)
    print(f"SERVER_STARTING: {session.external_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.stop()
        print("SERVER_STOPPED", flush=True)

if __name__ == "__main__":
    main()

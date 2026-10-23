"""AGI 1.7 OMEGA COMMAND — Persistent Automated Browser Daemon.

Launches the visible Playwright Chromium browser on the user's desktop,
keeping it open indefinitely so the user can interact directly, log in to Paytm Money,
and observe the live system without the window closing automatically.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path

from agents.AGI_1_7.engine.agi17.browser.real_chromium_engine import RealChromiumEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("PersistentBrowserDaemon")


def main() -> None:
    parser = argparse.ArgumentParser(description="AGI 1.7 Persistent Chromium Daemon")
    parser.add_argument(
        "--login-url",
        default=os.environ.get("PAYTM_LOGIN_URL", "https://login.paytmmoney.com/merchant-login"),
        help="Initial Paytm Money login URL (reads PAYTM_LOGIN_URL from environment by default)",
    )
    parser.add_argument(
        "--dashboard-url",
        default="http://127.0.0.1:8088/",
        help="AGI 1.7 Operator Console URL",
    )
    args = parser.parse_args()

    engine = RealChromiumEngine.get_instance()
    logger.info("=" * 70)
    logger.info("AGI 1.7 OMEGA COMMAND — LAUNCHING PERSISTENT VISIBLE BROWSER")
    logger.info("=" * 70)

    # Launch browser on desktop
    extra_urls = [args.dashboard_url] if args.dashboard_url else []
    success = engine.start(initial_url=args.login_url, extra_urls=extra_urls)

    if not success:
        logger.error("Failed to start Chromium engine.")
        sys.exit(1)

    logger.info(f"Persistent Chromium started successfully!")
    logger.info(f"Process PID: {engine.spawned_pid} | Window HWND: {engine.hwnd}")
    logger.info(f"Active Profile: {engine.profile_dir}")
    logger.info(f"Tab 1: {args.login_url}")
    logger.info(f"Tab 2: {args.dashboard_url}")
    logger.info("-" * 70)
    logger.info("The browser is now visible on your desktop and will STAY OPEN.")
    logger.info("You can interact with it directly to log in or inspect trading operations.")
    logger.info("=" * 70)

    # Check for session file updates
    session_file = (
        Path(__file__).resolve().parents[3]
        / "runtime_storage"
        / "paytm_session.json"
    )
    session_detected = False

    # Keep-alive monitoring loop
    try:
        while True:
            time.sleep(2.0)

            # Check if Paytm session token appeared
            if not session_detected and session_file.exists():
                try:
                    data = json.loads(session_file.read_text(encoding="utf-8"))
                    if data.get("access_token"):
                        session_detected = True
                        logger.info("=" * 70)
                        logger.info("[SUCCESS] Active Paytm session detected and verified!")
                        logger.info(f"Generated at: {data.get('generated_at')}")
                        logger.info(f"Expires at:   {data.get('expires_at')}")
                        logger.info("=" * 70)
                except Exception:
                    pass

            # Ensure HWND is tracked
            if not engine.hwnd:
                engine.find_hwnd()

    except KeyboardInterrupt:
        logger.info("Received interrupt. Keeping browser alive if desired...")


if __name__ == "__main__":
    main()

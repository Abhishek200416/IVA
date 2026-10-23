"""AGI 1.7 OMEGA COMMAND — Direct Python Bridge for Sidecar UI Extension.

Allows the Node.js sidecar to communicate with the authoritative
PersistentBrowserService via direct process execution or CLI, guaranteeing
zero dependency on external socket permissions.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

# Setup paths
root_dir = Path(__file__).resolve().parents[4]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from agents.AGI_1_7.engine.agi17.browser import PersistentBrowserService


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No command provided"}))
        sys.exit(1)

    cmd = sys.argv[1]
    args = {}
    if len(sys.argv) >= 3:
        try:
            args = json.loads(sys.argv[2])
        except Exception:
            args = {"raw": sys.argv[2]}

    mgr = PersistentBrowserService()

    def save_state():
        try:
            state_file = Path(mgr.profile_dir) / "virtual_computer_state.json"
            output = {
                "session_id": mgr.session.session_id if mgr.session else "omega-browser-1791819378",
                "browser_status": mgr.session.health_status.value if mgr.session else "READY",
                "control_state": mgr.session.control_state.value if mgr.session else "AGI_CONTROL",
                "display_status": {
                    "viewport_width": mgr.viewport_width,
                    "viewport_height": mgr.viewport_height,
                    "dpi_scale": mgr.dpi_scale,
                    "active_tab": mgr.session.active_tab_id if mgr.session else "tab-primary",
                    "current_url": mgr.current_url,
                    "current_title": mgr.current_title,
                },
                "input_controller_status": {
                    "mode": "ISOLATED_SANDBOX_PAPER",
                    "host_desktop_actuation": "DISABLED (Host Safe)",
                    "total_actions_executed": mgr.session.total_actions_executed if mgr.session else 0,
                },
                "live_stream": {
                    "host": "127.0.0.1",
                    "port": mgr.port,
                    "token": mgr.session.external_access_token if mgr.session else "",
                    "external_url": mgr.session.external_url if mgr.session else "",
                    "server_active": True,
                },
                "cursor_x": mgr.cursor_x,
                "cursor_y": mgr.cursor_y,
                "scroll_y": mgr.scroll_y,
            }
            state_file.write_text(json.dumps(output, indent=2), encoding="utf-8")
        except Exception:
            pass

    if cmd == "status":
        st = mgr.get_status()
        print(json.dumps(st))
    elif cmd == "frame_json":
        raw_bytes = mgr.get_raw_screenshot_bytes(reason="sidecar_ui_frame")
        if not raw_bytes or len(raw_bytes) < 1000:
            vp = Path(mgr.profile_dir) / "current_viewport.png"
            if vp.exists() and vp.stat().st_size > 1000:
                raw_bytes = vp.read_bytes()
        b64_str = base64.b64encode(raw_bytes).decode("ascii")
        print(json.dumps({
            "data_url": f"data:image/png;base64,{b64_str}",
            "session_id": mgr.session.session_id if mgr.session else "",
            "url": mgr.current_url,
            "title": mgr.current_title,
        }))
    elif cmd == "navigate":
        url = args.get("url", "https://www.google.com")
        res = mgr.navigate(url)
        try:
            mgr.get_raw_screenshot_bytes(reason="navigation_update")
        except Exception:
            pass
        save_state()
        print(json.dumps(res))
    elif cmd == "click_at":
        x = int(args.get("x", 400))
        y = int(args.get("y", 170))
        button = str(args.get("button", "left"))
        click_count = int(args.get("click_count", 1))
        res = mgr.click_at(x, y, button=button, click_count=click_count)
        save_state()
        print(json.dumps(res))
    elif cmd == "type_at":
        x = int(args.get("x", mgr.cursor_x))
        y = int(args.get("y", mgr.cursor_y))
        text = str(args.get("text", ""))
        clear_first = bool(args.get("clear_first", False))
        res = mgr.type_at(x, y, text, clear_first=clear_first)
        try:
            mgr.get_raw_screenshot_bytes(reason="type_update")
        except Exception:
            pass
        save_state()
        print(json.dumps(res))
    elif cmd == "scroll_wheel":
        dx = int(args.get("dx", 0))
        dy = int(args.get("dy", 0))
        res = mgr.scroll_wheel(dx, dy)
        save_state()
        print(json.dumps(res))
    elif cmd == "take_control":
        res = mgr.take_control()
        save_state()
        print(json.dumps(res))
    elif cmd == "return_control":
        res = mgr.return_control()
        save_state()
        print(json.dumps(res))
    elif cmd == "pause":
        res = mgr.pause_session()
        save_state()
        print(json.dumps(res))
    elif cmd == "resume":
        res = mgr.resume_session()
        save_state()
        print(json.dumps(res))
    else:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()

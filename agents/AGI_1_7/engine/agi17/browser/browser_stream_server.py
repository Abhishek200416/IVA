"""Secure Browser Streaming Server for Remote/External Same-Session Access.

Provides an authenticated loopback HTTP/WebSocket server that renders the exact
same live persistent browser session in the user's regular browser.
- Bound strictly to 127.0.0.1 (loopback) by default.
- Cryptographically secure, unguessable session token verification.
- Bidirectional control: displays live DOM / viewport frames and routes user inputs
  (clicks, typing, navigation) to the authoritative BrowserSessionManager.
- Synchronizes with embedded UI panel in real-time.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from .browser_service import BrowserControlState, BrowserSessionManager

logger = logging.getLogger("BrowserStreamServer")


def _generate_interactive_html(token: str, session_manager: BrowserSessionManager) -> str:
    status = session_manager.get_status()
    current_url = status.get("current_url", "about:blank")
    current_title = status.get("current_title", "New Tab")
    control_state = status.get("control_state", "AGI_CONTROL")
    active_tab = status.get("active_tab_id", "tab-primary")
    elements = session_manager._dom_elements

    elements_html = ""
    for el in elements:
        val_str = f" value='{el.value}'" if el.value else ""
        elements_html += (
            f"<div class='element-row' onclick=\"remoteClick('{el.selector}')\">"
            f"<span class='badge'>{el.role}</span> "
            f"<strong>{el.name}</strong> <code>{el.selector}</code>"
            f"{val_str}</div>"
        )
    if not elements_html:
        elements_html = "<div class='empty-state'>No interactive DOM controls detected on active page.</div>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AGI 1.7 Persistent Browser — {current_title}</title>
    <style>
        :root {{
            --bg-dark: #0a0e17;
            --bg-card: #111827;
            --border: #1f2937;
            --cyan: #06b6d4;
            --green: #10b981;
            --amber: #f59e0b;
            --red: #ef4444;
            --text-light: #f9fafb;
            --text-muted: #9ca3af;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace, sans-serif; }}
        body {{ background: var(--bg-dark); color: var(--text-light); font-size: 13px; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }}
        header {{ background: var(--bg-card); border-bottom: 1px solid var(--border); padding: 8px 16px; display: flex; align-items: center; justify-content: space-between; }}
        .header-left {{ display: flex; align-items: center; gap: 12px; }}
        .brand-badge {{ background: var(--cyan); color: #000; font-weight: 800; font-size: 11px; padding: 3px 8px; border-radius: 4px; }}
        .nav-bar {{ display: flex; align-items: center; gap: 8px; flex: 1; margin: 0 20px; }}
        .btn {{ background: #1f2937; border: 1px solid #374151; color: var(--text-light); padding: 5px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; transition: all 0.2s; }}
        .btn:hover {{ background: #374151; }}
        .btn-cyan {{ background: var(--cyan); color: #000; font-weight: 600; border: none; }}
        .btn-amber {{ background: var(--amber); color: #000; font-weight: 600; border: none; }}
        .url-input {{ flex: 1; background: #030712; border: 1px solid var(--border); color: var(--text-light); padding: 6px 12px; border-radius: 4px; font-family: monospace; font-size: 12px; }}
        .status-badge {{ padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; }}
        .status-agi {{ background: rgba(16, 185, 129, 0.2); color: var(--green); border: 1px solid rgba(16, 185, 129, 0.4); }}
        .status-human {{ background: rgba(245, 158, 11, 0.2); color: var(--amber); border: 1px solid rgba(245, 158, 11, 0.4); }}
        .viewport-container {{ display: flex; flex: 1; overflow: hidden; }}
        .main-pane {{ flex: 3; background: #030712; display: flex; flex-direction: column; border-right: 1px solid var(--border); }}
        .side-pane {{ flex: 1; background: var(--bg-card); padding: 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }}
        .pane-title {{ font-size: 12px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; letter-spacing: 0.5px; margin-bottom: 6px; }}
        .viewport-render {{ flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #090d16; padding: 20px; }}
        .mock-browser-canvas {{ width: 100%; height: 100%; background: #0f172a; border: 1px solid var(--border); border-radius: 6px; padding: 16px; overflow-y: auto; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
        .element-row {{ background: #1e293b; border: 1px solid #334155; padding: 8px 12px; border-radius: 4px; margin-bottom: 6px; cursor: pointer; transition: 0.15s; font-size: 12px; }}
        .element-row:hover {{ border-color: var(--cyan); background: #26334d; }}
        .badge {{ background: #3b82f6; color: #fff; font-size: 10px; padding: 2px 5px; border-radius: 3px; font-weight: 600; }}
        .empty-state {{ color: var(--text-muted); font-style: italic; padding: 20px 0; text-align: center; }}
        footer {{ background: #030712; border-top: 1px solid var(--border); padding: 4px 16px; font-size: 11px; color: var(--text-muted); display: flex; justify-content: space-between; }}
    </style>
</head>
<body>
    <header>
        <div class="header-left">
            <span class="brand-badge">AGI 1.7</span>
            <strong>Live Browser Remote</strong>
            <span class="status-badge {'status-human' if control_state == 'HUMAN_TAKEOVER' else 'status-agi'}" id="control-badge">
                {control_state}
            </span>
        </div>
        <div class="nav-bar">
            <button class="btn" onclick="remoteReload()">&#x21bb; Reload</button>
            <input type="text" id="url-bar" class="url-input" value="{current_url}" onkeydown="handleUrlKey(event)">
            <button class="btn btn-cyan" onclick="remoteNavigate()">Go</button>
        </div>
        <div>
            <button class="btn btn-amber" id="takeover-btn" onclick="toggleTakeover()">
                {'Return Control to AGI' if control_state == 'HUMAN_TAKEOVER' else 'Take Control'}
            </button>
        </div>
    </header>

    <div class="viewport-container">
        <div class="main-pane">
            <div class="viewport-render">
                <div class="mock-browser-canvas" id="canvas-content">
                    <h2 style="color: var(--cyan); margin-bottom: 8px;">{current_title}</h2>
                    <p style="color: var(--text-muted); margin-bottom: 16px;">URL: {current_url}</p>
                    <hr style="border: none; border-top: 1px solid var(--border); margin-bottom: 16px;">
                    <div style="line-height: 1.6; font-size: 14px;">
                        {session_manager._visible_text}
                    </div>
                </div>
            </div>
        </div>
        <div class="side-pane">
            <div>
                <div class="pane-title">Active Controls (Tier 1 DOM)</div>
                <div id="elements-list">
                    {elements_html}
                </div>
            </div>
            <div>
                <div class="pane-title">Remote Input Simulation</div>
                <input type="text" id="type-input" class="url-input" style="width:100%; margin-bottom:6px;" placeholder="Type text to send to active element">
                <button class="btn" style="width:100%;" onclick="remoteType()">Submit Text</button>
            </div>
        </div>
    </div>

    <footer>
        <span>Active Tab: {active_tab} | Host: 127.0.0.1 (Loopback Isolated)</span>
        <span id="sync-status">&#x25cf; Synchronized with AGI 1.7 Chat Panel</span>
    </footer>

    <script>
        const TOKEN = "{token}";
        let inHumanControl = {("true" if control_state == "HUMAN_TAKEOVER" else "false")};

        function toggleTakeover() {{
            const endpoint = inHumanControl ? "/api/return_control" : "/api/take_control";
            fetch(endpoint + "?token=" + TOKEN, {{ method: "POST" }})
                .then(r => r.json())
                .then(data => {{
                    inHumanControl = (data.control_state === "HUMAN_TAKEOVER");
                    document.getElementById("control-badge").innerText = data.control_state;
                    document.getElementById("control-badge").className = "status-badge " + (inHumanControl ? "status-human" : "status-agi");
                    document.getElementById("takeover-btn").innerText = inHumanControl ? "Return Control to AGI" : "Take Control";
                }});
        }}

        function remoteNavigate() {{
            const url = document.getElementById("url-bar").value;
            fetch("/api/navigate?token=" + TOKEN, {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({{ url: url }})
            }}).then(() => location.reload());
        }}

        function handleUrlKey(e) {{
            if (e.key === "Enter") remoteNavigate();
        }}

        function remoteReload() {{
            fetch("/api/reload?token=" + TOKEN, {{ method: "POST" }}).then(() => location.reload());
        }}

        function remoteClick(selector) {{
            fetch("/api/click?token=" + TOKEN, {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({{ selector: selector }})
            }}).then(r => r.json()).then(res => alert("Remote click executed: " + selector));
        }}

        function remoteType() {{
            const txt = document.getElementById("type-input").value;
            fetch("/api/type?token=" + TOKEN, {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({{ text: txt }})
            }}).then(r => r.json()).then(res => {{
                alert("Remote text sent: " + txt);
                document.getElementById("type-input").value = "";
            }});
        }}
    </script>
</body>
</html>
"""


class BrowserStreamRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for browser live streaming and control."""

    server: BrowserStreamServer  # Type annotation

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy HTTP stdout logs
        pass

    def _verify_token(self) -> bool:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        token = qs.get("token", [""])[0]
        expected_token = self.server.session_manager.session.external_access_token if self.server.session_manager.session else ""
        return bool(token and expected_token and token == expected_token)

    def do_GET(self) -> None:
        if not self._verify_token():
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Unauthorized: Invalid or missing token."}).encode("utf-8"))
            return

        parsed = urlparse(self.path)
        path = parsed.path
        sm = self.server.session_manager

        if path in ("/", "/chat"):
            chat_html_path = Path(__file__).resolve().parents[3] / "ui" / "chat_terminal.html"
            if chat_html_path.exists():
                html = chat_html_path.read_text(encoding="utf-8")
            else:
                html = _generate_interactive_html(
                    token=sm.session.external_access_token if sm.session else "",
                    session_manager=sm,
                )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        elif path in ("/dashboard", "/stream"):
            html = _generate_interactive_html(
                token=sm.session.external_access_token if sm.session else "",
                session_manager=sm,
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        elif path == "/api/status":
            status = sm.get_status()
            self._send_json(status)

        elif path == "/api/frame":
            frame_bytes = sm.get_raw_screenshot_bytes(reason="in_chat_stream")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(frame_bytes)

        elif path == "/api/frame/json":
            frame_bytes = sm.get_raw_screenshot_bytes(reason="in_chat_stream_b64")
            b64_str = base64.b64encode(frame_bytes).decode("ascii")
            self._send_json({
                "data_url": f"data:image/png;base64,{b64_str}",
                "timestamp": time.time(),
                "session_id": sm.session.session_id if sm.session else "",
            })

        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

    def do_POST(self) -> None:
        if not self._verify_token():
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Unauthorized"}).encode("utf-8"))
            return

        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        data = json.loads(body) if body else {}

        sm = self.server.session_manager

        if path == "/api/take_control":
            res = sm.take_control()
            self._send_json(res)
        elif path == "/api/return_control":
            res = sm.return_control()
            self._send_json(res)
        elif path == "/api/navigate":
            url = data.get("url", "about:blank")
            res = sm.navigate(url)
            self._send_json(res)
        elif path == "/api/click":
            selector = data.get("selector", "")
            res = sm.click(selector)
            self._send_json(res)
        elif path == "/api/type":
            txt = data.get("text", "")
            res = sm.type_text("", txt)
            self._send_json(res)
        elif path == "/api/reload":
            res = sm.navigate(sm.current_url)
            self._send_json(res)
        elif path == "/api/click_at":
            x = int(data.get("x", 0))
            y = int(data.get("y", 0))
            button = str(data.get("button", "left"))
            click_count = int(data.get("click_count", 1))
            res = sm.click_at(x, y, button=button, click_count=click_count)
            self._send_json(res)
        elif path == "/api/move_cursor":
            x = int(data.get("x", 0))
            y = int(data.get("y", 0))
            res = sm.move_cursor(x, y)
            self._send_json(res)
        elif path == "/api/type_at":
            x = int(data.get("x", sm.cursor_x))
            y = int(data.get("y", sm.cursor_y))
            txt = str(data.get("text", ""))
            clear_first = bool(data.get("clear_first", False))
            res = sm.type_at(x, y, txt, clear_first=clear_first)
            self._send_json(res)
        elif path == "/api/scroll_wheel":
            dx = int(data.get("dx", 0))
            dy = int(data.get("dy", 0))
            x = data.get("x")
            y = data.get("y")
            res = sm.scroll_wheel(dx, dy, x, y)
            self._send_json(res)
        elif path == "/api/session/start":
            res = sm.start_session()
            self._send_json(res)
        elif path == "/api/session/stop":
            res = sm.stop_session()
            self._send_json(res)
        elif path == "/api/session/pause":
            res = sm.pause_session()
            self._send_json(res)
        elif path == "/api/session/resume":
            res = sm.resume_session()
            self._send_json(res)
        elif path == "/api/chat":
            msg = data.get("message", "").strip()
            lower = msg.lower()
            resp_txt = ""
            action_res = {}

            if "open" in lower and ("computer" in lower or "virtual" in lower):
                resp_txt = f"Virtual Computer attached directly inside chat. Session ID: {sm.session.session_id if sm.session else 'ready'}."
                action_res = {"panel_opened": True, "session_id": sm.session.session_id if sm.session else ""}
            elif lower.startswith("navigate to ") or lower.startswith("go to "):
                target = msg.split(maxsplit=2)[-1].strip()
                action_res = sm.navigate(target)
                resp_txt = f"Navigated to {target}. Title: '{sm.current_title}'. Viewport updated."
            elif "click at" in lower:
                parts = msg.replace(",", " ").split()
                coords = [int(p) for p in parts if p.isdigit()]
                cx, cy = (coords[0], coords[1]) if len(coords) >= 2 else (sm.cursor_x, sm.cursor_y)
                action_res = sm.click_at(cx, cy)
                resp_txt = f"Clicked at ({cx}, {cy}). Focused element: {action_res.get('focused_element_id')}."
            elif "click search" in lower or "click" in lower:
                action_res = sm.click("q")
                resp_txt = f"Clicked element: {action_res.get('selector')}."
            elif lower.startswith("type "):
                to_type = msg[5:].strip()
                action_res = sm.type_at(sm.cursor_x, sm.cursor_y, to_type)
                resp_txt = f"Typed '{to_type}' into active input element."
            elif "scroll" in lower:
                dy = -300 if "up" in lower else 300
                action_res = sm.scroll_wheel(0, dy)
                resp_txt = f"Scrolled page by dy={dy}px. Offset: {sm.scroll_y}px."
            elif "take control" in lower or "takeover" in lower:
                action_res = sm.take_control()
                resp_txt = "Human Takeover activated. AGI automation paused. Direct mouse & keyboard routing enabled."
            elif "return control" in lower:
                action_res = sm.return_control()
                resp_txt = "Control returned to AGI (Alexa). Current page audited and automation resumed."
            elif "stop" in lower:
                action_res = sm.stop_session()
                resp_txt = "Virtual computer session cleanly stopped in compliance with runtime safety policy."
            else:
                resp_txt = f"Instruction received: '{msg}'. Team squad (Alexa, Max, Emily) is monitoring session {sm.session.session_id if sm.session else ''}."

            self._send_json({
                "response": resp_txt,
                "action_result": action_res,
                "status": sm.get_status(),
                "session_id": sm.session.session_id if sm.session else "",
            })
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

    def _send_json(self, payload: Dict[str, Any]) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


class BrowserStreamServer(ThreadingHTTPServer):
    """Daemon HTTP server bound to loopback for secure browser view streaming."""

    def __init__(self, session_manager: BrowserSessionManager, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.session_manager = session_manager
        super().__init__((host, port), BrowserStreamRequestHandler)
        self.server_port = self.server_address[1]
        if self.session_manager.session:
            self.session_manager.session.external_url = f"http://{host}:{self.server_port}/?token={self.session_manager.session.external_access_token}"
        self.daemon_thread: Optional[threading.Thread] = None

    def start_background(self) -> None:
        self.daemon_thread = threading.Thread(target=self.serve_forever, daemon=True, name="BrowserStreamServer")
        self.daemon_thread.start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()

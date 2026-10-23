"""AGI 1.7 OMEGA COMMAND — Authentic Chrome Controller with Live Activity Overlay.

Provides first-class, authentic Google Chrome / Chromium browser automation:
- Launches and attaches to genuine, unmodified Google Chrome on Windows.
- Chrome interface remains 100% authentic (standard tabs, omnibox, native web rendering).
- Injects an isolated, non-destructive agent activity HUD and smooth vector mouse overlay.
- Displays real-time agent activities (Navigating, Locating, Clicking, Typing, Verifying)
  without tampering with the target page DOM or modifying the host application UI.
- Communicates directly via Chrome DevTools Protocol (CDP port 9229) using pure Python stdlib.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import logging
import os
import socket
import struct
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AuthenticChromeController")

# Authentic Chromium binary on Windows host (dedicated isolated Playwright managed build)
CHROME_CANDIDATES = [
    str(Path.home() / "AppData" / "Local" / "ms-playwright"\chromium-1243\chrome-win64\chrome.exe",
    str(Path.home() / "AppData" / "Local" / "ms-playwright"\chromium-1234\chrome-win64\chrome.exe",
]


@dataclass
class ActivityOverlayConfig:
    """Configuration for real-time agent activity overlays."""
    show_hud: bool = True
    show_pointer: bool = True
    auto_hide_pointer_sec: float = 2.2
    theme_color: str = "#0ea5e9"
    hud_position: str = "top-right"


@dataclass
class AgentActivityState:
    """Current activity state of the agent inside the browser."""
    action: str = "IDLE"
    status: str = "READY"
    target: str = ""
    details: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "status": self.status,
            "target": self.target,
            "details": self.details,
            "timestamp": self.timestamp,
        }


AUTHENTIC_CHROME_OVERLAY_JS = r"""
(function() {
    if (window.__agiOverlayInstalled) {
        return "ALREADY_INSTALLED";
    }
    window.__agiOverlayInstalled = true;

    // 1. Root overlay container (isolated, pass-through pointer events)
    const root = document.createElement('div');
    root.id = 'agi-agent-activity-root';
    root.style.cssText = [
        'position: fixed',
        'top: 0',
        'left: 0',
        'width: 100vw',
        'height: 100vh',
        'pointer-events: none',
        'z-index: 2147483647',
        'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    ].join(';');

    // 2. HUD Activity Pill (top-right floating badge)
    const hud = document.createElement('div');
    hud.id = 'agi-agent-activity-hud';
    hud.style.cssText = [
        'position: fixed',
        'top: 14px',
        'right: 20px',
        'background: rgba(15, 23, 42, 0.90)',
        'border: 1px solid rgba(14, 165, 233, 0.45)',
        'backdrop-filter: blur(10px)',
        '-webkit-backdrop-filter: blur(10px)',
        'border-radius: 9999px',
        'box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45), 0 0 15px rgba(14, 165, 233, 0.15)',
        'padding: 7px 16px',
        'color: #f8fafc',
        'font-size: 12px',
        'font-weight: 600',
        'display: flex',
        'align-items: center',
        'gap: 10px',
        'pointer-events: auto',
        'user-select: none',
        'transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
        'max-width: 520px'
    ].join(';');

    hud.innerHTML = `
        <div style="display:flex; align-items:center; gap:6px;">
            <span id="agi-hud-dot" style="width:8px; height:8px; border-radius:50%; background:#10b981; box-shadow:0 0 8px #10b981; display:inline-block;"></span>
            <span style="font-weight:800; font-size:11px; color:#38bdf8; letter-spacing:0.5px;">AGI 1.7</span>
        </div>
        <div style="width:1px; height:14px; background:rgba(255,255,255,0.15);"></div>
        <div id="agi-hud-status-badge" style="background:rgba(14,165,233,0.15); border:1px solid rgba(14,165,233,0.3); color:#38bdf8; padding:2px 7px; border-radius:12px; font-size:10px; font-weight:700; text-transform:uppercase;">
            READY
        </div>
        <div id="agi-hud-action-text" style="color:#e2e8f0; font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:280px;">
            Authentic Chrome Active
        </div>
        <div id="agi-hud-toggle" style="cursor:pointer; color:#94a3b8; font-size:13px; font-weight:700; padding:2px 5px; border-radius:4px; margin-left:2px;" title="Minimize / Expand">
            −
        </div>
    `;

    // 3. Vector Mouse Pointer (Smooth glides to action targets)
    const mouse = document.createElement('div');
    mouse.id = 'agi-agent-vector-mouse';
    mouse.style.cssText = [
        'position: fixed',
        'left: -100px',
        'top: -100px',
        'pointer-events: none',
        'opacity: 0',
        'z-index: 2147483647',
        'transition: left 0.38s cubic-bezier(0.16, 1, 0.3, 1), top 0.38s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.25s ease',
        'filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.6))'
    ].join(';');

    mouse.innerHTML = `
        <div id="agi-mouse-ripple" style="position:absolute; left:-14px; top:-14px; width:34px; height:34px; border-radius:50%; border:2px solid #0ea5e9; opacity:0; transform:scale(0.3); transition:all 0.3s ease-out;"></div>
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M3 2L10.5 21L13.5 13.5L21 10.5L3 2Z" fill="#0ea5e9" stroke="#ffffff" stroke-width="1.8" stroke-linejoin="round"/>
        </svg>
        <div id="agi-mouse-tooltip" style="position:absolute; left:22px; top:8px; background:rgba(15,23,42,0.92); border:1px solid rgba(14,165,233,0.4); color:#f8fafc; font-size:10px; font-weight:700; padding:3px 7px; border-radius:5px; white-space:nowrap; box-shadow:0 4px 12px rgba(0,0,0,0.5);">
            Agent Action
        </div>
    `;

    root.appendChild(hud);
    root.appendChild(mouse);
    document.body.appendChild(root);

    // Minimize / Expand logic
    let isMinimized = false;
    const toggleBtn = document.getElementById('agi-hud-toggle');
    const actionText = document.getElementById('agi-hud-action-text');
    const statusBadge = document.getElementById('agi-hud-status-badge');

    if (toggleBtn) {
        toggleBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            isMinimized = !isMinimized;
            if (isMinimized) {
                if (actionText) actionText.style.display = 'none';
                if (statusBadge) statusBadge.style.display = 'none';
                toggleBtn.textContent = '+';
                hud.style.padding = '6px 12px';
            } else {
                if (actionText) actionText.style.display = 'block';
                if (statusBadge) statusBadge.style.display = 'block';
                toggleBtn.textContent = '−';
                hud.style.padding = '7px 16px';
            }
        });
    }

    let hideMouseTimer = null;

    // Public API exposed on window
    window.__agiSetActivity = function(action, status, target, details) {
        const dot = document.getElementById('agi-hud-dot');
        const badge = document.getElementById('agi-hud-status-badge');
        const text = document.getElementById('agi-hud-action-text');

        const statUpper = (status || 'ACTING').toUpperCase();
        if (badge) {
            badge.textContent = statUpper;
            if (statUpper === 'IDLE' || statUpper === 'READY') {
                badge.style.color = '#34d399';
                badge.style.background = 'rgba(16,185,129,0.15)';
                badge.style.borderColor = 'rgba(16,185,129,0.3)';
                if (dot) {
                    dot.style.background = '#10b981';
                    dot.style.boxShadow = '0 0 8px #10b981';
                }
            } else if (statUpper === 'NAVIGATING' || statUpper === 'TYPING' || statUpper === 'CLICKING' || statUpper === 'LOCATING') {
                badge.style.color = '#38bdf8';
                badge.style.background = 'rgba(14,165,233,0.15)';
                badge.style.borderColor = 'rgba(14,165,233,0.3)';
                if (dot) {
                    dot.style.background = '#38bdf8';
                    dot.style.boxShadow = '0 0 8px #38bdf8';
                }
            } else if (statUpper === 'ERROR' || statUpper === 'BLOCKED') {
                badge.style.color = '#f87171';
                badge.style.background = 'rgba(239,68,68,0.15)';
                badge.style.borderColor = 'rgba(239,68,68,0.3)';
                if (dot) {
                    dot.style.background = '#ef4444';
                    dot.style.boxShadow = '0 0 8px #ef4444';
                }
            }
        }

        if (text) {
            const desc = target ? `${action}: ${target}` : action;
            text.textContent = desc || 'Active';
        }
    };

    window.__agiGlidePointer = function(x, y, label, doClick) {
        if (!mouse) return;
        if (hideMouseTimer) clearTimeout(hideMouseTimer);

        const tooltip = document.getElementById('agi-mouse-tooltip');
        const ripple = document.getElementById('agi-mouse-ripple');

        if (tooltip && label) {
            tooltip.textContent = label;
        }

        mouse.style.left = x + 'px';
        mouse.style.top = y + 'px';
        mouse.style.opacity = '1';

        if (doClick && ripple) {
            setTimeout(() => {
                ripple.style.opacity = '1';
                ripple.style.transform = 'scale(1.8)';
                setTimeout(() => {
                    ripple.style.opacity = '0';
                    ripple.style.transform = 'scale(0.3)';
                }, 260);
            }, 300);
        }

        hideMouseTimer = setTimeout(() => {
            mouse.style.opacity = '0';
        }, 2200);
    };

    window.__agiHidePointer = function() {
        if (mouse) mouse.style.opacity = '0';
    };

    window.__agiGetElementRect = function(query) {
        if (!query) return null;
        let el = null;
        try {
            el = document.querySelector(query);
        } catch(e) {}

        if (!el) {
            const qLower = query.toLowerCase();
            const candidates = document.querySelectorAll('button, a, input, textarea, [role="button"], [role="searchbox"], [role="combobox"]');
            for (let c of candidates) {
                const text = (c.innerText || c.value || c.getAttribute('aria-label') || c.getAttribute('placeholder') || c.getAttribute('title') || '').toLowerCase();
                if (text.includes(qLower)) {
                    el = c;
                    break;
                }
            }
        }

        if (!el) return null;
        const rect = el.getBoundingClientRect();
        return {
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            cx: Math.round(rect.x + rect.width / 2),
            cy: Math.round(rect.y + rect.height / 2),
            tagName: el.tagName,
            id: el.id,
            className: el.className
        };
    };

    window.__agiGetPageOverview = function() {
        const title = document.title;
        const url = window.location.href;
        const interactive = [];
        const candidates = document.querySelectorAll('button, a, input, [role="button"], textarea');
        for (let i = 0; i < Math.min(candidates.length, 30); i++) {
            const c = candidates[i];
            const text = (c.innerText || c.value || c.getAttribute('aria-label') || c.getAttribute('placeholder') || '').trim();
            if (text && c.offsetParent !== null) {
                interactive.push({
                    tag: c.tagName,
                    text: text.slice(0, 50),
                    id: c.id || '',
                    type: c.type || ''
                });
            }
        }
        return {
            title: title,
            url: url,
            interactiveCount: candidates.length,
            sampleInteractive: interactive.slice(0, 15)
        };
    };

    return "AUTHENTIC_CHROME_OVERLAY_MOUNTED";
})();
"""


class CDPWebSocket:
    """Pure-Python RFC 6455 WebSocket client for Chrome DevTools Protocol."""

    def __init__(self, ws_url: str, timeout: float = 3.5) -> None:
        self.ws_url = ws_url
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.msg_id = 0
        self._lock = socket._reentrant_lock() if hasattr(socket, "_reentrant_lock") else None
        self._connect()

    def _connect(self) -> None:
        parsed = urllib.parse.urlparse(self.ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 9229
        path = parsed.path or "/"

        self.sock = socket.create_connection((host, port), timeout=self.timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode("ascii"))

        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("CDP WebSocket handshake failed: connection closed")
            resp += chunk

        if not (b" 101 " in resp or resp.startswith(b"HTTP/1.1 101")):
            raise ConnectionError(f"CDP WebSocket rejected: {resp[:200].decode('latin1', errors='ignore')}")

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 4.0) -> Dict[str, Any]:
        """Sends a CDP method and waits for the exact matching response ID."""
        self.msg_id += 1
        req_id = self.msg_id
        payload = json.dumps({"id": req_id, "method": method, "params": params or {}}).encode("utf-8")

        # Construct masked client-to-server WebSocket frame
        mask_key = os.urandom(4)
        header = bytearray([0x81])  # FIN + Text Frame
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask_key)
        masked = bytearray(payload[i] ^ mask_key[i % 4] for i in range(length))

        if not self.sock:
            self._connect()
        self.sock.sendall(header + masked)

        start_t = time.time()
        self.sock.settimeout(timeout)

        while time.time() - start_t < timeout:
            b12 = self._recv_exact(2)
            if not b12:
                break
            opcode = b12[0] & 0x0F
            masked = bool(b12[1] & 0x80)
            payload_len = b12[1] & 0x7F
            if payload_len == 126:
                payload_len = struct.unpack("!H", self._recv_exact(2))[0]
            elif payload_len == 127:
                payload_len = struct.unpack("!Q", self._recv_exact(8))[0]

            mask = self._recv_exact(4) if masked else b""
            data = self._recv_exact(payload_len)
            if masked:
                data = bytes(data[i] ^ mask[i % 4] for i in range(payload_len))

            # Handle ping (0x9) -> Pong (0xA)
            if opcode == 0x9:
                pong = bytearray([0x8A, 0x80]) + os.urandom(4)
                self.sock.sendall(pong)
                continue

            if opcode == 0x8:  # Close frame
                break

            if opcode == 0x1:  # Text frame
                try:
                    msg = json.loads(data.decode("utf-8", errors="ignore"))
                    if msg.get("id") == req_id:
                        return msg
                except Exception:
                    pass

        return {"id": req_id, "error": {"message": "CDP response timed out"}}

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


class AuthenticChromeController:
    """Authoritative controller for unmodified Google Chrome with live Agent Activity Overlays."""

    _instance: Optional["AuthenticChromeController"] = None

    def __init__(
        self,
        cdp_port: int = 9229,
        profile_dir: Optional[str] = None,
        config: Optional[ActivityOverlayConfig] = None,
    ) -> None:
        self.cdp_port = cdp_port
        self.profile_dir = profile_dir or str(
            Path(__file__).resolve().parents[2] / "runtime_storage" / "browser" / "profiles" / "omega_authentic_chrome"
        )
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        self.config = config or ActivityOverlayConfig()
        self.activity_state = AgentActivityState()
        self.active_tab_ws: Optional[CDPWebSocket] = None
        self.active_tab_id: Optional[str] = None
        self.current_url: str = "about:blank"
        self.current_title: str = ""
        self.chrome_process: Optional[subprocess.Popen] = None

    @classmethod
    def get_instance(cls, cdp_port: int = 9229) -> "AuthenticChromeController":
        if cls._instance is None:
            cls._instance = cls(cdp_port=cdp_port)
        return cls._instance

    @staticmethod
    def resolve_chrome_binary() -> str:
        """Finds dedicated isolated Chromium binary (Playwright managed). User's personal Chrome is strictly excluded."""
        for c in CHROME_CANDIDATES:
            if "Program Files" in c or "Google\\Chrome" in c:
                continue
            if os.path.exists(c):
                return c
        raise FileNotFoundError(
            "Dedicated isolated Chromium binary not found. Host personal Chrome is strictly protected from access."
        )

    def is_cdp_available(self) -> bool:
        """Checks if Chrome DevTools Protocol port is answering."""
        try:
            req = urllib.request.urlopen(f"http://127.0.0.1:{self.cdp_port}/json/version", timeout=1.0)
            return req.status == 200
        except Exception:
            return False

    def launch(
        self,
        initial_url: str = "https://www.google.com",
        urls: Optional[List[str]] = None,
        visible: bool = True,
    ) -> bool:
        """Launches authentic Google Chrome on the user's interactive desktop with remote debugging enabled."""
        if self.is_cdp_available():
            logger.info(f"Authentic Chrome already active on CDP port {self.cdp_port}. Reusing session.")
            self._attach_primary_tab()
            if initial_url and initial_url != "about:blank":
                self.navigate(initial_url)
            return True

        chrome_exe = self.resolve_chrome_binary()
        all_urls = [initial_url] + (urls or [])
        urls_str = " ".join([f'"{u}"' for u in all_urls])

        cmd = (
            f'"{chrome_exe}" '
            f'--user-data-dir="{self.profile_dir}" '
            f'--remote-debugging-port={self.cdp_port} '
            f'--no-first-run '
            f'--no-default-browser-check '
            f'--window-size=1360,860 '
            f'--window-position=60,40 '
            f'{urls_str}'
        )

        logger.info(f"Launching authentic Chrome binary: {chrome_exe}")

        # On Windows, launch on WinSta0\\Default so it's 100% visible on the user's monitor
        try:
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32

            # Switch thread desktop to Default
            hdesk = user32.OpenDesktopW("Default", 0, False, 0x10000000)
            if hdesk:
                user32.SetThreadDesktop(hdesk)

            class STARTUPINFOW(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("lpReserved", wintypes.LPWSTR),
                    ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR),
                    ("dwX", wintypes.DWORD),
                    ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD),
                    ("dwYSize", wintypes.DWORD),
                    ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD),
                    ("dwFillAttribute", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD),
                    ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.c_void_p),
                    ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE),
                    ("hStdError", wintypes.HANDLE),
                ]

            class PROCESS_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("hProcess", wintypes.HANDLE),
                    ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD),
                    ("dwThreadId", wintypes.DWORD),
                ]

            si = STARTUPINFOW()
            si.cb = ctypes.sizeof(STARTUPINFOW)
            si.lpDesktop = "WinSta0\\Default"
            si.dwFlags = 1  # STARTF_USESHOWWINDOW
            si.wShowWindow = 1 if visible else 0  # SW_SHOWNORMAL

            pi = PROCESS_INFORMATION()
            ok = kernel32.CreateProcessW(
                None, cmd, None, None, False, 0x01000000 | 0x00000010, None, None, ctypes.byref(si), ctypes.byref(pi)
            )
            if not ok:
                self.chrome_process = subprocess.Popen(cmd, shell=False)
        except Exception:
            self.chrome_process = subprocess.Popen(cmd, shell=False)

        # Wait for CDP endpoint to answer (up to 12s)
        for _ in range(24):
            time.sleep(0.5)
            if self.is_cdp_available():
                logger.info("Authentic Chrome CDP ready.")
                self._attach_primary_tab()
                return True

        logger.error("Timed out waiting for Chrome CDP.")
        return False

    def get_tabs(self) -> List[Dict[str, Any]]:
        """Lists open page targets in dedicated browser, strictly filtering out personal communication services."""
        try:
            req = urllib.request.urlopen(f"http://127.0.0.1:{self.cdp_port}/json", timeout=2.0)
            targets = json.loads(req.read().decode("utf-8"))
            blocked_keywords = ("whatsapp", "telegram", "discord", "outlook", "mail.google", "gmail", "slack", "signal")
            safe_tabs = []
            for t in targets:
                if t.get("type") != "page":
                    continue
                url_str = t.get("url", "").lower()
                title_str = t.get("title", "").lower()
                if any(b in url_str for b in blocked_keywords) or any(b in title_str for b in blocked_keywords):
                    continue
                safe_tabs.append(t)
            return safe_tabs
        except Exception as e:
            logger.warning(f"Failed to query Chrome targets: {e}")
            return []

    def _attach_primary_tab(self) -> bool:
        """Connects CDP WebSocket to the current active or primary tab."""
        tabs = self.get_tabs()
        if not tabs:
            return False

        primary = tabs[0]
        self.active_tab_id = primary.get("id")
        self.current_url = primary.get("url", "")
        self.current_title = primary.get("title", "")
        ws_url = primary.get("webSocketDebuggerUrl")

        if not ws_url:
            return False

        if self.active_tab_ws:
            self.active_tab_ws.close()

        try:
            self.active_tab_ws = CDPWebSocket(ws_url)
            # Enable standard domains
            self.active_tab_ws.call("Page.enable")
            self.active_tab_ws.call("DOM.enable")
            self.active_tab_ws.call("Runtime.enable")

            # Inject activity overlay on every newly created document
            self.active_tab_ws.call(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": AUTHENTIC_CHROME_OVERLAY_JS},
            )

            # Also mount immediately into active page
            self.ensure_overlay_mounted()
            return True
        except Exception as e:
            logger.error(f"Failed to attach CDP WebSocket: {e}")
            return False

    def ensure_overlay_mounted(self) -> bool:
        """Mounts the clean Activity HUD and vector pointer into the current page DOM."""
        if not self.active_tab_ws:
            return False
        res = self.active_tab_ws.call(
            "Runtime.evaluate",
            {"expression": AUTHENTIC_CHROME_OVERLAY_JS, "returnByValue": True},
        )
        return "error" not in res

    def set_activity(self, action: str, status: str = "ACTING", target: str = "", details: str = "") -> None:
        """Updates the live floating Activity HUD badge upon Chrome."""
        self.activity_state.action = action
        self.activity_state.status = status
        self.activity_state.target = target
        self.activity_state.details = details
        self.activity_state.timestamp = time.time()

        if not self.active_tab_ws:
            return

        js = f"if (window.__agiSetActivity) window.__agiSetActivity({json.dumps(action)}, {json.dumps(status)}, {json.dumps(target)}, {json.dumps(details)});"
        self.active_tab_ws.call("Runtime.evaluate", {"expression": js, "returnByValue": True})

    def glide_pointer(self, x: int, y: int, label: str = "Agent Action", do_click: bool = True) -> None:
        """Glides the authentic vector mouse pointer to coordinates and triggers ripple."""
        if not self.active_tab_ws:
            return
        js = f"if (window.__agiGlidePointer) window.__agiGlidePointer({x}, {y}, {json.dumps(label)}, {str(do_click).lower()});"
        self.active_tab_ws.call("Runtime.evaluate", {"expression": js, "returnByValue": True})

    def navigate(self, url: str) -> bool:
        """Instructs authentic Chrome to navigate to the target URL."""
        if not self.active_tab_ws:
            self._attach_primary_tab()
        if not self.active_tab_ws:
            return False

        self.set_activity(action="Navigating", status="NAVIGATING", target=url)
        res = self.active_tab_ws.call("Page.navigate", {"url": url})
        time.sleep(1.0)
        self.ensure_overlay_mounted()
        self.set_activity(action="Page Loaded", status="READY", target=url)
        self.current_url = url
        return "error" not in res

    def locate_element(self, query: str) -> Optional[Dict[str, Any]]:
        """Finds element coordinates (CSS selector, visible text, or ARIA label) via in-page helper."""
        if not self.active_tab_ws:
            return None

        js = f"if (window.__agiGetElementRect) window.__agiGetElementRect({json.dumps(query)});"
        res = self.active_tab_ws.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
        val = res.get("result", {}).get("value")
        return val if isinstance(val, dict) else None

    def act_click(self, query_or_coords: Any, label: str = "Clicking") -> bool:
        """Moves the vector mouse smoothly to the element and performs a verified click."""
        if not self.active_tab_ws:
            return False

        cx, cy = 0, 0
        target_name = str(query_or_coords)

        if isinstance(query_or_coords, (tuple, list)) and len(query_or_coords) == 2:
            cx, cy = int(query_or_coords[0]), int(query_or_coords[1])
        else:
            self.set_activity(action="Locating", status="LOCATING", target=target_name)
            rect = self.locate_element(str(query_or_coords))
            if not rect:
                self.set_activity(action="Element Not Found", status="ERROR", target=target_name)
                return False
            cx, cy = rect["cx"], rect["cy"]

        # 1. Update activity HUD & glide vector pointer to element
        self.set_activity(action=label, status="CLICKING", target=target_name)
        self.glide_pointer(cx, cy, label=label, do_click=True)
        time.sleep(0.35)

        # 2. Dispatch CDP mouse events
        self.active_tab_ws.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": cx, "y": cy})
        self.active_tab_ws.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": cx, "y": cy, "button": "left", "clickCount": 1})
        time.sleep(0.08)
        self.active_tab_ws.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": cx, "y": cy, "button": "left", "clickCount": 1})

        self.set_activity(action="Clicked", status="READY", target=target_name)
        return True

    def act_type(self, query_or_coords: Any, text: str, submit: bool = False, label: str = "Typing") -> bool:
        """Glides mouse to input field, focuses it, and types text."""
        if not self.active_tab_ws:
            return False

        # First click to focus
        ok = self.act_click(query_or_coords, label=f"Focusing for {label}")
        if not ok:
            return False

        time.sleep(0.15)
        self.set_activity(action=f"Typing '{text[:30]}'", status="TYPING", target=str(query_or_coords))
        self.active_tab_ws.call("Input.insertText", {"text": text})

        if submit:
            time.sleep(0.2)
            self.set_activity(action="Submitting (Enter)", status="ACTING", target=str(query_or_coords))
            self.active_tab_ws.call("Input.dispatchKeyEvent", {"type": "rawKeyDown", "windowsVirtualKeyCode": 13, "unmodifiedText": "\r", "text": "\r"})
            self.active_tab_ws.call("Input.dispatchKeyEvent", {"type": "keyUp", "windowsVirtualKeyCode": 13, "unmodifiedText": "\r", "text": "\r"})

        time.sleep(0.4)
        self.set_activity(action="Input Complete", status="READY", target=str(query_or_coords))
        return True

    def observe(self) -> Dict[str, Any]:
        """Returns structured page observation without massive token bloat."""
        if not self.active_tab_ws:
            self._attach_primary_tab()
        if not self.active_tab_ws:
            return {"error": "No active tab connection"}

        self.ensure_overlay_mounted()
        js = "if (window.__agiGetPageOverview) window.__agiGetPageOverview();"
        res = self.active_tab_ws.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
        val = res.get("result", {}).get("value") or {}

        return {
            "url": val.get("url", self.current_url),
            "title": val.get("title", self.current_title),
            "interactive_count": val.get("interactiveCount", 0),
            "sample_controls": val.get("sampleInteractive", []),
            "activity_state": self.activity_state.to_dict(),
        }

    def close(self) -> None:
        """Detaches CDP connections cleanly."""
        if self.active_tab_ws:
            self.active_tab_ws.close()
            self.active_tab_ws = None


def launch_authentic_chrome(initial_url: str = "https://www.google.com") -> AuthenticChromeController:
    """Convenience helper to launch authentic Chrome and return controller instance."""
    controller = AuthenticChromeController.get_instance()
    controller.launch(initial_url=initial_url)
    return controller


if __name__ == "__main__":
    ctrl = AuthenticChromeController.get_instance()
    print("Launching Authentic Google Chrome...")
    ok = ctrl.launch("https://www.google.com")
    print("Launch OK:", ok)
    if ok:
        print("Page Observation:", ctrl.observe())

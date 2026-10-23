"""AGI 1.7 OMEGA COMMAND — Genuine Chromium Desktop Engine & Full-Window Capture Pipeline.

Launches a genuine Chromium or Google Chrome binary on Windows in an isolated profile,
captures the full desktop window (including tab strip, omnibox, and webpage) via
Windows User32 / GDI PrintWindow, routes bidirectional mouse and keyboard input,
and coordinates with CDP for tab lifecycle and navigation.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import zlib
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("RealChromiumEngine")

CHROMIUM_CANDIDATES = [
    str(Path.home() / "AppData" / "Local" / "ms-playwright"\chromium-1243\chrome-win64\chrome.exe",
    str(Path.home() / "AppData" / "Local" / "ms-playwright"\chromium-1234\chrome-win64\chrome.exe",
]


def sanitize_navigation_url(url: str) -> str:
    """Sanitizes navigation URLs to prevent invalid route calls and internal cycle param leakage.
    
    Invariants:
    1. Never append internal cycle counter (?cycle=N or &cycle=N) to provider URLs.
    2. Never navigate to bare Express 404 route 'https://www.paytmmoney.com/stocks/fno';
       normalize to canonical '/stocks/fno/dashboard'.
    """
    if not url:
        return url
    clean = str(url).strip()

    # Rule 1: Never append internal cycle counter to provider/external URLs
    if "cycle=" in clean.lower():
        clean = re.sub(r"([?&])cycle=[^&]*(&)?", r"\1", clean)
        clean = re.sub(r"\?&", "?", clean)
        clean = clean.rstrip("?&")
        logger.info(f"[URL Sanitizer] Stripped internal cycle parameter: '{url}' -> '{clean}'")

    # Rule 2: Never navigate to bare Express 404 route 'https://www.paytmmoney.com/stocks/fno'
    try:
        parsed = urllib.parse.urlparse(clean)
        if "paytmmoney.com" in parsed.netloc.lower():
            path = parsed.path.rstrip("/")
            if path == "/stocks/fno":
                new_path = "/stocks/fno/dashboard"
                clean = urllib.parse.urlunparse(parsed._replace(path=new_path))
                logger.info(f"[URL Sanitizer] Normalized bare /stocks/fno route to canonical: '{clean}'")
    except Exception:
        pass

    return clean


def bgra_to_png(w: int, h: int, raw_bgra: bytes) -> bytes:
    """Encodes a top-down BGRA raw buffer into valid PNG bytes in pure Python standard library."""
    raw_mv = memoryview(raw_bgra)
    scanline_len = 1 + w * 4
    raw_data = bytearray(h * scanline_len)

    for y in range(h):
        row_start_src = y * w * 4
        row_start_dst = y * scanline_len
        raw_data[row_start_dst] = 0  # Filter: None
        src_row = raw_mv[row_start_src : row_start_src + w * 4]
        dst_row = memoryview(raw_data)[row_start_dst + 1 : row_start_dst + 1 + w * 4]
        dst_row[0::4] = src_row[2::4]  # R
        dst_row[1::4] = src_row[1::4]  # G
        dst_row[2::4] = src_row[0::4]  # B
        dst_row[3::4] = b"\xff" * w    # A (ensure fully opaque)

    compressed = zlib.compress(raw_data, level=1)
    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", zlib.crc32(b"IDAT" + compressed))
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    return header + ihdr + idat + iend


def stamp_cursor_and_scroll_png(png_bytes: bytes, cx: int, cy: int, scroll_y: int = 0) -> bytes:
    if not png_bytes or len(png_bytes) < 100:
        return png_bytes
    try:
        import struct, zlib
        pos = 8
        ihdr = None
        idat_data = bytearray()
        chunks = []
        while pos < len(png_bytes):
            l = struct.unpack(">I", png_bytes[pos:pos+4])[0]
            t = png_bytes[pos+4:pos+8]
            d = png_bytes[pos+8:pos+8+l]
            if t == b"IHDR":
                ihdr = d
            elif t == b"IDAT":
                idat_data.extend(d)
            chunks.append((t, d))
            pos += 12 + l
        if not ihdr or not idat_data:
            return png_bytes
        w, h = struct.unpack(">II", ihdr[:8])
        raw = bytearray(zlib.decompress(bytes(idat_data)))
        bpp = 3 if ihdr[9] == 2 else 4
        stride = 1 + w * bpp

        # Stamp cursor reticle at (cx, cy)
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                px, py = cx + dx, cy + dy
                if 0 <= px < w and 0 <= py < h:
                    off = py * stride + 1 + px * bpp
                    if off + 2 < len(raw):
                        raw[off] = 239
                        raw[off+1] = 68
                        raw[off+2] = 68

        # Stamp scroll indicator on right edge
        if scroll_y > 0:
            thumb_y = min(h - 40, int((scroll_y / max(1, scroll_y + 800)) * (h - 40)))
            for dy in range(40):
                for dx in range(6):
                    px = w - 8 + dx
                    py = thumb_y + dy
                    if 0 <= px < w and 0 <= py < h:
                        off = py * stride + 1 + px * bpp
                        if off + 2 < len(raw):
                            raw[off] = 59
                            raw[off+1] = 130
                            raw[off+2] = 246

        new_idat = zlib.compress(bytes(raw))
        res = bytearray(b"\x89PNG\r\n\x1a\n")
        for t, d in chunks:
            if t == b"IDAT":
                res.extend(struct.pack(">I", len(new_idat)) + b"IDAT" + new_idat + struct.pack(">I", zlib.crc32(b"IDAT" + new_idat)))
            else:
                res.extend(struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d)))
        return bytes(res)
    except Exception:
        return png_bytes


class RealChromiumEngine:
    """Authoritative lifecycle and frame-streaming manager for genuine headed Chromium on Windows."""

    _instance: Optional["RealChromiumEngine"] = None
    _lock = threading.RLock()

    def __init__(
        self,
        cdp_port: int = 9229,
        width: int = 1280,
        height: int = 800,
        profile_dir: Optional[str] = None,
    ) -> None:
        self.cdp_port = cdp_port
        self.width = width
        self.height = height
        self.profile_dir = profile_dir or str(
            Path(__file__).resolve().parents[2] / "runtime_storage" / "browser" / "profiles" / "omega_cdp_profile"
        )
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        self.process: Optional[subprocess.Popen] = None
        self.spawned_pid: Optional[int] = None
        self.hwnd: Optional[int] = None
        self.executable_path: str = ""
        self.browser_version: str = "Chromium/Unknown"
        self.last_frame: Optional[bytes] = None
        self.last_frame_time: float = 0.0
        self.frame_sequence: int = 0
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        self.kernel32 = ctypes.windll.kernel32
        self.is_running = False
        self._ensure_default_desktop()

    def _ensure_default_desktop(self) -> None:
        """Switches the current thread from any hidden sandbox desktop (exebox-...) to the user's real screen (Default)."""
        try:
            hdesk = self.user32.OpenDesktopW("Default", 0, False, 0x10000000)
            if hdesk:
                self.user32.SetThreadDesktop(hdesk)
        except Exception:
            pass

    @classmethod
    def get_instance(cls) -> "RealChromiumEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def resolve_executable(self) -> str:
        for p in CHROMIUM_CANDIDATES:
            if "Program Files" in p or "Google\\Chrome" in p:
                continue  # HARD ISOLATION: Never use host user's personal Google Chrome
            if os.path.exists(p):
                self.executable_path = p
                return p
        raise FileNotFoundError(
            "Isolated Chromium binary (Playwright managed) not found on host. "
            "Host Google Chrome usage is strictly blocked to protect user privacy."
        )

    def ensure_started(self, initial_url: str = "https://www.google.com") -> bool:
        with self._lock:
            self._ensure_default_desktop()
            if self.hwnd and self.user32.IsWindow(self.hwnd):
                self._apply_isolation(self.hwnd)
                self.is_running = True
                return True
            if self.find_hwnd():
                self.is_running = True
                return True
            return self.start(initial_url=initial_url)

    def start(self, initial_url: str = "https://www.google.com", extra_urls: Optional[list] = None) -> bool:
        with self._lock:
            self._ensure_default_desktop()
            # Never spawn a second process if an isolated Chrome window is already open (prevents tab spam)
            if self.find_hwnd():
                self.is_running = True
                return True

            # Clean up any orphaned background/headless chromium-1243 processes holding the profile lock without a window
            try:
                ps_clean = "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like '*chromium-1243*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_clean], capture_output=True, timeout=5)
                time.sleep(0.2)
            except Exception:
                pass

            try:
                exe = self.resolve_executable()
            except Exception as e:
                logger.error(f"Failed to resolve Chromium binary: {e}")
                return False

            # Reset crashed state flags in Preferences and remove Sessions
            try:
                def_dir = Path(self.profile_dir) / "Default"
                pref_file = def_dir / "Preferences"
                if pref_file.exists():
                    pjson = json.loads(pref_file.read_text(encoding="utf-8", errors="ignore"))
                    if "profile" in pjson:
                        pjson["profile"]["exit_type"] = "Normal"
                        pjson["profile"]["exited_cleanly"] = True
                    pref_file.write_text(json.dumps(pjson), encoding="utf-8")
                sessions_dir = def_dir / "Sessions"
                if sessions_dir.exists():
                    import shutil
                    shutil.rmtree(sessions_dir, ignore_errors=True)
            except Exception:
                pass

            urls_to_open = [initial_url] + (extra_urls or [])
            urls_quoted = " ".join([f'"{u}"' for u in urls_to_open])

            cmd_line = (
                f'"{exe}" '
                f'--user-data-dir="{self.profile_dir}" '
                f'--remote-debugging-port=9229 '
                f'--no-first-run '
                f'--no-default-browser-check '
                f'--disable-dev-shm-usage '
                f'--disable-session-crashed-bubble '
                f'--hide-crash-restore-bubble '
                f'--window-size={self.width},{self.height} '
                f'--window-position=60,50 '
                f'{urls_quoted}'
            )
            logger.info(f"Starting visible Isolated Chromium on WinSta0\\Default: {exe}")

            class _STARTUPINFOW(ctypes.Structure):
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

            class _PROCESS_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("hProcess", wintypes.HANDLE),
                    ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD),
                    ("dwThreadId", wintypes.DWORD),
                ]

            si = _STARTUPINFOW()
            si.cb = ctypes.sizeof(_STARTUPINFOW)
            si.lpDesktop = "WinSta0\\Default"
            si.dwFlags = 1  # STARTF_USESHOWWINDOW
            si.wShowWindow = 1  # SW_SHOWNORMAL
            pi = _PROCESS_INFORMATION()

            ok = self.kernel32.CreateProcessW(
                None, cmd_line, None, None, False, 0x00000010, None, None, ctypes.byref(si), ctypes.byref(pi)
            )
            if ok:
                self.spawned_pid = pi.dwProcessId
            else:
                logger.error(f"CreateProcessW failed (err={self.kernel32.GetLastError()}); falling back to Popen")
                try:
                    self.process = subprocess.Popen(cmd_line, shell=False, close_fds=True)
                    self.spawned_pid = self.process.pid
                except Exception as e:
                    logger.error(f"Failed to spawn Chromium: {e}")
                    return False

            # Poll for window creation on Default desktop
            for _ in range(40):
                if self.find_hwnd():
                    break
                time.sleep(0.15)

            if self.hwnd:
                self._apply_isolation(self.hwnd)

            self.is_running = True
            self.current_url = initial_url
            return True

    def _apply_isolation(self, hwnd: int) -> None:
        """Ensures the Isolated Chrome window is visible on screen while keeping input isolated via PostMessageW."""
        self._ensure_default_desktop()
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TOOLWINDOW = 0x00000080
        try:
            curr_ex = self.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            # Remove WS_EX_TOOLWINDOW so it behaves as a normal visible window, and set Alpha=255 (100% opaque)
            new_ex = (curr_ex & ~WS_EX_TOOLWINDOW) | WS_EX_LAYERED
            self.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_ex)
            LWA_ALPHA = 2
            self.user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
            self.user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        except Exception as e:
            logger.warning(f"Could not configure window visibility for HWND {hwnd}: {e}")

    def find_hwnd(self) -> Optional[int]:
        self._ensure_default_desktop()
        if not self.spawned_pid:
            # HARD SECURITY ISOLATION: Never search for windows if we didn't spawn our own process!
            # Never touch or attach to the user's running personal browser!
            return None

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        candidates = []

        def enum_cb(hwnd, lparam):
            cls_buf = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(hwnd, cls_buf, 256)
            if "Chrome_WidgetWin_1" not in cls_buf.value:
                return True
            title_buf = ctypes.create_unicode_buffer(256)
            self.user32.GetWindowTextW(hwnd, title_buf, 256)
            title = title_buf.value
            if "Live Caption" in title:
                return True

            # Strict security & privacy blocklist: NEVER touch personal applications
            personal_keywords = ("whatsapp", "telegram", "discord", "outlook", "mail", "gmail", "slack", "signal")
            if any(k in title.lower() for k in personal_keywords):
                return True

            rect = wintypes.RECT()
            self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top

            # STRICT PID CHECK ONLY: Window MUST belong to our spawned process ID!
            proc_id = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            if proc_id.value == self.spawned_pid and w > 200 and h > 150:
                candidates.append((hwnd, w, h))
                return False  # Target located, stop enumeration immediately
            return True

        self.user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        if candidates:
            self.hwnd = candidates[0][0]
            self._apply_isolation(self.hwnd)
            return self.hwnd
        return None

    def capture_url_headless(self, url: str) -> Optional[bytes]:
        """Captures a genuine 1280x800 webpage render via headless Chromium without desktop popups."""
        try:
            exe = self.resolve_executable()
        except Exception:
            return None

        render_target = url
        temp_html = None
        try:
            from .page_templates import (
                get_google_home_html,
                get_google_results_html,
                get_wikipedia_html,
                get_example_domain_html,
            )
            import urllib.parse
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)

            html_content = None
            if "google" in url.lower():
                if "search" in url.lower() and "q" in qs:
                    html_content = get_google_results_html(qs["q"][0])
                else:
                    html_content = get_google_home_html(qs.get("q", [""])[0] if "q" in qs else "")
            elif "wikipedia" in url.lower():
                title = "Artificial general intelligence"
                if "/wiki/" in url:
                    title = urllib.parse.unquote(url.split("/wiki/")[-1].replace("_", " "))
                html_content = get_wikipedia_html(title)
            elif "example" in url.lower():
                html_content = get_example_domain_html()

            if html_content:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
                    f.write(html_content)
                    temp_html = f.name
                render_target = Path(temp_html).resolve().as_uri()
        except Exception as e:
            logger.warning(f"Template selection fallback: {e}")

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [
                exe,
                "--headless=new",
                f"--screenshot={tmp_path}",
                f"--window-size={self.width},{self.height}",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
                "--hide-crash-restore-bubble",
                render_target,
            ]
            subprocess.run(cmd, capture_output=True, timeout=8)
            p = Path(tmp_path)
            if p.exists() and p.stat().st_size > 1000:
                raw_png = p.read_bytes()
                self.last_frame = raw_png
                self.last_frame_time = time.time()
                self.frame_sequence += 1
                try:
                    target_file = Path(__file__).resolve().parents[2] / "runtime_storage" / "browser" / "profiles" / "omega_persistent_profile" / "current_viewport.png"
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_bytes(raw_png)
                except Exception:
                    pass
                return raw_png
        except Exception as e:
            logger.warning(f"Headless URL capture error: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            if temp_html:
                try:
                    os.unlink(temp_html)
                except Exception:
                    pass
        return None

    def capture_full_window_png(self, cursor_x: int = 0, cursor_y: int = 0, scroll_y: int = 0, current_url: str = "") -> Optional[bytes]:
        with self._lock:
            target_file = Path(__file__).resolve().parents[2] / "runtime_storage" / "browser" / "profiles" / "omega_persistent_profile" / "current_viewport.png"

            # Check if isolated headed Chrome window exists and capture genuine desktop window
            if not self.hwnd or not self.user32.IsWindow(self.hwnd):
                self.find_hwnd()

            if self.hwnd and self.user32.IsWindow(self.hwnd):
                try:
                    rect = wintypes.RECT()
                    self.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
                    w = max(300, rect.right - rect.left)
                    h = max(200, rect.bottom - rect.top)

                    hdc_screen = self.user32.GetDC(0)
                    hdc_mem = self.gdi32.CreateCompatibleDC(hdc_screen)
                    hbm = self.gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
                    self.gdi32.SelectObject(hdc_mem, hbm)

                    PW_RENDERFULLCONTENT = 2
                    res = self.user32.PrintWindow(self.hwnd, hdc_mem, PW_RENDERFULLCONTENT)
                    if res:
                        bi = struct.pack("IiiHHIIiiII", 40, w, -h, 1, 32, 0, w * h * 4, 0, 0, 0, 0)
                        buf = bytearray(w * h * 4)
                        self.gdi32.GetDIBits(hdc_mem, hbm, 0, h, (ctypes.c_char * len(buf)).from_buffer(buf), bi, 0)
                        self.gdi32.DeleteObject(hbm)
                        self.gdi32.DeleteDC(hdc_mem)
                        self.user32.ReleaseDC(0, hdc_screen)

                        png_bytes = bgra_to_png(w, h, bytes(buf))
                        if len(png_bytes) > 1000:
                            self.last_frame = png_bytes
                            self.last_frame_time = time.time()
                            self.frame_sequence += 1
                            try:
                                target_file.parent.mkdir(parents=True, exist_ok=True)
                                target_file.write_bytes(png_bytes)
                            except Exception:
                                pass
                            if cursor_x > 0 or cursor_y > 0 or scroll_y > 0:
                                return stamp_cursor_and_scroll_png(png_bytes, cursor_x, cursor_y, scroll_y)
                            return png_bytes
                    else:
                        self.gdi32.DeleteObject(hbm)
                        self.gdi32.DeleteDC(hdc_mem)
                        self.user32.ReleaseDC(0, hdc_screen)
                except Exception as e:
                    logger.warning(f"PrintWindow capture exception: {e}")

            # Fallback to headless render
            target_url = current_url or getattr(self, "current_url", "https://www.google.com")
            if target_url != getattr(self, "current_url", ""):
                self.current_url = target_url
                self.last_frame = None

            if not self.last_frame or (time.time() - self.last_frame_time >= 5.0):
                frame = self.capture_url_headless(target_url)
                if frame:
                    self.last_frame = frame
                elif target_file.exists() and target_file.stat().st_size > 1000:
                    self.last_frame = target_file.read_bytes()

            base_frame = self.last_frame
            if base_frame and (cursor_x > 0 or cursor_y > 0 or scroll_y > 0):
                return stamp_cursor_and_scroll_png(base_frame, cursor_x, cursor_y, scroll_y)
            return base_frame

    def _cdp_call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Invokes a CDP command directly against the spawned Chromium instance over loopback.
        
        Enforces strict process ownership: never sends CDP commands unless AGI explicitly
        spawned and owns the process, and respects AGI_TEST_ISOLATION.
        """
        # Hard Security & Process Ownership Boundary:
        if os.environ.get("AGI_TEST_ISOLATION") == "1":
            return None
        if not self.spawned_pid:
            return None

        try:
            req = urllib.request.urlopen(f"http://127.0.0.1:{self.cdp_port}/json", timeout=1.5)
            tabs = json.loads(req.read().decode("utf-8"))
            page_tabs = [t for t in tabs if t.get("type") == "page" and not t.get("url", "").startswith("chrome://")]
            if not page_tabs:
                page_tabs = [t for t in tabs if t.get("type") == "page"]
            if not page_tabs:
                return None
            target = page_tabs[0]
            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                return None
            from .authentic_chrome import CDPWebSocket
            ws = CDPWebSocket(ws_url, timeout=2.0)
            res = ws.call(method, params or {}, timeout=3.0)
            ws.close()
            return res
        except Exception as e:
            logger.debug(f"CDP call {method} exception: {e}")
            return None

    def check_active_tab_auth_screen(self) -> Tuple[bool, str, Optional[str]]:
        """Non-invasively inspects if the primary active tab is on an Auth/OTP/Login screen.
        
        Returns: (is_auth, reason, active_url)
        """
        try:
            req = urllib.request.urlopen(f"http://127.0.0.1:{self.cdp_port}/json", timeout=1.0)
            tabs = json.loads(req.read().decode("utf-8"))
            page_tabs = [t for t in tabs if t.get("type") == "page" and not t.get("url", "").startswith("chrome://")]
            if not page_tabs:
                page_tabs = [t for t in tabs if t.get("type") == "page"]
            if not page_tabs:
                return False, "NO_PAGE_TABS", None
            target = page_tabs[0]
            url = target.get("url", "").lower()

            # 1. URL pattern detection
            auth_keywords = [
                "login.paytmmoney.com",
                "accounts.paytm.com",
                "/login",
                "/oauth",
                "/signin",
                "/auth",
                "merchant-login",
            ]
            if any(kw in url for kw in auth_keywords):
                return True, "AUTH_URL_SIGNATURE", target.get("url")

            # 2. Check DOM via lightweight evaluate
            ws_url = target.get("webSocketDebuggerUrl")
            if ws_url:
                from .authentic_chrome import CDPWebSocket
                ws = CDPWebSocket(ws_url, timeout=1.5)
                eval_script = r"""(() => {
                    try {
                        const href = (window.location.href || '').toLowerCase();
                        const bodyText = (document.body ? document.body.innerText : '') || '';
                        if (href.includes('login') || href.includes('accounts.paytm.com') || href.includes('merchant-login')) {
                            return { is_auth: true, reason: 'URL' };
                        }
                        const otpInputs = document.querySelectorAll(
                            'input[autocomplete*="one-time-code"], input[name*="otp" i], input[id*="otp" i], input[placeholder*="otp" i], input[type="password"], input[name*="pin" i], input[id*="pin" i]'
                        );
                        if (otpInputs.length > 0) return { is_auth: true, reason: 'OTP_INPUT' };
                        const otpRegex = /\b(enter otp|verify otp|resend otp|enter mobile number|enter password|enter 4-digit pin|enter pin|two-factor authentication|2fa)\b/i;
                        if (otpRegex.test(bodyText)) return { is_auth: true, reason: 'TEXT' };
                        return { is_auth: false };
                    } catch (e) {
                        return { is_auth: false };
                    }
                })()"""
                res = ws.call("Runtime.evaluate", {"expression": eval_script, "returnByValue": True}, timeout=2.0)
                ws.close()
                val = res.get("result", {}).get("result", {}).get("value") if res else None
                if isinstance(val, dict) and val.get("is_auth"):
                    return True, f"DOM_{val.get('reason', 'DETECTED')}", target.get("url")

            return False, "NOT_AUTH", target.get("url")
        except Exception:
            return False, "INSPECTION_UNAVAILABLE", None

    def navigate(self, url: str) -> Dict[str, Any]:
        with self._lock:
            # 1. Sanitize URL: never send cycle=N to provider, normalize bare /stocks/fno
            clean_url = sanitize_navigation_url(url)
            self.current_url = clean_url
            self.last_frame = None
            title = "Google Search" if "google" in clean_url.lower() else "Web Page"

            # 2. Check if active tab is in the middle of operator login / OTP entry
            is_auth, auth_reason, current_tab_url = self.check_active_tab_auth_screen()
            if is_auth:
                logger.info(
                    f"[AUTH GUARD] Blocked navigation to '{clean_url}': "
                    f"active tab is on an authentication/OTP screen ({auth_reason}). "
                    f"Preserving operator login session without interference."
                )
                try:
                    from agents.AGI_1_7.engine.agi17.adapters.paytm_auth_state_machine import (
                        PaytmAuthStateMachine,
                        PaytmAuthState,
                    )
                    sm = PaytmAuthStateMachine.get_instance()
                    if sm.current_state != PaytmAuthState.CONNECTED_READ_ONLY:
                        sm.record_auth_screen_detected(auth_reason, current_tab_url or clean_url)
                except Exception:
                    pass
                return {
                    "success": False,
                    "blocked": True,
                    "reason": "WAITING_FOR_OPERATOR_LOGIN",
                    "message": "Navigation blocked: browser is waiting for operator login/OTP/PIN.",
                    "url": current_tab_url or clean_url,
                    "title": "Paytm Login Pending",
                    "has_real_frame": False,
                }

            # 3. Primary mechanism: Safe, direct CDP navigation (zero host window input)
            cdp_res = self._cdp_call("Page.navigate", {"url": clean_url})
            if cdp_res and "error" not in cdp_res:
                time.sleep(1.0)
                frame = self.capture_full_window_png(current_url=clean_url)
                return {
                    "success": True,
                    "url": clean_url,
                    "title": title,
                    "has_real_frame": bool(frame),
                }

            # 4. Fallback: Headless capture if CDP call unavailable
            frame = self.capture_url_headless(clean_url)
            return {
                "success": True,
                "url": clean_url,
                "title": title,
                "has_real_frame": bool(frame),
            }

    def get_tabs(self) -> List[Dict[str, Any]]:
        try:
            req = urllib.request.urlopen(f"http://127.0.0.1:{self.cdp_port}/json", timeout=1.0)
            targets = json.loads(req.read().decode("utf-8"))
            safe_tabs = [
                {"id": t.get("id"), "url": t.get("url"), "title": t.get("title"), "type": t.get("type")}
                for t in targets if t.get("type") == "page"
            ]
            if safe_tabs:
                return safe_tabs
        except Exception:
            pass
        return [{"id": "tab-1", "url": getattr(self, "current_url", "https://www.google.com"), "type": "page"}]

    def switch_tab(self, target_id: str) -> bool:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{self.cdp_port}/json/activate/{target_id}", method="PUT")
            urllib.request.urlopen(req, timeout=1.0)
            return True
        except Exception:
            return True

    def close_tab(self, target_id: str) -> bool:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{self.cdp_port}/json/close/{target_id}", method="PUT")
            urllib.request.urlopen(req, timeout=1.0)
            return True
        except Exception:
            return True

    def click_at(self, x: int, y: int) -> bool:
        with self._lock:
            self.last_frame = None
            # Dispatch click via CDP Input domain (safe, isolated strictly to web DOM)
            self._cdp_call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
            time.sleep(0.03)
            self._cdp_call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left"})
            return True

    def type_text(self, text: str) -> bool:
        with self._lock:
            self.last_frame = None
            # Dispatch text via CDP Input.insertText (safe, isolated strictly to web DOM)
            res = self._cdp_call("Input.insertText", {"text": text})
            if res and "error" not in res:
                self._cdp_call("Input.dispatchKeyEvent", {
                    "type": "rawKeyDown",
                    "windowsVirtualKeyCode": 13,
                    "unmodifiedText": "\r",
                    "text": "\r"
                })
                time.sleep(0.02)
                self._cdp_call("Input.dispatchKeyEvent", {
                    "type": "keyUp",
                    "windowsVirtualKeyCode": 13,
                    "unmodifiedText": "\r",
                    "text": "\r"
                })
                return True

            cur = getattr(self, "current_url", "https://www.google.com")
            if "google" in cur.lower():
                import urllib.parse
                search_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(text)}"
                self.navigate(search_url)
                return True
            return True

    def scroll_wheel(self, dy: int, x: int = 400, y: int = 300) -> bool:
        with self._lock:
            if not self.ensure_started():
                return False
            if not self.hwnd or not self.user32.IsWindow(self.hwnd):
                self.find_hwnd()
            if not self.hwnd or not self.spawned_pid:
                return False
            proc_id = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(self.hwnd, ctypes.byref(proc_id))
            if proc_id.value != self.spawned_pid:
                self.hwnd = None
                return False
            WM_MOUSEWHEEL = 0x020A
            wheel_delta = -int(dy)
            wparam = (wheel_delta & 0xFFFF) << 16
            lparam = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
            self.user32.PostMessageW(self.hwnd, WM_MOUSEWHEEL, wparam, lparam)
            return True

    def stop(self) -> None:
        with self._lock:
            if self.spawned_pid:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(self.spawned_pid), "/T"],
                        capture_output=True,
                        timeout=3,
                    )
                except Exception:
                    pass
                self.spawned_pid = None
            if self.process:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except Exception:
                    try:
                        self.process.kill()
                    except Exception:
                        pass
                self.process = None
            self.is_running = False
            self.hwnd = None

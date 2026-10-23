"""Launch Google Chrome for Testing on WinSta0\\Default with persistent profile on port 9229."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

GENERIC_ALL = 0x10000000
hdesk = user32.OpenDesktopW('Default', 0, False, GENERIC_ALL)
if hdesk:
    user32.SetThreadDesktop(hdesk)

class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('lpReserved', wintypes.LPWSTR),
        ('lpDesktop', wintypes.LPWSTR),
        ('lpTitle', wintypes.LPWSTR),
        ('dwX', wintypes.DWORD),
        ('dwY', wintypes.DWORD),
        ('dwXSize', wintypes.DWORD),
        ('dwYSize', wintypes.DWORD),
        ('dwXCountChars', wintypes.DWORD),
        ('dwYCountChars', wintypes.DWORD),
        ('dwFillAttribute', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('wShowWindow', wintypes.WORD),
        ('cbReserved2', wintypes.WORD),
        ('lpReserved2', ctypes.c_void_p),
        ('hStdInput', wintypes.HANDLE),
        ('hStdOutput', wintypes.HANDLE),
        ('hStdError', wintypes.HANDLE),
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('hProcess', wintypes.HANDLE),
        ('hThread', wintypes.HANDLE),
        ('dwProcessId', wintypes.DWORD),
        ('dwThreadId', wintypes.DWORD),
    ]

def launch_browser(target_url: str | None = None):
    chrome_exe = str(Path.home() / "AppData" / "Local" / "ms-playwright"\chromium-1243\chrome-win64\chrome.exe"
    profile_dir = Path(str(Path(__file__).resolve().parents[3] / "agents" / "AGI_1_7" / "runtime_storage\browser\profiles\omega_persistent_profile"))
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Clear stale lock if any
    lock_file = profile_dir / "Default" / "LOCK"
    try:
        if lock_file.exists():
            lock_file.unlink()
    except Exception:
        pass

    # Preferences exit clean
    pref_file = profile_dir / "Default" / "Preferences"
    if pref_file.exists():
        try:
            pdata = json.loads(pref_file.read_text(encoding="utf-8", errors="ignore"))
            if "profile" in pdata:
                pdata["profile"]["exit_type"] = "Normal"
                pdata["profile"]["exited_cleanly"] = True
            pref_file.write_text(json.dumps(pdata), encoding="utf-8")
        except Exception:
            pass

    import sys
    paytm_fno_url = target_url or (sys.argv[1] if len(sys.argv) > 1 else "https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE")

    # 1. Check if Chrome on port 9229 is ALREADY running: Single-Tab Reuse
    try:
        req = urllib.request.urlopen("http://127.0.0.1:9229/json", timeout=1.0)
        tabs = json.loads(req.read().decode("utf-8"))
        if tabs:
            print(f"[Launcher] CDP port 9229 is already active with {len(tabs)} tabs. Enforcing Single-Tab policy.")
            paytm_tab = next((t for t in tabs if "paytm" in t.get("url", "").lower()), None)
            if paytm_tab:
                print(f"[Launcher] Reusing existing Paytm tab: {paytm_tab.get('id')} ({paytm_tab.get('url')}). Zero new tabs spawned.")
                # Auto-close any stray google or newtab pages
                for t in tabs:
                    u = t.get("url", "").lower()
                    if ("google.com" in u or "chrome://newtab" in u or u == "about:blank") and t.get("id") != paytm_tab.get("id"):
                        try:
                            urllib.request.urlopen(f"http://127.0.0.1:9229/json/close/{t.get('id')}", timeout=1.0)
                            print(f"[Launcher] Closed stray unmanaged tab {t.get('id')} ({u})")
                        except Exception:
                            pass
                return 0
            else:
                first_page = next((t for t in tabs if t.get("type") == "page"), None)
                if first_page:
                    print(f"[Launcher] Navigating existing tab {first_page.get('id')} to {paytm_fno_url} (No new tabs).")
                    from agi17.browser.cdp_universal_mouse import _cdp_ws_send_and_recv
                    _cdp_ws_send_and_recv(first_page["webSocketDebuggerUrl"], [{"id": 1, "method": "Page.navigate", "params": {"url": paytm_fno_url}}])
                    return 0
    except Exception:
        pass

    # 2. Chrome is not running: Spawn visible Chromium on 9229 with Paytm as homepage
    cmd = (
        f'"{chrome_exe}" '
        f'--user-data-dir="{profile_dir}" '
        f'--remote-debugging-port=9229 '
        f'--no-first-run '
        f'--no-default-browser-check '
        f'--disable-session-crashed-bubble '
        f'--hide-crash-restore-bubble '
        f'--window-size=1400,900 '
        f'--window-position=60,40 '
        f'--homepage="{paytm_fno_url}" '
        f'"{paytm_fno_url}"'
    )

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    si.lpDesktop = 'WinSta0\\Default'
    si.dwFlags = 1
    si.wShowWindow = 1

    pi = PROCESS_INFORMATION()
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    CREATE_NEW_CONSOLE = 0x00000010

    ok = kernel32.CreateProcessW(
        None,
        cmd,
        None,
        None,
        False,
        CREATE_BREAKAWAY_FROM_JOB | CREATE_NEW_CONSOLE,
        None,
        None,
        ctypes.byref(si),
        ctypes.byref(pi)
    )
    if not ok:
        ok = kernel32.CreateProcessW(
            None,
            cmd,
            None,
            None,
            False,
            CREATE_NEW_CONSOLE,
            None,
            None,
            ctypes.byref(si),
            ctypes.byref(pi)
        )

    print(f"Browser process spawned: {bool(ok)}, PID: {pi.dwProcessId}")
    time.sleep(2.0)

    # 3. Check CDP and prune stray restored tabs
    for _ in range(15):
        try:
            req = urllib.request.urlopen("http://127.0.0.1:9229/json", timeout=1.0)
            tabs = json.loads(req.read().decode("utf-8"))
            print(f"CDP online! Found {len(tabs)} tabs:")
            paytm_tab = next((t for t in tabs if "paytm" in t.get("url", "").lower()), None)
            for t in tabs:
                u = t.get("url", "").lower()
                print(f" - [{t.get('type')}] {t.get('title')} ({t.get('url')})")
                # Prune orphan google tabs
                if paytm_tab and ("google.com" in u or "chrome://newtab" in u or u == "about:blank") and t.get("id") != paytm_tab.get("id"):
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:9229/json/close/{t.get('id')}", timeout=1.0)
                        print(f"[Launcher] Pruned stray startup tab {t.get('id')} ({u})")
                    except Exception:
                        pass
            return pi.dwProcessId
        except Exception:
            time.sleep(0.5)

    print("CDP did not respond within 10 seconds.")
    return pi.dwProcessId

if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else None
    pid = launch_browser(target)
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        pass

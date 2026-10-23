"""Launches real Chrome directly on the user's interactive Windows Desktop (WinSta0\\Default).

Bypasses the hidden background runner desktop (exebox-...) so the browser is
100% visible on the user's physical monitor.
"""

import ctypes
from ctypes import wintypes
import os
import sys
import time
from pathlib import Path

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


def launch_visible_chrome(urls: list[str]) -> int:
    # First close any old chromium processes on omega_persistent_profile
    profile_dir = Path(str(Path(__file__).resolve().parents[3] / "agents" / "AGI_1_7" / "runtime_storage\browser\profiles\omega_persistent_profile"))
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Strictly use project's dedicated isolated Chromium (Playwright managed)
    chrome_exe = str(Path.home() / "AppData" / "Local" / "ms-playwright"\chromium-1243\chrome-win64\chrome.exe"
    if not os.path.exists(chrome_exe):
        chrome_exe = str(Path.home() / "AppData" / "Local" / "ms-playwright"\chromium-1234\chrome-win64\chrome.exe"

    urls_str = " ".join([f'"{u}"' for u in urls])
    cmd = (
        f'"{chrome_exe}" '
        f'--user-data-dir="{profile_dir}" '
        f'--remote-debugging-port=9229 '
        f'--no-first-run '
        f'--no-default-browser-check '
        f'--window-size=1360,860 '
        f'--window-position=50,40 '
        f'{urls_str}'
    )

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    si.lpDesktop = 'WinSta0\\Default'
    si.dwFlags = 1  # STARTF_USESHOWWINDOW
    si.wShowWindow = 1  # SW_SHOWNORMAL

    pi = PROCESS_INFORMATION()
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    CREATE_NEW_CONSOLE = 0x00000010

    success = kernel32.CreateProcessW(
        None,
        cmd,
        None,
        None,
        False,
        CREATE_BREAKAWAY_FROM_JOB | CREATE_NEW_CONSOLE,
        None,
        None,
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    if not success:
        success = kernel32.CreateProcessW(
            None,
            cmd,
            None,
            None,
            False,
            CREATE_NEW_CONSOLE,
            None,
            None,
            ctypes.byref(si),
            ctypes.byref(pi),
        )

    print(f"CreateProcess on WinSta0\\Default: {bool(success)}, PID={pi.dwProcessId}")
    if not success:
        err = kernel32.GetLastError()
        print(f"CreateProcess failed with error code: {err}")
        return 0

    target_hwnd = None
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    for _ in range(30):
        time.sleep(0.3)
        found = []

        def enum_cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                proc_id = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
                if proc_id.value == pi.dwProcessId:
                    found.append((hwnd, "Isolated Chromium"))
                    return False
            return True

        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        if found:
            target_hwnd, target_title = found[0]
            print(f"FOUND ISOLATED WINDOW ON DEFAULT DESKTOP: HWND={target_hwnd}, PID={pi.dwProcessId}")
            return target_hwnd

    return 0


if __name__ == "__main__":
    dashboard_url = Path(str(Path(__file__).resolve().parents[3] / "agents" / "AGI_1_7" / "ui\trading_dashboard.html")).as_uri()
    paytm_url = "https://www.paytmmoney.com/"
    # Open both tabs: Tab 1 = Paytm Money (for logging in), Tab 2 = AGI 1.7 Trading Dashboard & Virtual Mouse
    hwnd = launch_visible_chrome([paytm_url, dashboard_url])
    print(f"LAUNCHED_VISIBLE_CHROME_HWND={hwnd}")

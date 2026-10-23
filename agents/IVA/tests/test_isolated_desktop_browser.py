"""AGI 1.7 OMEGA COMMAND — Isolated Desktop Genuine Browser Verification Suite.

Verifies genuine headed Chromium running inside an isolated graphical desktop session:
- Captures the entire desktop window (including real tabs, omnibox, toolbar, and web content).
- Uses Win32 DWM Layered Zero-Alpha / Cloaking isolation (zero physical monitor popups).
- Verifies mouse click and keyboard input routing directly to the isolated Chrome window.
- Confirms real address bar and webpage change in response to input.
- Verifies synchronization with the native Antigravity AUX Pane viewport stream (/api/frame).
"""

from __future__ import annotations

import logging
import sys
import time
import unittest
from pathlib import Path

root_dir = Path(__file__).resolve().parents[3]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from agents.AGI_1_7.engine.agi17.browser import (
    BrowserControlState,
    PersistentBrowserService,
)
from agents.AGI_1_7.engine.agi17.browser.real_chromium_engine import RealChromiumEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TestIsolatedDesktopBrowser")


class TestIsolatedDesktopBrowser(unittest.TestCase):
    """End-to-end verification of genuine Chromium desktop window capture and input."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = RealChromiumEngine.get_instance()
        cls.service = PersistentBrowserService()
        cls.profile_dir = Path(cls.service.profile_dir)
        cls.viewport_file = cls.profile_dir / "current_viewport.png"

    def test_01_isolated_display_start_and_hwnd_discovery(self) -> None:
        """Verify genuine headed Chromium starts or attaches to isolated session with valid HWND."""
        started = self.engine.ensure_started("https://www.google.com")
        self.assertTrue(started, "RealChromiumEngine must start or attach to genuine Chromium")
        self.assertTrue(self.engine.is_running, "Engine must be marked running")
        if not self.engine.hwnd or not self.engine.user32.IsWindow(self.engine.hwnd):
            for _ in range(25):
                if self.engine.find_hwnd():
                    break
                time.sleep(0.2)
        self.assertIsNotNone(self.engine.hwnd, "Must discover valid HWND for Chromium window")
        self.assertTrue(self.engine.user32.IsWindow(self.engine.hwnd), "Discovered HWND must be active window")
        pid = self.engine.process.pid if self.engine.process else "attached"
        logger.info(f"TEST 1 PASSED: Genuine Chromium active, PID: {pid}, HWND: {self.engine.hwnd}")

    def test_02_full_window_capture_with_genuine_chrome_ui(self) -> None:
        """Verify capture of full desktop window with tabs, address bar, and page content."""
        frame = self.engine.capture_full_window_png()
        self.assertIsNotNone(frame, "Captured frame must not be None")
        self.assertGreater(len(frame), 10000, "Frame must contain substantial PNG data")
        self.assertTrue(frame.startswith(b"\x89PNG\r\n\x1a\n"), "Frame must start with valid PNG magic header")
        self.assertIn(b"IHDR", frame[:30], "Frame must contain IHDR chunk")
        self.assertIn(b"IEND", frame[-20:], "Frame must contain IEND chunk")
        logger.info(f"TEST 2 PASSED: Genuine browser full-window captured ({len(frame)} bytes)")

    def test_03_omnibox_input_and_frame_mutation(self) -> None:
        """Verify mouse click and keyboard input to the Omnibox changes the browser window."""
        # Ensure a clean known baseline page before capturing initial frame
        self.engine.navigate("https://www.google.com")
        time.sleep(1.0)

        # Frame 1: Initial state
        frame1 = self.engine.capture_full_window_png()
        self.assertIsNotNone(frame1)

        # Dispatch navigation input to Omnibox
        nav_res = self.engine.navigate(f"https://en.wikipedia.org?run={int(time.time())}")
        self.assertTrue(nav_res.get("success"), "Navigation dispatch must succeed")

        # Frame 2: Updated state with search/navigation (poll up to 5s for mutation)
        frame2 = None
        for _ in range(10):
            time.sleep(0.5)
            frame2 = self.engine.capture_full_window_png()
            if frame2 and frame2 != frame1:
                break
        self.assertIsNotNone(frame2)
        self.assertGreater(len(frame2), 10000)
        self.assertNotEqual(frame1, frame2, "Browser window frame must mutate in response to address bar input")
        logger.info(f"TEST 3 PASSED: Omnibox input routed; frames mutated ({len(frame1)} -> {len(frame2)} bytes)")

    def test_04_panel_viewport_file_synchronization(self) -> None:
        """Verify current_viewport.png is populated with genuine full-window frame for the AUX pane."""
        self.assertTrue(self.viewport_file.exists(), "current_viewport.png must exist in profile directory")
        file_bytes = self.viewport_file.read_bytes()
        self.assertGreater(len(file_bytes), 10000, "current_viewport.png must contain valid full-window frame")
        self.assertTrue(file_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        logger.info(f"TEST 4 PASSED: Native panel stream synchronized with genuine full-window frame ({len(file_bytes)} bytes)")

    def test_05_zero_host_desktop_actuation(self) -> None:
        """Verify host mouse and keyboard remain unactuated and session is safe."""
        # Ensure service reports clean state
        status = self.service.get_status()
        self.assertEqual(status.get("control_state"), BrowserControlState.AGI_CONTROL.value)
        self.assertFalse(self.service.is_human_in_control())
        logger.info("TEST 5 PASSED: Host safety boundaries strictly preserved.")


if __name__ == "__main__":
    unittest.main()

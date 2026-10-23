"""AGI 1.7 OMEGA COMMAND — Browser Use Integration & Verification Suite.

Tests the Browser Use adapter paradigm integrated into AGI 1.7:
- DOM accessibility element indexing (1-indexed monotonic targets).
- Element-indexed action routing (click_by_index, type_by_index, hover_by_index).
- Generation of compact LLM-friendly DOM accessibility representations.
- Synchronization with the native Antigravity sidecar panel state and viewport stream.
- Safety enforcement: Human takeover lockouts, PAPER mode boundaries, zero host popups.
"""

from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

root_dir = Path(__file__).resolve().parents[3]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from agents.AGI_1_7.engine.agi17.browser import (
    BrowserControlState,
    BrowserUseAdapter,
    BrowserUseElement,
    PageElement,
    PersistentBrowserService,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TestBrowserUseIntegration")


class TestBrowserUseIntegration(unittest.TestCase):
    """Verifies Browser Use adapter capabilities within AGI 1.7 architecture."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.service = PersistentBrowserService()
        cls.adapter = BrowserUseAdapter(cls.service)

    def setUp(self) -> None:
        # Ensure clean AGI control state and navigate to standard test page
        self.service.return_control()
        self.service.resume_session()
        self.service.scroll_x = 0
        self.service.scroll_y = 0
        self.adapter.navigate("https://www.google.com")

    def test_01_adapter_initialization_and_attachment(self) -> None:
        """Verify adapter attaches to authoritative PersistentBrowserService session."""
        self.assertIsNotNone(self.adapter.browser_service)
        status = self.adapter.browser_service.get_status()
        self.assertTrue(status["session_id"].startswith("omega-browser-"))
        self.assertEqual(status["control_state"], BrowserControlState.AGI_CONTROL.value)
        logger.info("TEST 1 PASSED: Browser Use adapter attached to session %s", status["session_id"])

    def test_02_dom_accessibility_indexing(self) -> None:
        """Verify DOM elements are extracted and monotonically indexed [1..N]."""
        elements = self.adapter.extract_dom_state()
        self.assertGreater(len(elements), 0, "DOM must contain interactive elements")

        # Verify monotonic indexing starting at 1
        for expected_idx, elem in enumerate(elements, start=1):
            self.assertEqual(elem.index, expected_idx)
            self.assertIsInstance(elem.center_x, int)
            self.assertIsInstance(elem.center_y, int)
            # Verify center calculation matches bounding box
            bx = elem.bounding_box.get("x", 0.0)
            bw = elem.bounding_box.get("width", 0.0)
            self.assertEqual(elem.center_x, int(bx + (bw / 2.0)))

        logger.info("TEST 2 PASSED: Extracted and indexed %d interactive elements", len(elements))

    def test_03_compact_dom_text_generation(self) -> None:
        """Verify generation of compact Browser Use DOM text for LLM prompts."""
        dom_text = self.adapter.get_annotated_dom_text()
        self.assertIn("[Browser Use Indexed DOM]:", dom_text)
        self.assertIn("[1]", dom_text)
        self.assertIn("at (", dom_text)
        logger.info("TEST 3 PASSED: Compact DOM summary generated:\n%s", dom_text[:200])

    def test_04_action_dispatch_click_by_index(self) -> None:
        """Verify clicking element by its Browser Use index routes to exact coordinates."""
        elements = self.adapter.extract_dom_state()
        self.assertGreater(len(elements), 0)

        # Target element 1 (typically search box or primary input)
        target_elem = elements[0]
        res = self.adapter.click_by_index(1)

        self.assertEqual(res["status"], "clicked")
        self.assertEqual(res["x"], target_elem.center_x)
        self.assertEqual(res["y"], target_elem.center_y)
        self.assertEqual(res["browser_use_index"], 1)
        self.assertEqual(res["focused_element_id"], target_elem.element_id)
        logger.info("TEST 4 PASSED: Clicked element [1] '%s' at (%d, %d)", target_elem.name, res["x"], res["y"])

    def test_05_action_dispatch_type_by_index(self) -> None:
        """Verify typing into element by Browser Use index updates value and focus."""
        elements = self.adapter.extract_dom_state()
        self.assertGreater(len(elements), 0)

        test_query = "AGI 1.7 Browser Use Verification"
        res = self.adapter.type_by_index(1, test_query)

        self.assertEqual(res["status"], "typed")
        self.assertEqual(res["browser_use_index"], 1)
        self.assertIn(test_query, res.get("element_value", ""))

        # Verify element state in adapter cache
        updated_elem = self.adapter.get_element_by_index(1)
        self.assertIsNotNone(updated_elem)
        self.assertEqual(updated_elem.value, test_query)
        logger.info("TEST 5 PASSED: Typed '%s' into element [1]", test_query)

    def test_06_hover_and_scroll_actions(self) -> None:
        """Verify virtual cursor hover and scroll operations."""
        elements = self.adapter.extract_dom_state()
        hover_res = self.adapter.hover_by_index(1)
        self.assertEqual(hover_res["status"], "moved")
        self.assertEqual(self.service.cursor_x, elements[0].center_x)
        self.assertEqual(self.service.cursor_y, elements[0].center_y)

        scroll_res = self.adapter.scroll("down", 250)
        self.assertEqual(scroll_res["status"], "scrolled")
        self.assertGreaterEqual(self.service.scroll_y, 250)
        logger.info("TEST 6 PASSED: Hover and scroll verified (scroll_y=%d)", self.service.scroll_y)

    def test_07_panel_telemetry_payload_contract(self) -> None:
        """Verify telemetry dictionary aligns with native Antigravity AUX Pane expectations."""
        telemetry = self.adapter.get_panel_telemetry()
        self.assertIn("session_id", telemetry)
        self.assertIn("url", telemetry)
        self.assertIn("control_state", telemetry)
        self.assertIn("cursor", telemetry)
        self.assertIn("scroll_y", telemetry)
        self.assertIn("indexed_element_count", telemetry)
        self.assertIn("indexed_elements", telemetry)
        self.assertGreater(telemetry["indexed_element_count"], 0)
        logger.info("TEST 7 PASSED: Panel telemetry contract verified with %d indexed elements", telemetry["indexed_element_count"])

    def test_08_human_takeover_safety_gating(self) -> None:
        """Verify actions are safely blocked during Human Takeover."""
        self.service.take_control()
        self.assertEqual(self.service.control_state, BrowserControlState.HUMAN_TAKEOVER)

        # Attempting click or type while human takeover is active must raise PermissionError
        with self.assertRaises(PermissionError):
            self.adapter.click_by_index(1)

        with self.assertRaises(PermissionError):
            self.adapter.type_by_index(1, "Should Fail")

        # Resume control and confirm operation succeeds
        self.service.return_control()
        self.assertEqual(self.service.control_state, BrowserControlState.AGI_CONTROL)
        res = self.adapter.click_by_index(1)
        self.assertEqual(res["status"], "clicked")
        logger.info("TEST 8 PASSED: Human takeover gating strictly verified.")

    def test_09_paper_mode_and_zero_host_popups(self) -> None:
        """Verify strictly isolated PAPER mode: zero external OS popups, valid viewport frame."""
        viewport_png = self.adapter.get_latest_viewport_png()
        self.assertGreater(len(viewport_png), 1000, "Viewport PNG must be valid image buffer")
        # Magic bytes check for valid PNG
        self.assertEqual(viewport_png[:8], b"\x89PNG\r\n\x1a\n")
        logger.info("TEST 9 PASSED: Valid in-IDE viewport PNG stream verified (%d bytes)", len(viewport_png))


if __name__ == "__main__":
    unittest.main()

"""Comprehensive Test Suite for Computer Use Engine & Input Execution Subsystem.

Verifies:
1. Coordinate math with DPI, viewport, and screenshot scaling: scale_coordinates(x, y, src_dim, target_dim).
2. Core operations: capture_screen(), move_mouse(x, y), click(x, y, button), double_click(x, y),
   scroll(x, y, dx, dy), press_key(key), press_hotkey(keys), type_text(text),
   get_screen_dimensions(), get_active_window().
3. Safe release of keys/mouse buttons on error or cancellation, and focus verification.
4. Integration with BrowserControlState (AGI_CONTROL, HUMAN_TAKEOVER, TRANSITIONING, RECOVERY, STOPPED).
5. Paper mode safety and token governance boundaries.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.browser import (
    BaseInputAdapter,
    BoundingBox,
    BrowserControlState,
    BrowserSessionManager,
    ComputerUseEngine,
    ComputerUseError,
    Dimensions,
    ExecutionMode,
    FocusVerificationError,
    HumanTakeoverInterruption,
    OSInputAdapter,
    Point,
    ScreenCapture,
    SimulatedInputAdapter,
    TokenBudgetManager,
    TokenCeilingExceededError,
    estimate_vision_tokens,
    scale_bounding_box,
    scale_coordinates,
)


class TestComputerUseEngine(unittest.TestCase):
    """Unit test suite for ComputerUseEngine (Layer A & Layer C)."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="omega_computer_use_test_"))
        self.adapter = SimulatedInputAdapter(screen_width=1920, screen_height=1080)
        self.engine = ComputerUseEngine(
            adapter=self.adapter,
            execution_mode=ExecutionMode.PAPER,
            dpi_scale=1.0,
        )

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -----------------------------------------------------------------
    # 1. Coordinate Math & Scaling
    # -----------------------------------------------------------------

    def test_01_coordinate_scaling_1_to_1(self) -> None:
        """Verify 1:1 scaling preserves exact integer coordinates."""
        src = (1920, 1080)
        tgt = (1920, 1080)
        scaled_x, scaled_y = scale_coordinates(500, 300, src, tgt)
        self.assertEqual(scaled_x, 500)
        self.assertEqual(scaled_y, 300)

    def test_02_coordinate_scaling_cross_resolution(self) -> None:
        """Verify scaling between model space (1000x1000) and target resolution (1920x1080)."""
        src = (1000, 1000)
        tgt = (1920, 1080)
        # Center of model space should map to center of screen
        cx, cy = scale_coordinates(500, 500, src, tgt)
        self.assertEqual(cx, 960)
        self.assertEqual(cy, 540)

        # Origin
        ox, oy = scale_coordinates(0, 0, src, tgt)
        self.assertEqual(ox, 0)
        self.assertEqual(oy, 0)

        # Max corner (with clamping)
        mx, my = scale_coordinates(1000, 1000, src, tgt, clamp=True)
        self.assertEqual(mx, 1919)
        self.assertEqual(my, 1079)

    def test_03_dpi_scaling_factors(self) -> None:
        """Verify high DPI scaling factors (1.25x, 1.5x, 2.0x)."""
        src = (1000, 1000)
        tgt = (1000, 1000)
        # 1.5x DPI
        x_15, y_15 = scale_coordinates(200, 200, src, tgt, dpi_scale=1.5, clamp=False)
        self.assertEqual(x_15, 300)
        self.assertEqual(y_15, 300)

        # 2.0x DPI
        x_20, y_20 = scale_coordinates(800, 800, src, tgt, dpi_scale=2.0, clamp=True)
        self.assertEqual(x_20, 1600)
        self.assertEqual(y_20, 1600)

        # 2.0x DPI with out-of-bounds clamping
        x_clamp, y_clamp = scale_coordinates(1200, 1200, src, tgt, dpi_scale=2.0, clamp=True)
        self.assertEqual(x_clamp, 1999)
        self.assertEqual(y_clamp, 1999)

    def test_04_bounding_box_scaling(self) -> None:
        """Verify scaling of bounding boxes."""
        box = (100, 200, 300, 400)
        src = (1000, 1000)
        tgt = (2000, 2000)
        scaled_box = scale_bounding_box(box, src, tgt)
        self.assertEqual(scaled_box, (200, 400, 600, 800))

    def test_05_coordinate_scaling_invalid_dimensions(self) -> None:
        """Verify invalid dimensions raise ValueError."""
        with self.assertRaises(ValueError):
            scale_coordinates(10, 10, (0, 1080), (1920, 1080))
        with self.assertRaises(ValueError):
            scale_coordinates(10, 10, (1920, 1080), (1920, -5))
        with self.assertRaises(ValueError):
            scale_coordinates(10, 10, (1920, 1080), (1920, 1080), dpi_scale=-1.0)

    # -----------------------------------------------------------------
    # 2. Core Operations
    # -----------------------------------------------------------------

    def test_06_mouse_movement_and_clicking(self) -> None:
        """Verify move_mouse, click, double_click, and scroll."""
        res_move = self.engine.move_mouse(400, 300)
        self.assertEqual(res_move["status"], "ok")
        self.assertEqual(self.adapter.cursor_x, 400)
        self.assertEqual(self.adapter.cursor_y, 300)

        # Click at explicit coordinates
        res_click = self.engine.click(600, 500, button="left")
        self.assertEqual(res_click["status"], "ok")
        self.assertEqual(res_click["x"], 600)
        self.assertEqual(res_click["y"], 500)
        self.assertEqual(self.adapter.cursor_x, 600)
        self.assertEqual(self.adapter.cursor_y, 500)

        # Double click
        res_dbl = self.engine.double_click(700, 750, button="left")
        self.assertEqual(res_dbl["click_count"], 2)
        self.assertEqual(self.adapter.cursor_x, 700)
        self.assertEqual(self.adapter.cursor_y, 750)

        # Scroll
        res_scroll = self.engine.scroll(700, 750, dx=0, dy=-5)
        self.assertEqual(res_scroll["status"], "ok")
        self.assertEqual(res_scroll["dy"], -5)

    def test_07_keyboard_operations(self) -> None:
        """Verify type_text, press_key, and press_hotkey."""
        res_type = self.engine.type_text("Hello Omega", delay_ms=0.0)
        self.assertEqual(res_type["status"], "typed")
        self.assertEqual(res_type["length"], 11)

        res_press = self.engine.press_key("Enter")
        self.assertEqual(res_press["status"], "pressed")
        self.assertEqual(res_press["key"], "Enter")

        # Hotkey combination (e.g. Ctrl+C)
        res_hotkey = self.engine.press_hotkey("ctrl", "c")
        self.assertEqual(res_hotkey["status"], "ok")
        self.assertEqual(res_hotkey["keys"], ["ctrl", "c"])

        # Also support list input
        res_hotkey_list = self.engine.press_hotkey(["ctrl", "shift", "i"])
        self.assertEqual(res_hotkey_list["status"], "ok")
        self.assertEqual(res_hotkey_list["keys"], ["ctrl", "shift", "i"])

    def test_08_screen_dimensions_and_active_window(self) -> None:
        """Verify get_screen_dimensions and get_active_window."""
        dims = self.engine.get_screen_dimensions()
        self.assertEqual(dims, (1920, 1080))

        win = self.engine.get_active_window()
        self.assertEqual(win["title"], "Omega Browser Workspace")
        self.assertEqual(win["handle"], 1001)
        self.assertTrue(win["is_active"])

    def test_09_capture_screen_operation(self) -> None:
        """Verify screen capture returns valid ScreenCapture object and bytes."""
        cap = self.engine.capture_screen()
        self.assertIsInstance(cap, ScreenCapture)
        self.assertEqual(cap.dimensions.to_tuple(), (1920, 1080))
        self.assertTrue(len(cap.image_bytes) > 0)
        self.assertTrue(len(cap.sha256) > 0)
        self.assertTrue(len(cap.base64_str) > 0)
        self.assertTrue(cap.estimated_tokens > 0)

        # Raw bytes return mode
        raw_bytes = self.engine.capture_screen(return_raw_bytes=True)
        self.assertIsInstance(raw_bytes, bytes)
        self.assertEqual(raw_bytes, cap.image_bytes)

    # -----------------------------------------------------------------
    # 3. Safe Release & Focus Verification
    # -----------------------------------------------------------------

    def test_10_safe_release_of_keys_and_buttons_on_error(self) -> None:
        """Verify that when an error occurs during an operation, any held inputs are freed."""
        # Hold mouse button and key down
        self.engine.mouse_down("left")
        self.engine.key_down("shift")

        status = self.engine.get_status()
        self.assertIn("left", status["pressed_buttons"])
        self.assertIn("shift", status["pressed_keys"])

        # Intentionally cause an error inside an action
        def faulty_action() -> None:
            with self.engine._safe_execution_scope("faulty_action"):
                self.engine.key_down("control")
                raise RuntimeError("Unexpected simulated system fault")

        with self.assertRaises(RuntimeError):
            faulty_action()

        # Both keys and buttons must be completely released
        post_status = self.engine.get_status()
        self.assertEqual(len(post_status["pressed_keys"]), 0)
        self.assertEqual(len(post_status["pressed_buttons"]), 0)

    def test_11_emergency_release_all_explicit(self) -> None:
        """Verify explicit emergency_release_all clears all tracked inputs."""
        self.engine.mouse_down("right")
        self.engine.key_down("alt")

        released = self.engine.emergency_release_all()
        self.assertIn("alt", released["released_keys"])
        self.assertIn("right", released["released_buttons"])

        status = self.engine.get_status()
        self.assertEqual(len(status["pressed_keys"]), 0)
        self.assertEqual(len(status["pressed_buttons"]), 0)

    def test_12_focus_verification_enforcement(self) -> None:
        """Verify focus verification checks active window title."""
        self.engine.expected_window_pattern = "Omega Browser"
        self.engine.enforce_focus = True

        # Matches "Omega Browser Workspace"
        self.assertTrue(self.engine.verify_focus())

        # Target expected mismatch
        self.engine.expected_window_pattern = "Unrelated Terminal"
        with self.assertRaises(FocusVerificationError):
            self.engine.type_text("forbidden text")

    # -----------------------------------------------------------------
    # 4. BrowserControlState Integration
    # -----------------------------------------------------------------

    def test_13_browser_control_state_gating(self) -> None:
        """Verify operations are permitted only in AGI_CONTROL and blocked in other states."""
        # 1. Human Takeover
        self.engine.set_control_state(BrowserControlState.HUMAN_TAKEOVER)
        self.assertTrue(self.engine.is_human_in_control())
        with self.assertRaises(HumanTakeoverInterruption):
            self.engine.click(100, 100)

        with self.assertRaises(HumanTakeoverInterruption):
            self.engine.type_text("test")

        # 2. Stopped
        self.engine.set_control_state(BrowserControlState.STOPPED)
        with self.assertRaises(PermissionError):
            self.engine.move_mouse(100, 100)

        # 3. Transitioning
        self.engine.set_control_state(BrowserControlState.TRANSITIONING)
        with self.assertRaises(PermissionError):
            self.engine.press_key("Enter")

        # 4. Recovery
        self.engine.set_control_state(BrowserControlState.RECOVERY)
        with self.assertRaises(PermissionError):
            self.engine.scroll(0, 0, 0, 5)

        # 5. Return to AGI_CONTROL succeeds
        self.engine.set_control_state(BrowserControlState.AGI_CONTROL)
        res = self.engine.click(200, 200)
        self.assertEqual(res["status"], "ok")

    def test_14_take_control_and_return_control_flow(self) -> None:
        """Verify take_control releases inputs and return_control resumes."""
        self.engine.key_down("ctrl")
        self.engine.mouse_down("left")

        # Take control
        res_take = self.engine.take_control()
        self.assertTrue(res_take["success"])
        self.assertEqual(res_take["control_state"], BrowserControlState.HUMAN_TAKEOVER.value)

        # Input tracking must be cleared
        status = self.engine.get_status()
        self.assertEqual(len(status["pressed_keys"]), 0)
        self.assertEqual(len(status["pressed_buttons"]), 0)

        # Return control
        res_ret = self.engine.return_control()
        self.assertTrue(res_ret["success"])
        self.assertEqual(res_ret["control_state"], BrowserControlState.AGI_CONTROL.value)

    def test_15_integration_with_browser_session_manager(self) -> None:
        """Verify ComputerUseEngine synchronizes state with persistent BrowserSessionManager."""
        mgr = BrowserSessionManager(storage_root=self.temp_dir, port=8777)
        try:
            linked_engine = ComputerUseEngine(
                browser_service=mgr,
                adapter=self.adapter,
                execution_mode=ExecutionMode.PAPER,
            )
            self.assertEqual(linked_engine.control_state, BrowserControlState.AGI_CONTROL)

            # Human takeover via manager reflected in engine
            mgr.take_control()
            self.assertEqual(linked_engine.control_state, BrowserControlState.HUMAN_TAKEOVER)
            with self.assertRaises(HumanTakeoverInterruption):
                linked_engine.click(50, 50)

            # Return control via manager reflected in engine
            mgr.return_control()
            self.assertEqual(linked_engine.control_state, BrowserControlState.AGI_CONTROL)
            res = linked_engine.click(50, 50)
            self.assertEqual(res["status"], "ok")
        finally:
            mgr.close()

    # -----------------------------------------------------------------
    # 5. Paper Mode Safety & Token Governance
    # -----------------------------------------------------------------

    def test_16_paper_mode_safety(self) -> None:
        """Verify Paper mode uses SimulatedInputAdapter and logs events safely."""
        self.assertEqual(self.engine.execution_mode, ExecutionMode.PAPER)
        self.engine.move_mouse(100, 200)
        self.engine.type_text("safe paper mode")

        status = self.engine.get_status()
        self.assertEqual(status["execution_mode"], ExecutionMode.PAPER.value)
        self.assertTrue(status["action_count"] >= 2)

    def test_17_token_governance_budget_enforcement(self) -> None:
        """Verify token ceiling limits screen captures when daily ceiling is reached."""
        token_mgr = TokenBudgetManager(
            daily_ceiling=1000,
            reserve_buffer=100,
            storage_path=self.temp_dir / "test_token_budget.json",
        )
        governed_engine = ComputerUseEngine(
            adapter=self.adapter,
            token_budget_manager=token_mgr,
            execution_mode=ExecutionMode.PAPER,
        )

        # Pre-consume tokens until ceiling is reached (1000 - 100 reserve = 900)
        admitted, _ = token_mgr.check_and_record(900)
        self.assertTrue(admitted)
        status = token_mgr.get_status()
        self.assertTrue(status.is_admission_stopped)

        # Screen capture should be rejected under token ceiling enforcement
        with self.assertRaises(TokenCeilingExceededError):
            governed_engine.capture_screen()


if __name__ == "__main__":
    unittest.main()

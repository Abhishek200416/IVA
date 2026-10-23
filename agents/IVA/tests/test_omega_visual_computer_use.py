"""Acceptance Test Battery for Visual Computer Use & Visual Browser Control.

Verifies P0 Directive — Section 22 and 23 Acceptance Criteria:
- Test A: Visible navigation & post-action screenshot verification
- Test B: Coordinate-based mouse click
- Test C: Coordinate-based text typing & field focus
- Test D: Mouse-wheel scrolling & viewport change detection
- Test E: Tab & window switching without coordinate drift
- Test F: Dynamic UI change / modal recovery
- Test G: Two-way human takeover & state reconciliation
- Test H: Persistent session lifecycle & crash recovery
- Test I: Emergency stop, least privilege, paper-mode enforcement
- Test J: End-to-end task execution loop
- Edge Cases: DPI scaling, network lag, modal popups, focus loss
"""

from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List

from agents.AGI_1_7.engine.agi17.browser import (
    ActionBatcher,
    ActionKind,
    AdaptiveObservationPolicy,
    BrowserAction,
    BrowserControlState,
    BrowserHealthStatus,
    BrowserSessionManager,
    ExecutionMode,
    GroundedTarget,
    LoopPhase,
    ObservationPolicyMode,
    ObservationTier,
    PageElement,
    RecoveryStrategy,
    RiskControlGate,
    VerificationResult,
    VisualAction,
    VisualAgentLoop,
    VisualObservationSnapshot,
    VisualStepResult,
    VisualTaskReport,
)


class TestOmegaVisualComputerUse(unittest.TestCase):
    """P0 Acceptance Test Battery for Human-Like Visual Computer Use and Browser Control."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="omega_visual_test_"))
        self.driver = BrowserSessionManager(storage_root=self.temp_dir, port=8777)
        self.risk_gate = RiskControlGate(default_mode=ExecutionMode.PAPER)
        self.loop = VisualAgentLoop(
            driver=self.driver,
            risk_gate=self.risk_gate,
            policy_mode=ObservationPolicyMode.STRUCTURED_FIRST,
        )

    def tearDown(self) -> None:
        self.driver.close()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Test A: Visible navigation & post-action screenshot verification
    # ------------------------------------------------------------------
    def test_A_visible_navigation_and_post_action_screenshot_verification(self) -> None:
        """Verify navigation updates URL, captures valid PNG, and triggers post-action visual diffing."""
        target_url = "https://www.google.com"
        action = VisualAction.navigate(target_url)

        res = self.loop.step(action)

        self.assertTrue(res.success, f"Step failed: {res.error_message}")
        self.assertEqual(res.phase_reached, LoopPhase.COMPLETED)
        self.assertEqual(self.driver.current_url, target_url)

        # Pre and post observations must be present
        self.assertIsNotNone(res.pre_observation)
        self.assertIsNotNone(res.post_observation)
        assert res.post_observation is not None
        assert res.pre_observation is not None

        # Post observation URL and valid PNG screenshot check
        self.assertEqual(res.post_observation.url, target_url)
        self.assertTrue(res.post_observation.screenshot_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        # Post-action verification must confirm visual change
        self.assertIsNotNone(res.verification)
        assert res.verification is not None
        self.assertTrue(res.verification.is_verified)
        self.assertTrue(res.verification.visual_diff_detected)
        self.assertGreater(res.verification.visual_change_ratio, 0.0)
        self.assertNotEqual(res.verification.pre_hash, res.verification.post_hash)

    # ------------------------------------------------------------------
    # Test B: Coordinate-based mouse click
    # ------------------------------------------------------------------
    def test_B_coordinate_based_mouse_click(self) -> None:
        """Verify coordinate mouse clicks update cursor position, hit-test DOM, and verify visually."""
        # Navigate to page with interactive elements
        self.loop.step(VisualAction.navigate("https://www.google.com"))

        # Click Google Search button at known bounding box (280, 210, w=120, h=36) -> center (340, 228)
        click_action = VisualAction.click_coordinate(340, 228)
        res = self.loop.step(click_action)

        self.assertTrue(res.success)
        self.assertEqual(self.driver.cursor_x, 340)
        self.assertEqual(self.driver.cursor_y, 228)
        self.assertEqual(self.driver.focused_element_id, "btnK")

        # Verify post-action visual verification succeeded
        assert res.verification is not None
        self.assertTrue(res.verification.is_verified)
        self.assertTrue(res.verification.visual_diff_detected)
        self.assertIn("Search Results Loaded", self.driver._visible_text)

    # ------------------------------------------------------------------
    # Test C: Coordinate-based text typing & field focus
    # ------------------------------------------------------------------
    def test_C_coordinate_based_text_typing_and_field_focus(self) -> None:
        """Verify coordinate typing gains field focus, inputs text, and alters visual state."""
        self.loop.step(VisualAction.navigate("https://www.google.com"))

        # Target search box: bbox (x=200, y=150, w=400, h=40) -> center (400, 170)
        type_action = VisualAction.type_coordinate(400, 170, "BANKNIFTY 51200 CALL")
        res = self.loop.step(type_action)

        self.assertTrue(res.success)
        self.assertEqual(self.driver.focused_element_id, "q")

        # Verify typed value in element
        elem = self.driver.inspect_element("q")
        self.assertIsNotNone(elem)
        assert elem is not None
        self.assertEqual(elem.get("value"), "BANKNIFTY 51200 CALL")

        # Verify post-action visual diff reflects typed text
        assert res.verification is not None
        self.assertTrue(res.verification.is_verified)
        self.assertTrue(res.verification.visual_diff_detected)

    # ------------------------------------------------------------------
    # Test D: Mouse-wheel scrolling & viewport change detection
    # ------------------------------------------------------------------
    def test_D_mouse_wheel_scrolling_and_viewport_change_detection(self) -> None:
        """Verify mouse wheel scrolling shifts viewport scroll_y and triggers visual diff."""
        self.loop.step(VisualAction.navigate("https://open-api.paytmmoney.com/dashboard"))
        initial_scroll_y = self.driver.scroll_y
        self.assertEqual(initial_scroll_y, 0)

        # Scroll down by 400px
        scroll_action = VisualAction.scroll_wheel(delta_y=400)
        res = self.loop.step(scroll_action)

        self.assertTrue(res.success)
        self.assertEqual(self.driver.scroll_y, 400)

        # Post-action verification must confirm scroll offset and visual diff
        assert res.verification is not None
        self.assertTrue(res.verification.is_verified)
        self.assertTrue(res.verification.visual_diff_detected)
        self.assertGreater(res.verification.visual_change_ratio, 0.0)

        # Subsequent grounding must offset document coordinates by scroll_y
        grounded = self.loop.ground(
            VisualAction.click_selector("#btn-place-order"),
            res.post_observation,
        )
        # Element #btn-place-order is at doc_y = 250 + 22.5 = 272.5; scroll_y = 400 -> viewport_y = 272.5 - 400 = -128
        self.assertEqual(grounded.y, int(round(272.5 - 400)))

    # ------------------------------------------------------------------
    # Test E: Tab & window switching without coordinate drift
    # ------------------------------------------------------------------
    def test_E_tab_and_window_switching_without_coordinate_drift(self) -> None:
        """Verify tab switching isolates coordinate space and prevents coordinate drift."""
        # Tab 1: Google
        self.loop.step(VisualAction.navigate("https://www.google.com"))
        self.driver.scroll_wheel(0, 250)
        tab1_id = self.driver.session.active_tab_id
        self.assertEqual(self.driver.scroll_y, 250)

        # Open Tab 2: Paytm
        t2 = self.driver.new_tab("https://open-api.paytmmoney.com/dashboard")
        tab2_id = t2["tab_id"]
        self.loop.step(VisualAction.navigate("https://open-api.paytmmoney.com/dashboard"))
        self.assertEqual(self.driver.scroll_y, 0)

        # Ground search box in Tab 2 -> search box does not exist in Tab 2, default viewport mid returned
        obs2 = self.loop.observe()
        grounded_t2 = self.loop.ground(VisualAction.click_selector("input[name='q']"), obs2)
        self.assertEqual(grounded_t2.target_type, "viewport_relative")

        # Switch back to Tab 1
        switch_action = VisualAction.switch_tab(tab1_id)
        res_switch = self.loop.step(switch_action)
        self.assertTrue(res_switch.success)
        self.assertEqual(self.driver.session.active_tab_id, tab1_id)
        self.assertEqual(self.driver.current_url, "https://www.google.com")

        # Coordinate space in Tab 1 must be exactly preserved: scroll_y = 250
        self.assertEqual(self.driver.scroll_y, 250)
        obs1_restored = self.loop.observe()
        grounded_t1 = self.loop.ground(VisualAction.click_selector("input[name='q']"), obs1_restored)
        self.assertEqual(grounded_t1.target_type, "element_center")
        # Center in doc = 170. scroll_y = 250 -> viewport_y = 170 - 250 = -80
        self.assertEqual(grounded_t1.y, -80)

    # ------------------------------------------------------------------
    # Test F: Dynamic UI change / modal recovery
    # ------------------------------------------------------------------
    def test_F_dynamic_ui_change_and_modal_recovery(self) -> None:
        """Verify autonomous recovery detects modal popup, dismisses it, and retries action."""
        self.loop.step(VisualAction.navigate("https://open-api.paytmmoney.com/dashboard"))

        # Trigger a popup modal over the viewport
        self.driver.show_modal(
            modal_id="cookie_consent_banner",
            title="Cookie Consent & Risk Notice",
            text="Please acknowledge market risk disclosures before continuing.",
            dismiss_box={"x": 560.0, "y": 330.0, "width": 80.0, "height": 40.0},
        )
        self.assertIsNotNone(self.driver.active_modal)

        # Attempt to click background Place Order button at (475, 272) which is occluded by the modal box
        action = VisualAction.click_coordinate(475, 272)
        res = self.loop.step(action)

        # Autonomous recovery must have triggered DISMISS_MODAL strategy
        self.assertTrue(res.success)
        self.assertGreater(len(res.recovery_attempts), 0)
        self.assertEqual(res.recovery_attempts[0].strategy, RecoveryStrategy.DISMISS_MODAL)
        self.assertTrue(res.recovery_attempts[0].success)

        # Modal must now be dismissed and viewport clear
        self.assertIsNone(self.driver.active_modal)

    # ------------------------------------------------------------------
    # Test G: Two-way human takeover & state reconciliation
    # ------------------------------------------------------------------
    def test_G_two_way_human_takeover_and_state_reconciliation(self) -> None:
        """Verify human takeover halts agent automation and returning control triggers reconciliation."""
        self.loop.step(VisualAction.navigate("https://www.google.com"))
        initial_digest = self.loop.observe().state_digest

        # 1. Human initiates takeover
        takeover_info = self.driver.take_control()
        self.assertEqual(takeover_info["control_state"], BrowserControlState.HUMAN_TAKEOVER.value)
        self.assertTrue(self.driver.is_human_in_control())

        # 2. Agent attempt during takeover must pause immediately
        res_blocked = self.loop.step(VisualAction.click_coordinate(100, 100))
        self.assertFalse(res_blocked.success)
        self.assertTrue(res_blocked.interrupted_by_human)
        self.assertEqual(res_blocked.phase_reached, LoopPhase.PAUSED_HUMAN_TAKEOVER)

        # Direct driver operations by automated caller are also strictly rejected
        with self.assertRaises(PermissionError):
            self.driver.navigate("https://malicious.site")

        # 3. Simulate human interactions directly on session
        self.driver._current_url = "https://chatgpt.com/c/shared-session"
        self.driver._current_title = "ChatGPT Workspace"
        self.driver._visible_text = "Human operator verified chart setup."

        # 4. Human returns control
        return_info = self.driver.return_control()
        self.assertEqual(return_info["control_state"], BrowserControlState.AGI_CONTROL.value)
        self.assertFalse(self.driver.is_human_in_control())

        # 5. Agent reconciles state
        reconciled_obs = self.loop.reconcile_state()
        self.assertEqual(reconciled_obs.url, "https://chatgpt.com/c/shared-session")
        self.assertNotEqual(reconciled_obs.state_digest, initial_digest)

        # Loop resumes execution safely
        res_resumed = self.loop.step(VisualAction.click_coordinate(200, 200))
        self.assertTrue(res_resumed.success)

    # ------------------------------------------------------------------
    # Test H: Persistent session lifecycle & crash recovery
    # ------------------------------------------------------------------
    def test_H_persistent_session_lifecycle_and_crash_recovery(self) -> None:
        """Verify persistent session survives steps and recovers safely from simulated crashes."""
        self.loop.step(VisualAction.navigate("https://www.google.com"))
        session_id_before = self.driver.session.session_id

        # Run several actions on the same persistent session
        self.loop.step(VisualAction.click_coordinate(200, 200))
        self.loop.step(VisualAction.scroll_wheel(delta_y=150))
        self.assertEqual(self.driver.session.session_id, session_id_before)

        # Simulate browser crash
        self.driver.session.health_status = BrowserHealthStatus.CRASHED
        self.assertEqual(self.driver.session.health_status, BrowserHealthStatus.CRASHED)

        # Trigger recovery
        recovery_res = self.driver.recover_session()
        self.assertTrue(recovery_res["recovered"])
        self.assertEqual(self.driver.session.health_status, BrowserHealthStatus.READY)
        self.assertEqual(self.driver.session.session_id, session_id_before)
        self.assertEqual(self.driver.current_url, "https://www.google.com")

    # ------------------------------------------------------------------
    # Test I: Emergency stop, least privilege, paper-mode enforcement
    # ------------------------------------------------------------------
    def test_I_emergency_stop_least_privilege_and_paper_mode_enforcement(self) -> None:
        """Verify RiskExecutionGate halts live trading, enforces paper mode, and honors kill switch."""
        self.loop.step(VisualAction.navigate("https://open-api.paytmmoney.com/dashboard"))

        # Default mode is strictly PAPER
        self.assertEqual(self.risk_gate.mode, ExecutionMode.PAPER)

        # Attempting financial order action in PAPER mode: intercepted safely
        order_action = VisualAction.click_coordinate(475, 272, is_financial=True)
        res_paper = self.loop.step(order_action)
        self.assertTrue(res_paper.success)
        self.assertTrue(order_action.metadata.get("paper_mode_intercepted"))

        # Attempt to arm live trading without owner authorization: strictly blocked
        with self.assertRaises(PermissionError):
            self.risk_gate.set_mode(ExecutionMode.LIVE_ACTIVE)

        # Trigger Emergency Kill Switch
        self.risk_gate.trigger_emergency_kill_switch("Risk threshold breach")
        self.assertEqual(self.risk_gate.mode, ExecutionMode.HALTED)
        self.assertTrue(self.risk_gate.emergency_stop_triggered)

        # Any financial action must now be immediately blocked
        res_blocked = self.loop.step(VisualAction.click_coordinate(475, 272, is_financial=True))
        self.assertFalse(res_blocked.success)
        self.assertIsNotNone(res_blocked.error_message)
        self.assertIn("Emergency Stop is active", res_blocked.error_message)

        # Direct act invocation also strictly raises PermissionError
        with self.assertRaises(PermissionError):
            grounded = self.loop.ground(order_action, self.loop.observe())
            self.loop.act(order_action, grounded)

    # ------------------------------------------------------------------
    # Test J: End-to-end task execution loop
    # ------------------------------------------------------------------
    def test_J_end_to_end_task_execution_loop(self) -> None:
        """Verify full end-to-end task execution: navigate -> click -> type -> submit -> scroll -> verify."""
        mission_steps = [
            VisualAction.navigate("https://www.google.com"),
            VisualAction.click_coordinate(400, 170),
            VisualAction.type_coordinate(400, 170, "AGI 1.7 OMEGA MISSION"),
            VisualAction.click_coordinate(340, 228),  # Submit search
            VisualAction.scroll_wheel(delta_y=300),   # Scroll to results
        ]

        report: VisualTaskReport = self.loop.run_task(mission_steps, task_id="task-e2e-omega-01")

        self.assertTrue(report.success)
        self.assertEqual(report.total_steps, 5)
        self.assertEqual(report.steps_succeeded, 5)
        self.assertEqual(report.steps_failed, 0)
        self.assertGreater(report.total_elapsed_ms, 0.0)
        self.assertGreater(report.token_economy_savings_pct, 40.0)
        self.assertEqual(len(report.audit_trail), 5)
        self.assertIn("Search Results Loaded", self.driver._visible_text)

    # ------------------------------------------------------------------
    # Edge Case 1: DPI scaling coordinate mapping
    # ------------------------------------------------------------------
    def test_edge_case_dpi_scaling_coordinate_mapping(self) -> None:
        """Verify coordinate translation across DPI scaling factors (1.0, 1.25, 1.5, 2.0)."""
        self.loop.step(VisualAction.navigate("https://www.google.com"))

        test_cases = [
            (1.0, 200, 150, 200, 150),
            (1.25, 200, 150, 250, 188),
            (1.5, 200, 150, 300, 225),
            (2.0, 200, 150, 400, 300),
        ]

        for scale, css_x, css_y, expected_dev_x, expected_dev_y in test_cases:
            self.driver.set_dpi_scale(scale)
            obs = self.loop.observe()
            self.assertEqual(obs.dpi_scale, scale)

            grounded = self.loop.ground(VisualAction.click_coordinate(css_x, css_y), obs)
            self.assertEqual(grounded.x, css_x)
            self.assertEqual(grounded.y, css_y)
            self.assertEqual(grounded.device_x, expected_dev_x)
            self.assertEqual(grounded.device_y, expected_dev_y)

    # ------------------------------------------------------------------
    # Edge Case 2: Network lag & backoff recovery
    # ------------------------------------------------------------------
    def test_edge_case_network_lag_backoff_recovery(self) -> None:
        """Verify recovery handles network lag and loading states gracefully."""
        self.loop.step(VisualAction.navigate("https://www.google.com"))

        # Simulate network lag flag
        self.driver._is_loading = True

        rec_attempt = self.loop.recovery.diagnose_and_recover(
            action=VisualAction.navigate("https://www.google.com"),
            verification=VerificationResult(
                is_verified=False,
                visual_diff_detected=False,
                visual_change_ratio=0.0,
                pre_hash="a",
                post_hash="a",
                reasons=["Page is loading."],
            ),
            observation=self.loop.observe(),
            grounded=None,
        )

        self.assertTrue(rec_attempt.success)
        self.assertEqual(rec_attempt.strategy, RecoveryStrategy.RETRY_WITH_BACKOFF)
        self.driver._is_loading = False

    # ------------------------------------------------------------------
    # Edge Case 3: Modal occlusion and dismissal hit-testing
    # ------------------------------------------------------------------
    def test_edge_case_modal_occlusion_and_dismissal(self) -> None:
        """Verify click hit-testing differentiates between modal dismiss button, modal body, and background."""
        self.loop.step(VisualAction.navigate("https://open-api.paytmmoney.com/dashboard"))

        self.driver.show_modal(
            modal_id="popup_promo",
            title="Promo Announcement",
            text="Exclusive offers available today.",
            dismiss_coords=(600, 350),
            dismiss_box={"x": 560.0, "y": 330.0, "width": 80.0, "height": 40.0},
        )

        obs = self.loop.observe()

        # 1. Click outside modal: background element at (50, 50) is outside modal box (300, 200, w=400, h=200)
        grounded_bg = self.loop.ground(VisualAction.click_coordinate(50, 50), obs)
        self.assertFalse(grounded_bg.is_occluded)

        # 2. Click inside modal body: (400, 250) is inside modal box but outside dismiss box -> occluded
        grounded_modal_body = self.loop.ground(VisualAction.click_coordinate(400, 250), obs)
        self.assertTrue(grounded_modal_body.is_occluded)
        self.assertEqual(grounded_modal_body.occluding_modal_id, "popup_promo")

        # 3. Click directly on dismiss button: (600, 350) is inside dismiss box -> not occluded
        grounded_dismiss = self.loop.ground(VisualAction.click_coordinate(600, 350), obs)
        self.assertFalse(grounded_dismiss.is_occluded)

        # Clicking dismiss button directly closes modal
        res_dismiss = self.driver.click_at(600, 350)
        self.assertTrue(res_dismiss.get("modal_dismissed"))
        self.assertIsNone(self.driver.active_modal)

    # ------------------------------------------------------------------
    # Edge Case 4: Focus loss detection and refocus
    # ------------------------------------------------------------------
    def test_edge_case_focus_loss_detection_and_refocus(self) -> None:
        """Verify recovery restores focus if input element loses focus during typing."""
        self.loop.step(VisualAction.navigate("https://www.google.com"))

        # Focus element 'q' at (400, 170)
        self.driver.click_at(400, 170)
        self.assertEqual(self.driver.focused_element_id, "q")

        # Blur element by clicking away to (10, 10)
        self.driver.click_at(10, 10)
        self.assertIsNone(self.driver.focused_element_id)

        # Recovery engine refocuses field and enters text
        rec = self.loop.recovery.diagnose_and_recover(
            action=VisualAction.type_coordinate(400, 170, "RECOVERED QUERY"),
            verification=VerificationResult(
                is_verified=False,
                visual_diff_detected=False,
                visual_change_ratio=0.0,
                pre_hash="h1",
                post_hash="h1",
                reasons=["Field lost focus."],
            ),
            observation=self.loop.observe(),
            grounded=None,
        )

        self.assertTrue(rec.success)
        self.assertEqual(rec.strategy, RecoveryStrategy.RESTORE_FOCUS)
        self.assertEqual(self.driver.focused_element_id, "q")
        elem = self.driver.inspect_element("q")
        assert elem is not None
        self.assertEqual(elem.get("value"), "RECOVERED QUERY")


if __name__ == "__main__":
    unittest.main()

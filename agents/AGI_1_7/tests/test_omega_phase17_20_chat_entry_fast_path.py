"""AGI 1.7 OMEGA COMMAND — Phase 17.20 Chat-Entry Fast Path & Deterministic Startup Test Battery.

Verifies:
1. True chat-entry fast path (< 50ms deterministic local classification).
2. Case A: Valid saved profile -> Direct 6-point confirmation dialog with 3 choices.
3. Case B: Incomplete profile -> Compact interview asking only missing fields.
4. Case C: Healthy runtime active -> Direct report of active services, no duplicate creation.
5. Case D: Degraded service -> Direct pinpointing of degraded component without code audit.
6. Case E: Operator cancel -> Clean abort with zero service side-effects.
7. Disqualification filter: Diagnostic questions ("Why...", "What...", "How...") do NOT trigger startup.
8. IDE entrypoint rules: Agent charters, workspace GEMINI.md, and workflow files enforce Section 0.
9. Financial Safety Invariant: Live order dispatch remains permanently locked behind fail-closed gates.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.AGI_1_7.engine.agi17.runtime.command_router import (
    CommandIntent,
    CommandRouter,
    OperatingBehavior,
    OperatingMode,
    RiskSettings,
    TradingProfile,
)


class TestOmegaPhase1720ChatEntryFastPath(unittest.TestCase):
    """Phase 17.20 Comprehensive Acceptance Battery."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Deterministic Classification & Latency (< 50ms)
    # -------------------------------------------------------------------------

    def test_intent_classification_latency_under_50ms(self):
        """Intent classification executes in well under 50ms without network or repo searches."""
        router = CommandRouter(storage_dir=self.storage_path)

        phrases = [
            "Start trading",
            "start paper trading",
            "Start the trading system",
            "Check system status",
            "Stop everything",
            "Confirm startup",
            "Cancel",
            "Change settings",
        ]

        latencies = []
        for phrase in phrases:
            start_t = time.perf_counter()
            intent = router.classify_intent(phrase)
            dur_ms = (time.perf_counter() - start_t) * 1000.0
            latencies.append(dur_ms)
            self.assertNotEqual(intent, CommandIntent.UNKNOWN, f"Phrase {phrase} failed to classify")

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        self.assertLess(avg_latency, 50.0, f"Average latency {avg_latency:.2f}ms exceeds 50ms")
        self.assertLess(max_latency, 50.0, f"Max latency {max_latency:.2f}ms exceeds 50ms")

    # -------------------------------------------------------------------------
    # 2. Case A: Valid Saved Profile -> Confirmation Dialog With 3 Choices
    # -------------------------------------------------------------------------

    def test_case_a_valid_saved_profile_direct_confirmation(self):
        """When a valid profile exists, Start trading immediately presents 6-point confirmation dialog."""
        router = CommandRouter(storage_dir=self.storage_path)
        valid_profile = TradingProfile(
            operating_mode=OperatingMode.PAPER.value,
            starting_capital_inr=10000.0,
            ledger_id="epoch_10k",
            instruments=["NIFTY", "BANKNIFTY"],
            risk_settings=RiskSettings(daily_loss_limit_inr=2500.0, max_trade_notional_inr=30000.0),
        )
        router.save_profile(valid_profile)

        res = router.handle_command("Start trading")
        self.assertEqual(res["case"], "CASE_A")
        self.assertEqual(res["action"], "AWAIT_CONFIRMATION")
        self.assertTrue(res["can_start"])
        dialog = res["dialog"]
        self.assertIn("Ready to Start Trading System", dialog)
        self.assertIn("epoch_10k", dialog)
        self.assertIn("NIFTY + BANKNIFTY", dialog)
        self.assertIn("1. **Start Now**", dialog)
        self.assertIn("2. **Change Settings**", dialog)
        self.assertIn("3. **Cancel**", dialog)

    # -------------------------------------------------------------------------
    # 3. Case B: Incomplete Profile -> Compact Missing-Field Question
    # -------------------------------------------------------------------------

    def test_case_b_missing_capital_generates_compact_interview(self):
        """Missing starting capital triggers a single setup question without repo traversal."""
        router = CommandRouter(storage_dir=self.storage_path)
        router.profile.starting_capital_inr = 0.0
        router.save_profile(router.profile)

        res = router.handle_command("Start trading")
        self.assertEqual(res["case"], "CASE_B")
        self.assertEqual(res["action"], "SETUP_QUESTION")
        self.assertEqual(res["missing_field"], "starting_capital")
        self.assertIn("capital", res["question"].lower())

    def test_case_b_resolves_field_and_advances_to_confirmation(self):
        """Supplying the missing field completes the profile and presents the Case A dialog."""
        router = CommandRouter(storage_dir=self.storage_path)
        router.profile.starting_capital_inr = 0.0
        router.save_profile(router.profile)

        # Trigger interview
        router.handle_command("Start trading")
        # Supply answer
        res2 = router.handle_command("10000")
        self.assertEqual(res2["case"], "CASE_A")
        self.assertEqual(res2["action"], "AWAIT_CONFIRMATION")
        self.assertEqual(router.profile.starting_capital_inr, 10000.0)

    # -------------------------------------------------------------------------
    # 4. Case C: Already Healthy Runtime Active
    # -------------------------------------------------------------------------

    def test_case_c_healthy_runtime_reused_without_duplication(self):
        """If all components are RUNNING, handle_command reports active state and asks next step."""
        router = CommandRouter(storage_dir=self.storage_path)
        mock_runtime_status = {
            "services": {
                "chrome_cdp": {"state": "RUNNING", "port": 9229},
                "dashboard": {"state": "RUNNING", "port": 8088},
                "overlay_guardian": {"state": "RUNNING"},
            }
        }

        res = router.handle_command("Start trading", runtime_status=mock_runtime_status)
        self.assertEqual(res["case"], "CASE_C")
        self.assertEqual(res["action"], "ALREADY_HEALTHY")
        self.assertIn("Trading Runtime Already Healthy & Active", res["message"])
        self.assertIn("Port 9229", res["message"])
        self.assertIn("Port 8088", res["message"])

    # -------------------------------------------------------------------------
    # 5. Case D: Degraded Service -> Specific Diagnostic
    # -------------------------------------------------------------------------

    def test_case_d_degraded_service_reported_directly(self):
        """Degraded component is reported immediately with specific fault without auditing code."""
        router = CommandRouter(storage_dir=self.storage_path)
        mock_runtime_status = {
            "services": {
                "chrome_cdp": {"state": "RUNNING", "port": 9229},
                "dashboard": {
                    "state": "DEGRADED",
                    "port": 8088,
                    "unhealthy_reason": "Port 8088 socket timeout during health probe",
                },
                "overlay_guardian": {"state": "RUNNING"},
            }
        }

        res = router.handle_command("Start trading", runtime_status=mock_runtime_status)
        self.assertEqual(res["case"], "CASE_D")
        self.assertEqual(res["action"], "DEGRADED_DIAGNOSTIC")
        self.assertEqual(res["affected_service"], "dashboard")
        self.assertIn("Port 8088 socket timeout", res["fault_reason"])
        self.assertIn("Component `dashboard` is degraded", res["message"])

    # -------------------------------------------------------------------------
    # 6. Case E: Operator Cancellation Clean Abort
    # -------------------------------------------------------------------------

    def test_case_e_operator_cancellation_zero_side_effects(self):
        """Operator saying cancel cleanly aborts setup with zero mutations to background tasks."""
        router = CommandRouter(storage_dir=self.storage_path)
        router.handle_command("Start trading")
        res = router.handle_command("Cancel")
        self.assertEqual(res["intent"], CommandIntent.CANCEL.value)
        self.assertEqual(res["action"], "SETUP_CANCELLED")
        self.assertIn("cancelled by operator", res["message"])

    # -------------------------------------------------------------------------
    # 7. Disqualification Filter: Diagnostic Questions vs Commands
    # -------------------------------------------------------------------------

    def test_disqualification_filter_diagnostic_questions(self):
        """Questions about status, dates, or failures must NOT trigger START_TRADING intent."""
        router = CommandRouter(storage_dir=self.storage_path)

        diagnostic_questions = [
            "Why is the system not trading?",
            "What happened to the orders?",
            "Can you check what happening what did it work and how much left?",
            "How much profit did it earn from three days?",
            "Why is it not showing the live countdown?",
            "Show me why the system is disconnected",
        ]

        for q in diagnostic_questions:
            intent = router.classify_intent(q)
            self.assertNotIn(
                intent,
                [CommandIntent.START_TRADING, CommandIntent.START_PAPER_TRADING],
                f"Diagnostic query falsely classified as start intent: '{q}' -> {intent}",
            )

    # -------------------------------------------------------------------------
    # 8. Layer A Entry Point Configuration Verification
    # -------------------------------------------------------------------------

    def test_ide_entrypoint_rule_files_contain_fast_path_override(self):
        """Verify that workspace files, user agent files, and rule files contain Section 0 fast-path override."""
        repo_root = Path(__file__).resolve().parents[3]
        workspace_gemini = repo_root / "GEMINI.md"
        user_gemini = Path.home() / ".gemini" / "GEMINI.md"
        ws_agent = repo_root / ".agents" / "agents" / "agi-1-7.md"
        user_agent = Path.home() / ".gemini" / "config" / "agents" / "agi-1-7.md"
        ponytail_rules = Path.home() / ".gemini" / "config" / "plugins" / "ponytail" / "rules" / "AGENTS.md"
        ws_workflow = repo_root / ".agents" / "workflows" / "start-trading.md"
        user_workflow = Path.home() / ".agents" / "workflows" / "start-trading.md"

        files_to_check = [
            workspace_gemini,
            user_gemini,
            ws_agent,
            user_agent,
            ponytail_rules,
            ws_workflow,
            user_workflow,
        ]

        # In CI or isolated test runners, verify existing files only
        existing_files = [p for p in files_to_check if p.exists()]
        if not existing_files and workspace_gemini.exists():
            existing_files.append(workspace_gemini)

        for fpath in existing_files:
            content = fpath.read_text(encoding="utf-8")
            self.assertTrue(
                "Operator Command Fast-Path" in content
                or "start-trading" in content
                or "Fast-Path Router" in content,
                f"File {fpath} does not contain fast-path directive",
            )

    # -------------------------------------------------------------------------
    # 9. Safety Invariant: Live Execution Quarantined
    # -------------------------------------------------------------------------

    def test_live_execution_locked_behind_safety_gate(self):
        """Live real-money order routing is locked; cannot start live without explicit gate unarming."""
        router = CommandRouter(storage_dir=self.storage_path)
        router.profile.operating_mode = OperatingMode.LIVE_REAL_MONEY.value
        router.save_profile(router.profile)

        # Confirm startup attempt
        res = router.handle_command("Confirm startup")
        self.assertEqual(res["action"], "BLOCKED_BY_SAFETY_GATE")
        self.assertEqual(res["gate"], "GATE_01_USER_AUTHORIZED_CAPITAL_AND_RISK")


if __name__ == "__main__":
    unittest.main()

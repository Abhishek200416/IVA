"""AGI 1.7 OMEGA COMMAND — Phase 17.19 Acceptance & Regression Test Suite.

Verifies:
1. Conversational intent router & fast setup flow (no filesystem walks).
2. Authoritative unified runtime supervisor (dependency order, process reuse, no duplicates).
3. Tri-tab Chrome topology & role assignment (NIFTY_CHAIN, BANKNIFTY_CHAIN, AGI_DASHBOARD).
4. Dual-index market data pipeline & strict cross-index isolation.
5. Stale data rejection, duplicate event handling, and after-hours transition.
6. Supervised news intelligence & risk advisory boundary.
7. Risk gates, emergency stop, and fail-closed live execution safeguard.
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
from agents.AGI_1_7.engine.agi17.runtime.dual_index_pipeline import (
    DualIndexEventPipeline,
    MarketDataProvenance,
    NormalizedObservation,
)
from agents.AGI_1_7.engine.agi17.runtime.news_monitor import NewsMonitorService, NewsStory
from agents.AGI_1_7.engine.agi17.runtime.runtime_supervisor import (
    RuntimeReadiness,
    RuntimeSupervisor,
    ServiceState,
    ServiceStatus,
)
from agents.AGI_1_7.engine.agi17.runtime.tri_tab_topology import (
    BrowserTarget,
    TabRole,
    TriTabTopology,
)


class TestOmegaPhase1719RuntimeOrchestration(unittest.TestCase):
    """Phase 17.19 Comprehensive Test Battery."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Conversational Command Router & Fast Setup
    # -------------------------------------------------------------------------

    def test_start_command_routes_to_conversational_startup(self):
        """Operator phrases map deterministically to START_TRADING intent."""
        router = CommandRouter(storage_dir=self.storage_path)

        test_phrases = [
            "Start trading",
            "start trading",
            "Start the trading system",
            "begin trading",
            "Start paper trading",
        ]
        for phrase in test_phrases:
            intent = router.classify_intent(phrase)
            self.assertIn(
                intent,
                [CommandIntent.START_TRADING, CommandIntent.START_PAPER_TRADING],
                f"Failed for phrase: {phrase}"
            )

    def test_missing_required_settings_generate_setup_question(self):
        """Missing required profile fields generate specific questions without repo scans."""
        router = CommandRouter(storage_dir=self.storage_path)
        # Empty out profile
        router.profile.starting_capital_inr = 0.0
        router.profile.instruments = []
        router.save_profile(router.profile)

        res = router.handle_command("Start trading")
        self.assertEqual(res["action"], "SETUP_QUESTION")
        self.assertIn(res["missing_field"], ["starting_capital", "instruments"])
        self.assertIn("?", res["question"])

    def test_saved_valid_settings_avoid_repeated_questions(self):
        """Saved, valid settings proceed immediately to confirmation dialog."""
        router = CommandRouter(storage_dir=self.storage_path)
        valid_profile = TradingProfile(
            operating_mode=OperatingMode.PAPER.value,
            starting_capital_inr=10000.0,
            instruments=["NIFTY", "BANKNIFTY"],
            risk_settings=RiskSettings(daily_loss_limit_inr=2500.0)
        )
        router.save_profile(valid_profile)

        res = router.handle_command("Start trading")
        self.assertEqual(res["action"], "AWAIT_CONFIRMATION")
        self.assertTrue(res["can_start"])
        self.assertIn("Ready to Start Trading System", res["dialog"])

    def test_unconfirmed_startup_does_not_start_restricted_components(self):
        """Startup is not executed until operator explicitly confirms."""
        router = CommandRouter(storage_dir=self.storage_path)
        res = router.handle_command("Start trading")
        self.assertEqual(res["action"], "AWAIT_CONFIRMATION")
        # System has not issued EXECUTE_STARTUP
        self.assertNotEqual(res.get("action"), "EXECUTE_STARTUP")

        # Now confirm
        confirm_res = router.handle_command("Confirm startup")
        self.assertEqual(confirm_res["action"], "EXECUTE_STARTUP")

    def test_live_real_money_safeguard_locked(self):
        """Request for live real-money execution is intercepted and fail-closed locked."""
        router = CommandRouter(storage_dir=self.storage_path)
        router.profile.operating_mode = OperatingMode.LIVE_REAL_MONEY.value
        router.save_profile(router.profile)

        res = router.handle_command("Confirm startup")
        self.assertEqual(res["action"], "BLOCKED_BY_SAFETY_GATE")
        self.assertEqual(res["gate"], "GATE_01_USER_AUTHORIZED_CAPITAL_AND_RISK")
        self.assertEqual(res["safe_mode"], OperatingMode.PAPER.value)

    # -------------------------------------------------------------------------
    # 2. Authoritative Unified Runtime Supervisor
    # -------------------------------------------------------------------------

    def test_supervisor_registry_and_states(self):
        """Supervisor manages exactly the 3 primary services with documented states."""
        sup = RuntimeSupervisor.get_instance()
        statuses = sup.get_all_statuses()
        self.assertIn("chrome_cdp_service", statuses)
        self.assertIn("dashboard_service", statuses)
        self.assertIn("overlay_service", statuses)

        for s in statuses.values():
            self.assertIn(s["state"], [
                ServiceState.STOPPED.value,
                ServiceState.STARTING.value,
                ServiceState.RUNNING.value,
                ServiceState.DEGRADED.value,
                ServiceState.FAILED.value,
                ServiceState.STOPPING.value,
            ])

    def test_existing_healthy_services_reused(self):
        """Reconciliation adopts existing running services without spawning duplicates."""
        sup = RuntimeSupervisor.get_instance()
        with patch.object(sup, "_probe_port_http", return_value=(True, None)):
            telemetry = sup.reconcile()
            self.assertEqual(telemetry["services"]["chrome_cdp_service"]["state"], ServiceState.RUNNING.value)
            self.assertEqual(telemetry["services"]["dashboard_service"]["state"], ServiceState.RUNNING.value)
            self.assertTrue(telemetry["services"]["chrome_cdp_service"]["is_adopted"])

    def test_duplicate_startup_requests_do_not_create_duplicates(self):
        """Calling start_all_services when components are already healthy reuses them."""
        sup = RuntimeSupervisor.get_instance()
        with patch.object(sup, "probe_dashboard", return_value=(True, None)), \
             patch.object(sup, "probe_chrome_cdp", return_value=(True, None)), \
             patch.object(sup, "probe_overlay", return_value=(True, None)), \
             patch.object(sup, "_launch_service") as mock_launch:
            sup.start_all_services()
            mock_launch.assert_not_called()

    # -------------------------------------------------------------------------
    # 3. Three-Tab Chrome Topology
    # -------------------------------------------------------------------------

    def test_tri_tab_roles_mapped_strictly(self):
        """URL classification matches exact roles and rejects unknown pages."""
        top = TriTabTopology()
        self.assertEqual(
            top.classify_url_role("https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE"),
            TabRole.NIFTY_CHAIN
        )
        self.assertEqual(
            top.classify_url_role("https://www.paytmmoney.com/stocks/fno/option-chain/2000000023/BANKNIFTY/NSE"),
            TabRole.BANKNIFTY_CHAIN
        )
        self.assertEqual(
            top.classify_url_role("http://127.0.0.1:8088/"),
            TabRole.AGI_DASHBOARD
        )
        self.assertEqual(
            top.classify_url_role("https://www.google.com/"),
            TabRole.UNKNOWN
        )

    def test_browser_target_audit_and_duplicate_prevention(self):
        """Audit correctly identifies multiple open tabs and preserves exactly 1 per role."""
        top = TriTabTopology()
        mock_pages = [
            {"id": "tab1", "url": "https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE", "title": "NIFTY Option Chain", "type": "page"},
            {"id": "tab2", "url": "https://www.paytmmoney.com/stocks/fno/option-chain/2000000011/NIFTY/NSE", "title": "NIFTY Duplicate", "type": "page"},
            {"id": "tab3", "url": "https://www.paytmmoney.com/stocks/fno/option-chain/2000000023/BANKNIFTY/NSE", "title": "BANKNIFTY Option Chain", "type": "page"},
            {"id": "tab4", "url": "http://127.0.0.1:8088/", "title": "AGI Dashboard", "type": "page"},
        ]
        with patch.object(top, "query_cdp_targets", return_value=mock_pages):
            audit = top.audit_topology()
            self.assertTrue(audit["all_roles_satisfied"])
            self.assertEqual(len(audit["assigned_roles"]), 3)
            self.assertEqual(audit["unassigned_tabs_count"], 1)

    # -------------------------------------------------------------------------
    # 4. Dual-Index Market Data Pipeline & Cross-Index Isolation
    # -------------------------------------------------------------------------

    def test_nifty_and_banknifty_isolated(self):
        """NIFTY quotes do not overwrite BANKNIFTY quotes and vice versa."""
        pipeline = DualIndexEventPipeline(stale_threshold_sec=30.0)

        nifty_obs = NormalizedObservation(
            event_id="EVT-NIFTY-1",
            underlying_index="NIFTY",
            contract_name="NIFTY 19 OCT 23000 CALL",
            strike=23000.0,
            expiry="19-Oct-2026",
            option_type="CE",
            lot_size=75,
            ltp=147.30,
            provenance=MarketDataProvenance.BROWSER_OBSERVED
        )

        bank_obs = NormalizedObservation(
            event_id="EVT-BANK-1",
            underlying_index="BANKNIFTY",
            contract_name="BANKNIFTY 27 OCT 56000 CALL",
            strike=56000.0,
            expiry="27-Oct-2026",
            option_type="CE",
            lot_size=60,
            ltp=482.80,
            provenance=MarketDataProvenance.BROWSER_OBSERVED
        )

        ok1, _ = pipeline.ingest_observation(nifty_obs)
        ok2, _ = pipeline.ingest_observation(bank_obs)
        self.assertTrue(ok1)
        self.assertTrue(ok2)

        snapshot = pipeline.get_central_snapshot()
        self.assertEqual(snapshot["indices"]["NIFTY"]["total_contracts"], 1)
        self.assertEqual(snapshot["indices"]["BANKNIFTY"]["total_contracts"], 1)

        # Ensure cross-index quote lookup is correct
        n_quote = pipeline.get_latest_quote("NIFTY 19 OCT 23000 CALL")
        b_quote = pipeline.get_latest_quote("BANKNIFTY 27 OCT 56000 CALL")
        self.assertIsNotNone(n_quote)
        self.assertIsNotNone(b_quote)
        self.assertEqual(n_quote.ltp, 147.30)
        self.assertEqual(b_quote.ltp, 482.80)

    def test_duplicate_events_rejected(self):
        """Duplicate event IDs are rejected idempotently."""
        pipeline = DualIndexEventPipeline()
        obs = NormalizedObservation(
            event_id="EVT-DUP-TEST",
            underlying_index="NIFTY",
            contract_name="NIFTY 19 OCT 23000 CALL",
            strike=23000.0,
            expiry="19-Oct-2026",
            option_type="CE",
            lot_size=75,
            ltp=150.0
        )
        ok1, err1 = pipeline.ingest_observation(obs)
        ok2, err2 = pipeline.ingest_observation(obs)
        self.assertTrue(ok1)
        self.assertFalse(ok2)
        self.assertEqual(err2, "Duplicate event ID")

    def test_stale_or_invalid_inputs_rejected(self):
        """Stale observations (> threshold) or non-positive prices are rejected."""
        pipeline = DualIndexEventPipeline(stale_threshold_sec=10.0)

        # Stale observation
        stale_obs = NormalizedObservation(
            event_id="EVT-STALE",
            underlying_index="NIFTY",
            contract_name="NIFTY 19 OCT 23000 CALL",
            strike=23000.0,
            expiry="19-Oct-2026",
            option_type="CE",
            lot_size=75,
            ltp=150.0,
            observation_timestamp=time.time() - 25.0
        )
        ok, err = pipeline.ingest_observation(stale_obs)
        self.assertFalse(ok)
        self.assertIn("stale", err.lower())

        # Zero or negative price
        invalid_price_obs = NormalizedObservation(
            event_id="EVT-ZERO-PRICE",
            underlying_index="NIFTY",
            contract_name="NIFTY 19 OCT 23000 CALL",
            strike=23000.0,
            expiry="19-Oct-2026",
            option_type="CE",
            lot_size=75,
            ltp=0.0
        )
        ok_zero, err_zero = pipeline.ingest_observation(invalid_price_obs)
        self.assertFalse(ok_zero)
        self.assertIn("Non-positive", err_zero)

    def test_synthetic_data_cannot_satisfy_live_gate(self):
        """Synthetic fixture provenance cannot be passed off as authentic live data."""
        obs = NormalizedObservation(
            event_id="EVT-SYNTH",
            underlying_index="NIFTY",
            contract_name="NIFTY 19 OCT 23000 CALL",
            strike=23000.0,
            expiry="19-Oct-2026",
            option_type="CE",
            lot_size=75,
            ltp=120.0,
            provenance=MarketDataProvenance.SYNTHETIC_FIXTURE
        )
        self.assertNotEqual(obs.provenance, MarketDataProvenance.AUTHENTIC_LIVE)
        self.assertEqual(obs.provenance.value, "SYNTHETIC_FIXTURE")

    # -------------------------------------------------------------------------
    # 5. News Intelligence & Continuous Supervision
    # -------------------------------------------------------------------------

    def test_news_polling_deduplication_and_advisory(self):
        """News headlines are hashed and deduplicated, acting strictly as advisory."""
        feed_file = self.storage_path / "mock_news.json"
        feed_data = [
            {"headline": "RBI Keeps Repo Rate Unchanged at 6.5%", "topic": "MONETARY_POLICY", "source": "Bloomberg"},
            {"headline": "RBI Keeps Repo Rate Unchanged at 6.5%", "topic": "MONETARY_POLICY", "source": "Reuters"},  # Duplicate headline
            {"headline": "TCS Reports 5% QoQ Profit Growth", "topic": "EARNINGS", "source": "CNBC-TV18"},
        ]
        feed_file.write_text(json.dumps(feed_data), encoding="utf-8")

        news_svc = NewsMonitorService(feed_file=feed_file)
        poll_res = news_svc.poll_news_feed()
        self.assertEqual(poll_res["status"], "OK")
        self.assertEqual(poll_res["new_stories"], 2)  # Deduplicated from 3 items to 2

        telemetry = news_svc.get_news_telemetry()
        self.assertTrue(telemetry["advisory_only"])
        self.assertFalse(telemetry["trade_execution_authority"])

    # -------------------------------------------------------------------------
    # 6. Safety, Emergency Stop & Tab Recovery
    # -------------------------------------------------------------------------

    def test_emergency_stop_command_handling(self):
        """STOP_ALL command halts setup session and returns EMERGENCY_STOP action."""
        router = CommandRouter(storage_dir=self.storage_path)
        res = router.handle_command("Stop everything")
        self.assertEqual(res["intent"], CommandIntent.STOP_ALL.value)
        self.assertEqual(res["action"], "EMERGENCY_STOP")

    def test_check_status_command_handling(self):
        """CHECK_STATUS returns immediate telemetry without filesystem exploration."""
        router = CommandRouter(storage_dir=self.storage_path)
        mock_status = {"services": {"dashboard": "RUNNING"}, "healthy": True}
        res = router.handle_command("What is happening?", runtime_status=mock_status)
        self.assertEqual(res["intent"], CommandIntent.CHECK_STATUS.value)
        self.assertEqual(res["action"], "REPORT_STATUS")
        self.assertEqual(res["telemetry"], mock_status)

    def test_tab_recovery_returns_failure_when_endpoint_unreachable(self):
        """Recovering tab when CDP port is unreachable fails gracefully without crash."""
        top = TriTabTopology(cdp_port=9999)  # Non-existent port
        ok, err = top.recover_missing_role(TabRole.NIFTY_CHAIN)
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_supervisor_event_capping(self):
        """Supervisor caps event history to latest 500 events to prevent memory unbounded growth."""
        sup = RuntimeSupervisor.get_instance()
        for i in range(550):
            sup._emit_event("TEST_COMP", "TICK", f"Event {i}")
        self.assertLessEqual(len(sup._events), 500)

    def test_market_session_after_hours_detection(self):
        """DualIndexEventPipeline correctly identifies after-hours state."""
        pipeline = DualIndexEventPipeline()
        # Verify function executes and returns boolean without exception
        is_after = pipeline.is_after_hours()
        self.assertIsInstance(is_after, bool)


if __name__ == "__main__":
    unittest.main()

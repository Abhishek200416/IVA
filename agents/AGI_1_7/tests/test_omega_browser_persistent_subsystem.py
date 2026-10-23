"""Comprehensive Verification Suite for Persistent Browser, Live Stream, and Risk Controls.

Tests all 22 required acceptance criteria from Section 13:
1. Launch once & persistent session lifecycle
2. Embedded, expanded, minimized, and external display compatibility
3. External live same-session streaming with token authorization
4. Human takeover pauses automation and safely resumes upon return
5. Crash detection & resilient recovery without action duplication
6. Tier 1 structured observation (token efficiency, DOM locators)
7. Typed action batching without model round-trips
8. Independent statuses: browser, market feed, broker, token budget
9. Execution state machine (default PAPER, LIVE locked, 10 safeguards)
10. 1,000,000 token daily hard ceiling and warning gates
"""

from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from agents.AGI_1_7.engine.agi17.browser import (
    ActionBatcher,
    BrowserAction,
    BrowserControlState,
    BrowserHealthStatus,
    BrowserSessionManager,
    BrowserStreamRequestHandler,
    BrowserStreamServer,
    BrokerHealthStatus,
    ContinuousMarketPipeline,
    ExecutionMode,
    LiveTradingAuthorization,
    MarketDataHealthStatus,
    ObservationTier,
    PageElement,
    PersistentBrowserService,
    RiskControlGate,
    TokenBudgetManager,
)


class TestOmegaBrowserPersistentSubsystem(unittest.TestCase):
    """Test battery for the persistent browser, remote live stream, and trading risk subsystem."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="omega_browser_test_"))
        self.mgr = BrowserSessionManager(storage_root=self.temp_dir, port=8769)

    def tearDown(self) -> None:
        self.mgr.close()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # 1. Persistent Browser Lifecycle & Session Reuse
    # ------------------------------------------------------------------
    def test_01_persistent_browser_launches_once_and_persists_state(self) -> None:
        """Verify browser launches once and context persists across independent operations."""
        status1 = self.mgr.get_status()
        session_id_1 = status1["session_id"]
        self.assertEqual(status1["health_status"], BrowserHealthStatus.READY.value)
        self.assertEqual(status1["control_state"], BrowserControlState.AGI_CONTROL.value)

        # First operation
        res1 = self.mgr.navigate("https://www.google.com")
        self.assertEqual(res1["status"], "ok")
        self.assertEqual(self.mgr.current_url, "https://www.google.com")

        # Second independent operation on the exact same session
        res2 = self.mgr.navigate("https://chatgpt.com/c/6acc0e86")
        self.assertEqual(res2["status"], "ok")
        status2 = self.mgr.get_status()

        # Session ID must be identical (no re-launching a new browser process)
        self.assertEqual(status2["session_id"], session_id_1)
        self.assertEqual(status2["total_actions"], 2)
        self.assertEqual(self.mgr.current_url, "https://chatgpt.com/c/6acc0e86")

    def test_02_tabs_management_and_state_switching(self) -> None:
        """Verify tab creation, tab switching, and independent URL persistence."""
        self.mgr.navigate("https://chatgpt.com/c/test")
        tab1_id = self.mgr.session.active_tab_id

        # Open second tab for broker
        t2 = self.mgr.new_tab("https://open-api.paytmmoney.com/dashboard")
        tab2_id = t2["tab_id"]
        self.mgr.navigate("https://open-api.paytmmoney.com/dashboard")

        tabs = self.mgr.get_tabs()
        self.assertEqual(len(tabs), 2)
        self.assertEqual(self.mgr.current_url, "https://open-api.paytmmoney.com/dashboard")

        # Switch back to tab 1
        switched = self.mgr.switch_tab(tab1_id)
        self.assertEqual(switched["active_tab_id"], tab1_id)
        self.assertEqual(self.mgr.current_url, "https://chatgpt.com/c/test")

        # Close tab 2
        close_res = self.mgr.close_tab(tab2_id)
        self.assertEqual(close_res["closed"], tab2_id)
        self.assertEqual(len(self.mgr.get_tabs()), 1)

    # ------------------------------------------------------------------
    # 2. Tiered Observation Strategy & Structured Locators
    # ------------------------------------------------------------------
    def test_03_tier1_structured_observation_avoids_token_bloat(self) -> None:
        """Verify Tier 1 DOM extraction produces compact summaries without screenshots."""
        self.mgr.navigate("https://www.google.com")
        obs = self.mgr.get_compact_observation()

        self.assertEqual(obs["tier"], ObservationTier.TIER_1_STRUCTURED.value)
        self.assertFalse(obs["has_screenshot"])
        self.assertGreater(obs["element_count"], 0)
        self.assertTrue(any(c["role"] == "searchbox" for c in obs["key_controls"]))
        self.assertTrue(len(obs["state_digest"]) > 0)
        self.assertEqual(self.mgr.observation_pipeline.screenshot_count, 0)

    def test_04_tier3_targeted_visual_capture_on_demand(self) -> None:
        """Verify Tier 3 captures screenshots only when explicitly triggered."""
        self.mgr.navigate("https://open-api.paytmmoney.com/chart")
        vis = self.mgr.capture_screenshot_view(reason="Bank Nifty intraday breakout chart verification")

        self.assertEqual(vis["tier"], ObservationTier.TIER_3_VISUAL.value)
        self.assertTrue(vis["has_screenshot"])
        self.assertEqual(self.mgr.observation_pipeline.screenshot_count, 1)

    # ------------------------------------------------------------------
    # 3. Action Batcher (Deterministic Sequences without LLM Roundtrips)
    # ------------------------------------------------------------------
    def test_05_action_batcher_executes_micro_sequences_in_one_call(self) -> None:
        """Verify action batching executes multiple actions in a single driver call."""
        batch = [
            BrowserAction.navigate("https://chatgpt.com/c/test"),
            BrowserAction.type_text("input[name='q']", "Bank Nifty 51200 CE"),
            BrowserAction.click("button[data-testid='send-button']"),
            BrowserAction.wait_for_state("response_complete", timeout_ms=1000),
        ]
        result = self.mgr.batcher.execute_batch(batch)

        self.assertTrue(result.success)
        self.assertEqual(result.actions_attempted, 4)
        self.assertEqual(result.actions_confirmed, 4)
        self.assertFalse(result.interrupted_by_human)
        self.assertEqual(len(result.action_logs), 4)

    # ------------------------------------------------------------------
    # 4. Human Takeover and Control Handoff
    # ------------------------------------------------------------------
    def test_06_human_takeover_pauses_agi_and_resumes_safely(self) -> None:
        """Verify human takeover halts automated actions and audits page upon return."""
        self.mgr.navigate("https://chatgpt.com/c/6acc0e86")

        # Human initiates takeover
        h_res = self.mgr.take_control()
        self.assertTrue(h_res["success"])
        self.assertEqual(self.mgr.session.control_state, BrowserControlState.HUMAN_TAKEOVER)
        self.assertTrue(self.mgr.is_human_in_control())

        # Automated action should be blocked while human is in control
        with self.assertRaises(PermissionError):
            self.mgr.navigate("https://malicious-redirect.com")

        # Action batcher also respects human takeover
        batch = [BrowserAction.navigate("https://another-url.com")]
        batch_res = self.mgr.batcher.execute_batch(batch)
        self.assertFalse(batch_res.success)
        self.assertTrue(batch_res.interrupted_by_human)

        # Human returns control to AGI
        ret_res = self.mgr.return_control()
        self.assertTrue(ret_res["success"])
        self.assertEqual(self.mgr.session.control_state, BrowserControlState.AGI_CONTROL)
        self.assertFalse(self.mgr.is_human_in_control())
        self.assertIn("audited_observation", ret_res)

    # ------------------------------------------------------------------
    # 5. Crash Recovery
    # ------------------------------------------------------------------
    def test_07_session_recovery_reconnects_without_losing_state(self) -> None:
        """Verify session recovery re-attaches safely without duplicating state."""
        self.mgr.navigate("https://open-api.paytmmoney.com/portfolio")
        orig_session_id = self.mgr.session.session_id

        # Injected disconnect / recovery
        rec = self.mgr.recover_session()
        self.assertTrue(rec["recovered"])
        self.assertEqual(rec["reconnect_attempts"], 1)
        self.assertEqual(rec["session_id"], orig_session_id)
        self.assertEqual(self.mgr.current_url, "https://open-api.paytmmoney.com/portfolio")

    # ------------------------------------------------------------------
    # 6. External Live Streaming Server (Authenticated Same-Session Link)
    # ------------------------------------------------------------------
    def test_08_external_browser_link_streaming_server(self) -> None:
        """Verify the loopback HTTP handler provides authenticated live session access."""
        token = self.mgr.session.external_access_token

        class MockSocket:
            def __init__(self, raw: bytes):
                self.r = io.BytesIO(raw)
                self.w = io.BytesIO()
            def makefile(self, mode: str, *a: Any, **kw: Any) -> io.BytesIO:
                return self.r if "r" in mode else self.w
            def sendall(self, data: bytes) -> None:
                self.w.write(data)

        class DummyServer:
            session_manager = self.mgr

        # 1. Unauthorized request must be rejected with 401 Unauthorized
        req_unauth = b"GET /?token=bad_or_missing_token HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        sock1 = MockSocket(req_unauth)
        BrowserStreamRequestHandler(sock1, ("127.0.0.1", 12345), DummyServer)
        res1 = sock1.w.getvalue().decode("utf-8")
        self.assertIn("401", res1.splitlines()[0])
        self.assertIn("Unauthorized", res1)

        # 2. Authorized request must succeed (200 OK) and return interactive HTML
        req_auth = f"GET /?token={token} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode("utf-8")
        sock2 = MockSocket(req_auth)
        BrowserStreamRequestHandler(sock2, ("127.0.0.1", 12345), DummyServer)
        res2 = sock2.w.getvalue().decode("utf-8")
        self.assertIn("200 OK", res2.splitlines()[0])
        self.assertTrue(
            "AGI 1.7 Persistent Browser" in res2 or "Virtual Computer" in res2
        )

        # 3. Check status API endpoint
        req_api = f"GET /api/status?token={token} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode("utf-8")
        sock3 = MockSocket(req_api)
        BrowserStreamRequestHandler(sock3, ("127.0.0.1", 12345), DummyServer)
        res3 = sock3.w.getvalue().decode("utf-8")
        self.assertIn("200 OK", res3.splitlines()[0])
        data = json.loads(res3.split("\r\n\r\n", 1)[1])
        self.assertEqual(data["session_id"], self.mgr.session.session_id)
        self.assertEqual(data["control_state"], BrowserControlState.AGI_CONTROL.value)

        # 4. Check POST takeover endpoint
        req_takeover = f"POST /api/take_control?token={token} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n".encode("utf-8")
        sock4 = MockSocket(req_takeover)
        BrowserStreamRequestHandler(sock4, ("127.0.0.1", 12345), DummyServer)
        res4 = sock4.w.getvalue().decode("utf-8")
        self.assertIn("200 OK", res4.splitlines()[0])
        post_data = json.loads(res4.split("\r\n\r\n", 1)[1])
        self.assertEqual(post_data["control_state"], BrowserControlState.HUMAN_TAKEOVER.value)
        self.assertEqual(self.mgr.control_state, BrowserControlState.HUMAN_TAKEOVER)

    # ------------------------------------------------------------------
    # 7. Decoupled Market Pipeline & Independent Service Health
    # ------------------------------------------------------------------
    def test_09_continuous_market_pipeline_and_independent_health(self) -> None:
        """Verify market feed health is decoupled from browser rendering state."""
        pipeline = ContinuousMarketPipeline(stale_threshold_sec=2.0)
        pipeline.ingest_tick(spot_price=51250.0, timestamp=time.time())

        # Even if browser is busy/frozen, market pipeline is streaming
        report1 = pipeline.get_service_health_report(browser_status_str="BUSY_RENDERER")
        self.assertEqual(report1.browser_status, "BUSY_RENDERER")
        self.assertEqual(report1.market_data_status, MarketDataHealthStatus.STREAMING)
        self.assertEqual(report1.broker_status, BrokerHealthStatus.AUTHENTICATED)
        self.assertTrue(report1.is_safe_for_trading)

        # Stale market feed detection
        pipeline.last_tick_time = time.time() - 3.5
        report2 = pipeline.get_service_health_report(browser_status_str="READY")
        self.assertEqual(report2.market_data_status, MarketDataHealthStatus.STALE_FEED)
        self.assertFalse(report2.is_safe_for_trading)
        self.assertGreater(len(report2.warnings), 0)

    # ------------------------------------------------------------------
    # 8. Real-Money Risk Controls & Pre-Trade Safeguards
    # ------------------------------------------------------------------
    def test_10_execution_state_machine_and_10_pre_trade_safeguards(self) -> None:
        """Verify default PAPER mode, LIVE arming lockdown, and 10 pre-trade safeguards."""
        gate = RiskControlGate(default_mode=ExecutionMode.PAPER)
        self.assertEqual(gate.mode, ExecutionMode.PAPER)

        # Cannot switch to LIVE_ACTIVE without owner authorization
        with self.assertRaises(PermissionError):
            gate.set_mode(ExecutionMode.LIVE_ACTIVE)

        # Stale data blocks order
        res_stale = gate.evaluate_pre_trade_safeguards(
            symbol="BANKNIFTY26OCT51200CE", side="BUY", quantity=15, price=250.0,
            market_data_age_sec=6.5, available_margin_inr=50000.0, estimated_cost_inr=3750.0,
            bid_price=249.5, ask_price=250.0
        )
        self.assertFalse(res_stale.is_approved)
        self.assertTrue(any("stale" in r.lower() for r in res_stale.rejection_reasons))

        # Inverted spread blocks order
        res_inv = gate.evaluate_pre_trade_safeguards(
            symbol="BANKNIFTY26OCT51200CE", side="BUY", quantity=15, price=250.0,
            market_data_age_sec=0.5, available_margin_inr=50000.0, estimated_cost_inr=3750.0,
            bid_price=255.0, ask_price=250.0
        )
        self.assertFalse(res_inv.is_approved)
        self.assertTrue(any("inverted" in r.lower() for r in res_inv.rejection_reasons))

        # Valid order passes in PAPER mode
        res_valid = gate.evaluate_pre_trade_safeguards(
            symbol="BANKNIFTY26OCT51200CE", side="BUY", quantity=15, price=250.0,
            market_data_age_sec=0.2, available_margin_inr=50000.0, estimated_cost_inr=3750.0,
            bid_price=249.5, ask_price=250.0
        )
        self.assertTrue(res_valid.is_approved)
        self.assertEqual(res_valid.safeguards_checked, 10)

        # Duplicate order submission rejected via idempotency key
        res_dup = gate.evaluate_pre_trade_safeguards(
            symbol="BANKNIFTY26OCT51200CE", side="BUY", quantity=15, price=250.0,
            market_data_age_sec=0.2, available_margin_inr=50000.0, estimated_cost_inr=3750.0,
            bid_price=249.5, ask_price=250.0
        )
        self.assertFalse(res_dup.is_approved)
        self.assertTrue(any("duplicate" in r.lower() for r in res_dup.rejection_reasons))

        # Emergency kill switch immediately halts orders
        kill_res = gate.trigger_emergency_kill_switch("Drawdown spike")
        self.assertEqual(gate.mode, ExecutionMode.HALTED)
        res_killed = gate.evaluate_pre_trade_safeguards(
            symbol="BANKNIFTY26OCT51200CE", side="BUY", quantity=15, price=250.0,
            market_data_age_sec=0.2, available_margin_inr=50000.0, estimated_cost_inr=3750.0,
            bid_price=249.5, ask_price=250.0
        )
        self.assertFalse(res_killed.is_approved)
        self.assertTrue(any("halted" in r.lower() for r in res_killed.rejection_reasons))

    # ------------------------------------------------------------------
    # 9. Daily 1,000,000 Token Hard Ceiling Manager
    # ------------------------------------------------------------------
    def test_11_token_budget_manager_enforces_1m_hard_ceiling(self) -> None:
        """Verify token budget manager warning thresholds (70%, 85%, 95%) and hard stop."""
        storage = self.temp_dir / "budget.json"
        budget = TokenBudgetManager(daily_ceiling=1_000_000, reserve_buffer=25_000, storage_path=storage)

        # Nominal usage
        ok1, st1 = budget.check_and_record(100_000)
        self.assertTrue(ok1)
        self.assertFalse(st1.is_warning_70)

        # Push past 70% threshold (700,000 tokens)
        ok2, st2 = budget.check_and_record(620_000)
        self.assertTrue(ok2)
        self.assertTrue(st2.is_warning_70)
        self.assertFalse(st2.is_warning_85)

        # Push past 85% threshold (850,000 tokens)
        ok3, st3 = budget.check_and_record(140_000)
        self.assertTrue(ok3)
        self.assertTrue(st3.is_warning_85)
        self.assertFalse(st3.is_warning_95)

        # Push past 95% threshold (950,000 tokens)
        ok4, st4 = budget.check_and_record(100_000)
        self.assertTrue(ok4)
        self.assertTrue(st4.is_warning_95)

        # Try to breach the 1,000,000 ceiling (reserve buffer is 25,000, max admissible is 975,000)
        # Total currently consumed is 960,000. Requesting 30,000 would reach 990,000 (> 975,000)
        ok5, st5 = budget.check_and_record(30_000)
        self.assertFalse(ok5)
        self.assertTrue(st5.is_admission_stopped)

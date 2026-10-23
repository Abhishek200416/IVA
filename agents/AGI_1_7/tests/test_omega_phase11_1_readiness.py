# -*- coding: utf-8 -*-
"""AGI 1.7 OMEGA COMMAND — Phase 11.1 Master Readiness Test Suite.

Authoritative verification of:
1. Derivatives vs Cash market calendar closing times (15:40 vs 15:30 IST) & 15:15 entry cutoff.
2. Effective-dated statutory accounting (STT 0.10% vs 0.15% vs 0.125% exercise, NSE Circular 73061 ₹3,553/crore).
3. Clean ₹10,000 paper evaluation epoch (EPOCH-PAPER-10K-20261014-001) with zero demo pollution.
4. Historical demo epoch preservation and ?epoch=demo retrieval.
5. Watchlist affordability gating calibrated against ₹10,000 starting capital.
6. Voice controller 8 trading intents and fail-closed live order rejection.
7. Multi-provider routing pricing tiers, circuit breaker, and deterministic fallback.
8. Strict paper invariant: live routes fail-closed (HTTP 403 / REJECTED_LIVE_PROHIBITED).
"""

import datetime
import json
import os
import tempfile
import unittest
import urllib.request
from http import HTTPStatus
from pathlib import Path

from agents.AGI_1_7.engine.agi17.finance.dynamic_market_calendar import (
    CalendarSessionPhase,
    DynamicExchangeCalendar,
    IST,
)
from agents.AGI_1_7.engine.agi17.finance.live_accounting import (
    calculate_statutory_charges,
)
from agents.AGI_1_7.engine.agi17.finance.watchlist_manager import WatchlistManager
from agents.AGI_1_7.engine.agi17.voice.voice_interface import (
    VoiceIntent,
    VoiceInteractionController,
)
from agents.AGI_1_7.engine.agi17.adapters.omniroute_adapter import (
    OmniRouteAdapter,
    TaskType,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer


class TestOmegaPhase11Readiness(unittest.TestCase):
    """Phase 11.1 Master Readiness and Deterministic Verification Battery."""

    TEST_PORT = 8399
    BASE_URL = f"http://127.0.0.1:{TEST_PORT}"

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.storage_dir = Path(cls.temp_dir.name)

        # Standalone server with default Phase 11.1 clean ₹10,000 paper evaluation epoch
        cls.server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=cls.TEST_PORT,
            storage_dir=cls.storage_dir,
            starting_capital=10000.0,
            epoch_id="EPOCH-PAPER-10K-20261014-001",
        )
        cls.server.start_background()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop_server()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def setUp(self) -> None:
        self.server.session_state = "IDLE"
        self.server.emergency_stop_active = False
        self.server.transition_log.clear()

    def _http_get(self, path: str) -> tuple[int, str, dict]:
        req = urllib.request.Request(f"{self.BASE_URL}{path}")
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            status = resp.status
            content = resp.read().decode("utf-8")
            headers = dict(resp.getheaders())
            return status, content, headers

    def _http_post(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE_URL}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                status = resp.status
                body = json.loads(resp.read().decode("utf-8"))
                return status, body
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode("utf-8")) if e.fp else {}
            return e.code, body

    # =========================================================================
    # 1. Exchange Calendar Timing & Segment Boundaries
    # =========================================================================
    def test_01_derivatives_vs_cash_closing_time(self) -> None:
        """Derivatives closes at 15:40 IST whereas cash closes at 15:30 IST."""
        cal = DynamicExchangeCalendar()
        # Wednesday October 14, 2026 at 15:35 and 15:45 IST
        dt_1535 = datetime.datetime(2026, 10, 14, 15, 35, 0, tzinfo=IST)
        dt_1545 = datetime.datetime(2026, 10, 14, 15, 45, 0, tzinfo=IST)

        # Cash segment is in POST_MARKET at 15:35
        self.assertEqual(
            cal.get_session_phase(dt=dt_1535, segment="EQUITY"),
            CalendarSessionPhase.POST_MARKET,
        )
        # Derivatives segment remains in REGULAR_MARKET at 15:35
        self.assertEqual(
            cal.get_session_phase(dt=dt_1535, segment="DERIVATIVES"),
            CalendarSessionPhase.REGULAR_MARKET,
        )
        # At 15:45, both are past regular session (POST_MARKET)
        self.assertEqual(
            cal.get_session_phase(dt=dt_1545, segment="DERIVATIVES"),
            CalendarSessionPhase.POST_MARKET,
        )

    def test_02_intraday_entry_cutoff_at_1515_ist(self) -> None:
        """New intraday strategy entries must cut off at 15:15 IST."""
        cal = DynamicExchangeCalendar()
        dt_1510 = datetime.datetime(2026, 10, 14, 15, 10, 0, tzinfo=IST)
        dt_1516 = datetime.datetime(2026, 10, 14, 15, 16, 0, tzinfo=IST)

        # 15:10 IST -> entry allowed
        self.assertTrue(cal.is_intraday_entry_allowed(dt=dt_1510))
        # 15:16 IST -> entry prohibited
        self.assertFalse(cal.is_intraday_entry_allowed(dt=dt_1516))

    # =========================================================================
    # 2. Effective-Dated Statutory Accounting & Options Exercise
    # =========================================================================
    def test_03_date_aware_stt_schedule(self) -> None:
        """STT rate is 0.10% prior to April 1, 2026 and 0.15% after April 1, 2026 on sell."""
        # 1 crore sell turnover
        premium_cr = 10_000_000.0

        # Before April 1, 2026: 0.10% = ₹10,000
        charges_pre = calculate_statutory_charges(
            premium_turnover=premium_cr,
            is_sell=True,
            as_of_date=datetime.date(2026, 3, 15),
        )
        self.assertEqual(charges_pre.stt_inr, 10_000.0)

        # After April 1, 2026: 0.15% = ₹15,000
        charges_post = calculate_statutory_charges(
            premium_turnover=premium_cr,
            is_sell=True,
            as_of_date=datetime.date(2026, 4, 15),
        )
        self.assertEqual(charges_post.stt_inr, 15_000.0)

    def test_04_options_exercise_stt_on_intrinsic_value(self) -> None:
        """Exercised options attract 0.125% STT on settlement intrinsic value."""
        # In-the-money option settled with ₹1,000,000 intrinsic value
        charges_exercise = calculate_statutory_charges(
            premium_turnover=0.0,
            is_sell=False,
            is_exercise=True,
            settlement_intrinsic_value=1_000_000.0,
        )
        # 0.125% of 1,000,000 = ₹1,250.00
        self.assertEqual(charges_exercise.stt_inr, 1_250.0)

    def test_05_nse_circular_73061_transaction_and_ipft(self) -> None:
        """NSE transaction charge ₹3,552.99 + IPFT ₹0.01 = ₹3,553 per crore on options."""
        charges = calculate_statutory_charges(
            premium_turnover=10_000_000.0,  # 1 crore turnover
            is_sell=False,
            as_of_date=datetime.date(2026, 3, 1),
        )
        # Outflow per crore should be exactly ₹3,553.00
        self.assertEqual(round(charges.exchange_txn_charge_inr + charges.ipft_inr, 2), 3553.00)

    # =========================================================================
    # 3. Clean ₹10,000 Paper Evaluation Epoch Isolation
    # =========================================================================
    def test_06_server_clean_epoch_isolation(self) -> None:
        """Active epoch starts with exactly ₹10,000 capital, 0 P&L, 0 positions."""
        status, content, _ = self._http_get("/api/status")
        self.assertEqual(status, HTTPStatus.OK)
        data = json.loads(content)

        self.assertEqual(data["mode"], "PAPER")
        self.assertFalse(data["is_live_allowed"])
        self.assertEqual(data["initial_capital"], 10000.0)
        self.assertEqual(data["current_equity"], 10000.0)
        self.assertEqual(data["realized_pnl"], 0.0)
        self.assertEqual(data["unrealized_pnl"], 0.0)
        self.assertEqual(data["active_positions_count"], 0)

        # Positions endpoint reflects clean active epoch
        pos_status, pos_content, _ = self._http_get("/api/paper_positions")
        self.assertEqual(pos_status, HTTPStatus.OK)
        pos_data = json.loads(pos_content)
        self.assertEqual(pos_data["epoch_id"], "EPOCH-PAPER-10K-20261014-001")
        self.assertEqual(len(pos_data["active_positions"]), 0)
        self.assertEqual(len(pos_data["closed_positions"]), 0)
        self.assertEqual(pos_data["starting_capital_inr"], 10000.0)
        self.assertEqual(pos_data["current_equity_inr"], 10000.0)

    def test_07_historical_demo_epoch_retrieval(self) -> None:
        """Historical demo fixtures remain queryable via ?epoch=demo without polluting active."""
        pos_status, pos_content, _ = self._http_get("/api/paper_positions?epoch=demo")
        self.assertEqual(pos_status, HTTPStatus.OK)
        demo_data = json.loads(pos_content)
        self.assertEqual(demo_data["epoch_id"], "EPOCH-DEMO-50K-20261013")
        self.assertEqual(demo_data["starting_capital_inr"], 50000.0)
        self.assertEqual(demo_data["realized_pnl_inr"], 1680.45)
        self.assertEqual(len(demo_data["active_positions"]), 1)
        self.assertEqual(len(demo_data["closed_positions"]), 1)

    def test_08_epochs_catalog_endpoint(self) -> None:
        """Endpoint /api/epochs enumerates active evaluation and archived demo epochs."""
        status, content, _ = self._http_get("/api/epochs")
        self.assertEqual(status, HTTPStatus.OK)
        epochs = json.loads(content)
        self.assertEqual(epochs["active_epoch"]["epoch_id"], "EPOCH-PAPER-10K-20261014-001")
        self.assertEqual(epochs["active_epoch"]["starting_capital_inr"], 10000.0)
        self.assertGreaterEqual(len(epochs["archived_epochs"]), 1)
        self.assertEqual(epochs["archived_epochs"][0]["epoch_id"], "EPOCH-DEMO-50K-20261013")

    def test_09_risk_safety_limits_calibrated_for_10k(self) -> None:
        """Risk limits are scaled: max daily drawdown ₹1,000 (10%), max loss per trade ₹500 (5%)."""
        status, content, _ = self._http_get("/api/risk_safety")
        self.assertEqual(status, HTTPStatus.OK)
        risk = json.loads(content)
        self.assertEqual(risk["initial_capital_inr"], 10000.0)
        self.assertEqual(risk["max_daily_drawdown_limit_inr"], 1000.0)
        self.assertEqual(risk["max_loss_per_trade_inr"], 500.0)
        self.assertTrue(risk["live_dispatch_locked"])

    # =========================================================================
    # 4. Watchlist & Capital Affordability Gates
    # =========================================================================
    def test_10_watchlist_affordability_gate_against_10k(self) -> None:
        """Candidates exceeding available capital ₹10,000 are marked unaffordable."""
        wm = WatchlistManager(
            storage_dir=self.storage_dir / "wm_test",
            initial_capital=10000.0,
        )

        # Affordable candidate: NIFTY lot 65 @ premium 100 -> ₹6,500 <= ₹10,000
        cand_aff = wm.add_candidate(
            underlying="NIFTY",
            strike=24200.0,
            option_type="CE",
            expiry_date="2026-10-29",
            current_premium=100.0,
            trigger_price=102.0,
            target_price=130.0,
            stop_loss_price=85.0,
        )
        self.assertTrue(cand_aff.is_affordable)

        # Unaffordable candidate: BANKNIFTY lot 30 @ premium 400 -> ₹12,000 > ₹10,000
        cand_unaff = wm.add_candidate(
            underlying="BANKNIFTY",
            strike=51200.0,
            option_type="PE",
            expiry_date="2026-10-29",
            current_premium=400.0,
            trigger_price=405.0,
            target_price=480.0,
            stop_loss_price=350.0,
        )
        self.assertFalse(cand_unaff.is_affordable)

    # =========================================================================
    # 5. Voice Interaction Controller & Protected Order Shield
    # =========================================================================
    def test_11_voice_controller_8_intents(self) -> None:
        """Voice controller maps 8 distinct trading-desk operational queries."""
        intents_map = [
            ("what is the market status", VoiceIntent.MARKET_STATUS),
            ("scan setups for nifty", VoiceIntent.SCAN_SETUPS),
            ("explain candidate setup", VoiceIntent.EXPLAIN_CANDIDATE),
            ("show watchlist", VoiceIntent.WATCHLIST_OPS),
            ("set alert on nifty", VoiceIntent.ALERT_CRUD),
            ("show open positions", VoiceIntent.READ_POSITIONS),
            ("start paper session", VoiceIntent.CONTROL_SESSION),
            ("eod briefing summary", VoiceIntent.EOD_BRIEFING),
        ]

        for phrase, expected_intent in intents_map:
            vc = VoiceInteractionController()
            res = vc.process_utterance(phrase)
            self.assertEqual(res.intent, expected_intent, f"Failed on: {phrase}")

    def test_12_voice_go_real_fail_closed(self) -> None:
        """Utterances like 'go real' or 'place live order' trigger fail-closed security shield."""
        vc = VoiceInteractionController()
        prohibited_phrases = [
            "go real now",
            "switch to live",
            "enable live trading",
        ]

        for phrase in prohibited_phrases:
            res = vc.process_utterance(phrase)
            self.assertEqual(res.action_status, "REJECTED_LIVE_PROHIBITED")
            self.assertIn("strictly prohibited", res.spoken_response.lower())

    # =========================================================================
    # 6. Multi-Provider Router & Deterministic Fallback
    # =========================================================================
    def test_13_omniroute_deterministic_fallback_and_breaker(self) -> None:
        """OmniRoute falls back locally when API keys are absent and breaker opens after 3 failures."""
        router = OmniRouteAdapter()

        # In offline / test environment without API keys, request falls back cleanly
        res = router.route_request(
            task_type=TaskType.FAST,
            messages=[{"role": "user", "content": "status check"}],
        )
        self.assertTrue(res.is_fallback)
        self.assertEqual(res.model, "DETERMINISTIC_FALLBACK")
        self.assertIn("Deterministic fast evaluation", res.content)

        # Force record failures to verify breaker
        router.circuit_breaker.record_failure()
        router.circuit_breaker.record_failure()
        router.circuit_breaker.record_failure()
        self.assertEqual(router.circuit_breaker.state.value, "OPEN")

    # =========================================================================
    # 7. Strict Paper Order Boundary Invariant
    # =========================================================================
    def test_14_live_routes_fail_closed_http_403(self) -> None:
        """All live trading endpoints must strictly reject with HTTP 403 Forbidden."""
        live_endpoints = [
            "/api/live/submit_order",
            "/api/order/live",
            "/api/live/dispatch",
        ]

        for ep in live_endpoints:
            code, body = self._http_post(ep, {"instrument": "NIFTY24200CE"})
            self.assertEqual(code, HTTPStatus.FORBIDDEN, f"Endpoint {ep} did not fail closed!")
            self.assertIn(body.get("status"), ("ERROR", "FORBIDDEN"))


if __name__ == "__main__":
    unittest.main()

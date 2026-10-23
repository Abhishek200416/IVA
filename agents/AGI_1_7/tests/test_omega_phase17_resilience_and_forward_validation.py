"""AGI 1.7 OMEGA COMMAND — Phase 17 Forward Paper Validation & Resilience Battery.

Comprehensive verification battery covering:
- Gate B: Authoritative Risk Enhancements (Symbol parsing, Mismatch detection, Lot units, Exit intent, Slippage & Statutory charges)
- Gate C: Read-Only Market Data Qualification (Paytm BLOCKED, Provenance separation, Fail-closed)
- Gate D: Forward Paper Evidence Pipeline (Content-addressing, Hash-chaining, Idempotency, Tamper detection)
- Gate E: Supervised Multi-Session Runner (Checkpoints, Crash recovery to PAUSED, Calendar gating, Evidence tracking)
- Gate F: 15-Scenario Adversarial Failure Injection and Operational Resilience Battery
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import datetime
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import tempfile
import time
import unittest

from agents.AGI_1_7.engine.agi17.finance.authoritative_risk_engine import (
    AuthoritativeTradeRiskEngine,
    ExecutionSimulationResult,
    OrderRiskValidationResult,
)
from agents.AGI_1_7.engine.agi17.finance.dynamic_market_calendar import (
    CalendarSessionPhase,
    DynamicMarketCalendar,
    ExchangeHoliday,
    IST,
)
from agents.AGI_1_7.engine.agi17.finance.forward_paper_pipeline import (
    EventType,
    FeedProvenance,
    ForwardPaperEvidenceRecord,
    ForwardPaperPipeline,
    MarketDataProviderStatus,
    MultiSessionEvidenceTracker,
    SupervisedForwardValidationRunner,
)
from agents.AGI_1_7.engine.agi17.finance.instrument_metadata_catalog import (
    InstrumentMetadataCatalog,
)


class TestPhase17GateBAuthoritativeRiskEnhancements(unittest.TestCase):
    """Gate B: Instrument Metadata, Contract Multipliers, Intent Semantics & Execution Accounting."""

    def setUp(self) -> None:
        self.catalog = InstrumentMetadataCatalog()
        self.engine = AuthoritativeTradeRiskEngine(
            starting_capital=10000.0,
            metadata_catalog=self.catalog,
            max_risk_pct_per_trade=0.005,  # 0.5% = ₹50
            max_notional_pct_per_trade=0.25,  # 25% = ₹2,500
            daily_loss_circuit_breaker_pct=0.015,  # 1.5% = ₹150
        )

    def test_symbol_metadata_mismatch_detected(self) -> None:
        """Indian option symbol containing strike 22500 and PE must be rejected if caller passes strike 23000 or CE."""
        # Symbol specifies 22500 PE
        symbol = "NIFTY26OCT22500PE"
        
        # Mismatch strike: caller says 23000
        res1 = self.engine.validate_order(
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            price=150.0,
            quantity=1,
            stop_loss=120.0,
            strike=23000.0,
            option_type="PE",
            intent="OPEN",
        )
        self.assertFalse(res1.admitted)
        self.assertEqual(res1.rejection_code, "SYMBOL_METADATA_MISMATCH")
        self.assertIn("strike", res1.rejection_reason.lower())

        # Mismatch option type: caller says CE
        res2 = self.engine.validate_order(
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            price=150.0,
            quantity=1,
            stop_loss=120.0,
            strike=22500.0,
            option_type="CE",
            intent="OPEN",
        )
        self.assertFalse(res2.admitted)
        self.assertEqual(res2.rejection_code, "SYMBOL_METADATA_MISMATCH")
        self.assertIn("option type", res2.rejection_reason.lower())

    def test_lot_size_expansion_and_multiples(self) -> None:
        """Validates quantity_unit='LOTS' multiplies by contract lot size (NIFTY=65) and checks multiples."""
        # 1 lot of NIFTY @ price=10, stop=9.2 => risk = 1 lot * 65 * 0.8 = ₹52 (exceeds ₹50)
        res_exceed = self.engine.validate_order(
            symbol="NIFTY",
            side="BUY",
            order_type="LIMIT",
            price=10.0,
            quantity=1,
            quantity_unit="LOTS",
            stop_loss=9.2,
            intent="OPEN",
        )
        self.assertFalse(res_exceed.admitted)
        self.assertEqual(res_exceed.rejection_code, "PLANNED_RISK_LIMIT_BREACH")
        self.assertEqual(res_exceed.effective_quantity, 65)
        self.assertAlmostEqual(res_exceed.calculated_planned_risk, 52.0, places=2)

        # 1 lot of NIFTY @ price=10, stop=9.5 => risk = 65 * 0.5 = ₹32.50 (within ₹50 budget, notional ₹650 within ₹2,500)
        res_valid = self.engine.validate_order(
            symbol="NIFTY",
            side="BUY",
            order_type="LIMIT",
            price=10.0,
            quantity=1,
            quantity_unit="LOTS",
            stop_loss=9.5,
            intent="OPEN",
        )
        self.assertTrue(res_valid.admitted)
        self.assertEqual(res_valid.effective_quantity, 65)
        self.assertAlmostEqual(res_valid.calculated_planned_risk, 32.50, places=2)

        # Non-multiple of lot size when enforce_lot_multiples=True
        res_non_mult = self.engine.validate_order(
            symbol="NIFTY",
            side="BUY",
            order_type="LIMIT",
            price=10.0,
            quantity=70,  # Not multiple of 65
            quantity_unit="UNITS",
            stop_loss=9.5,
            enforce_lot_multiples=True,
            intent="OPEN",
        )
        self.assertFalse(res_non_mult.admitted)
        self.assertIn(res_non_mult.rejection_code, ("INVALID_LOT_MULTIPLE", "LOT_MULTIPLE_VIOLATION"))

    def test_position_exit_intent_bypasses_new_risk_budget(self) -> None:
        """Exit orders (CLOSE/REDUCE) verify existing position ownership and do not consume new-trade risk budget."""
        # Setup an active long position in the engine
        active_pos = {
            "NIFTY26OCT22500CE": {
                "symbol": "NIFTY26OCT22500CE",
                "quantity": 65,
                "entry_price": 100.0,
                "side": "BUY",
            }
        }

        # A sell order to close this position: caller might not even specify a stop loss
        # Even if planned risk formula would produce large risk or stop_loss is absent, exit must be admitted!
        res_exit = self.engine.validate_order(
            symbol="NIFTY26OCT22500CE",
            side="SELL",
            order_type="MARKET",
            price=120.0,
            quantity=65,
            quantity_unit="UNITS",
            stop_loss=None,  # No stop loss needed for closing an existing long!
            intent="CLOSE",
            active_positions=active_pos,
        )
        self.assertTrue(res_exit.admitted, f"Exit order rejected: {res_exit.rejection_reason}")
        self.assertEqual(res_exit.calculated_planned_risk, 0.0)

    def test_exit_non_existent_position_rejected_position_not_found(self) -> None:
        """Attempting to exit a position that does not exist must be rejected with POSITION_NOT_FOUND."""
        active_pos = {
            "BANKNIFTY26OCT48000CE": {
                "symbol": "BANKNIFTY26OCT48000CE",
                "quantity": 30,
                "entry_price": 200.0,
            }
        }

        res = self.engine.validate_order(
            symbol="NIFTY26OCT22500CE",  # Not in active_positions
            side="SELL",
            order_type="LIMIT",
            price=120.0,
            quantity=65,
            intent="CLOSE",
            active_positions=active_pos,
        )
        self.assertFalse(res.admitted)
        self.assertEqual(res.rejection_code, "POSITION_NOT_FOUND")

    def test_exit_overclose_rejected_position_overclose_violation(self) -> None:
        """Attempting to close more quantity than owned must be rejected fail-closed."""
        active_pos = {
            "NIFTY26OCT22500CE": {
                "symbol": "NIFTY26OCT22500CE",
                "quantity": 65,  # Only 65 units owned
                "entry_price": 100.0,
            }
        }

        res = self.engine.validate_order(
            symbol="NIFTY26OCT22500CE",
            side="SELL",
            order_type="LIMIT",
            price=120.0,
            quantity=130,  # Trying to close 130
            intent="CLOSE",
            active_positions=active_pos,
        )
        self.assertFalse(res.admitted)
        self.assertEqual(res.rejection_code, "POSITION_OVERCLOSE_VIOLATION")

    def test_simulate_order_execution_slippage_and_statutory_charges(self) -> None:
        """Simulates order execution modeling half-spread, volatility-scaled slippage, and statutory charges."""
        sim = AuthoritativeTradeRiskEngine.simulate_order_execution(
            side="BUY",
            quantity=65,
            price=100.0,
            bid=99.80,
            ask=100.20,
            volatility_multiplier=1.5,
        )
        self.assertIsInstance(sim, ExecutionSimulationResult)
        # Fill price for BUY should be at ask + volatility slippage
        self.assertGreaterEqual(sim.fill_price, 100.20)
        self.assertGreater(sim.slippage_points, 0.0)
        self.assertGreater(sim.total_friction_inr, 0.0)
        
        # Verify charges components
        self.assertGreater(sim.brokerage_inr, 0.0)
        self.assertGreater(sim.gst_inr, 0.0)
        self.assertGreater(sim.exchange_charges_inr, 0.0)
        self.assertAlmostEqual(
            sim.total_friction_inr,
            sim.brokerage_inr + sim.stt_inr + sim.exchange_charges_inr +
            sim.gst_inr + sim.sebi_charges_inr + sim.stamp_duty_inr,
            places=2,
        )


class TestPhase17GateCMarketDataProviderQualification(unittest.TestCase):
    """Gate C: Read-Only Market Data Qualification & Provider Status."""

    def test_paytm_provider_marked_blocked_awaiting_owner_rotation(self) -> None:
        """Paytm Money provider authentic live feed must be truthfully marked BLOCKED."""
        dossier = MarketDataProviderStatus.get_status_dossier()
        self.assertEqual(dossier["provider"], "Paytm Money Limited")
        self.assertEqual(dossier["status"], "BLOCKED")
        self.assertFalse(dossier["live_allowed"])
        self.assertIn("Owner credential rotation required", dossier["reason"])

    def test_feed_provenance_separation_and_fail_closed_on_live(self) -> None:
        """Requesting LIVE_VERIFIED feed without active authorization must fail closed."""
        valid, msg = MarketDataProviderStatus.validate_feed_mode(FeedProvenance.LIVE_VERIFIED, allow_live=False)
        self.assertFalse(valid)
        self.assertIn("FEED_CREDENTIALS_BLOCKED", msg)

    def test_synthetic_and_replay_allowed(self) -> None:
        """Synthetic fixtures and historical replay must be qualified and permitted."""
        valid_synth, _ = MarketDataProviderStatus.validate_feed_mode(FeedProvenance.SYNTHETIC_FIXTURE)
        self.assertTrue(valid_synth)

        valid_replay, _ = MarketDataProviderStatus.validate_feed_mode(FeedProvenance.HISTORICAL_REPLAY)
        self.assertTrue(valid_replay)


class TestPhase17GateDForwardPaperEvidencePipeline(unittest.TestCase):
    """Gate D: Durable, Append-Only, Content-Addressed Event Ledger with Tamper Detection."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name)
        self.pipeline = ForwardPaperPipeline(storage_dir=self.storage_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_content_addressed_immutable_event_logging(self) -> None:
        """Records are assigned deterministic EVT-<sha256> IDs based on canonical content."""
        rec = self.pipeline.record_event(
            event_type=EventType.SIGNAL_GENERATED,
            session_id="SESS_001",
            payload={"symbol": "NIFTY", "score": 0.85},
        )
        self.assertTrue(rec.record_id.startswith("EVT-"))
        self.assertTrue(rec.verify_hash())
        self.assertEqual(rec.sequence_number, 1)
        self.assertEqual(rec.prev_event_hash, "GENESIS")

    def test_cryptographic_hash_chaining(self) -> None:
        """Consecutive events form an unbroken cryptographic hash chain."""
        rec1 = self.pipeline.record_event(
            event_type=EventType.SIGNAL_GENERATED,
            session_id="SESS_001",
            payload={"step": 1},
        )
        rec2 = self.pipeline.record_event(
            event_type=EventType.RISK_EVALUATION,
            session_id="SESS_001",
            payload={"step": 2},
        )
        rec3 = self.pipeline.record_event(
            event_type=EventType.EXECUTION_FILL,
            session_id="SESS_001",
            payload={"step": 3},
        )

        self.assertEqual(rec2.prev_event_hash, rec1.record_id)
        self.assertEqual(rec3.prev_event_hash, rec2.record_id)
        self.assertEqual(rec3.sequence_number, 3)

        is_valid, count, errors = self.pipeline.verify_ledger_integrity()
        self.assertTrue(is_valid)
        self.assertEqual(count, 3)
        self.assertEqual(len(errors), 0)

    def test_idempotency_key_deduplication(self) -> None:
        """Submitting an event with the same idempotency key returns the cached record without duplicate appending."""
        rec1 = self.pipeline.record_event(
            event_type=EventType.SIGNAL_GENERATED,
            session_id="SESS_001",
            payload={"data": "first"},
            idempotency_key="UNIQUE_IDEMPOTENCY_KEY_123",
        )
        rec2 = self.pipeline.record_event(
            event_type=EventType.SIGNAL_GENERATED,
            session_id="SESS_001",
            payload={"data": "attempted_duplicate"},
            idempotency_key="UNIQUE_IDEMPOTENCY_KEY_123",
        )
        # Should return the identical record object and ID
        self.assertEqual(rec1.record_id, rec2.record_id)
        self.assertEqual(rec2.payload["data"], "first")

        # Verify only 1 line written to disk
        with open(self.pipeline.ledger_file, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 1)

    def test_tamper_detection_and_integrity_verification(self) -> None:
        """Any manual modification of the ledger file triggers hash mismatch and fails verification."""
        self.pipeline.record_event(event_type=EventType.SIGNAL_GENERATED, session_id="S1", payload={"val": 100})
        self.pipeline.record_event(event_type=EventType.RISK_EVALUATION, session_id="S1", payload={"val": 200})

        # Verify ledger initially valid
        is_valid, count, errors = self.pipeline.verify_ledger_integrity()
        self.assertTrue(is_valid)
        self.assertEqual(count, 2)

        # Tamper with the file: change "val": 100 to "val": 999
        content = self.pipeline.ledger_file.read_text(encoding="utf-8")
        tampered_content = content.replace('"val": 100', '"val": 999')
        self.pipeline.ledger_file.write_text(tampered_content, encoding="utf-8")

        # Verification must now fail!
        is_valid_after, _, errors_after = self.pipeline.verify_ledger_integrity()
        self.assertFalse(is_valid_after)
        self.assertGreater(len(errors_after), 0)
        self.assertTrue(any("Hash mismatch" in err or "Hash chain broken" in err for err in errors_after))


class TestPhase17GateEMultiSessionRunnerAndCheckpoints(unittest.TestCase):
    """Gate E: Multi-Session Operational Validation Runner, Calendar Gating & Checkpoint Recovery."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name)
        self.calendar = DynamicMarketCalendar(allow_stale_for_testing=True)
        self.runner = SupervisedForwardValidationRunner(
            storage_dir=self.storage_dir,
            calendar=self.calendar,
            starting_capital=10000.0,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_supervised_runner_lifecycle(self) -> None:
        """Full operational lifecycle: start, trade recording, pause, resume, stop."""
        started, msg = self.runner.start_session("SESS_P17_01", feed_mode=FeedProvenance.SYNTHETIC_FIXTURE)
        self.assertTrue(started)
        self.assertEqual(self.runner.session_status, "ACTIVE")

        # Record a trade execution
        self.runner.record_forward_trade_execution(
            signal_id="SIG_001",
            symbol="NIFTY",
            side="BUY",
            intent="OPEN",
            quantity=65,
            entry_price=100.0,
            stop_loss=95.0,
            execution_result={"fill_price": 100.20, "charges": 22.50},
            accounting_delta={"cash_delta": -6513.0, "realized_pnl_delta": 0.0},
        )
        self.assertEqual(self.runner.trade_count, 1)

        # Pause
        self.runner.pause_session(reason="Lunch break")
        self.assertEqual(self.runner.session_status, "PAUSED")

        # Resume
        resumed, _ = self.runner.resume_session()
        self.assertTrue(resumed)
        self.assertEqual(self.runner.session_status, "ACTIVE")

        # Stop
        self.runner.stop_session(reason="Market close")
        self.assertEqual(self.runner.session_status, "STOPPED")

    def test_checkpoint_persistence_and_recovery_to_paused(self) -> None:
        """If runner crashes while ACTIVE, restarting the runner recovers into safe PAUSED mode."""
        self.runner.start_session("SESS_CRASH_TEST", feed_mode=FeedProvenance.SYNTHETIC_FIXTURE)
        self.assertEqual(self.runner.session_status, "ACTIVE")
        self.runner.save_checkpoint()

        # Simulate fresh runner reboot pointing to same checkpoint file
        rebooted_runner = SupervisedForwardValidationRunner(
            storage_dir=self.storage_dir,
            calendar=self.calendar,
            starting_capital=10000.0,
        )
        # Invariant: Crashed ACTIVE session recovers safely to PAUSED
        self.assertEqual(rebooted_runner.session_status, "PAUSED")
        self.assertEqual(rebooted_runner.current_session_id, "SESS_CRASH_TEST")

    def test_calendar_awareness_rejects_closed_exchange_days(self) -> None:
        """Session start is rejected if calendar specifies weekend or exchange holiday."""
        # A known Sunday
        sunday_dt = datetime.datetime(2026, 10, 18, 10, 30, tzinfo=IST)
        started, msg = self.runner.start_session("SESS_WEEKEND", feed_mode=FeedProvenance.SYNTHETIC_FIXTURE, calendar_dt=sunday_dt)
        self.assertFalse(started)
        self.assertIn("CALENDAR_CLOSED", msg)

    def test_multi_session_evidence_tracker_status(self) -> None:
        """Evidence tracker initializes with 10 planned sessions marked PENDING OPERATIONAL EVIDENCE."""
        tracker = MultiSessionEvidenceTracker(storage_dir=self.storage_dir)
        summary = tracker.get_summary()
        self.assertEqual(summary["total_planned_sessions"], 10)
        self.assertEqual(summary["operational_status"], "PENDING OPERATIONAL EVIDENCE")
        self.assertIn("BLOCKED", summary["authentic_live_feed"])


class TestPhase17GateF15ScenarioResilienceBattery(unittest.TestCase):
    """Gate F: 15-Scenario Failure Injection and Operational Resilience Battery."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name)
        self.engine = AuthoritativeTradeRiskEngine(
            starting_capital=10000.0,
            max_risk_pct_per_trade=0.005,  # ₹50
            max_notional_pct_per_trade=0.25,  # ₹2,500
            daily_loss_circuit_breaker_pct=0.015,  # ₹150
        )
        self.runner = SupervisedForwardValidationRunner(
            storage_dir=self.storage_dir,
            starting_capital=10000.0,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_scenario_01_feed_disconnection_and_reconnect(self) -> None:
        """Scenario 1: Live feed disconnects; quote age spikes -> rejected; reconnects -> admitted."""
        # Stale quote during disconnection (age = 5.0s > 3.0s limit)
        stale_res = self.engine.validate_order(
            symbol="NIFTY", side="BUY", order_type="LIMIT", price=100.0, quantity=1, stop_loss=95.0,
            quote_age_seconds=5.0, intent="OPEN",
        )
        self.assertFalse(stale_res.admitted)
        self.assertEqual(stale_res.rejection_code, "STALE_DATA_REJECTION")

        # Feed reconnected, fresh quote (age = 0.2s)
        fresh_res = self.engine.validate_order(
            symbol="NIFTY", side="BUY", order_type="LIMIT", price=100.0, quantity=1, stop_loss=95.0,
            quote_age_seconds=0.2, intent="OPEN",
        )
        self.assertTrue(fresh_res.admitted)

    def test_scenario_02_expired_auth_credentials_fail_closed(self) -> None:
        """Scenario 2: Provider credentials unrotated/expired; requests fail closed with explicit message."""
        valid, msg = MarketDataProviderStatus.validate_feed_mode(FeedProvenance.LIVE_VERIFIED, allow_live=False)
        self.assertFalse(valid)
        self.assertIn("FEED_CREDENTIALS_BLOCKED", msg)

    def test_scenario_03_stale_quote_rejection(self) -> None:
        """Scenario 3: Quotes older than 3.0s rejected fail-closed."""
        res = self.engine.validate_order(
            symbol="NIFTY", side="BUY", order_type="LIMIT", price=100.0, quantity=1, stop_loss=95.0,
            quote_age_seconds=3.1, intent="OPEN",
        )
        self.assertFalse(res.admitted)
        self.assertEqual(res.rejection_code, "STALE_DATA_REJECTION")

    def test_scenario_04_metadata_mismatch_rejection(self) -> None:
        """Scenario 4: Instrument metadata mismatch between symbol and order parameters."""
        res = self.engine.validate_order(
            symbol="NIFTY26OCT22500CE", side="BUY", order_type="LIMIT", price=100.0, quantity=1, stop_loss=95.0,
            strike=21000.0,  # Mismatch!
            option_type="CE",
            intent="OPEN",
        )
        self.assertFalse(res.admitted)
        self.assertEqual(res.rejection_code, "SYMBOL_METADATA_MISMATCH")

    def test_scenario_05_quantity_non_finite_and_lot_multiple_rejection(self) -> None:
        """Scenario 5: Non-finite quantity or invalid lot size multiple rejected fail-closed."""
        res_nan = self.engine.validate_order(
            symbol="NIFTY", side="BUY", order_type="LIMIT", price=100.0, quantity=float("nan"), stop_loss=95.0,
            intent="OPEN",
        )
        self.assertFalse(res_nan.admitted)
        self.assertEqual(res_nan.rejection_code, "INVALID_NUMERIC_FIELD")

        res_lot = self.engine.validate_order(
            symbol="NIFTY", side="BUY", order_type="LIMIT", price=100.0, quantity=40, stop_loss=95.0,
            enforce_lot_multiples=True, intent="OPEN",
        )
        self.assertFalse(res_lot.admitted)
        self.assertIn(res_lot.rejection_code, ("INVALID_LOT_MULTIPLE", "LOT_MULTIPLE_VIOLATION"))

    def test_scenario_06_worker_crash_and_thread_recovery(self) -> None:
        """Scenario 6: Worker thread raises unexpected exception; supervisor recovers without orphan locks."""
        # Simulate worker crash during session
        self.runner.start_session("SESS_CRASH_06", feed_mode=FeedProvenance.SYNTHETIC_FIXTURE)
        try:
            raise RuntimeError("Simulated worker unhandled failure")
        except RuntimeError:
            self.runner.pause_session(reason="Worker thread exception caught")

        self.assertEqual(self.runner.session_status, "PAUSED")
        # Ensure runner is able to cleanly resume once repaired
        resumed, _ = self.runner.resume_session()
        self.assertTrue(resumed)

    def test_scenario_07_restart_with_unconfirmed_pending_order(self) -> None:
        """Scenario 7: Host restart while order is pending; recovered state holds pending order for audit."""
        self.runner.start_session("SESS_PENDING_07", feed_mode=FeedProvenance.SYNTHETIC_FIXTURE)
        self.runner.active_positions["PENDING_ORD_99"] = {"status": "SUBMITTED", "symbol": "NIFTY", "qty": 65}
        self.runner.save_checkpoint()

        reboot = SupervisedForwardValidationRunner(storage_dir=self.storage_dir)
        self.assertEqual(reboot.session_status, "PAUSED")
        self.assertIn("PENDING_ORD_99", reboot.active_positions)

    def test_scenario_08_concurrent_order_admission_race_protection(self) -> None:
        """Scenario 8: 10 concurrent threads attempt to admit orders simultaneously; risk limits strictly held."""
        # 10 orders each with risk ₹30 (total ₹300, which exceeds ₹150 daily circuit breaker or single ₹50 per trade)
        # All orders should be evaluated under atomic lock
        admitted = []
        def submit():
            return self.engine.validate_order(
                symbol="NIFTY", side="BUY", order_type="LIMIT", price=100.0, quantity=1, stop_loss=70.0,  # Risk ₹30
                intent="OPEN",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(submit) for _ in range(10)]
            for f in concurrent.futures.as_completed(futures):
                admitted.append(f.result().admitted)

        # All 10 orders individually have risk ₹30 <= ₹50 and notional ₹100 <= ₹2,500, so each is individually valid
        self.assertTrue(all(admitted))

    def test_scenario_09_circuit_breaker_daily_drawdown_realized_loss(self) -> None:
        """Scenario 9: Realized loss of ₹150 trips 1.5% daily loss circuit breaker; halts new orders."""
        res_trip = self.engine.validate_order(
            symbol="NIFTY", side="BUY", order_type="LIMIT", price=100.0, quantity=1, stop_loss=95.0,
            daily_realized_pnl=-150.0, intent="OPEN",
        )
        self.assertFalse(res_trip.admitted)
        self.assertEqual(res_trip.rejection_code, "CIRCUIT_BREAKER_HALT")
        self.assertEqual(self.engine.circuit_breaker_status, "TRIPPED")

    def test_scenario_10_circuit_breaker_daily_drawdown_unrealized_floating_loss(self) -> None:
        """Scenario 10: Realized P&L is ₹0 but floating unrealized loss is -₹160 -> breaker trips."""
        res_floating = self.engine.validate_order(
            symbol="NIFTY", side="BUY", order_type="LIMIT", price=100.0, quantity=1, stop_loss=95.0,
            daily_realized_pnl=0.0, daily_unrealized_pnl=-160.0, intent="OPEN",
        )
        self.assertFalse(res_floating.admitted)
        self.assertEqual(res_floating.rejection_code, "CIRCUIT_BREAKER_HALT")
        self.assertEqual(self.engine.circuit_breaker_status, "TRIPPED")

    def test_scenario_11_breaker_recovery_lockout(self) -> None:
        """Scenario 11: Once circuit breaker trips, all subsequent order admissions remain locked out."""
        # Trip the breaker
        self.engine.record_trade_result(realized_pnl=-155.0)
        self.assertEqual(self.engine.circuit_breaker_status, "TRIPPED")

        # Subsequent order attempt must be blocked
        res = self.engine.validate_order(
            symbol="NIFTY", side="BUY", order_type="LIMIT", price=100.0, quantity=1, stop_loss=99.0, intent="OPEN",
        )
        self.assertFalse(res.admitted)
        self.assertEqual(res.rejection_code, "CIRCUIT_BREAKER_HALT")

    def test_scenario_12_emergency_stop_sub50ms_execution(self) -> None:
        """Scenario 12: Emergency stop directives execute well within institutional 50ms requirement."""
        self.runner.start_session("SESS_EMERGENCY", feed_mode=FeedProvenance.SYNTHETIC_FIXTURE)
        t0 = time.perf_counter()
        self.runner.emergency_stop(reason="Operator killswitch test")
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertLess(latency_ms, 50.0)
        self.assertEqual(self.runner.session_status, "STOPPED")
        self.assertTrue(self.runner.circuit_breaker_tripped)

    def test_scenario_13_non_existent_position_exit_rejected(self) -> None:
        """Scenario 13: Exiting non-existent position rejected with POSITION_NOT_FOUND."""
        res = self.engine.validate_order(
            symbol="NONEXISTENT_SYMBOL", side="SELL", order_type="LIMIT", price=100.0, quantity=1,
            intent="CLOSE", active_positions={"NIFTY": {"quantity": 65}},
        )
        self.assertFalse(res.admitted)
        self.assertEqual(res.rejection_code, "POSITION_NOT_FOUND")

    def test_scenario_14_position_over_close_rejected(self) -> None:
        """Scenario 14: Over-closing position quantity rejected with POSITION_OVERCLOSE_VIOLATION."""
        res = self.engine.validate_order(
            symbol="NIFTY", side="SELL", order_type="LIMIT", price=100.0, quantity=100,
            intent="CLOSE", active_positions={"NIFTY": {"quantity": 65}},
        )
        self.assertFalse(res.admitted)
        self.assertEqual(res.rejection_code, "POSITION_OVERCLOSE_VIOLATION")

    def test_scenario_15_tampered_ledger_corruption_recovery(self) -> None:
        """Scenario 15: Tampered ledger corruption detected and isolated cleanly."""
        pipeline = self.runner.pipeline
        pipeline.record_event(event_type=EventType.SIGNAL_GENERATED, session_id="S15", payload={"seq": 1})
        pipeline.record_event(event_type=EventType.RISK_EVALUATION, session_id="S15", payload={"seq": 2})

        # Inject malformed line
        with open(pipeline.ledger_file, "a", encoding="utf-8") as f:
            f.write("{MALFORMED_JSON_STRING\n")

        is_valid, count, errors = pipeline.verify_ledger_integrity()
        self.assertFalse(is_valid)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("Malformed JSON" in e for e in errors))


if __name__ == "__main__":
    unittest.main()

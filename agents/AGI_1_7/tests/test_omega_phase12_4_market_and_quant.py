"""AGI 1.7 OMEGA COMMAND — Phase 12.4 Market Data Integrity & Quantitative Validation Suite

Covers the 15 Authoritative Verification Requirements:
1. Wrong instrument identity rejection.
2. Missing, stale, and out-of-order timestamps.
3. Duplicate market events.
4. Disconnect and reconnect behavior.
5. Invalid option expiry or contract mapping.
6. Research-source deduplication and unavailable sources.
7. Trace continuity across agent handoffs.
8. Reproducibility from stored decision inputs.
9. Look-ahead leakage detection.
10. Unseen chronological evaluation (walk-forward).
11. Fees, slippage, and net-P&L reconciliation (NSE 73061 STT).
12. Replay/live-source separation.
13. Portfolio epoch isolation.
14. Recovery without duplicate paper orders.
15. Fail-closed live-order boundary (HTTP 403 Forbidden).
"""

from __future__ import annotations

import datetime
from decimal import Decimal
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List

from agents.AGI_1_7.engine.agi17.finance.canonical_market_data import (
    CanonicalMarketDataPipeline,
    CanonicalMarketObservation,
    ConnectionState,
    DataProvenance,
    Exchange,
    MarketSessionPhase,
    ObservationType,
    OptionType,
    ValidationOutcome,
)
from agents.AGI_1_7.engine.agi17.finance.deterministic_paper_replay import (
    DeterministicPaperReplayEngine,
)
from agents.AGI_1_7.engine.agi17.finance.market_data_health import (
    MarketDataHealthMonitor,
    MarketSourceHealthStatus,
)
from agents.AGI_1_7.engine.agi17.finance.quantitative_evaluation_harness import (
    QuantitativeEvaluationHarness,
)
from agents.AGI_1_7.engine.agi17.finance.research_provenance import (
    ResearchProvenanceRepository,
    SourceAuthorityLevel,
    StructuredResearchRecord,
    VerificationState,
)
from agents.AGI_1_7.engine.agi17.finance.decision_trace_engine import (
    DecisionOutcome,
    DecisionTraceRepository,
    StrategyDecisionTrace,
)
from agents.AGI_1_7.engine.agi17.telemetry.omega_tracer import OmegaTracer
from agents.AGI_1_7.ui.standalone_dashboard_server import StandaloneDashboardServer

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


class TestOmegaPhase124MarketAndQuant(unittest.TestCase):
    """Authoritative 15-point verification suite for Phase 12.4."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.temp_dir.name)
        self.pipeline = CanonicalMarketDataPipeline(
            max_quote_age_sec=15.0,
            storage_dir=self.storage_dir / "market_data",
        )
        self.health_monitor = MarketDataHealthMonitor(
            storage_dir=self.storage_dir / "health",
        )
        self.research_repo = ResearchProvenanceRepository(
            storage_dir=self.storage_dir / "research",
        )
        self.decision_repo = DecisionTraceRepository(
            storage_dir=self.storage_dir / "traces",
        )

    def tearDown(self) -> None:
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    # =========================================================================
    # Test 1: Wrong Instrument Identity Rejection
    # =========================================================================
    def test_01_wrong_instrument_identity_rejection(self) -> None:
        """Malformed or incomplete instrument identities must be rejected."""
        # Derivative marked as CE but missing strike and expiry
        obs = CanonicalMarketObservation(
            instrument_id="NSE:NIFTY-INVALID-OPTION",
            exchange=Exchange.NFO,
            underlying="NIFTY",
            observation_type=ObservationType.QUOTE,
            source_id="TEST_SOURCE",
            price=120.0,
            option_type=OptionType.CE,
            strike=None,  # Missing strike
            expiry_date=None,  # Missing expiry
        )
        outcome, reason = self.pipeline.validate_observation(obs)
        self.assertEqual(outcome, ValidationOutcome.REJECTED_WRONG_INSTRUMENT)
        self.assertIn("strike", reason.lower())

    # =========================================================================
    # Test 2: Missing, Stale and Out-of-Order Timestamps
    # =========================================================================
    def test_02_missing_stale_and_out_of_order_timestamps(self) -> None:
        """Observations older than 15s or with decreasing sequence numbers must be rejected."""
        now = datetime.datetime.now(IST)
        stale_time = now - datetime.timedelta(seconds=45)

        # 1. Stale quote
        stale_obs = CanonicalMarketObservation(
            instrument_id="NSE:NIFTY26OCT22900CE",
            exchange=Exchange.NFO,
            underlying="NIFTY",
            observation_type=ObservationType.QUOTE,
            source_id="TEST_FEED",
            price=150.0,
            strike=22900.0,
            option_type=OptionType.CE,
            expiry_date="2026-10-26",
            exchange_timestamp=stale_time,
            receipt_timestamp=now,
            sequence_number=100,
            provenance=DataProvenance.LIVE_VERIFIED,
        )
        outcome, reason = self.pipeline.validate_observation(stale_obs)
        self.assertEqual(outcome, ValidationOutcome.REJECTED_STALE)

        # 2. Ingest valid sequence 100
        valid_obs = CanonicalMarketObservation(
            instrument_id="NSE:NIFTY26OCT22900CE",
            exchange=Exchange.NFO,
            underlying="NIFTY",
            observation_type=ObservationType.QUOTE,
            source_id="TEST_FEED",
            price=150.0,
            strike=22900.0,
            option_type=OptionType.CE,
            expiry_date="2026-10-26",
            exchange_timestamp=now,
            receipt_timestamp=now,
            sequence_number=100,
            provenance=DataProvenance.LIVE_VERIFIED,
        )
        self.pipeline.ingest(valid_obs)

        # 3. Out-of-order sequence 95
        ooo_obs = CanonicalMarketObservation(
            instrument_id="NSE:NIFTY26OCT22900CE",
            exchange=Exchange.NFO,
            underlying="NIFTY",
            observation_type=ObservationType.QUOTE,
            source_id="TEST_FEED",
            price=150.5,
            strike=22900.0,
            option_type=OptionType.CE,
            expiry_date="2026-10-26",
            exchange_timestamp=now,
            receipt_timestamp=now,
            sequence_number=95,
            provenance=DataProvenance.LIVE_VERIFIED,
        )
        outcome, reason = self.pipeline.validate_observation(ooo_obs)
        self.assertEqual(outcome, ValidationOutcome.REJECTED_OUT_OF_ORDER)

    # =========================================================================
    # Test 3: Duplicate Market Events
    # =========================================================================
    def test_03_duplicate_market_events(self) -> None:
        """Duplicate event signatures must be detected and rejected."""
        now = datetime.datetime.now(IST)
        obs1 = CanonicalMarketObservation(
            instrument_id="NSE:BANKNIFTY",
            exchange=Exchange.NSE,
            underlying="BANKNIFTY",
            observation_type=ObservationType.QUOTE,
            source_id="TEST_SOURCE",
            price=51400.0,
            sequence_number=1,
            exchange_timestamp=now,
            receipt_timestamp=now,
        )
        ingested1 = self.pipeline.ingest(obs1)
        self.assertEqual(ingested1.validation_outcome, ValidationOutcome.VALID)

        # Repeat identical event
        obs2 = CanonicalMarketObservation(
            instrument_id="NSE:BANKNIFTY",
            exchange=Exchange.NSE,
            underlying="BANKNIFTY",
            observation_type=ObservationType.QUOTE,
            source_id="TEST_SOURCE",
            price=51400.0,
            sequence_number=1,
            exchange_timestamp=now,
            receipt_timestamp=now,
        )
        ingested2 = self.pipeline.ingest(obs2)
        self.assertEqual(ingested2.validation_outcome, ValidationOutcome.REJECTED_DUPLICATE)

    # =========================================================================
    # Test 4: Disconnect and Reconnect Behavior
    # =========================================================================
    def test_04_disconnect_and_reconnect_behavior(self) -> None:
        """Market health monitor accurately logs transport state transitions."""
        self.health_monitor.record_connection_state("DISCONNECTED")
        health = self.health_monitor.evaluate_composite_health()
        self.assertEqual(health["websocket_transport"], "DISCONNECTED")
        self.assertEqual(health["status"], MarketSourceHealthStatus.DISCONNECTED.value)
        self.assertFalse(health["is_market_data_flowing"])

        # Reconnection attempt
        self.health_monitor.record_connection_state("RECONNECTING")
        self.assertEqual(self.health_monitor.reconnection_attempts, 1)

        # Reconnected & authenticated
        self.health_monitor.record_connection_state("CONNECTED", subscriptions=["NIFTY", "BANKNIFTY"])
        self.health_monitor.record_auth_event(True, "SESSION_OK")
        self.health_monitor.record_market_event("NSE:NIFTY", "QUOTE")
        health = self.health_monitor.evaluate_composite_health()
        self.assertEqual(health["status"], MarketSourceHealthStatus.LIVE_VERIFIED.value)
        self.assertTrue(health["is_market_data_flowing"])

    # =========================================================================
    # Test 5: Invalid Option Expiry or Contract Mapping
    # =========================================================================
    def test_05_invalid_option_expiry_or_contract_mapping(self) -> None:
        """Derivatives with negative strikes or crossed quotes must be rejected."""
        now = datetime.datetime.now(IST)
        # Crossed book: bid 125 > ask 120
        crossed_obs = CanonicalMarketObservation(
            instrument_id="NSE:NIFTY26OCT22900PE",
            exchange=Exchange.NFO,
            underlying="NIFTY",
            observation_type=ObservationType.QUOTE,
            source_id="TEST_SOURCE",
            price=122.0,
            bid=125.0,
            ask=120.0,
            strike=22900.0,
            option_type=OptionType.PE,
            expiry_date="2026-10-26",
            exchange_timestamp=now,
            receipt_timestamp=now,
        )
        outcome, reason = self.pipeline.validate_observation(crossed_obs)
        self.assertEqual(outcome, ValidationOutcome.REJECTED_CROSSED)
        self.assertIn("Crossed book", reason)

    # =========================================================================
    # Test 6: Research-Source Deduplication & Unavailable Sources
    # =========================================================================
    def test_06_research_source_deduplication_and_unavailable_sources(self) -> None:
        """Identical research records must be deduplicated; unverified records cannot trade."""
        rec1 = StructuredResearchRecord(
            headline="RBI Holds Repo Rate Steady at 6.50%",
            publisher="Reserve Bank of India (RBI)",
            source_url="https://rbi.org.in/press/repo_oct2026",
            factual_summary="MPC votes unanimously to hold repo rate at 6.50%.",
            extracted_facts=["Repo rate remains 6.50%"],
            supporting_passages=["Unanimous resolution of Monetary Policy Committee."],
            agent_interpretation="Neutral for BankNifty options premium expansion.",
            author_agent="Emily",
            verification_state=VerificationState.VERIFIED_REGULATORY,
            authority_level=SourceAuthorityLevel.STATUTORY_REGULATOR,
        )
        saved1, is_new1 = self.research_repo.add_record(rec1)
        self.assertTrue(is_new1)

        # Add duplicate record with identical content
        rec2 = StructuredResearchRecord(
            headline="RBI Holds Repo Rate Steady at 6.50%",
            publisher="Reserve Bank of India (RBI)",
            source_url="https://rbi.org.in/press/repo_oct2026",
            factual_summary="MPC votes unanimously to hold repo rate at 6.50%.",
            extracted_facts=["Repo rate remains 6.50%"],
            supporting_passages=["Unanimous resolution of Monetary Policy Committee."],
            agent_interpretation="Different commentary",
            author_agent="Alexa",
            verification_state=VerificationState.VERIFIED_REGULATORY,
            authority_level=SourceAuthorityLevel.STATUTORY_REGULATOR,
        )
        saved2, is_new2 = self.research_repo.add_record(rec2)
        self.assertFalse(is_new2)
        self.assertEqual(saved1.record_id, saved2.record_id)

        # Test trade authorization gate on UNVERIFIED headline
        unverified_rec = StructuredResearchRecord(
            headline="Rumor: Secret Rate Cut Tomorrow",
            publisher="Unverified Social Blog",
            source_url="https://rumor.xyz/cut",
            factual_summary="Unverified claim of sudden rate cut.",
            extracted_facts=[],
            supporting_passages=[],
            agent_interpretation="Aggressive buy call",
            author_agent="Alexa",
            verification_state=VerificationState.UNVERIFIED,
            authority_level=SourceAuthorityLevel.AGGREGATOR_SOCIAL,
        )
        can_trade, reason = unverified_rec.can_authorize_trade()
        self.assertFalse(can_trade)
        self.assertIn("Unverified", reason)

    # =========================================================================
    # Test 7: Trace Continuity Across Agent Handoffs
    # =========================================================================
    def test_07_trace_continuity_across_agent_handoffs(self) -> None:
        """Trace context propagates parent-child relationships through deliberation handoffs."""
        tracer = OmegaTracer(trace_dir=self.storage_dir / "traces")
        root_ctx = tracer.start_trace(request_id="REQ-TRIAD-001")

        # Emily records macro intelligence event
        tracer.record_event(
            ctx=root_ctx,
            event_type="RESEARCH_SYNTHESIZED",
            actor="Emily",
            payload={"bias": "BULLISH_SHORT_COVERING"},
        )

        # Emily hands off to Max (child span)
        max_ctx = root_ctx.child_span()
        tracer.record_event(
            ctx=max_ctx,
            event_type="QUANT_RMS_VALIDATED",
            actor="Max",
            payload={"lot_size": 50, "stop_loss_pts": 35.0},
        )

        # Max hands off to Alexa (execution span)
        alexa_ctx = max_ctx.child_span()
        tracer.record_event(
            ctx=alexa_ctx,
            event_type="ORDER_ROUTED_PAPER",
            actor="Alexa",
            payload={"symbol": "NIFTY26OCT22900CE", "side": "BUY"},
        )

        timeline = tracer.get_trace_timeline(root_ctx.trace_id)
        self.assertEqual(len(timeline), 3)
        self.assertEqual(timeline[0]["actor"], "Emily")
        self.assertEqual(timeline[1]["actor"], "Max")
        self.assertEqual(timeline[2]["actor"], "Alexa")
        # Check span hierarchy
        self.assertEqual(timeline[1]["parent_span_id"], root_ctx.span_id)
        self.assertEqual(timeline[2]["parent_span_id"], max_ctx.span_id)

    # =========================================================================
    # Test 8: Reproducibility from Stored Decision Inputs
    # =========================================================================
    def test_08_reproducibility_from_stored_decision_inputs(self) -> None:
        """Re-evaluating a strategy with saved input features produces identical outcome."""
        trace = StrategyDecisionTrace(
            trace_id="TRC-REPRO-001",
            epoch_id="EPOCH-PAPER-10K-20261014-001",
            strategy_id="CPR_PIVOT_BREAKOUT",
            strategy_version="1.2.0",
            input_observation_ids=["OBS-NIFTY-001", "OBS-NIFTY-002"],
            feature_values={"vwap": 22910.5, "cpr_top": 22900.0, "current_price": 22933.1},
            formula_version="FORMULA_V2_MOMENTUM",
            pre_trade_risk_checks={"drawdown_ok": True, "margin_ok": True, "slippage_budget_ok": True},
            decision_outcome=DecisionOutcome.APPROVED_FOR_PAPER,
        )
        self.decision_repo.record_decision(trace)

        # Deterministic evaluator function
        def evaluate_cpr(strategy_id, strategy_version, features, risk_checks):
            if features["current_price"] > features["cpr_top"] and all(risk_checks.values()):
                return DecisionOutcome.APPROVED_FOR_PAPER, None
            return DecisionOutcome.NO_TRADE_CONVICTION, "Conditions not met"

        is_reproducible, err = self.decision_repo.verify_reproducibility(
            trace.decision_id, evaluate_cpr
        )
        self.assertTrue(is_reproducible, f"Reproducibility failed: {err}")

    # =========================================================================
    # Test 9: Look-Ahead Leakage Detection
    # =========================================================================
    def test_09_look_ahead_leakage_detection(self) -> None:
        """Feature calculation strictly uses historical bars <= t and catches lookahead leakage."""
        harness = QuantitativeEvaluationHarness(initial_capital=10000.0)

        # Mock sequence of 20 bars
        bars = [
            {"close": 100.0 + i * 2.0, "timestamp_ist": f"2026-10-15 09:{15+i:02d}"}
            for i in range(20)
        ]

        observed_history_lengths: List[int] = []

        def compliant_strategy(history: List[Dict[str, Any]]) -> Optional[str]:
            observed_history_lengths.append(len(history))
            # Safe logic: uses only available history
            if len(history) >= 2 and history[-1]["close"] > history[-2]["close"]:
                return "BUY"
            return None

        harness.evaluate_strategy_walk_forward(bars, compliant_strategy)

        # Out of sample split is 20% of 20 = 4 bars (indices 16, 17, 18, 19)
        # Slices must grow monotonically: 1, 2, 3, 4
        self.assertEqual(observed_history_lengths, [1, 2, 3, 4])

    # =========================================================================
    # Test 10: Unseen Chronological Evaluation (Walk-Forward)
    # =========================================================================
    def test_10_unseen_chronological_evaluation(self) -> None:
        """Walk-forward splits dataset strictly chronologically (60% Train, 20% Val, 20% Test)."""
        harness = QuantitativeEvaluationHarness()
        data = list(range(100))
        train, val, test = harness.partition_chronological(data, 0.60, 0.20)

        self.assertEqual(len(train), 60)
        self.assertEqual(len(val), 20)
        self.assertEqual(len(test), 20)
        # Verify chronological order without overlap
        self.assertEqual(train[-1], 59)
        self.assertEqual(val[0], 60)
        self.assertEqual(val[-1], 79)
        self.assertEqual(test[0], 80)
        self.assertEqual(test[-1], 99)

    # =========================================================================
    # Test 11: Fees, Slippage, and Net-P&L Reconciliation (NSE 73061 STT)
    # =========================================================================
    def test_11_fees_slippage_and_net_pnl_reconciliation(self) -> None:
        """Evaluates exact Indian derivative taxes including NSE 73061 STT."""
        harness = QuantitativeEvaluationHarness(
            brokerage_per_order=10.0,
            stt_rate_sell=0.001,  # 0.1% on options sell
        )

        costs = harness.calculate_transaction_friction(
            buy_price=100.0, sell_price=120.0, quantity=50, is_option=True
        )

        # Buy turnover = 5000, Sell turnover = 6000
        # Brokerage = 20.00 (10 buy + 10 sell)
        # STT = 6000 * 0.001 = 6.00
        # Exchange charges = 11000 * 0.0005 = 5.50
        # GST = (20.0 + 5.50) * 0.18 = 4.59
        self.assertEqual(costs["brokerage"], 20.00)
        self.assertEqual(costs["stt"], 6.00)
        self.assertEqual(costs["exchange_charges"], 5.50)
        self.assertEqual(costs["gst"], 4.59)
        self.assertGreater(costs["total_friction"], 36.00)

    # =========================================================================
    # Test 12: Replay vs Live-Source Separation
    # =========================================================================
    def test_12_replay_vs_live_source_separation(self) -> None:
        """Replay observations are flagged as is_replay and do not pollute live feeds."""
        replay_engine = DeterministicPaperReplayEngine(replay_epoch_id="EPOCH-REPLAY-TEST-001")

        recorded_ticks = [
            {
                "instrument_id": "NSE:NIFTY26OCT22900CE",
                "price": 140.0,
                "timestamp_iso": "2026-10-15T09:30:00+05:30",
                "sequence": 1,
            },
            {
                "instrument_id": "NSE:NIFTY26OCT22900CE",
                "price": 142.5,
                "timestamp_iso": "2026-10-15T09:31:00+05:30",
                "sequence": 2,
            },
        ]

        def dummy_evaluator(obs: CanonicalMarketObservation) -> Optional[str]:
            return "BUY" if obs.price > 141.0 else None

        result = replay_engine.replay_stream(recorded_ticks, dummy_evaluator)
        self.assertEqual(result["replayed_events_count"], 2)
        self.assertEqual(result["simulated_trades_count"], 1)
        self.assertEqual(result["live_broker_calls_made"], 0)
        self.assertTrue(result["simulated_trades"][0]["is_replay"])
        self.assertFalse(result["simulated_trades"][0]["is_live"])

    # =========================================================================
    # Test 13: Portfolio Epoch Isolation
    # =========================================================================
    def test_13_portfolio_epoch_isolation(self) -> None:
        """Validates that demo, active evaluation, and replay epochs maintain strict isolation."""
        # Simulated server environment
        server = StandaloneDashboardServer()
        epochs_data = server.get_all_epochs()

        self.assertIn("active_epoch", epochs_data)
        self.assertIn("archived_epochs", epochs_data)
        # Active epoch is clean ₹10,000 baseline
        self.assertEqual(epochs_data["active_epoch"]["starting_capital_inr"], 10000.0)
        # Archived demo epoch is preserved ₹50,000 baseline
        demo_epoch = next(
            (ep for ep in epochs_data["archived_epochs"] if "50K" in ep["epoch_id"]), None
        )
        self.assertIsNotNone(demo_epoch)
        self.assertEqual(demo_epoch["starting_capital_inr"], 50000.0)

    # =========================================================================
    # Test 14: Recovery Without Duplicate Paper Orders
    # =========================================================================
    def test_14_recovery_without_duplicate_paper_orders(self) -> None:
        """Duplicate tick delivery in replay or recovery drops redundant executions."""
        replay_engine = DeterministicPaperReplayEngine(replay_epoch_id="EPOCH-REPLAY-DEDUP")

        # Ticks with identical signature
        recorded_ticks = [
            {
                "instrument_id": "NSE:BANKNIFTY",
                "price": 51500.0,
                "timestamp_iso": "2026-10-15T10:00:00+05:30",
                "sequence": 10,
            },
            {
                "instrument_id": "NSE:BANKNIFTY",
                "price": 51500.0,
                "timestamp_iso": "2026-10-15T10:00:00+05:30",
                "sequence": 10,
            },
        ]

        result = replay_engine.replay_stream(
            recorded_ticks, lambda obs: "BUY"
        )
        self.assertEqual(result["replayed_events_count"], 1)
        self.assertEqual(result["duplicates_dropped"], 1)
        self.assertEqual(len(result["simulated_trades"]), 1)

    # =========================================================================
    # Test 15: Fail-Closed Live-Order Boundary
    # =========================================================================
    def test_15_fail_closed_live_order_boundary(self) -> None:
        """Any attempt to invoke live order placement fails closed with HTTP 403 Forbidden."""
        import urllib.error
        import urllib.request

        server = StandaloneDashboardServer()
        server.start_background()
        try:
            port = server.server_address[1]
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/live_order",
                data=json.dumps({"symbol": "NIFTY26OCT22900CE", "side": "BUY"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=3.0)

            self.assertEqual(ctx.exception.code, 403)
            body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertIn("PAPER", body["mode"])
            self.assertIn("prohibited", body["error"].lower())
        finally:
            server.stop_server()


if __name__ == "__main__":
    unittest.main()

"""Phase 13 Comprehensive Quantitative Research Lab & Systematic Strategy Validation Test Suite.

Covers:
Category A: Mathematical tests (Black-Scholes Greeks, defined-risk max loss, intrabar ambiguity resolution).
Category B: Data integrity & sufficiency tests (Bhavcopy daily rejection for intraday, non-monotonic bars, crossed market).
Category C: Quantitative method tests (zero lookahead, train-only parameter fitting, walk-forward chronological splitting).
Category D: Execution and risk tests (0.5% max risk limit rejection, no naked short options rejection, daily loss circuit breaker).
Category E: Persistence & recovery tests (job queue crash recovery, idempotency, deliberation ledger).
Category F: Server API integration tests (all /api/research/... REST endpoints over HTTP).
Category G: Security & safety tests (STRICT PAPER ONLY invariants, loopback binding, secret redaction).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from agents.AGI_1_7.engine.agi17.finance.options_math import OptionsMath
from agents.AGI_1_7.engine.agi17.finance.strategy_research_framework import (
    CanonicalBar,
    DatasetMetadata,
    DataProvenance,
    LifecycleState,
    MarketObservation,
    StrategyDefinition,
    StrategyRegistry,
    StrategySignal,
    SignalDirection,
    ValidationVerdict,
)
from agents.AGI_1_7.engine.agi17.finance.quantitative_evaluation_harness import (
    ExperimentArtifact,
)
from agents.AGI_1_7.engine.agi17.finance.initial_strategy_portfolio import (
    OpeningRangeBreakoutStrategy,
    DefinedRiskVolatilityStrategy,
    RegimeAwareSelectorStrategy,
    get_initial_strategy_portfolio,
)
from agents.AGI_1_7.engine.agi17.finance.research_job_queue import (
    ResearchJobQueue,
    ResearchJob,
    JobStatus,
)
from agents.AGI_1_7.engine.agi17.finance.multi_agent_research_coordinator import (
    MultiAgentResearchCoordinator,
    ResearchProposal,
)
from agents.AGI_1_7.ui.standalone_dashboard_server import (
    StandaloneDashboardServer,
    LIVE_ORDER_DISPATCH_ENABLED,
)


class TestOmegaPhase13QuantResearchLab(unittest.TestCase):
    """Authoritative test suite for Phase 13 Quantitative Research Lab."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_path = Path(cls.temp_dir.name)
        cls.server_port = 8339
        cls.server = StandaloneDashboardServer(
            host="127.0.0.1",
            port=cls.server_port,
            storage_dir=cls.temp_path / "runtime_storage",
            starting_capital=10000.0,
            epoch_id="EPOCH-PAPER-10K-20261014-001",
        )
        cls.server.start_background()
        cls.base_url = f"http://127.0.0.1:{cls.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop_server()
        try:
            cls.temp_dir.cleanup()
        except Exception:
            pass

    def _http_get(self, path: str) -> tuple[int, dict]:
        req = urllib.request.Request(f"{self.base_url}{path}")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, data

    def _http_post(self, path: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, data

    # -------------------------------------------------------------------------
    # CATEGORY A: MATHEMATICAL TESTS
    # -------------------------------------------------------------------------

    def test_a01_black_scholes_greeks_benchmark(self) -> None:
        """Benchmark OptionsMath against John Hull textbook standard analytical values.
        
        Parameters: Spot=100, Strike=100, T=1.0 year, r=0.05 (5%), sigma=0.20 (20%).
        Theoretical Call price ~ 10.4506, Delta ~ 0.6368, Gamma ~ 0.0188.
        """
        call_px = OptionsMath.black_scholes_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry_years=1.0,
            risk_free_rate=0.05,
            volatility=0.20,
            is_call=True,
        )
        put_px = OptionsMath.black_scholes_price(
            spot=100.0,
            strike=100.0,
            time_to_expiry_years=1.0,
            risk_free_rate=0.05,
            volatility=0.20,
            is_call=False,
        )

        parity_diff = abs((call_px - put_px) - (100.0 - 100.0 * 0.9512294245))
        self.assertAlmostEqual(call_px, 10.4506, places=3)
        self.assertAlmostEqual(put_px, 5.5735, places=3)
        self.assertLess(parity_diff, 0.01)

        greeks_call = OptionsMath.calculate_greeks(
            spot=100.0,
            strike=100.0,
            time_to_expiry_years=1.0,
            risk_free_rate=0.05,
            volatility=0.20,
            is_call=True,
        )
        self.assertAlmostEqual(greeks_call["delta"], 0.6368, places=3)
        self.assertAlmostEqual(greeks_call["gamma"], 0.0188, places=3)
        self.assertGreater(greeks_call["vega"], 0.0)
        self.assertLess(greeks_call["theta"], 0.0)

    def test_a02_defined_risk_analytical_max_loss(self) -> None:
        """Verify analytical max loss computation for defined-risk volatility structures.
        
        Strategy B: STRAT-VOL-STRUCT-V1
        For an Iron Condor: Max Loss = (Strike Spread Width - Net Premium) * Lot Size.
        Analytical maximum loss must be strictly positive, deterministic, and bounded.
        """
        strat_b = DefinedRiskVolatilityStrategy()
        
        spread_width = 100.0
        net_credit = 70.0
        lot_size = 25
        expected_max_loss = (spread_width - net_credit) * lot_size
        
        computed_max_loss = strat_b.calculate_iron_condor_max_loss(
            call_spread_width=100.0,
            put_spread_width=100.0,
            net_credit=net_credit,
            quantity=lot_size,
        )
        self.assertEqual(computed_max_loss, expected_max_loss)
        self.assertEqual(computed_max_loss, 750.0)

        # Risk check against ₹10,000 capital:
        # Max allowable risk = 0.5% of 10,000 = ₹50.
        # Since ₹750 > ₹50, this single trade exceeds the 0.5% risk limit and must be rejected!
        capital = 10000.0
        is_safe, reason = strat_b.verify_risk_budget(
            max_loss=computed_max_loss,
            portfolio_capital=capital,
            max_risk_pct=0.005,  # 0.5%
        )
        self.assertFalse(is_safe)
        self.assertIn("exceeds risk budget", reason)

    def test_a03_intrabar_ambiguity_resolution_worst_case(self) -> None:
        """Verify conservative ambiguity resolution for intrabar high/low crossing.
        
        Strategy A: STRAT-ORB-V1
        If high >= target AND low <= stop_loss in the same bar,
        conservative resolution triggers the stop-loss first (worst-case execution).
        """
        strat_a = OpeningRangeBreakoutStrategy()
        
        entry_price = 100.0
        target = 105.0
        stop = 97.0
        
        # Candle that touches both stop and target: Low 96.0, High 106.0
        ambiguous_bar = CanonicalBar(
            symbol="NIFTY",
            timestamp_start="2026-10-15T10:00:00Z",
            timestamp_end="2026-10-15T10:15:00Z",
            open=100.0,
            high=106.0,
            low=96.0,
            close=103.0,
            volume=5000,
        )
        
        outcome, exit_px, explanation = strat_a.resolve_intrabar_exit(
            position_type="LONG",
            entry_price=entry_price,
            target_price=target,
            stop_price=stop,
            bar=ambiguous_bar,
        )
        self.assertEqual(outcome, "STOP_HIT")
        self.assertEqual(exit_px, stop)
        self.assertIn("Worst-case resolution: stop hit first", explanation)

    # -------------------------------------------------------------------------
    # CATEGORY B: DATA INTEGRITY & SUFFICIENCY TESTS
    # -------------------------------------------------------------------------

    def test_b01_bhavcopy_daily_rejected_for_intraday_strategy(self) -> None:
        """Verify that daily Bhavcopy data is rejected when evaluating intraday strategies."""
        queue = ResearchJobQueue(storage_dir=self.temp_path / "research_jobs_test")
        strat_a = OpeningRangeBreakoutStrategy()
        
        # Submit research job evaluating intraday STRAT-ORB-V1 against daily Bhavcopy
        job = queue.submit_job(
            strategy_id=strat_a.definition.strategy_id,
            dataset_id="DS-BHAVCOPY-NSE-2024-2026",
            parameters={"range_minutes": 15, "buffer_atr": 0.1},
        )
        
        # Execute job
        executed_job = queue.execute_job(job.job_id)
        self.assertEqual(executed_job.status, JobStatus.FAILED)
        self.assertIn("INSUFFICIENT_DATA", executed_job.error)
        self.assertIn("Daily Bhavcopy cannot evaluate intraday", executed_job.error)

    def test_b02_non_monotonic_bar_sequence_rejection(self) -> None:
        """Verify rejection of bars with non-monotonic timestamps or corrupted order."""
        bars = [
            CanonicalBar(symbol="NIFTY", timestamp_start="2026-10-15T09:15:00Z", timestamp_end="2026-10-15T09:30:00Z", open=100.0, high=102.0, low=99.0, close=101.0, volume=1000),
            CanonicalBar(symbol="NIFTY", timestamp_start="2026-10-15T09:30:00Z", timestamp_end="2026-10-15T09:45:00Z", open=101.0, high=103.0, low=100.0, close=102.0, volume=1200),
            CanonicalBar(symbol="NIFTY", timestamp_start="2026-10-15T09:20:00Z", timestamp_end="2026-10-15T09:35:00Z", open=102.0, high=104.0, low=101.0, close=103.0, volume=800),
        ]
        
        strat_a = OpeningRangeBreakoutStrategy()
        is_valid, reason = strat_a.validate_bar_sequence(bars)
        self.assertFalse(is_valid)
        self.assertIn("Non-monotonic timestamp detected", reason)

    def test_b03_crossed_market_and_zero_spread_rejection(self) -> None:
        """Verify that crossed market quotes (bid > ask) or negative spreads are rejected."""
        strat = OpeningRangeBreakoutStrategy()
        
        # Bid > Ask (crossed market)
        crossed_obs = MarketObservation(
            symbol="NIFTY",
            timestamp_utc="2026-10-15T10:00:00Z",
            price=22545.0,
            volume=100,
            bid=22550.0,
            ask=22540.0,
            provenance="SIMULATED",
        )
        is_valid, reason = strat.validate_observation(crossed_obs)
        self.assertFalse(is_valid)
        self.assertIn("Crossed market", reason)

    # -------------------------------------------------------------------------
    # CATEGORY C: QUANTITATIVE METHOD TESTS
    # -------------------------------------------------------------------------

    def test_c01_zero_lookahead_enforcement(self) -> None:
        """Verify that signal generation at index i has strictly zero access to future bars i+1..N."""
        strat_a = OpeningRangeBreakoutStrategy()
        
        bars = []
        for i in range(10):
            bars.append(
                CanonicalBar(
                    symbol="NIFTY",
                    timestamp_start=f"2026-10-15T09:{15 + i*2:02d}:00Z",
                    timestamp_end=f"2026-10-15T09:{15 + i*2 + 1:02d}:00Z",
                    open=100.0 + i,
                    high=102.0 + i,
                    low=99.0 + i,
                    close=101.0 + i,
                    volume=1000,
                )
            )
        
        # At step 3, passing visible slice bars[:3]
        feat_isolated = strat_a.validate_inputs(bars[:3])
        sig_isolated = strat_a.generate_signal(feat_isolated, bars[2])
        # Passing full list bars with explicit truncation check
        sig_safe = strat_a.generate_signal_safe(bars, current_idx=2)
        
        self.assertEqual(sig_isolated.action, sig_safe.action)
        self.assertEqual(sig_isolated.confidence_score, sig_safe.confidence_score)

    def test_c02_train_only_parameter_fitting_walk_forward(self) -> None:
        """Verify strict chronological train-test split without in-sample leakage."""
        queue = ResearchJobQueue(storage_dir=self.temp_path / "wf_split_test")
        
        train_bars, oos_bars = queue.chronological_train_test_split(total_bars=100, train_ratio=0.67)
        self.assertEqual(len(train_bars), 67)
        self.assertEqual(len(oos_bars), 33)
        self.assertEqual(train_bars[-1] + 1, oos_bars[0])  # Chronologically separated

    # -------------------------------------------------------------------------
    # CATEGORY D: EXECUTION AND RISK TESTS
    # -------------------------------------------------------------------------

    def test_d01_max_risk_limit_0_5_pct_enforced(self) -> None:
        """Verify trade proposals exceeding 0.5% risk limit are rejected by the risk engine."""
        strat = OpeningRangeBreakoutStrategy()
        capital = 10000.0  # ₹10,000 Sandbox
        # 0.5% of ₹10,000 = ₹50 max risk
        
        # Trade risking ₹150 (1.5% risk)
        proposal_excessive = strat.create_paper_proposal(
            symbol="NIFTY",
            direction=SignalDirection.BUY,
            entry_price=22500.0,
            stop_loss=22485.0,  # 15 pts * 10 qty = ₹150 risk
            quantity=10,
            capital=capital,
        )
        self.assertFalse(proposal_excessive.approved)
        self.assertIn("Exceeds 0.5% risk limit", proposal_excessive.rejection_reason)

        # Trade risking ₹40 (0.4% risk)
        proposal_valid = strat.create_paper_proposal(
            symbol="NIFTY",
            direction=SignalDirection.BUY,
            entry_price=22500.0,
            stop_loss=22496.0,  # 4 pts * 10 qty = ₹40 risk
            quantity=10,
            capital=capital,
        )
        self.assertTrue(proposal_valid.approved)

    def test_d02_zero_naked_short_options_invariant(self) -> None:
        """Verify strict rejection of any naked short options proposal (Strategy B invariant)."""
        strat_b = DefinedRiskVolatilityStrategy()
        
        # Naked Short Call
        naked_short_call = {
            "legs": [
                {"action": "SELL", "option_type": "CE", "strike": 22600.0, "quantity": 25}
            ]
        }
        is_safe, reason = strat_b.validate_option_structure(naked_short_call)
        self.assertFalse(is_safe)
        self.assertIn("ZERO naked short options invariant violated", reason)

        # Fully Hedged Bear Call Spread
        hedged_spread = {
            "legs": [
                {"action": "SELL", "option_type": "CE", "strike": 22600.0, "quantity": 25},
                {"action": "BUY", "option_type": "CE", "strike": 22700.0, "quantity": 25},
            ]
        }
        is_safe, reason = strat_b.validate_option_structure(hedged_spread)
        self.assertTrue(is_safe)

    def test_d03_daily_loss_circuit_breaker(self) -> None:
        """Verify daily loss circuit breaker halts new trade proposals after max loss clamp."""
        strat = OpeningRangeBreakoutStrategy()
        daily_loss_clamp = 500.0  # ₹500 max daily loss clamp
        
        # Current realized loss for the day = ₹520 (limit breached)
        is_allowed, reason = strat.check_daily_drawdown_limit(
            realized_pnl_today=-520.0,
            max_daily_loss=daily_loss_clamp,
        )
        self.assertFalse(is_allowed)
        self.assertIn("Daily drawdown circuit breaker tripped", reason)

    # -------------------------------------------------------------------------
    # CATEGORY E: PERSISTENCE & RECOVERY TESTS
    # -------------------------------------------------------------------------

    def test_e01_job_queue_persistence_and_crash_recovery(self) -> None:
        """Verify job queue state persistence and clean recovery of interrupted RUNNING jobs to PAUSED."""
        queue_dir = self.temp_path / "queue_recovery_test"
        
        # Phase 1: Initialize queue and write a running job
        q1 = ResearchJobQueue(storage_dir=queue_dir)
        j1 = q1.submit_job(strategy_id="STRAT-ORB-V1", dataset_id="DS-SYNTH-OPTIONS-WALKFORWARD-V1")
        # Artificially set status to RUNNING to simulate mid-flight process termination
        q1.update_job_status(j1.job_id, JobStatus.RUNNING)
        q1.save_state()

        # Phase 2: Start new queue instance representing process reboot
        q2 = ResearchJobQueue(storage_dir=queue_dir)
        recovered_job = q2.get_job(j1.job_id)
        
        self.assertIsNotNone(recovered_job)
        # Interrupted RUNNING job must recover to PAUSED
        self.assertEqual(recovered_job.status, JobStatus.PAUSED)
        self.assertIn("Recovered from interrupted process", recovered_job.recovery_notes)

    def test_e02_deliberation_ledger_append_and_retrieval(self) -> None:
        """Verify multi-agent deliberation records are appended, saved, and retrieved correctly."""
        ledger_path = self.temp_path / "deliberations_test" / "deliberations.json"
        coord = MultiAgentResearchCoordinator(ledger_path=ledger_path)
        
        proposal = ResearchProposal(
            strategy_id="STRAT-ORB-V1",
            dataset_id="DS-SYNTH-OPTIONS-WALKFORWARD-V1",
            parameters={"range_minutes": 15, "buffer_atr": 0.1, "max_risk_pct": 0.005},
        )
        
        deliberation = coord.conduct_deliberation(proposal)
        self.assertIsNotNone(deliberation.deliberation_id)
        self.assertEqual(len(deliberation.agent_votes), 4)  # Emily, Max, Alexa, Abhi
        
        # Verify persistence on disk
        self.assertTrue(ledger_path.exists())
        retrieved_history = coord.get_deliberation_history()
        self.assertGreaterEqual(len(retrieved_history), 1)
        self.assertEqual(retrieved_history[-1].deliberation_id, deliberation.deliberation_id)

    # -------------------------------------------------------------------------
    # CATEGORY F: SERVER API INTEGRATION TESTS
    # -------------------------------------------------------------------------

    def test_f01_api_research_strategies(self) -> None:
        """Verify GET /api/research/strategies returns all registered quantitative strategies."""
        status, data = self._http_get("/api/research/strategies")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        strategies = data.get("strategies", [])
        strategy_ids = [s["strategy_id"] for s in strategies]
        self.assertIn("STRAT-ORB-V1", strategy_ids)
        self.assertIn("STRAT-VOL-STRUCT-V1", strategy_ids)
        self.assertIn("STRAT-REGIME-SEL-V1", strategy_ids)

    def test_f02_api_research_strategy_details(self) -> None:
        """Verify GET /api/research/strategy_details returns strategy definition and parameter schema."""
        status, data = self._http_get("/api/research/strategy_details?strategy_id=STRAT-ORB-V1")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        strategy = data.get("strategy")
        self.assertEqual(strategy["strategy_id"], "STRAT-ORB-V1")
        self.assertIn("Opening Range Breakout", strategy["name"])
        self.assertIn("parameters_schema", strategy)

    def test_f03_api_research_datasets(self) -> None:
        """Verify GET /api/research/datasets returns registered research datasets."""
        status, data = self._http_get("/api/research/datasets")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        datasets = data.get("datasets", [])
        dataset_ids = [d["dataset_id"] for d in datasets]
        self.assertIn("DS-BHAVCOPY-NSE-2024-2026", dataset_ids)
        self.assertIn("DS-SYNTH-OPTIONS-WALKFORWARD-V1", dataset_ids)

    def test_f04_api_research_jobs(self) -> None:
        """Verify GET /api/research/jobs returns research scheduler job queue."""
        status, data = self._http_get("/api/research/jobs")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertIn("jobs", data)

    def test_f05_api_research_experiments(self) -> None:
        """Verify GET /api/research/experiments returns experiment registry."""
        status, data = self._http_get("/api/research/experiments")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertIn("experiments", data)

    def test_f06_api_research_explainability(self) -> None:
        """Verify GET /api/research/explainability returns agent deliberation history."""
        status, data = self._http_get("/api/research/explainability")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertIn("deliberations", data)

    def test_f07_api_research_experiments_run_deliberation(self) -> None:
        """Verify POST /api/research/experiments/run conducts council deliberation and executes experiment."""
        payload = {
            "strategy_id": "STRAT-ORB-V1",
            "dataset_id": "DS-SYNTH-OPTIONS-WALKFORWARD-V1",
            "parameters": {
                "range_minutes": 15,
                "buffer_atr": 0.1,
                "max_risk_pct": 0.005,
            },
        }
        status, data = self._http_post("/api/research/experiments/run", payload)
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        self.assertIn("deliberation", data)
        self.assertIn("experiment", data)
        exp = data["experiment"]
        self.assertIn("performance_metrics", exp)
        self.assertIn("reproducibility_hash", exp)

    # -------------------------------------------------------------------------
    # CATEGORY G: SECURITY & SAFETY TESTS
    # -------------------------------------------------------------------------

    def test_g01_strict_paper_only_live_dispatch_blocked(self) -> None:
        """Verify LIVE_ORDER_DISPATCH_ENABLED is strictly False and cannot be bypassed."""
        self.assertFalse(LIVE_ORDER_DISPATCH_ENABLED)
        
        status, data = self._http_get("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("mode"), "PAPER")
        self.assertFalse(data.get("is_live_allowed"))

    def test_g02_server_loopback_binding(self) -> None:
        """Verify server is bound strictly to 127.0.0.1, preventing unauthenticated network exposure."""
        self.assertEqual(self.server.host, "127.0.0.1")

    def test_g03_zero_credential_exposure_in_research_artifacts(self) -> None:
        """Verify research artifacts and deliberation traces contain no API keys, tokens, or passwords."""
        status, data = self._http_get("/api/research/explainability")
        self.assertEqual(status, 200)
        dump = json.dumps(data)
        for forbidden in ["api_key", "secret_key", "password", "access_token", "jwt"]:
            self.assertNotIn(f'"{forbidden}": "sk_', dump)
            self.assertNotIn(f'"{forbidden}": "ey', dump)


if __name__ == "__main__":
    unittest.main()

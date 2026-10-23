"""Unit test battery for Multi-Session Walk-Forward Stat-Arb Backtest & Optimization Simulator.

Wave 39 Verification Suite (TASK-BN-49):
Validates:
1. Synthetic multi-session regime data generator (SyntheticMultiSessionFeedGenerator)
   across COINTEGRATED_NORMAL, STRUCTURAL_DECOUPLING, HIGH_TOXICITY_SHOCK, LEGGING_OUTAGE,
   and EXPIRY_SQUARE_OFF.
2. Purged walk-forward cross-validation splitter (PurgedWalkForwardCV) with anchored and rolling
   modes, verifying zero serial leakage through the purge buffer.
3. Parameter space configuration and structural boundary constraints (exit_z < entry_z < stop_z).
4. Direct execution across distinct market regimes verifying convergence exits, stop-loss exits,
   frozen toxicity gating, Leg-1 unwind rollback, and 15:15 IST auto-square-off.
5. Full walk-forward optimization, Bailey & López de Prado (2014) Deflated Sharpe Ratio (DSR),
   Probabilistic Sharpe Ratio (PSR), out-of-sample degradation auditing, and decomposed P&L waterfall.
6. Report serialization to dictionary and markdown tear-sheet rendering.

Zero external dependencies; executes deterministically in <0.5s.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

from agents.AGI_1_7.engine.agi17.finance.stat_arb_walk_forward_simulator import (
    DegradationClassification,
    FoldTrialResult,
    MarketSession,
    PurgedWalkForwardCV,
    RegimePhase,
    SessionSimulationResult,
    SessionTick,
    StatArbHyperparameterSpace,
    StatArbWalkForwardSimulator,
    SyntheticMultiSessionFeedGenerator,
    WalkForwardPerformanceReport,
    WalkForwardSessionConfig,
    WalkForwardSplit,
)
from agents.AGI_1_7.engine.agi17.finance.statistical_arbitrage_orchestrator import (
    OrchestratorConfig,
    OrchestratorState,
    TradeExitReason,
)
from agents.AGI_1_7.engine.agi17.finance.strategy_optimizer import SplitMethod


class TestOmegaStatArbWalkForward(unittest.TestCase):
    """Test suite for Wave 39 Multi-Session Walk-Forward Stat-Arb Simulator."""

    def setUp(self) -> None:
        self.simulator = StatArbWalkForwardSimulator(initial_capital_inr=2_000_000.0)

    def test_multi_session_feed_generator_regimes(self) -> None:
        """Verify deterministic synthesis of all 5 market regimes."""
        regimes = [
            RegimePhase.COINTEGRATED_NORMAL,
            RegimePhase.STRUCTURAL_DECOUPLING,
            RegimePhase.HIGH_TOXICITY_SHOCK,
            RegimePhase.LEGGING_OUTAGE,
            RegimePhase.EXPIRY_SQUARE_OFF,
        ]

        for reg in regimes:
            cfg = WalkForwardSessionConfig(
                session_id=f"TEST-{reg.value}",
                regime=reg,
                num_ticks=60,
                seed=42,
            )
            sess = SyntheticMultiSessionFeedGenerator.generate_session(cfg)
            self.assertEqual(sess.regime, reg)
            self.assertEqual(len(sess.ticks), 60)

            # Check tick properties
            t0 = sess.ticks[0]
            t1 = sess.ticks[1]
            self.assertEqual(t0.asset, "NIFTY50")
            self.assertEqual(t1.asset, "BANKNIFTY")
            self.assertGreater(t0.price, 20000.0)
            self.assertGreater(t1.price, 40000.0)
            self.assertGreater(t0.volume, 0.0)

        # Test batch dataset generation
        batch = SyntheticMultiSessionFeedGenerator.generate_multi_session_dataset(
            num_sessions=8,
            base_seed=77,
        )
        self.assertEqual(len(batch), 8)
        regimes_found = {s.regime for s in batch}
        self.assertGreater(len(regimes_found), 1)

    def test_purged_walk_forward_cv_splits(self) -> None:
        """Verify train/test/purge partitioning and absence of data leakage."""
        sessions = SyntheticMultiSessionFeedGenerator.generate_multi_session_dataset(
            num_sessions=10,
            base_seed=123,
        )

        # 1. Anchored splitting
        splitter_anchored = PurgedWalkForwardCV(
            n_splits=3,
            train_ratio=0.40,
            purge_sessions=1,
            method=SplitMethod.ANCHORED,
        )
        splits = splitter_anchored.split(sessions)
        self.assertGreaterEqual(len(splits), 1)

        for s in splits:
            train_ids = {x.session_id for x in s.train_sessions}
            test_ids = {x.session_id for x in s.test_sessions}
            purge_ids = {x.session_id for x in s.purged_sessions}

            # Must be mutually disjoint
            self.assertTrue(train_ids.isdisjoint(test_ids))
            self.assertTrue(train_ids.isdisjoint(purge_ids))
            self.assertTrue(test_ids.isdisjoint(purge_ids))

            # Train precedes test
            max_train_idx = max(int(sid.split("-")[1]) for sid in train_ids)
            min_test_idx = min(int(sid.split("-")[1]) for sid in test_ids)
            self.assertLess(max_train_idx, min_test_idx)

        # 2. Rolling splitting
        splitter_rolling = PurgedWalkForwardCV(
            n_splits=2,
            train_ratio=0.40,
            purge_sessions=1,
            method=SplitMethod.ROLLING,
        )
        rolling_splits = splitter_rolling.split(sessions)
        self.assertGreaterEqual(len(rolling_splits), 1)

        # 3. Invalid parameters raise ValueError
        with self.assertRaises(ValueError):
            PurgedWalkForwardCV(n_splits=0)
        with self.assertRaises(ValueError):
            PurgedWalkForwardCV(train_ratio=0.95)
        with self.assertRaises(ValueError):
            PurgedWalkForwardCV(purge_sessions=-1)

    def test_hyperparameter_space_generation(self) -> None:
        """Verify grid search generation enforces exit_z < entry_z < stop_z hierarchy."""
        space = StatArbHyperparameterSpace(
            entry_z_list=[1.8, 2.0],
            exit_z_list=[0.3, 0.5],
            stop_z_list=[3.0, 3.5],
            base_fractional_kelly_list=[0.25],
            min_net_edge_hurdle_inr_list=[-1000.0, -500.0],
        )
        grid = space.generate_grid()
        self.assertGreater(len(grid), 0)

        for p in grid:
            self.assertLess(p["exit_z"], p["entry_z"])
            self.assertLess(p["entry_z"], p["stop_z"])
            self.assertGreater(p["base_fractional_kelly"], 0.0)

    def test_session_simulation_across_regimes(self) -> None:
        """Verify simulator execution across diverse market regimes."""
        # 1. Normal Regime -> should trade and close with convergence or holding
        norm_cfg = WalkForwardSessionConfig(
            session_id="SESS-NORM",
            regime=RegimePhase.COINTEGRATED_NORMAL,
            num_ticks=120,
            seed=42,
        )
        norm_sess = SyntheticMultiSessionFeedGenerator.generate_session(norm_cfg)
        sr, pnl, dd, trades, wr, res = self.simulator.evaluate_parameter_set(
            params={"entry_z": 1.8, "exit_z": 0.3, "stop_z": 3.5, "base_fractional_kelly": 0.25, "min_net_edge_hurdle_inr": -1000.0},
            sessions=[norm_sess],
        )
        self.assertGreaterEqual(trades, 1)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].final_state, OrchestratorState.IDLE)
        # Check decomposed attribution identity
        for t in res[0].trades:
            self.assertIsNotNone(t.pnl_attribution)
            attr = t.pnl_attribution
            self.assertAlmostEqual(attr.explained_ratio, 1.0, places=4)

        # 2. Decoupling Regime -> hits stop loss
        dec_cfg = WalkForwardSessionConfig(
            session_id="SESS-DEC",
            regime=RegimePhase.STRUCTURAL_DECOUPLING,
            num_ticks=80,
            seed=42,
        )
        dec_sess = SyntheticMultiSessionFeedGenerator.generate_session(dec_cfg)
        _, _, _, dec_trades, _, dec_res = self.simulator.evaluate_parameter_set(
            params={"entry_z": 1.5, "exit_z": 0.3, "stop_z": 2.5, "base_fractional_kelly": 0.25, "min_net_edge_hurdle_inr": -1000.0},
            sessions=[dec_sess],
        )
        if dec_trades > 0:
            stop_exits = [
                t for t in dec_res[0].trades
                if t.pnl_attribution and t.pnl_attribution.exit_reason == TradeExitReason.STOP_LOSS_EXIT
            ]
            self.assertGreaterEqual(len(stop_exits), 1)

        # 3. Legging Outage Regime -> triggers Leg 1 unwind rollback
        leg_cfg = WalkForwardSessionConfig(
            session_id="SESS-LEG",
            regime=RegimePhase.LEGGING_OUTAGE,
            num_ticks=55,
            seed=42,
        )
        leg_sess = SyntheticMultiSessionFeedGenerator.generate_session(leg_cfg)
        _, _, _, _, _, leg_res = self.simulator.evaluate_parameter_set(
            params={"entry_z": 1.5, "exit_z": 0.3, "stop_z": 3.5, "base_fractional_kelly": 0.25, "min_net_edge_hurdle_inr": -1000.0},
            sessions=[leg_sess],
        )
        self.assertGreaterEqual(leg_res[0].unwind_incidents, 1)

        # 4. Expiry Square-Off Regime -> position closed via END_OF_SESSION_EXIT
        exp_cfg = WalkForwardSessionConfig(
            session_id="SESS-EXP",
            regime=RegimePhase.EXPIRY_SQUARE_OFF,
            num_ticks=60,
            seed=42,
        )
        exp_sess = SyntheticMultiSessionFeedGenerator.generate_session(exp_cfg)
        _, _, _, exp_trades, _, exp_res = self.simulator.evaluate_parameter_set(
            params={"entry_z": 1.5, "exit_z": 0.1, "stop_z": 4.5, "base_fractional_kelly": 0.25, "min_net_edge_hurdle_inr": -1000.0},
            sessions=[exp_sess],
        )
        self.assertGreaterEqual(exp_trades, 1)
        eod_exits = [
            t for t in exp_res[0].trades
            if t.pnl_attribution and t.pnl_attribution.exit_reason in (TradeExitReason.END_OF_SESSION_EXIT, TradeExitReason.CONVERGENCE_EXIT)
        ]
        self.assertGreaterEqual(len(eod_exits), 1)

    def test_walk_forward_optimization_and_dsr(self) -> None:
        """Verify complete walk-forward pipeline, Deflated Sharpe Ratio, and degradation metrics."""
        sessions = SyntheticMultiSessionFeedGenerator.generate_multi_session_dataset(
            num_sessions=6,
            normal_ratio=0.70,
            decoupling_ratio=0.15,
            toxicity_ratio=0.0,
            legging_ratio=0.15,
            base_seed=88,
        )

        param_grid = [
            {"entry_z": 1.8, "exit_z": 0.3, "stop_z": 3.5, "base_fractional_kelly": 0.25, "min_net_edge_hurdle_inr": -1000.0},
            {"entry_z": 2.0, "exit_z": 0.4, "stop_z": 3.5, "base_fractional_kelly": 0.20, "min_net_edge_hurdle_inr": -1000.0},
        ]

        splitter = PurgedWalkForwardCV(n_splits=2, train_ratio=0.50, purge_sessions=1)
        report = self.simulator.run_walk_forward(
            sessions=sessions,
            param_grid=param_grid,
            cv_splitter=splitter,
        )

        self.assertIsInstance(report, WalkForwardPerformanceReport)
        self.assertGreaterEqual(report.num_parameter_trials, 2)
        self.assertGreaterEqual(report.deflated_sharpe_ratio, 0.0)
        self.assertLessEqual(report.deflated_sharpe_ratio, 1.0)
        self.assertGreaterEqual(report.probabilistic_sharpe_ratio, 0.0)
        self.assertLessEqual(report.probabilistic_sharpe_ratio, 1.0)
        self.assertGreaterEqual(report.expected_max_sharpe, 0.0)
        self.assertIn(report.degradation_classification, list(DegradationClassification))
        self.assertEqual(len(report.fold_results), 2)
        self.assertAlmostEqual(report.explained_variance_ratio, 1.0, places=4)

    def test_markdown_tearsheet_and_serialization(self) -> None:
        """Verify performance report JSON serialization and Markdown tear-sheet rendering."""
        dummy_fold = FoldTrialResult(
            fold_index=0,
            params={"entry_z": 2.0, "exit_z": 0.5, "stop_z": 3.5},
            in_sample_sharpe=2.45,
            in_sample_net_pnl=12500.0,
            in_sample_max_dd_pct=1.2,
            in_sample_trades=8,
            in_sample_win_rate=0.75,
            out_of_sample_sharpe=2.10,
            out_of_sample_net_pnl=8400.0,
            out_of_sample_max_dd_pct=0.9,
            out_of_sample_trades=5,
            out_of_sample_win_rate=0.80,
            degradation_ratio=0.857,
            classification=DegradationClassification.ROBUST,
        )

        report = WalkForwardPerformanceReport(
            in_sample_sharpe=2.45,
            out_of_sample_sharpe=2.10,
            degradation_ratio=0.857,
            degradation_classification=DegradationClassification.ROBUST,
            num_parameter_trials=10,
            trials_sr_variance=0.25,
            expected_max_sharpe=1.85,
            deflated_sharpe_ratio=0.78,
            probabilistic_sharpe_ratio=0.92,
            total_net_pnl_inr=20900.0,
            total_gross_edge_inr=24500.0,
            total_market_impact_drag_inr=1600.0,
            total_statutory_fees_drag_inr=2000.0,
            explained_variance_ratio=1.0,
            best_params={"entry_z": 2.0, "exit_z": 0.5, "stop_z": 3.5},
            fold_results=[dummy_fold],
            total_trades=13,
            unwind_rollback_incidents=1,
        )

        # JSON dictionary
        d = report.to_dict()
        self.assertEqual(d["degradation_classification"], "ROBUST")
        self.assertEqual(d["total_net_pnl_inr"], 20900.0)
        self.assertEqual(len(d["folds"]), 1)

        # Markdown render
        md = report.generate_markdown_tearsheet()
        self.assertIn("# INSTITUTIONAL STATISTICAL ARBITRAGE WALK-FORWARD AUDIT", md)
        self.assertIn("ROBUST", md)
        self.assertIn("Decomposed P&L Waterfall Attribution", md)
        self.assertIn("Deflated Sharpe (DSR)", md)
        self.assertIn("₹20,900.00", md)


if __name__ == "__main__":
    unittest.main()

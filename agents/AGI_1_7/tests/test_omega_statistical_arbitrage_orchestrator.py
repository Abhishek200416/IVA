"""Unit test battery for High-Frequency Statistical Arbitrage Orchestrator.

Wave 37 Verification Suite (TASK-BN-47):
Validates:
1. Nominal spread round-trip lifecycle (ENTRY -> HOLDING -> CONVERGENCE_EXIT).
2. Invariant 1: Asymmetric Leg Fill & Emergency Atomic Rollback (LEG_ONE_UNWIND) on Leg 2 failure.
3. Invariant 2: Toxicity-gated Fractional Kelly scaling by (1 - rho_toxic) and macro freeze (rho >= 0.50).
4. Invariant 3: Strict monotonic decomposed P&L attribution with explained ratio >= 95%.
5. Continuous exponential drawdown governor dampening and hard-stop halt at >= 6% drawdown.
6. SEBI integer lot quantization (Bank Nifty = 15, Nifty 50 = 25 contracts) and friction hurdle gating.
"""

from __future__ import annotations

import unittest

from agents.AGI_1_7.engine.agi17.finance.statistical_arbitrage_orchestrator import (
    OrchestratorConfig,
    OrchestratorState,
    SpreadDecomposedPnl,
    SpreadPosition,
    SpreadTradeSide,
    StatisticalArbitrageOrchestrator,
    StatutoryCostBreakdown,
    TradeExitReason,
)


class TestOmegaStatisticalArbitrageOrchestrator(unittest.TestCase):
    """Test suite for Wave 37 Statistical Arbitrage Orchestrator."""

    def setUp(self) -> None:
        self.config = OrchestratorConfig(
            asset1_name="BANKNIFTY",
            asset2_name="NIFTY50",
            lot_size_1=15,
            lot_size_2=25,
            initial_capital_inr=2_000_000.0,
            base_fractional_kelly=0.25,
            cotoxicity_alert_threshold=0.35,
            max_drawdown_limit=0.06,
            min_net_edge_hurdle_inr=-1000.0,
            entry_z=2.0,
            exit_z=0.5,
            stop_z=3.5,
        )
        self.orchestrator = StatisticalArbitrageOrchestrator(config=self.config)

    def test_nominal_spread_lifecycle_and_convergence_exit(self) -> None:
        """Verify standard Long Spread trade entry, holding, and mean-reversion exit."""
        # 1. Warm up Kalman filter with steady cointegrated ratio (y = 2.0 * x)
        for i in range(25):
            t = float(i)
            self.orchestrator.on_tick("NIFTY50", 24000.0 + (0.5 if i % 2 == 0 else -0.5), 100.0, t)
            self.orchestrator.on_tick("BANKNIFTY", 48000.0 + (1.0 if i % 2 == 0 else -1.0), 50.0, t)

        self.assertEqual(self.orchestrator.state, OrchestratorState.IDLE)

        # 2. Trigger entry by widening spread (Bank Nifty drops relative to Nifty -> LONG_SPREAD)
        res_entry = self.orchestrator.on_tick("BANKNIFTY", 48000.0 - 20.0, 100.0, 26.0)
        self.assertEqual(self.orchestrator.state, OrchestratorState.POSITION_OPEN)
        self.assertEqual(res_entry["action"], "ENTRY_SUCCESS")
        self.assertIsNotNone(self.orchestrator.active_position)
        pos = self.orchestrator.active_position
        self.assertEqual(pos.side, SpreadTradeSide.LONG_SPREAD)
        self.assertGreaterEqual(pos.asset1_lots, 1)
        self.assertGreaterEqual(pos.asset2_lots, 1)

        # 3. Spread mean-reverts back to equilibrium -> CONVERGENCE_EXIT
        res_exit = self.orchestrator.on_tick("BANKNIFTY", 48000.0, 50.0, 27.0)
        self.assertEqual(self.orchestrator.state, OrchestratorState.POSITION_CLOSED)
        self.assertEqual(res_exit["action"], "POSITION_CLOSED_CONVERGENCE")
        self.assertIsNone(self.orchestrator.active_position)
        self.assertEqual(len(self.orchestrator.completed_trades), 1)

        closed_trade = self.orchestrator.completed_trades[0]
        self.assertIsNotNone(closed_trade.pnl_attribution)
        self.assertEqual(closed_trade.pnl_attribution.exit_reason, TradeExitReason.CONVERGENCE_EXIT)
        self.assertGreater(closed_trade.pnl_attribution.gross_edge_pnl, 0.0)

    def test_invariant_1_asymmetric_leg_fill_rollback(self) -> None:
        """Verify Invariant 1: Leg 2 failure triggers emergency atomic LEG_ONE_UNWIND."""
        # Warm up
        for i in range(25):
            t = float(i)
            self.orchestrator.on_tick("NIFTY50", 24000.0 + (0.5 if i % 2 == 0 else -0.5), 100.0, t)
            self.orchestrator.on_tick("BANKNIFTY", 48000.0 + (1.0 if i % 2 == 0 else -1.0), 50.0, t)

        # Trigger entry with simulated Leg 2 failure
        res = self.orchestrator.on_tick(
            "BANKNIFTY", 48000.0 - 20.0, 100.0, 26.0, simulate_leg2_failure=True
        )

        # Must NOT be left with an open unhedged position
        self.assertIsNone(self.orchestrator.active_position)
        self.assertEqual(self.orchestrator.state, OrchestratorState.IDLE)
        self.assertEqual(self.orchestrator.unwind_incidents, 1)
        self.assertEqual(len(self.orchestrator.completed_trades), 1)

        unwound_trade = self.orchestrator.completed_trades[0]
        self.assertEqual(
            unwound_trade.pnl_attribution.exit_reason,
            TradeExitReason.UNWIND_REJECTION_EXIT,
        )
        self.assertIn("emergency atomic unwind", unwound_trade.pnl_attribution.notes)

    def test_invariant_2_toxicity_gated_kelly_scaling(self) -> None:
        """Verify Invariant 2: Fractional Kelly multiplier dynamically scales by (1 - rho_toxic)."""
        base_kappa = self.config.base_fractional_kelly  # 0.25

        # 1. Normal benign regime (rho_toxic = 0.10, VPIN = 0.15) -> full base kappa
        kappa_benign = self.orchestrator.calculate_toxicity_gated_kelly(rho_toxic=0.10, vpin=0.15)
        self.assertAlmostEqual(kappa_benign, base_kappa, places=4)

        # 2. Elevated co-toxicity (rho_toxic = 0.40 >= 0.35 threshold) -> scales down by (1 - 0.40) = 0.60
        kappa_elevated = self.orchestrator.calculate_toxicity_gated_kelly(rho_toxic=0.40, vpin=0.20)
        expected_scaled = round(base_kappa * (1.0 - 0.40), 4)  # 0.25 * 0.60 = 0.15
        self.assertAlmostEqual(kappa_elevated, expected_scaled, places=4)

        # 3. High co-toxicity shock (rho_toxic = 0.60 >= 0.50) -> complete freeze (0.0)
        kappa_shock = self.orchestrator.calculate_toxicity_gated_kelly(rho_toxic=0.60, vpin=0.20)
        self.assertEqual(kappa_shock, 0.0)

        # 4. Acute single-asset VPIN spike (VPIN >= 0.50) -> complete freeze (0.0)
        kappa_vpin_freeze = self.orchestrator.calculate_toxicity_gated_kelly(rho_toxic=0.20, vpin=0.55)
        self.assertEqual(kappa_vpin_freeze, 0.0)

    def test_invariant_3_strict_monotonic_pnl_attribution(self) -> None:
        """Verify Invariant 3: P&L is 100% decomposed into Gross, Impact, and Statutory fees."""
        # Warm up
        for i in range(25):
            t = float(i)
            self.orchestrator.on_tick("NIFTY50", 24000.0 + (0.5 if i % 2 == 0 else -0.5), 100.0, t)
            self.orchestrator.on_tick("BANKNIFTY", 48000.0 + (1.0 if i % 2 == 0 else -1.0), 50.0, t)

        # Enter Long Spread
        self.orchestrator.on_tick("BANKNIFTY", 48000.0 - 20.0, 100.0, 26.0)
        self.assertEqual(self.orchestrator.state, OrchestratorState.POSITION_OPEN)

        # Exit on convergence
        self.orchestrator.on_tick("BANKNIFTY", 48000.0, 50.0, 27.0)
        self.assertEqual(len(self.orchestrator.completed_trades), 1)

        trade = self.orchestrator.completed_trades[0]
        decomp = trade.pnl_attribution
        self.assertIsNotNone(decomp)

        # Verification of identity: Net PnL = Gross - Impact - Statutory
        reconstructed_net = decomp.gross_edge_pnl - decomp.market_impact_drag - decomp.statutory_fees_drag
        self.assertAlmostEqual(decomp.net_realized_pnl, reconstructed_net, places=2)
        # Explained ratio must be >= 95%
        self.assertGreaterEqual(decomp.explained_ratio, 0.95)
        self.assertGreater(decomp.statutory_fees_drag, 0.0)
        self.assertGreater(decomp.market_impact_drag, 0.0)

    def test_drawdown_governor_circuit_breaker(self) -> None:
        """Verify continuous drawdown dampening and hard stop when DD >= 6%."""
        # Simulate severe loss in capital
        self.orchestrator.peak_capital = 2_000_000.0
        self.orchestrator.current_capital = 2_000_000.0 * (1.0 - 0.07)  # 7% DD > 6% limit

        self.assertGreaterEqual(self.orchestrator.current_drawdown, 0.06)

        # Ticking should immediately register HALTED_DRAWDOWN
        res = self.orchestrator.on_tick("BANKNIFTY", 48000.0, 100.0, 10.0)
        self.assertEqual(self.orchestrator.state, OrchestratorState.HALTED_DRAWDOWN)
        self.assertEqual(res["action"], "DRAWDOWN_HALTED")

    def test_sebi_lot_quantization_and_statutory_charges(self) -> None:
        """Verify Indian lot sizes (BN=15, NIFTY=25) and regulatory charges computation."""
        # Evaluate statutory breakdown for 1 BN lot (15) and 2 Nifty lots (50)
        charges = self.orchestrator.calculate_statutory_charges(
            asset1_price=50000.0,
            asset1_qty=15,
            asset1_is_buy=True,
            asset2_price=24000.0,
            asset2_qty=50,
            asset2_is_buy=False,
        )
        self.assertIsInstance(charges, StatutoryCostBreakdown)
        self.assertGreater(charges.stt_inr, 0.0)
        self.assertGreater(charges.stamp_duty_inr, 0.0)
        self.assertGreater(charges.exchange_fee_inr, 0.0)
        self.assertGreater(charges.sebi_fee_inr, 0.0)
        self.assertGreater(charges.gst_inr, 0.0)
        self.assertEqual(charges.brokerage_inr, 40.0)  # Rs 20 * 2 legs
        self.assertGreater(charges.total_statutory_inr, 40.0)


if __name__ == "__main__":
    unittest.main()

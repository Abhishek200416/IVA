"""Acceptance tests for Cross-Index Beta Hedging and Margin Call Liquidation.

Covers:
1. TASK-BN-13: BetaWeightedHedgeEngine:
   - Log returns generation.
   - Rolling covariance, beta, correlation, and R^2 estimation.
   - Cross-index dollar delta hedge allocation and discrete lot sizing on NIFTY 50.
2. TASK-BN-14: MarginCallLiquidationEngine:
   - 4-tier margin health state transitions (HEALTHY, WARNING, CALL, FORCE_LIQUIDATION).
   - Trade lockout gating under margin deficit.
   - Orderly priority-weighted unwinding of risky option legs until safe buffer restored.
"""

from __future__ import annotations

import math
import unittest

from agents.AGI_1_7.engine.agi17.finance.cross_index_hedge import (
    BetaHedgeRatioResult,
    BetaWeightedHedgeEngine,
)
from agents.AGI_1_7.engine.agi17.finance.margin_liquidation import (
    LiquidationCandidate,
    MarginCallLiquidationEngine,
    MarginStatus,
)


class TestOmegaCrossHedgeAndMarginLiquidation(unittest.TestCase):
    """Test suite for Cross-Index Hedging and Margin Call Liquidation."""

    def test_01_beta_and_r_squared_estimation(self) -> None:
        """Verifies econometric beta, R^2, and residual basis std estimation."""
        # Simulated realistic cointegrated price path (Nifty 50 and Bank Nifty)
        # Bank Nifty innovations are beta * Nifty innovations + tiny residual noise
        nifty_innovations = [0.005, -0.004, 0.008, 0.002, -0.006, 0.007, -0.003, 0.009, 0.001, -0.005]
        bank_nifty_innovations = [1.30 * r + 0.0001 for r in nifty_innovations]

        nifty_prices = [24000.0]
        for r in nifty_innovations:
            nifty_prices.append(nifty_prices[-1] * math.exp(r))

        bank_nifty_prices = [50000.0]
        for r in bank_nifty_innovations:
            bank_nifty_prices.append(bank_nifty_prices[-1] * math.exp(r))

        nifty_returns = BetaWeightedHedgeEngine.calculate_log_returns(nifty_prices)
        bank_nifty_returns = BetaWeightedHedgeEngine.calculate_log_returns(bank_nifty_prices)

        self.assertEqual(len(nifty_returns), 10)
        self.assertEqual(len(bank_nifty_returns), 10)

        beta, r_squared, corr, residual_std = BetaWeightedHedgeEngine.calculate_rolling_beta(
            target_returns=bank_nifty_returns,
            hedge_returns=nifty_returns,
        )

        self.assertAlmostEqual(beta, 1.30, delta=0.05)
        self.assertGreater(corr, 0.95)
        self.assertGreater(r_squared, 0.90)
        self.assertLess(residual_std, 0.001)

    def test_02_cross_hedge_allocation(self) -> None:
        """Verifies multi-asset dollar delta cross-hedging into NIFTY 50 contracts."""
        target_net_delta = 25.0  # Net Long Bank Nifty Delta
        target_spot = 50000.0
        hedge_spot = 24000.0
        beta = 1.25
        hedge_lot_size = 25

        res = BetaWeightedHedgeEngine.calculate_hedge_allocation(
            target_net_delta=target_net_delta,
            target_spot=target_spot,
            hedge_spot=hedge_spot,
            beta=beta,
            r_squared=0.88,
            correlation=0.938,
            residual_std=0.004,
            hedge_lot_size=hedge_lot_size,
        )

        self.assertIsInstance(res, BetaHedgeRatioResult)
        self.assertEqual(res.target_dollar_delta, 1_250_000.0)
        # Hedge Dollar Delta = -1.25 * 1,250,000 = -1,562,500.0
        self.assertEqual(res.hedge_dollar_delta, -1_562_500.0)
        # 1 NIFTY Lot = 24,000 * 25 = 600,000
        # Float contracts = -1,562,500 / 600,000 = -2.604 lots -> Round to -3 lots
        self.assertAlmostEqual(res.hedge_contracts_float, -2.604, places=2)
        self.assertEqual(res.hedge_lots_recommended, -3)
        self.assertIn("SELL 3 LOTS (NIFTY)", res.recommended_action)
        self.assertAlmostEqual(res.effective_hedge_pct, 88.0)

    def test_03_margin_health_classification(self) -> None:
        """Verifies 4-tier margin health and lockout transitions."""
        # 1. Healthy: 60% utilization
        s1 = MarginCallLiquidationEngine.evaluate_account_margin(
            total_equity=1_000_000.0,
            available_cash=400_000.0,
            initial_margin_required=600_000.0,
        )
        self.assertEqual(s1.status, MarginStatus.HEALTHY)
        self.assertFalse(s1.is_locked_out)
        self.assertEqual(s1.margin_deficit, 0.0)

        # 2. Warning: 85% utilization
        s2 = MarginCallLiquidationEngine.evaluate_account_margin(
            total_equity=1_000_000.0,
            available_cash=150_000.0,
            initial_margin_required=850_000.0,
        )
        self.assertEqual(s2.status, MarginStatus.MARGIN_WARNING)
        self.assertFalse(s2.is_locked_out)

        # 3. Margin Call: 105% utilization
        s3 = MarginCallLiquidationEngine.evaluate_account_margin(
            total_equity=1_000_000.0,
            available_cash=-50_000.0,
            initial_margin_required=1_050_000.0,
        )
        self.assertEqual(s3.status, MarginStatus.MARGIN_CALL)
        self.assertTrue(s3.is_locked_out)
        self.assertEqual(s3.margin_deficit, 50_000.0)

        # 4. Force Liquidation: 125% utilization
        s4 = MarginCallLiquidationEngine.evaluate_account_margin(
            total_equity=1_000_000.0,
            available_cash=-250_000.0,
            initial_margin_required=1_250_000.0,
        )
        self.assertEqual(s4.status, MarginStatus.FORCE_LIQUIDATION)
        self.assertTrue(s4.is_locked_out)

    def test_04_orderly_liquidation_unwinding(self) -> None:
        """Verifies orderly unwinding prioritizes short options and restores safe margin."""
        account = MarginCallLiquidationEngine.evaluate_account_margin(
            total_equity=1_000_000.0,
            available_cash=-100_000.0,
            initial_margin_required=1_200_000.0,  # 120% Force Liquidation
        )
        self.assertEqual(account.status, MarginStatus.FORCE_LIQUIDATION)

        candidates = [
            LiquidationCandidate(
                position_id="POS-LONG-CE",
                contract_symbol="BANKNIFTY26OCT50000CE",
                lots=5,
                is_short=False,
                margin_per_lot=20_000.0,
                unrealized_pnl_per_lot=-1_000.0,
                risk_priority=1.0,  # Long option: low risk priority
            ),
            LiquidationCandidate(
                position_id="POS-SHORT-PE",
                contract_symbol="BANKNIFTY26OCT49000PE",
                lots=4,
                is_short=True,
                margin_per_lot=150_000.0,  # Naked short: heavy SPAN margin
                unrealized_pnl_per_lot=-5_000.0,
                risk_priority=2.0,  # Short option: high risk priority
            ),
        ]

        plan = MarginCallLiquidationEngine.plan_orderly_liquidation(
            account=account,
            positions=candidates,
            target_utilization=0.70,
        )

        self.assertTrue(plan.trade_lockout_active)
        self.assertTrue(plan.restored_to_safe_level)
        self.assertGreater(len(plan.actions), 0)

        # Confirm first unwound position is POS-SHORT-PE due to risk priority
        first_action = plan.actions[0]
        self.assertEqual(first_action.position_id, "POS-SHORT-PE")
        self.assertIn("UNWIND_SHORT_FOR_MARGIN_RELIEF", first_action.reason)

        # Confirm projected margin utilization dropped to or below 70%
        self.assertLessEqual(plan.projected_utilization, 0.70)

    def test_05_boundary_and_validation_guards(self) -> None:
        """Verifies input validation, empty returns, and edge guards."""
        # 1. calculate_log_returns with single price
        self.assertEqual(BetaWeightedHedgeEngine.calculate_log_returns([50000.0]), [])
        with self.assertRaises(ValueError):
            BetaWeightedHedgeEngine.calculate_log_returns([50000.0, -100.0])

        # 2. Insufficient sample size (< 5)
        with self.assertRaises(ValueError):
            BetaWeightedHedgeEngine.calculate_rolling_beta([0.01, 0.02], [0.01, 0.02])

        # 3. Flat target prices (zero target variance)
        b, r2, c, res = BetaWeightedHedgeEngine.calculate_rolling_beta(
            [0.0, 0.0, 0.0, 0.0, 0.0],
            [0.01, -0.01, 0.02, -0.02, 0.01],
        )
        self.assertEqual(b, 0.0)
        self.assertEqual(r2, 0.0)

        # 4. Negative initial margin
        with self.assertRaises(ValueError):
            MarginCallLiquidationEngine.evaluate_account_margin(
                total_equity=100_000.0,
                available_cash=50_000.0,
                initial_margin_required=-100.0,
            )

        # 5. Healthy account liquidation plan returns empty actions
        healthy_acc = MarginCallLiquidationEngine.evaluate_account_margin(
            total_equity=1_000_000.0,
            available_cash=500_000.0,
            initial_margin_required=400_000.0,
        )
        empty_plan = MarginCallLiquidationEngine.plan_orderly_liquidation(
            account=healthy_acc,
            positions=[],
            target_utilization=0.70,
        )
        self.assertEqual(len(empty_plan.actions), 0)
        self.assertFalse(empty_plan.trade_lockout_active)


if __name__ == "__main__":
    unittest.main()

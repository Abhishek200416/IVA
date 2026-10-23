"""Test Suite 39: Dynamic Multi-Leg Gamma Scalp & Elasticity-Aware Cross-Hedging Router.

Wave 30 Acceptance Tests (TASK-BN-40):
1. Cross-asset hedge allocation weight calculation based on queue elasticity and costs.
2. Toxicity-adaptive Whalley-Wilmott delta bandwidth expansion.
3. SEBI-compliant integer lot quantization (Bank Nifty = 15, Nifty 50 = 25) and tracking error.
4. Rebalance threshold triggering vs delta drift within tolerance.
5. High-adverse-selection SHORT_GAMMA_FREEZE rebalancing lockout.
6. Parameter validation and edge case handling.
"""

from __future__ import annotations

import unittest

from agents.AGI_1_7.engine.agi17.finance.elasticity_cross_hedge_scalper import (
    CrossHedgeDecision,
    CrossHedgeRegime,
    CrossHedgeScalpDecision,
    ElasticityCrossHedgeScalper,
    ElasticityCrossHedgeScalperEngine,
    ElasticityParams,
    PortfolioDeltaState,
    ScalpOrderLeg,
    ScalpRegime,
    ToxicityParams,
    TransactionCostParams,
)


class TestOmegaElasticityCrossHedgeScalper(unittest.TestCase):
    """Acceptance tests for ElasticityCrossHedgeScalper."""

    def setUp(self) -> None:
        self.scalper = ElasticityCrossHedgeScalper(
            elasticity_params=ElasticityParams(eps_1=20.0, eps_2=25.0),
            cost_params=TransactionCostParams(c_1=4.0, c_2=3.0),
            toxicity_params=ToxicityParams(
                delta_base=0.05,
                k_vpin=1.5,
                k_toxic=1.0,
                vpin_threshold=0.35,
                rho_threshold=0.50,
            ),
        )

    def test_cross_hedge_allocation_weight_calculation(self) -> None:
        """Verifies alpha = (C_2 * eps_1) / (C_2 * eps_1 + C_1 * eps_2)."""
        # alpha = (3.0 * 20.0) / (3.0 * 20.0 + 4.0 * 25.0) = 60.0 / (60.0 + 100.0) = 60 / 160 = 0.375
        alpha_bn, alpha_n50 = self.scalper.compute_allocation_weights()
        self.assertAlmostEqual(alpha_bn, 0.375, places=4)
        self.assertAlmostEqual(alpha_n50, 0.625, places=4)
        self.assertAlmostEqual(alpha_bn + alpha_n50, 1.0, places=4)

        # Higher Bank Nifty queue elasticity increases alpha
        high_bn_scalper = ElasticityCrossHedgeScalper(
            elasticity_params=ElasticityParams(eps_1=60.0, eps_2=20.0),
            cost_params=TransactionCostParams(c_1=2.0, c_2=2.0),
        )
        # alpha = (2.0 * 60) / (2.0 * 60 + 2.0 * 20) = 120 / 160 = 0.75
        alpha_high_bn, alpha_high_n50 = high_bn_scalper.compute_allocation_weights()
        self.assertAlmostEqual(alpha_high_bn, 0.75, places=4)
        self.assertAlmostEqual(alpha_high_n50, 0.25, places=4)

    def test_toxicity_adaptive_delta_bandwidth_expansion(self) -> None:
        """Verifies delta bandwidth expands with VPIN and toxicity correlation."""
        # Low toxicity: VPIN=0.10, rho=0.10
        # tolerance = 0.05 * (1 + 1.5 * 0.10 + 1.0 * 0.10) = 0.05 * (1 + 0.15 + 0.10) = 0.05 * 1.25 = 0.0625
        tol_norm, reg_norm, freeze_norm = self.scalper.evaluate_toxicity_and_bandwidth(
            vpin_joint=0.10, rho_toxic=0.10
        )
        self.assertEqual(reg_norm, ScalpRegime.NORMAL)
        self.assertFalse(freeze_norm)
        self.assertAlmostEqual(tol_norm, 0.0625, places=4)

        # Elevated toxicity: VPIN=0.25, rho=0.40
        # tolerance = 0.05 * (1 + 1.5 * 0.25 + 1.0 * 0.40) = 0.05 * (1 + 0.375 + 0.40) = 0.05 * 1.775 = 0.0888
        tol_adap, reg_adap, freeze_adap = self.scalper.evaluate_toxicity_and_bandwidth(
            vpin_joint=0.25, rho_toxic=0.40
        )
        self.assertEqual(reg_adap, ScalpRegime.ADAPTIVE)
        self.assertFalse(freeze_adap)
        self.assertAlmostEqual(tol_adap, 0.0888, places=3)
        self.assertGreater(tol_adap, tol_norm)

    def test_short_gamma_freeze_lockout(self) -> None:
        """Verifies SHORT_GAMMA_FREEZE locks rebalancing when adverse selection is critical."""
        # Severe toxicity: VPIN=0.40 >= 0.35, rho=0.60 >= 0.50
        tol_frz, reg_frz, freeze_active = self.scalper.evaluate_toxicity_and_bandwidth(
            vpin_joint=0.40, rho_toxic=0.60
        )
        self.assertEqual(reg_frz, ScalpRegime.SHORT_GAMMA_FREEZE)
        self.assertTrue(freeze_active)

        # Decision with massive delta drift should still NOT rebalance
        decision = self.scalper.route_hedge_rebalance(
            delta_exposure=0.50,
            spot_bank=51200.0,
            spot_nifty=24100.0,
            vpin_joint=0.40,
            rho_toxic=0.60,
        )
        self.assertEqual(decision.regime, ScalpRegime.SHORT_GAMMA_FREEZE)
        self.assertTrue(decision.is_freeze_active)
        self.assertFalse(decision.should_rebalance)
        self.assertEqual(len(decision.legs), 0)
        self.assertIn("SHORT_GAMMA_FREEZE active", decision.reason)

    def test_sebi_integer_lot_quantization_and_rupee_delta_tracking(self) -> None:
        """Verifies SEBI integer lot quantization (Bank Nifty = 15, Nifty 50 = 25)."""
        # Delta drift +30.0 contracts exceeds tolerance ~0.06
        # Target hedge delta = -30.0 contracts
        decision = self.scalper.route_hedge_rebalance(
            delta_exposure=30.0,
            spot_bank=51000.0,
            spot_nifty=24000.0,
            vpin_joint=0.10,
            rho_toxic=0.10,
        )
        self.assertTrue(decision.should_rebalance)
        self.assertFalse(decision.is_freeze_active)
        self.assertEqual(len(decision.legs), 2)

        leg_bn, leg_n50 = decision.legs

        # Bank Nifty checks: lot size 15, multiple of 15
        self.assertEqual(leg_bn.symbol, "BANK_NIFTY")
        self.assertEqual(leg_bn.lot_size, 15)
        self.assertEqual(leg_bn.quantized_contracts % 15, 0)
        self.assertEqual(leg_bn.quantized_lots, leg_bn.quantized_contracts // 15)
        self.assertEqual(leg_bn.direction, "SELL")

        # Nifty 50 checks: lot size 25, multiple of 25
        self.assertEqual(leg_n50.symbol, "NIFTY_50")
        self.assertEqual(leg_n50.lot_size, 25)
        self.assertEqual(leg_n50.quantized_contracts % 25, 0)
        self.assertEqual(leg_n50.quantized_lots, leg_n50.quantized_contracts // 25)
        self.assertEqual(leg_n50.direction, "SELL")

        # Tracking error must be computed and bounded
        self.assertGreaterEqual(decision.tracking_error_ratio, 0.0)
        self.assertLessEqual(decision.tracking_error_ratio, 0.35)
        self.assertAlmostEqual(
            decision.executed_rupee_delta + decision.residual_rupee_delta,
            decision.target_rupee_delta,
            places=1,
        )

    def test_rebalance_trigger_threshold(self) -> None:
        """Verifies rebalancing only triggers when drift exceeds dynamic tolerance."""
        # Tiny drift: 0.02 < tolerance 0.0625
        small_drift_dec = self.scalper.route_hedge_rebalance(
            delta_exposure=0.02,
            spot_bank=51000.0,
            spot_nifty=24000.0,
            vpin_joint=0.10,
            rho_toxic=0.10,
        )
        self.assertFalse(small_drift_dec.should_rebalance)
        self.assertEqual(len(small_drift_dec.legs), 0)
        self.assertIn("within tolerance", small_drift_dec.reason)

        # Large negative drift: -30.0 contracts -> hedge needs BUY
        buy_dec = self.scalper.route_hedge_rebalance(
            delta_exposure=-30.0,
            spot_bank=51000.0,
            spot_nifty=24000.0,
            vpin_joint=0.10,
            rho_toxic=0.10,
        )
        self.assertTrue(buy_dec.should_rebalance)
        self.assertEqual(len(buy_dec.legs), 2)
        self.assertEqual(buy_dec.legs[0].direction, "BUY")
        self.assertEqual(buy_dec.legs[1].direction, "BUY")

    def test_validation_and_edge_cases(self) -> None:
        """Verifies parameter validation checks."""
        with self.assertRaises(ValueError):
            ElasticityCrossHedgeScalper(
                elasticity_params=ElasticityParams(eps_1=-5.0, eps_2=10.0)
            )

        with self.assertRaises(ValueError):
            ElasticityCrossHedgeScalper(
                cost_params=TransactionCostParams(c_1=0.0, c_2=3.0)
            )

        with self.assertRaises(ValueError):
            self.scalper.route_hedge_rebalance(
                delta_exposure=0.10,
                spot_bank=0.0,
                spot_nifty=24000.0,
            )


if __name__ == "__main__":
    unittest.main()

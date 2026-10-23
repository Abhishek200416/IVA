"""Test Suite 38: Cross-Asset Order Book Level Imbalance & Bid-Ask Elasticity Coupling Engine.

Wave 29 Acceptance Tests (TASK-BN-39):
1. Multi-level depth imbalance calculation across 5 levels with exponential weighting.
2. Cross-asset elasticity coupling matrix, queue replenishment prediction, and time decay.
3. Phantom liquidity & queue evaporation detection with dynamic spread widening.
4. Asymmetric queue pressure regime classification.
5. Execution pacing decision, recommended delay, and forced passive-only routing.
"""

from __future__ import annotations

import math
import unittest

from agents.AGI_1_7.engine.agi17.finance.cross_asset_elasticity import (
    CrossAssetElasticityEngine,
    CrossElasticityMatrix,
    CrossElasticityMetrics,
    ElasticityCouplingMatrix,
    ElasticityDepthSnapshot,
    ElasticityRegime,
    ExecutionPacingDecision,
    OrderBookDepthSnapshot,
    OrderBookLevel,
)


class TestOmegaCrossAssetElasticity(unittest.TestCase):
    """Acceptance tests for CrossAssetElasticityEngine and coupling dynamics."""

    def setUp(self) -> None:
        self.engine = CrossAssetElasticityEngine(
            symbol_nifty="NIFTY_50",
            symbol_bank="BANK_NIFTY",
            coupling_matrix=ElasticityCouplingMatrix(
                e_11=20.0,
                e_22=12.0,
                e_12=6.0,
                e_21=6.0,
                tau_replenish_sec=2.0,
            ),
            alpha_depth_decay=0.25,
            breakdown_threshold=30.0,
            spread_sensitivity_lambda=0.04,
        )

    def test_multi_level_depth_imbalance_and_integrated_pressure(self) -> None:
        """Verifies 5-level queue imbalance calculation and exponential weighting."""
        levels = [
            OrderBookLevel(level=1, bid_price=51200.0, bid_qty=150.0, ask_price=51205.0, ask_qty=50.0),
            OrderBookLevel(level=2, bid_price=51195.0, bid_qty=200.0, ask_price=51210.0, ask_qty=100.0),
            OrderBookLevel(level=3, bid_price=51190.0, bid_qty=300.0, ask_price=51215.0, ask_qty=150.0),
            OrderBookLevel(level=4, bid_price=51185.0, bid_qty=100.0, ask_price=51220.0, ask_qty=100.0),
            OrderBookLevel(level=5, bid_price=51180.0, bid_qty=50.0, ask_price=51225.0, ask_qty=100.0),
        ]
        snapshot = OrderBookDepthSnapshot(
            symbol="BANK_NIFTY",
            timestamp=1700000000.0,
            mid_price=51202.5,
            levels=levels,
        )

        imbalances, w_i = snapshot.compute_integrated_pressure(alpha=0.25)
        self.assertEqual(len(imbalances), 5)
        # Level 1 imbalance: (150 - 50) / 200 = 0.50
        self.assertAlmostEqual(imbalances[0], 0.50, places=3)
        # Level 2 imbalance: (200 - 100) / 300 = 0.333...
        self.assertAlmostEqual(imbalances[1], 0.333, places=2)
        # Level 4 imbalance: (100 - 100) / 200 = 0.0
        self.assertAlmostEqual(imbalances[3], 0.0, places=3)
        # Integrated pressure should be positive (net buy pressure)
        self.assertGreater(w_i, 0.20)
        self.assertLessEqual(w_i, 1.0)

        # Empty snapshot handling
        empty_snap = OrderBookDepthSnapshot("EMPTY", 1700000000.0, 100.0, [])
        empty_imb, empty_wi = empty_snap.compute_integrated_pressure()
        self.assertEqual(empty_imb, [])
        self.assertEqual(empty_wi, 0.0)

    def test_cross_elasticity_coupling_matrix_replenishment_prediction(self) -> None:
        """Verifies replenishment prediction Delta Q = E * Delta P and decay."""
        matrix = ElasticityCouplingMatrix(
            e_11=20.0,
            e_22=12.0,
            e_12=6.0,
            e_21=6.0,
            tau_replenish_sec=2.0,
        )
        # Normalized cross elasticity: 6.0 / sqrt(20 * 12) = 6.0 / sqrt(240) = 6.0 / 15.4919 = 0.3873
        norm_cross = matrix.normalized_cross_elasticity
        self.assertAlmostEqual(norm_cross, 0.3873, places=3)

        # Predict replenishment: delta_p_nifty = 5.0, delta_p_bank = 10.0
        # q1 = 20*5 + 6*10 = 100 + 60 = 160
        # q2 = 6*5 + 12*10 = 30 + 120 = 150
        q1_pred, q2_pred = matrix.predict_replenishment(5.0, 10.0)
        self.assertAlmostEqual(q1_pred, 160.0)
        self.assertAlmostEqual(q2_pred, 150.0)

        # Exponential decay after 2.0 seconds (one half-life = exp(-1))
        decayed_q1 = matrix.decay_replenishment(q1_pred, elapsed_seconds=2.0)
        self.assertAlmostEqual(decayed_q1, 160.0 * math.exp(-1.0), places=3)

    def test_phantom_liquidity_evaporation_regime_and_spread_widening(self) -> None:
        """Verifies phantom liquidity detection and dynamic spread multiplier expansion."""
        # Initial snapshot to establish previous price
        nifty_snap_0 = OrderBookDepthSnapshot(
            "NIFTY_50", 1700000000.0, 24000.0,
            [OrderBookLevel(1, 23995.0, 100.0, 24005.0, 100.0)]
        )
        bank_snap_0 = OrderBookDepthSnapshot(
            "BANK_NIFTY", 1700000000.0, 51000.0,
            [OrderBookLevel(1, 50990.0, 100.0, 51010.0, 100.0)]
        )
        self.engine.evaluate_coupling(nifty_snap_0, bank_snap_0)

        # Subsequent snapshot with price jump: NIFTY +10 pts, BANK NIFTY +20 pts
        nifty_snap_1 = OrderBookDepthSnapshot(
            "NIFTY_50", 1700000001.0, 24010.0,
            [OrderBookLevel(1, 24005.0, 100.0, 24015.0, 100.0)]
        )
        bank_snap_1 = OrderBookDepthSnapshot(
            "BANK_NIFTY", 1700000001.0, 51020.0,
            [OrderBookLevel(1, 51010.0, 100.0, 51030.0, 100.0)]
        )

        # Predicted replenishment would be:
        # q1_pred = 20*10 + 6*20 = 200 + 120 = 320 contracts
        # q2_pred = 6*10 + 12*20 = 60 + 240 = 300 contracts
        # But observed queue replenishment severely collapses (phantom liquidity evaporates):
        metrics = self.engine.evaluate_coupling(
            nifty_snap_1,
            bank_snap_1,
            observed_delta_q_nifty=10.0,  # error = 310 > threshold 30.0
            observed_delta_q_bank=5.0,    # error = 295 > threshold 30.0
        )

        self.assertEqual(metrics.regime, ElasticityRegime.PHANTOM_LIQUIDITY_EVAPORATION)
        self.assertTrue(metrics.phantom_liquidity_alert)
        self.assertGreaterEqual(metrics.spread_multiplier, 1.5)
        self.assertLessEqual(metrics.spread_multiplier, 3.0)

    def test_asymmetric_pressure_regime(self) -> None:
        """Verifies asymmetric queue pressure classification when order books diverge."""
        # NIFTY heavily skewed bid (buy pressure W_I ~ +0.8)
        nifty_snap = OrderBookDepthSnapshot(
            "NIFTY_50", 1700000000.0, 24000.0,
            [
                OrderBookLevel(1, 23999.0, 450.0, 24001.0, 50.0),
                OrderBookLevel(2, 23998.0, 400.0, 24002.0, 50.0),
            ]
        )
        # BANK NIFTY heavily skewed ask (sell pressure W_I ~ -0.8)
        bank_snap = OrderBookDepthSnapshot(
            "BANK_NIFTY", 1700000000.0, 51000.0,
            [
                OrderBookLevel(1, 50995.0, 50.0, 51005.0, 450.0),
                OrderBookLevel(2, 50990.0, 50.0, 51010.0, 400.0),
            ]
        )

        metrics = self.engine.evaluate_coupling(nifty_snap, bank_snap)
        self.assertGreaterEqual(metrics.pressure_imbalance_ratio, 0.60)
        self.assertEqual(metrics.regime, ElasticityRegime.ASYMMETRIC_PRESSURE)
        self.assertEqual(metrics.spread_multiplier, 1.25)
        self.assertFalse(metrics.phantom_liquidity_alert)

    def test_execution_pacing_decision_and_passive_routing(self) -> None:
        """Verifies compute_pacing_decision converts metrics into execution delay and passive-only gates."""
        # Scenario A: Phantom Liquidity Evaporation forces passive-only and max pacing
        evap_metrics = CrossElasticityMetrics(
            symbol_nifty="NIFTY_50",
            symbol_bank="BANK_NIFTY",
            pressure_nifty=0.1,
            pressure_bank=-0.1,
            pressure_imbalance_ratio=0.2,
            normalized_cross_elasticity=0.35,
            predicted_replenish_nifty=200.0,
            predicted_replenish_bank=200.0,
            observed_replenish_nifty=10.0,
            observed_replenish_bank=10.0,
            replenishment_asymmetry=0.0,
            prediction_error_nifty=190.0,
            prediction_error_bank=190.0,
            regime=ElasticityRegime.PHANTOM_LIQUIDITY_EVAPORATION,
            phantom_liquidity_alert=True,
            spread_multiplier=2.5,
        )
        decision_evap = self.engine.compute_pacing_decision(evap_metrics, base_delay_ms=50.0)
        self.assertTrue(decision_evap.is_passive_only)
        self.assertGreaterEqual(decision_evap.pacing_multiplier, 2.5)
        self.assertGreaterEqual(decision_evap.recommended_delay_ms, 125.0)

        # Scenario B: High Asymmetric Pressure (> 0.70) forces passive-only
        asym_metrics_high = CrossElasticityMetrics(
            symbol_nifty="NIFTY_50",
            symbol_bank="BANK_NIFTY",
            pressure_nifty=0.8,
            pressure_bank=-0.1,
            pressure_imbalance_ratio=0.9,
            normalized_cross_elasticity=0.35,
            predicted_replenish_nifty=50.0,
            predicted_replenish_bank=50.0,
            observed_replenish_nifty=50.0,
            observed_replenish_bank=50.0,
            replenishment_asymmetry=0.0,
            prediction_error_nifty=0.0,
            prediction_error_bank=0.0,
            regime=ElasticityRegime.ASYMMETRIC_PRESSURE,
            phantom_liquidity_alert=False,
            spread_multiplier=1.25,
        )
        decision_asym = self.engine.compute_pacing_decision(asym_metrics_high, base_delay_ms=50.0)
        self.assertTrue(decision_asym.is_passive_only)
        self.assertEqual(decision_asym.pacing_multiplier, 3.5)
        self.assertEqual(decision_asym.recommended_delay_ms, 175.0)

        # Scenario C: Normal Equilibrium allows active orders and base delay
        norm_metrics = CrossElasticityMetrics(
            symbol_nifty="NIFTY_50",
            symbol_bank="BANK_NIFTY",
            pressure_nifty=0.1,
            pressure_bank=0.1,
            pressure_imbalance_ratio=0.0,
            normalized_cross_elasticity=0.25,
            predicted_replenish_nifty=20.0,
            predicted_replenish_bank=20.0,
            observed_replenish_nifty=20.0,
            observed_replenish_bank=20.0,
            replenishment_asymmetry=0.0,
            prediction_error_nifty=0.0,
            prediction_error_bank=0.0,
            regime=ElasticityRegime.NORMAL_EQUILIBRIUM,
            phantom_liquidity_alert=False,
            spread_multiplier=1.0,
        )
        decision_norm = self.engine.compute_pacing_decision(norm_metrics, base_delay_ms=50.0)
        self.assertFalse(decision_norm.is_passive_only)
        self.assertEqual(decision_norm.pacing_multiplier, 1.0)
        self.assertEqual(decision_norm.recommended_delay_ms, 50.0)


if __name__ == "__main__":
    unittest.main()

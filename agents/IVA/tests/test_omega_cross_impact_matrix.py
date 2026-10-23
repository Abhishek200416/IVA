"""Acceptance Test Suite 35: Multi-Asset Cross-Impact & Hayashi-Yoshida Lead-Lag Matrix.

Validates:
1. Positive definiteness (det(S) > 0) and manipulation-free / round-trip arbitrage rejection (Huberman-Stanzl 2004).
2. Onsager reciprocal symmetry (lambda_12 == lambda_21) and Cholesky decomposition.
3. Hayashi-Yoshida (2005) asynchronous high-frequency covariance and correlation calculation.
4. Informational lead-lag profile scanning across lag horizons.
5. Cross-asset optimal inventory delta rebalancing with strict Indian lot sizes (Bank Nifty 15, Nifty 25),
   0.05 tick size enforcement, and statutory fee modeling.
"""

from __future__ import annotations

import math
import unittest

from agents.AGI_1_7.engine.agi17.finance.cross_impact_matrix import (
    AsynchronousTick,
    CrossAssetExecutionRebalancer,
    CrossImpactMatrix,
    CrossRebalanceResult,
    HayashiYoshidaEstimator,
    LeadLagPeak,
    MarketIndex,
)


class TestOmegaCrossImpactMatrix(unittest.TestCase):
    """Suite 35: Multi-Asset Cross-Impact & Lead-Lag Matrix."""

    def setUp(self) -> None:
        # Standard calibration:
        # NIFTY 50 self-impact: 0.0004
        # BANK NIFTY self-impact: 0.0008
        # Cross-impact: 0.0003
        self.matrix = CrossImpactMatrix(
            lambda_11=0.0004,
            lambda_22=0.0008,
            lambda_12=0.0003,
            lambda_21=0.0003,
        )

    def test_01_positive_definiteness_and_no_arbitrage(self) -> None:
        """Matrix must be positive definite to prevent round-trip money machine arbitrage."""
        self.assertTrue(self.matrix.is_positive_definite)
        self.assertTrue(self.matrix.is_onsager_symmetric)
        self.assertAlmostEqual(self.matrix.skewness, 0.0, places=7)

        # det(S) = (0.0004 * 0.0008) - (0.0003^2) = 0.00000032 - 0.00000009 = 0.00000023 > 0
        self.assertGreater(self.matrix.determinant_symmetric, 0.0)

        # Round trip cost for non-zero trades must be strictly positive
        cost = self.matrix.compute_round_trip_cost(q_nifty=100.0, q_bank=-50.0)
        self.assertGreater(cost, 0.0)
        self.assertFalse(self.matrix.check_round_trip_arbitrage(100.0, -50.0))

        # Cholesky factorization
        l11, l21, l22 = self.matrix.cholesky_factors()
        self.assertAlmostEqual(l11 * l11, self.matrix.lambda_11, places=6)
        self.assertAlmostEqual(l21 * l11, self.matrix.symmetric_cross, places=6)
        self.assertAlmostEqual((l21 ** 2) + (l22 ** 2), self.matrix.lambda_22, places=6)

        # Non-PD matrix with excessive cross-impact violating Cauchy-Schwarz
        invalid_matrix = CrossImpactMatrix(
            lambda_11=0.0002,
            lambda_22=0.0002,
            lambda_12=0.0005,
            lambda_21=0.0005,
        )
        self.assertFalse(invalid_matrix.is_positive_definite)
        # Should detect arbitrage risk when round-trip cost is negative
        self.assertTrue(invalid_matrix.check_round_trip_arbitrage(100.0, -100.0))

    def test_02_onsager_reciprocal_symmetry_and_cross_elasticity(self) -> None:
        """Cross-elasticity must be bounded in (-1, +1) and price impacts correctly calculated."""
        # Cross elasticity: 0.0003 / sqrt(0.0004 * 0.0008) = 0.0003 / 0.000565685 = ~0.5303
        elasticity = self.matrix.cross_elasticity
        self.assertGreater(elasticity, 0.0)
        self.assertLess(elasticity, 1.0)
        self.assertAlmostEqual(elasticity, 0.0003 / math.sqrt(0.0004 * 0.0008), places=4)

        # Compute mid-price impact: Delta P = Lambda * Q
        delta_nifty, delta_bank = self.matrix.compute_price_impact(q_nifty=50.0, q_bank=30.0)
        # Delta P1 = (0.0004 * 50) + (0.0003 * 30) = 0.02 + 0.009 = 0.029
        # Delta P2 = (0.0003 * 50) + (0.0008 * 30) = 0.015 + 0.024 = 0.039
        self.assertAlmostEqual(delta_nifty, 0.029, places=6)
        self.assertAlmostEqual(delta_bank, 0.039, places=6)

    def test_03_hayashi_yoshida_asynchronous_correlation(self) -> None:
        """Hayashi-Yoshida computes covariance for non-synchronous overlapping trade intervals."""
        # Ticks for NIFTY 50: [0, 1.2], [1.2, 2.5], [2.5, 4.0]
        nifty_ticks = [
            AsynchronousTick(
                index=MarketIndex.NIFTY_50,
                start_time=0.0,
                end_time=1.2,
                price=24500.0,
                price_change=2.5,
                volume=50.0,
            ),
            AsynchronousTick(
                index=MarketIndex.NIFTY_50,
                start_time=1.2,
                end_time=2.5,
                price=24503.0,
                price_change=3.0,
                volume=75.0,
            ),
            AsynchronousTick(
                index=MarketIndex.NIFTY_50,
                start_time=2.5,
                end_time=4.0,
                price=24499.0,
                price_change=-4.0,
                volume=100.0,
            ),
        ]

        # Ticks for BANK NIFTY: [0.5, 1.8], [1.8, 3.2], [3.2, 5.0] (asynchronous arrival)
        bank_ticks = [
            AsynchronousTick(
                index=MarketIndex.BANK_NIFTY,
                start_time=0.5,
                end_time=1.8,
                price=52000.0,
                price_change=5.0,
                volume=30.0,
            ),
            AsynchronousTick(
                index=MarketIndex.BANK_NIFTY,
                start_time=1.8,
                end_time=3.2,
                price=52008.0,
                price_change=8.0,
                volume=45.0,
            ),
            AsynchronousTick(
                index=MarketIndex.BANK_NIFTY,
                start_time=3.2,
                end_time=5.0,
                price=51995.0,
                price_change=-13.0,
                volume=60.0,
            ),
        ]

        cov = HayashiYoshidaEstimator.calculate_cross_covariance(nifty_ticks, bank_ticks)
        corr = HayashiYoshidaEstimator.calculate_cross_correlation(nifty_ticks, bank_ticks)

        # Both indices move up then down; covariance and correlation must be strongly positive
        self.assertGreater(cov, 0.0)
        self.assertGreater(corr, 0.0)
        self.assertLessEqual(corr, 1.0)

        # Empty series returns 0.0 safely
        self.assertEqual(HayashiYoshidaEstimator.calculate_cross_correlation([], bank_ticks), 0.0)

    def test_04_hayashi_yoshida_lead_lag_profile(self) -> None:
        """Hayashi-Yoshida lead-lag profile detects which asset leads informationally."""
        # Synthetic ticks: NIFTY moves first, BANK NIFTY follows after ~1.0 second lag
        nifty_ticks = [
            AsynchronousTick(MarketIndex.NIFTY_50, 0.0, 1.0, 24500.0, 4.0, 50.0),
            AsynchronousTick(MarketIndex.NIFTY_50, 1.0, 2.0, 24504.0, 4.0, 50.0),
            AsynchronousTick(MarketIndex.NIFTY_50, 2.0, 3.0, 24508.0, -5.0, 50.0),
            AsynchronousTick(MarketIndex.NIFTY_50, 3.0, 4.0, 24503.0, -6.0, 50.0),
            AsynchronousTick(MarketIndex.NIFTY_50, 4.0, 5.0, 24497.0, 5.0, 50.0),
        ]

        # Bank Nifty ticks lagged by 1.0 second: identical return pattern shifted
        bank_ticks = [
            AsynchronousTick(MarketIndex.BANK_NIFTY, 1.0, 2.0, 52000.0, 8.0, 30.0),
            AsynchronousTick(MarketIndex.BANK_NIFTY, 2.0, 3.0, 52008.0, 8.0, 30.0),
            AsynchronousTick(MarketIndex.BANK_NIFTY, 3.0, 4.0, 52016.0, -10.0, 30.0),
            AsynchronousTick(MarketIndex.BANK_NIFTY, 4.0, 5.0, 52006.0, -12.0, 30.0),
            AsynchronousTick(MarketIndex.BANK_NIFTY, 5.0, 6.0, 51994.0, 10.0, 30.0),
        ]

        lag_grid = [-2.0, -1.0, 0.0, 1.0, 2.0]
        peak = HayashiYoshidaEstimator.analyze_lead_lag_profile(nifty_ticks, bank_ticks, lag_grid)

        # Bank Nifty arrives lagged by 1s. Shifting series2 by +1s aligns them perfectly
        self.assertAlmostEqual(peak.optimal_lag_seconds, 1.0, places=2)
        self.assertGreater(peak.max_correlation, 0.85)
        self.assertEqual(peak.leading_asset, MarketIndex.NIFTY_50)
        self.assertTrue(peak.is_statistically_significant)

    def test_05_cross_asset_rebalancing_with_indian_lot_sizes_and_ticks(self) -> None:
        """Cross-asset execution engine enforces NSE lot sizes, 0.05 tick size, and statutory fees."""
        rebalancer = CrossAssetExecutionRebalancer(
            impact_matrix=self.matrix,
            beta_bank_to_nifty=1.20,
        )

        # Target 100 contracts Nifty delta
        res = rebalancer.calculate_cross_rebalance(
            target_nifty_delta=100.0,
            spot_nifty=24500.0,
            spot_bank=52000.0,
        )

        self.assertIsInstance(res, CrossRebalanceResult)
        # Nifty quantity must be multiple of 25 (100 = 4 lots)
        self.assertEqual(res.nifty_lots, 4)
        self.assertEqual(res.nifty_quantity, 100)
        self.assertEqual(res.nifty_quantity % CrossAssetExecutionRebalancer.NIFTY_50_LOT_SIZE, 0)

        # Bank Nifty quantity must be multiple of 15
        self.assertEqual(res.bank_quantity % CrossAssetExecutionRebalancer.BANK_NIFTY_LOT_SIZE, 0)
        self.assertGreater(res.bank_lots, 0)

        # Price impact must strictly align with 0.05 INR tick size
        tick = CrossAssetExecutionRebalancer.MIN_TICK_SIZE
        self.assertAlmostEqual(round(res.expected_nifty_impact / tick) * tick, res.expected_nifty_impact, places=2)
        self.assertAlmostEqual(round(res.expected_bank_impact / tick) * tick, res.expected_bank_impact, places=2)

        # Economic costs
        self.assertGreater(res.total_permanent_cost_inr, 0.0)
        self.assertGreater(res.statutory_fees_inr, 0.0)
        self.assertEqual(res.net_economic_cost_inr, res.total_permanent_cost_inr + res.statutory_fees_inr)
        self.assertTrue(res.is_arbitrage_free)


if __name__ == "__main__":
    unittest.main()

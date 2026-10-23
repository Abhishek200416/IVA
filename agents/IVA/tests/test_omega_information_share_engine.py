"""Unit test battery for High-Frequency Information Share & Price Discovery Engine.

Wave 33 Verification Suite (TASK-BN-43):
Validates:
1. Synthetic forward extraction via Put-Call Parity.
2. Market 1 leadership detection (VECM alpha_1 ~ 0, alpha_2 > 0, IS_1 > 0.60, GG_1 > 0.60).
3. Market 2 leadership detection (VECM alpha_1 < 0, alpha_2 ~ 0, IS_2 > 0.60, GG_2 > 0.60).
4. Synchronous mutual discovery under symmetric error-correction.
5. Contemporaneous correlation bounds expansion and conservation invariant IS_1 + IS_2 = 1.0.
"""

from __future__ import annotations

import math
import random
import unittest

from agents.AGI_1_7.engine.agi17.finance.information_share_engine import (
    ExecutionRoutingAdvice,
    HasbrouckBounds,
    HighFrequencyInformationShareEngine,
    PriceDiscoveryMetrics,
    PriceDiscoveryRegime,
    PricePairTick,
)


class TestOmegaInformationShareEngine(unittest.TestCase):
    """Test suite for Wave 33 High-Frequency Information Share & Price Discovery."""

    def setUp(self) -> None:
        self.engine = HighFrequencyInformationShareEngine(
            min_ticks=20,
            lead_threshold=0.60,
            uncertainty_threshold=0.35,
            cointegrating_beta=1.0,
        )

    def test_synthetic_forward_extraction(self) -> None:
        """Verify Put-Call Parity synthetic forward extraction and validation."""
        # Bank Nifty spot at 50,000, Strike 50,000, Call=420.0, Put=380.0
        # F_syn = 50,000 + 420.0 - 380.0 = 50,040.0
        f_syn = HighFrequencyInformationShareEngine.extract_synthetic_forward(
            underlying_price=50000.0,
            call_price=420.0,
            put_price=380.0,
            strike=50000.0,
        )
        self.assertAlmostEqual(f_syn, 50040.0, places=4)

        # Negative price error handling
        with self.assertRaises(ValueError):
            HighFrequencyInformationShareEngine.extract_synthetic_forward(
                underlying_price=50000.0, call_price=-10.0, put_price=380.0, strike=50000.0
            )

    def test_market_1_pure_leader(self) -> None:
        """Market 1 behaves as an autonomous random walk, Market 2 adjusts to Market 1."""
        rng = random.Random(42)
        n = 100
        p1 = [50000.0]
        p2 = [50000.0]

        for _ in range(n - 1):
            # Market 1 random walk innovation (driving factor)
            e1 = rng.gauss(0.0, 5.0)
            # Market 2 independent noise
            e2 = rng.gauss(0.0, 1.5)
            # Equilibrium error: z = p1 - p2
            z_prev = p1[-1] - p2[-1]
            
            # Market 1 does NOT adjust to z (alpha_1 = 0)
            next_p1 = p1[-1] + e1
            # Market 2 strongly adjusts toward Market 1 (alpha_2 = +0.55)
            next_p2 = p2[-1] + 0.55 * z_prev + e2
            
            p1.append(next_p1)
            p2.append(next_p2)

        metrics = self.engine.fit_from_arrays(p1, p2)

        self.assertGreaterEqual(metrics.market_1_gg_share, 0.65)
        self.assertGreaterEqual(metrics.market_1_hasbrouck.is_mid, 0.60)
        self.assertEqual(metrics.regime, PriceDiscoveryRegime.LEADER_MARKET_1)
        self.assertEqual(metrics.recommended_routing, ExecutionRoutingAdvice.AGGRESSIVE_1_PASSIVE_2)
        self.assertAlmostEqual(
            metrics.market_1_hasbrouck.is_mid + metrics.market_2_hasbrouck.is_mid,
            1.0,
            places=4,
        )

    def test_market_2_pure_leader(self) -> None:
        """Market 2 behaves as autonomous random walk, Market 1 adjusts to Market 2."""
        rng = random.Random(101)
        n = 100
        p1 = [50000.0]
        p2 = [50000.0]

        for _ in range(n - 1):
            e1 = rng.gauss(0.0, 1.5)
            e2 = rng.gauss(0.0, 5.0)
            z_prev = p1[-1] - p2[-1]

            # Market 1 adjusts downward when p1 > p2 (alpha_1 = -0.55)
            next_p1 = p1[-1] - 0.55 * z_prev + e1
            # Market 2 does NOT adjust (alpha_2 = 0)
            next_p2 = p2[-1] + e2

            p1.append(next_p1)
            p2.append(next_p2)

        metrics = self.engine.fit_from_arrays(p1, p2)

        self.assertGreaterEqual(metrics.market_2_gg_share, 0.65)
        self.assertGreaterEqual(metrics.market_2_hasbrouck.is_mid, 0.60)
        self.assertEqual(metrics.regime, PriceDiscoveryRegime.LEADER_MARKET_2)
        self.assertEqual(metrics.recommended_routing, ExecutionRoutingAdvice.AGGRESSIVE_2_PASSIVE_1)

    def test_synchronous_mutual_discovery(self) -> None:
        """Symmetric error-correction produces balanced mutual discovery."""
        rng = random.Random(999)
        n = 100
        p1 = [50000.0]
        p2 = [50000.0]

        for _ in range(n - 1):
            e1 = rng.gauss(0.0, 3.0)
            e2 = rng.gauss(0.0, 3.0)
            z_prev = p1[-1] - p2[-1]

            # Symmetric error correction: alpha_1 = -0.30, alpha_2 = +0.30
            next_p1 = p1[-1] - 0.30 * z_prev + e1
            next_p2 = p2[-1] + 0.30 * z_prev + e2

            p1.append(next_p1)
            p2.append(next_p2)

        metrics = self.engine.fit_from_arrays(p1, p2)

        # Both shares should be near 0.50
        self.assertAlmostEqual(metrics.market_1_gg_share, 0.50, delta=0.15)
        self.assertAlmostEqual(metrics.market_1_hasbrouck.is_mid, 0.50, delta=0.15)
        self.assertEqual(metrics.regime, PriceDiscoveryRegime.SYNCHRONOUS_DISCOVERY)
        self.assertEqual(metrics.recommended_routing, ExecutionRoutingAdvice.SYMMETRIC_CROSS_HEDGE)

    def test_contemporaneous_uncertainty_and_bounds_invariance(self) -> None:
        """High residual correlation widens Hasbrouck bounds, triggering CONTEMPORANEOUS_UNCERTAINTY."""
        rng = random.Random(777)
        n = 120
        p1 = [50000.0]
        p2 = [50000.0]

        for _ in range(n - 1):
            # Common shock with high correlation (rho > 0.85)
            common = rng.gauss(0.0, 4.0)
            e1 = common + rng.gauss(0.0, 0.5)
            e2 = common + rng.gauss(0.0, 0.5)
            z_prev = p1[-1] - p2[-1]

            next_p1 = p1[-1] - 0.20 * z_prev + e1
            next_p2 = p2[-1] + 0.20 * z_prev + e2

            p1.append(next_p1)
            p2.append(next_p2)

        metrics = self.engine.fit_from_arrays(p1, p2)

        # Residual correlation should be high (> 0.80)
        self.assertGreater(metrics.residual_correlation, 0.80)
        # Bounds spread should be wide (>= 0.35)
        self.assertGreaterEqual(metrics.market_1_hasbrouck.spread, 0.35)
        self.assertEqual(metrics.regime, PriceDiscoveryRegime.CONTEMPORANEOUS_UNCERTAINTY)
        self.assertEqual(metrics.recommended_routing, ExecutionRoutingAdvice.REDUCE_EXPOSURE_HIGH_CORR)

        # Conservation Invariant: IS_1 + IS_2 == 1.0 for mid, min/max duality
        self.assertAlmostEqual(
            metrics.market_1_hasbrouck.is_mid + metrics.market_2_hasbrouck.is_mid,
            1.0,
            places=4,
        )
        self.assertAlmostEqual(
            metrics.market_1_hasbrouck.is_min + metrics.market_2_hasbrouck.is_max,
            1.0,
            places=4,
        )


if __name__ == "__main__":
    unittest.main()

"""Acceptance test suite for Avellaneda-Stoikov (2008) Market Making Engine."""

import unittest

from agents.AGI_1_7.engine.agi17.finance.inventory_market_making import (
    AvellanedaStoikovEngine,
    InventoryRiskRegime,
    OptimalQuotes,
)


class TestOmegaInventoryMarketMaking(unittest.TestCase):
    """Test suite for AvellanedaStoikovEngine."""

    def setUp(self) -> None:
        self.engine = AvellanedaStoikovEngine(
            risk_aversion_gamma=0.01,
            order_intensity_kappa=1.5,
            default_volatility_sigma=0.20,
            max_inventory_units=150,
            tick_size=0.05,
            min_statutory_spread_bps=2.0,
            bank_nifty_lot_size=15,
        )

    def test_reservation_price_inventory_skew(self) -> None:
        """Verify reservation price shifts inversely with inventory sign."""
        mid = 50000.0
        r_neutral = self.engine.calculate_reservation_price(mid, inventory=0, tau=1.0)
        self.assertEqual(r_neutral, mid)

        # Long inventory (q > 0) -> lower reservation price to encourage selling
        r_long = self.engine.calculate_reservation_price(mid, inventory=60, tau=1.0)
        self.assertLess(r_long, mid)

        # Short inventory (q < 0) -> higher reservation price to encourage buying
        r_short = self.engine.calculate_reservation_price(mid, inventory=-60, tau=1.0)
        self.assertGreater(r_short, mid)

    def test_asymmetric_quote_placement(self) -> None:
        """Verify optimal bid and ask quotes around reservation price and tick alignment."""
        mid = 50000.0
        quotes = self.engine.compute_quotes(mid_price=mid, inventory=0, tau=1.0)
        
        # Symmetrical spread when inventory = 0
        self.assertGreater(quotes.optimal_ask, quotes.optimal_bid)
        self.assertAlmostEqual(quotes.half_spread_bid, quotes.half_spread_ask, delta=0.10)
        
        # Verify tick alignment (multiples of 0.05)
        self.assertEqual(round(quotes.optimal_bid * 100) % 5, 0)
        self.assertEqual(round(quotes.optimal_ask * 100) % 5, 0)

    def test_statutory_spread_floor(self) -> None:
        """Verify statutory spread floor prevents quotes undercutting minimum transaction friction."""
        mid = 50000.0
        # Create an engine with near-zero risk aversion
        low_gamma_engine = AvellanedaStoikovEngine(
            risk_aversion_gamma=0.0001,
            order_intensity_kappa=10.0,
            default_volatility_sigma=0.01,
            min_statutory_spread_bps=3.0,
        )
        spread = low_gamma_engine.calculate_optimal_spread(tau=1.0, mid_price=mid)
        min_statutory_pts = (3.0 / 10000.0) * mid  # 15.0 pts
        self.assertGreaterEqual(spread, min_statutory_pts)

    def test_inventory_regimes_and_hard_limit(self) -> None:
        """Verify regime classification and one-sided quoting upon reaching max inventory."""
        mid = 50000.0
        
        # Balanced regime
        q_bal = self.engine.compute_quotes(mid_price=mid, inventory=15)
        self.assertEqual(q_bal.regime, InventoryRiskRegime.BALANCED)
        self.assertTrue(q_bal.post_bid)
        self.assertTrue(q_bal.post_ask)

        # Long skew
        q_long = self.engine.compute_quotes(mid_price=mid, inventory=45)
        self.assertEqual(q_long.regime, InventoryRiskRegime.LONG_SKEW)

        # Short skew
        q_short = self.engine.compute_quotes(mid_price=mid, inventory=-45)
        self.assertEqual(q_short.regime, InventoryRiskRegime.SHORT_SKEW)

        # Max Long hit (150 units) -> halt bids, only post asks to shed inventory
        q_max_long = self.engine.compute_quotes(mid_price=mid, inventory=150)
        self.assertEqual(q_max_long.regime, InventoryRiskRegime.INVENTORY_LIMIT_HIT)
        self.assertFalse(q_max_long.post_bid)
        self.assertTrue(q_max_long.post_ask)

        # Max Short hit (-150 units) -> halt asks, only post bids to cover
        q_max_short = self.engine.compute_quotes(mid_price=mid, inventory=-150)
        self.assertEqual(q_max_short.regime, InventoryRiskRegime.INVENTORY_LIMIT_HIT)
        self.assertTrue(q_max_short.post_bid)
        self.assertFalse(q_max_short.post_ask)

    def test_options_delta_effective_inventory(self) -> None:
        """Verify delta-weighted inventory scales reservation price proportionally."""
        mid = 50000.0
        inv = 60
        r_linear = self.engine.calculate_reservation_price(mid, inventory=inv, tau=1.0, delta=1.0)
        r_option = self.engine.calculate_reservation_price(mid, inventory=inv, tau=1.0, delta=0.50)

        # Delta 0.50 should cause half the skew distance from mid
        dist_linear = mid - r_linear
        dist_option = mid - r_option
        self.assertAlmostEqual(dist_option, 0.5 * dist_linear, places=4)


if __name__ == "__main__":
    unittest.main()

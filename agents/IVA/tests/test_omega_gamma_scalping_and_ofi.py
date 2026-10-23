"""Acceptance tests for Dynamic Gamma Scalping and Order Flow Imbalance (OFI) Engines.

TASK-BN-20 & TASK-BN-21:
Covers:
1. Whalley-Wilmott / Leland transaction-cost optimal delta bandwidth calculation.
2. Threshold-based discrete delta rebalancing triggers and BUY/SELL hedge sizing.
3. Full intraday oscillating session gamma scalping simulation with positive net P&L capture.
4. Level-1 Cont-Kukanov-Stoikov (2014) OFI calculation under price upticks, cancels, and fills.
5. Multi-Level OFI (MLOFI) across 5-level book transitions and ratio normalization.
6. Pre-trade breakout confirmation and false breakout absorption trap detection.
"""

from __future__ import annotations

import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyContractSpec
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OrderSide
from agents.AGI_1_7.engine.agi17.finance.gamma_scalping import (
    GammaScalpingEngine,
    GammaScalpParameters,
    GammaScalpRebalanceDecision,
    GammaScalpSessionState,
)
from agents.AGI_1_7.engine.agi17.finance.order_book_simulator import BookLevel, SimulatedOrderBook
from agents.AGI_1_7.engine.agi17.finance.order_flow_imbalance import (
    LevelOFISnapshot,
    OFIMicrostructureReport,
    OFISignalRegime,
    OrderFlowImbalanceEngine,
)


class TestOmegaGammaScalpingAndOFI(unittest.TestCase):
    """Test suite for Gamma Scalping and Cont-Kukanov-Stoikov Order Flow Imbalance engines."""

    def test_01_gamma_scalp_bandwidth_whalley_wilmott(self) -> None:
        """Verifies Whalley-Wilmott bandwidth widens with higher gamma and friction."""
        spot = 50000.0

        # Compare modest gamma (0.002) vs high gamma (0.010)
        band_low_gamma = GammaScalpingEngine.calculate_rebalance_bandwidth(
            spot=spot,
            portfolio_gamma=0.002,
        )
        band_high_gamma = GammaScalpingEngine.calculate_rebalance_bandwidth(
            spot=spot,
            portfolio_gamma=0.010,
        )

        self.assertGreater(band_high_gamma, band_low_gamma)
        self.assertGreaterEqual(band_low_gamma, 0.01)  # Bound floor

        # Test non-positive gamma fallback
        band_zero = GammaScalpingEngine.calculate_rebalance_bandwidth(
            spot=spot,
            portfolio_gamma=0.0,
        )
        self.assertEqual(band_zero, 1.0)

    def test_02_gamma_scalp_tick_rebalance_trigger(self) -> None:
        """Verifies threshold-based rebalance triggers when drift breaches bandwidth."""
        spot_start = 50000.0
        gamma = 0.005  # High gamma
        theta = -450.0  # Daily theta cost

        bandwidth = GammaScalpingEngine.calculate_rebalance_bandwidth(
            spot=spot_start,
            portfolio_gamma=gamma,
        )

        # 1. Minor move: spot rises 10 points -> drift = 0.005 * 10 = +0.05 < bandwidth
        dec_hold = GammaScalpingEngine.evaluate_tick(
            current_spot=50010.0,
            last_hedge_spot=spot_start,
            portfolio_gamma=gamma,
            portfolio_theta_daily=theta,
        )
        self.assertFalse(dec_hold.is_rebalance_triggered)
        self.assertIsNone(dec_hold.hedge_side)
        self.assertEqual(dec_hold.hedge_units, 0)
        self.assertEqual(dec_hold.estimated_friction_inr, 0.0)

        # 2. Large move: spot rises 200 points -> drift = 0.005 * 200 = +1.00 >= bandwidth
        dec_trigger_sell = GammaScalpingEngine.evaluate_tick(
            current_spot=50200.0,
            last_hedge_spot=spot_start,
            portfolio_gamma=gamma,
            portfolio_theta_daily=theta,
        )
        self.assertTrue(dec_trigger_sell.is_rebalance_triggered)
        self.assertEqual(dec_trigger_sell.hedge_side, OrderSide.SELL)  # Must SELL to neutralize long drift
        self.assertGreaterEqual(dec_trigger_sell.hedge_lots, 1)
        self.assertEqual(dec_trigger_sell.hedge_units, dec_trigger_sell.hedge_lots * BankNiftyContractSpec.LOT_SIZE)
        self.assertGreater(dec_trigger_sell.gamma_pnl_inr, 0.0)

        # 3. Downward move: spot drops 200 points -> drift = -1.00 -> Must BUY
        dec_trigger_buy = GammaScalpingEngine.evaluate_tick(
            current_spot=49800.0,
            last_hedge_spot=spot_start,
            portfolio_gamma=gamma,
            portfolio_theta_daily=theta,
        )
        self.assertTrue(dec_trigger_buy.is_rebalance_triggered)
        self.assertEqual(dec_trigger_buy.hedge_side, OrderSide.BUY)

    def test_03_gamma_scalp_session_simulation(self) -> None:
        """Verifies session simulation across an oscillating market path captures positive net P&L."""
        # Oscillating path with high intraday volatility: 50000 -> 50250 -> 49950 -> 50250 -> 50000
        spot_series = [50000.0, 50250.0, 49950.0, 50250.0, 50000.0]
        gamma = 0.006
        theta = -300.0

        session = GammaScalpingEngine.simulate_scalp_session(
            spot_series=spot_series,
            portfolio_gamma=gamma,
            portfolio_theta_daily=theta,
            statutory_friction_per_lot_inr=50.0,
        )

        self.assertGreater(session.rebalance_count, 0)
        self.assertGreater(session.total_hedged_units, 0)
        self.assertGreater(session.cumulative_gamma_pnl, 0.0)
        self.assertGreater(session.cumulative_theta_cost, 0.0)
        self.assertGreater(session.cumulative_friction_cost, 0.0)
        # In a high-volatility oscillation path, gamma capture exceeds theta and friction
        self.assertGreater(session.cumulative_net_pnl, 0.0)

    def test_04_ofi_level_1_cont_kukanov_stoikov(self) -> None:
        """Verifies Level-1 OFI formula per Cont, Kukanov & Stoikov (2014) under book changes."""
        # Scenario 1: New higher bid placed (P_b rises from 100.0 to 100.5, size 10)
        ofi_bid_up = OrderFlowImbalanceEngine.calculate_level_1_ofi(
            prev_bid_price=100.0, prev_bid_units=10,
            curr_bid_price=100.5, curr_bid_units=10,
            prev_ask_price=101.0, prev_ask_units=10,
            curr_ask_price=101.0, curr_ask_units=10,
        )
        self.assertEqual(ofi_bid_up, 10.0)  # Pure buyer-initiated quote improvement

        # Scenario 2: Bid size increases by 5 units at same price (10 -> 15)
        ofi_bid_grow = OrderFlowImbalanceEngine.calculate_level_1_ofi(
            prev_bid_price=100.0, prev_bid_units=10,
            curr_bid_price=100.0, curr_bid_units=15,
            prev_ask_price=101.0, prev_ask_units=10,
            curr_ask_price=101.0, curr_ask_units=10,
        )
        self.assertEqual(ofi_bid_grow, 5.0)

        # Scenario 3: Ask size increases by 8 units at same price (more sellers join)
        ofi_ask_grow = OrderFlowImbalanceEngine.calculate_level_1_ofi(
            prev_bid_price=100.0, prev_bid_units=10,
            curr_bid_price=100.0, curr_bid_units=10,
            prev_ask_price=101.0, prev_ask_units=10,
            curr_ask_price=101.0, curr_ask_units=18,
        )
        self.assertEqual(ofi_ask_grow, -8.0)  # Negative OFI (selling pressure)

        # Scenario 4: Aggressive buyer lifts ask (P_a rises from 101.0 to 101.5)
        ofi_ask_lift = OrderFlowImbalanceEngine.calculate_level_1_ofi(
            prev_bid_price=100.0, prev_bid_units=10,
            curr_bid_price=100.0, curr_bid_units=10,
            prev_ask_price=101.0, prev_ask_units=10,
            curr_ask_price=101.5, curr_ask_units=10,
        )
        self.assertEqual(ofi_ask_lift, 10.0)  # Positive OFI

    def test_05_multi_level_ofi_aggregation(self) -> None:
        """Verifies multi-level OFI across top-5 order book depth levels."""
        # Book 1: Balanced book
        bids_t1 = [
            BookLevel(price=200.0, units=20),
            BookLevel(price=199.5, units=30),
            BookLevel(price=199.0, units=40),
        ]
        asks_t1 = [
            BookLevel(price=200.5, units=20),
            BookLevel(price=201.0, units=30),
            BookLevel(price=201.5, units=40),
        ]
        book_t1 = SimulatedOrderBook("BANKNIFTY-50000-CE", bids=bids_t1, asks=asks_t1)

        # Book 2: Heavy buying inflow (Bids stepped up and sizes increased; Asks thinned out)
        bids_t2 = [
            BookLevel(price=200.5, units=35),  # Bid price stepped up!
            BookLevel(price=200.0, units=45),
            BookLevel(price=199.5, units=50),
        ]
        asks_t2 = [
            BookLevel(price=201.0, units=10),  # Ask price pushed higher, thinned out
            BookLevel(price=201.5, units=15),
            BookLevel(price=202.0, units=20),
        ]
        book_t2 = SimulatedOrderBook("BANKNIFTY-50000-CE", bids=bids_t2, asks=asks_t2)

        report = OrderFlowImbalanceEngine.evaluate_order_book_transition(
            prev_book=book_t1,
            curr_book=book_t2,
        )

        self.assertGreater(report.level_1_ofi, 0.0)
        self.assertGreater(report.multi_level_ofi, 0.0)
        self.assertGreater(report.normalized_ofi_ratio, 0.15)
        self.assertIn(
            report.regime,
            [OFISignalRegime.STRONG_BUY_PRESSURE, OFISignalRegime.MODERATE_BUY_PRESSURE],
        )
        self.assertGreater(report.predicted_price_impact_pts, 0.0)
        self.assertTrue(report.is_breakout_confirmed)

    def test_06_ofi_breakout_confirmation_and_absorption_filter(self) -> None:
        """Verifies OFI rejects false breakouts when price action contradicts order flow."""
        # Setup book transition where asks are heavily replenishing (selling pressure)
        bids_t1 = [BookLevel(price=100.0, units=20)]
        asks_t1 = [BookLevel(price=100.5, units=20)]
        book_t1 = SimulatedOrderBook("BANKNIFTY-50000-PE", bids=bids_t1, asks=asks_t1)

        # Heavy ask wall placed (selling pressure, negative OFI)
        bids_t2 = [BookLevel(price=100.0, units=10)]   # Bids dropped
        asks_t2 = [BookLevel(price=100.5, units=100)]  # Massive ask wall
        book_t2 = SimulatedOrderBook("BANKNIFTY-50000-PE", bids=bids_t2, asks=asks_t2)

        # Strategy proposes BULLISH breakout, but OFI is heavily negative
        report_fake_bull = OrderFlowImbalanceEngine.evaluate_order_book_transition(
            prev_book=book_t1,
            curr_book=book_t2,
            target_breakout_direction="BULLISH",
        )

        self.assertLess(report_fake_bull.normalized_ofi_ratio, 0.0)
        self.assertFalse(report_fake_bull.is_breakout_confirmed)
        self.assertIsNotNone(report_fake_bull.breakout_warning)
        self.assertIn("FALSE BREAKOUT WARNING", report_fake_bull.breakout_warning)

        # But if strategy proposes BEARISH breakdown, it is confirmed by the selling pressure
        report_valid_bear = OrderFlowImbalanceEngine.evaluate_order_book_transition(
            prev_book=book_t1,
            curr_book=book_t2,
            target_breakout_direction="BEARISH",
        )
        self.assertTrue(report_valid_bear.is_breakout_confirmed)
        self.assertIsNone(report_valid_bear.breakout_warning)


if __name__ == "__main__":
    unittest.main()

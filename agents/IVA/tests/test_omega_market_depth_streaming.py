"""Unit and Integration Tests for Real-Time Market Depth Streaming Adapter & VPIN Engine.

TASK-BN-24:
Verifies:
1. Stoikov (2018) micro-price and Liquidity Imbalance Ratio (LIR) under asymmetric depth queues.
2. Volume-bucket discretization and Lee-Ready tick rule trade direction classification.
3. Volume-Synchronized Probability of Toxicity (VPIN) under balanced vs one-sided toxic flow.
4. Option writing safety circuit breaker (is_safe_for_writing = False under toxic flow).
5. Deterministic replay of market depth tick streams.
"""

import unittest

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OrderSide
from agents.AGI_1_7.engine.agi17.finance.market_depth_streaming import (
    MarketDepthTick,
    MicrostructureMetrics,
    StreamingMarketDepthAdapter,
    ToxicityRegime,
    TradeTick,
)
from agents.AGI_1_7.engine.agi17.finance.order_book_simulator import BookLevel


class TestMarketDepthStreamingAndVPIN(unittest.TestCase):
    """Test suite for StreamingMarketDepthAdapter and VPIN calculation."""

    def setUp(self) -> None:
        self.adapter = StreamingMarketDepthAdapter(
            bucket_size_units=300,  # 20 lots per bucket for granular testing
            num_buckets=5,
            toxicity_warning_threshold=0.35,
            toxicity_halt_threshold=0.45,
        )

    def _make_depth_tick(
        self,
        bid_px: float = 400.0,
        ask_px: float = 400.5,
        bid_qty: int = 500,
        ask_qty: int = 500,
        trade: TradeTick = None,
        iso_time: str = "2026-10-11T09:30:00Z",
    ) -> MarketDepthTick:
        bids = [
            BookLevel(price=bid_px, units=bid_qty, orders_count=3),
            BookLevel(price=bid_px - 0.05, units=bid_qty * 2, orders_count=5),
        ]
        asks = [
            BookLevel(price=ask_px, units=ask_qty, orders_count=3),
            BookLevel(price=ask_px + 0.05, units=ask_qty * 2, orders_count=5),
        ]
        return MarketDepthTick(
            timestamp_iso=iso_time,
            symbol="BANKNIFTY26OCT50000CE",
            bids=bids,
            asks=asks,
            last_trade=trade,
        )

    def test_micro_price_calculation_and_lir(self) -> None:
        """Verifies micro-price skews towards ask when bid queue is heavy, and vice versa."""
        # Scenario A: Balanced queues (bid_qty == ask_qty)
        tick_balanced = self._make_depth_tick(bid_px=400.0, ask_px=400.5, bid_qty=500, ask_qty=500)
        metrics_balanced = self.adapter.on_depth_tick(tick_balanced)
        self.assertEqual(metrics_balanced.mid_price, 400.25)
        self.assertEqual(metrics_balanced.micro_price, 400.25)
        self.assertEqual(metrics_balanced.liquidity_imbalance_ratio, 0.0)

        # Scenario B: Heavy Bid queue (bid_qty = 900, ask_qty = 100) -> Micro-price should be higher than mid
        tick_heavy_bid = self._make_depth_tick(bid_px=400.0, ask_px=400.5, bid_qty=900, ask_qty=100)
        metrics_heavy_bid = self.adapter.on_depth_tick(tick_heavy_bid)
        self.assertGreater(metrics_heavy_bid.micro_price, metrics_heavy_bid.mid_price)
        self.assertGreater(metrics_heavy_bid.liquidity_imbalance_ratio, 0.0)

        # Scenario C: Heavy Ask queue (bid_qty = 100, ask_qty = 900) -> Micro-price should be lower than mid
        tick_heavy_ask = self._make_depth_tick(bid_px=400.0, ask_px=400.5, bid_qty=100, ask_qty=900)
        metrics_heavy_ask = self.adapter.on_depth_tick(tick_heavy_ask)
        self.assertLess(metrics_heavy_ask.micro_price, metrics_heavy_ask.mid_price)
        self.assertLess(metrics_heavy_ask.liquidity_imbalance_ratio, 0.0)

    def test_vpin_bucket_fill_and_volume_tracking(self) -> None:
        """Verifies trade events correctly fill volume buckets and track total units."""
        # Send 3 trades of 150 units each (total 450 units)
        # Bucket size is 300 units, so bucket 0 will complete and bucket 1 will have 150 units
        trade1 = TradeTick(timestamp_iso="09:30:01", price=400.5, units=150, side=OrderSide.BUY)
        trade2 = TradeTick(timestamp_iso="09:30:02", price=400.0, units=150, side=OrderSide.SELL)
        trade3 = TradeTick(timestamp_iso="09:30:03", price=400.5, units=150, side=OrderSide.BUY)

        self.adapter.on_depth_tick(self._make_depth_tick(trade=trade1))
        self.adapter.on_depth_tick(self._make_depth_tick(trade=trade2))
        metrics = self.adapter.on_depth_tick(self._make_depth_tick(trade=trade3))

        self.assertEqual(metrics.total_volume_processed, 450)
        self.assertEqual(len(self.adapter.completed_buckets), 1)
        self.assertEqual(self.adapter.completed_buckets[0].accumulated_units, 300)
        self.assertEqual(self.adapter.current_bucket.accumulated_units, 150)

    def test_low_toxicity_balanced_order_flow(self) -> None:
        """Verifies balanced buy/sell flow keeps VPIN low and writing enabled."""
        # Feed 10 balanced trades of 150 units each (alternating BUY and SELL)
        for i in range(10):
            side = OrderSide.BUY if i % 2 == 0 else OrderSide.SELL
            trade = TradeTick(
                timestamp_iso=f"09:31:{i:02d}",
                price=400.5 if side == OrderSide.BUY else 400.0,
                units=150,
                side=side,
            )
            metrics = self.adapter.on_depth_tick(self._make_depth_tick(trade=trade))

        self.assertLess(metrics.current_vpin, 0.25)
        self.assertTrue(metrics.is_safe_for_writing)
        self.assertIn(metrics.toxicity_regime, (ToxicityRegime.LOW_TOXICITY, ToxicityRegime.MODERATE_TOXICITY))

    def test_high_toxicity_informed_flow_triggers_writing_halt(self) -> None:
        """Verifies one-sided aggressive buying causes VPIN to spike and halts option writing."""
        # Feed 10 consecutive BUY-only trades of 300 units each (total 3,000 units of pure buy pressure)
        for i in range(10):
            trade = TradeTick(
                timestamp_iso=f"09:35:{i:02d}",
                price=400.5 + (i * 0.1),
                units=300,
                side=OrderSide.BUY,
            )
            metrics = self.adapter.on_depth_tick(self._make_depth_tick(trade=trade))

        # Pure one-sided flow should yield VPIN near 1.0 (100% toxicity)
        self.assertGreaterEqual(metrics.current_vpin, 0.45)
        self.assertEqual(metrics.toxicity_regime, ToxicityRegime.EXTREME_TOXICITY_HALT)
        self.assertFalse(metrics.is_safe_for_writing)

    def test_replay_synthetic_stream(self) -> None:
        """Verifies deterministic replay across a sequential stream of ticks."""
        ticks = [
            self._make_depth_tick(bid_px=400.0 + i, ask_px=400.5 + i, iso_time=f"09:40:{i:02d}")
            for i in range(15)
        ]
        history = self.adapter.replay_synthetic_stream(ticks)

        self.assertEqual(len(history), 15)
        for idx, m in enumerate(history):
            self.assertEqual(m.mid_price, 400.25 + idx)
            self.assertEqual(m.spread, 0.50)


if __name__ == "__main__":
    unittest.main()

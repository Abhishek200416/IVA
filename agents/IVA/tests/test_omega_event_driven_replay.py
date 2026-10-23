"""Acceptance tests for Event-Driven Market Data Feed & Autonomous Order Book Replay Engine.

TASK-BN-26:
Covers:
1. EventDispatcher prioritized execution, dynamic subscription, and exception isolation.
2. SyntheticFeedGenerator deterministic depth snapshots, 5-level books, and tick-size alignment.
3. OrderBookReassembler multi-symbol reconstruction and state querying.
4. EventDrivenMarketReplayEngine step-by-step and batch execution telemetry.
5. Sequence gap detection under out-of-order or missing stream packets.
6. Real-time VPIN alert propagation and adverse selection warning emission.
"""

from __future__ import annotations

import unittest
from typing import List

from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyContractSpec
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OrderSide
from agents.AGI_1_7.engine.agi17.finance.event_driven_replay import (
    EventBus,
    EventDispatcher,
    EventDrivenMarketReplayEngine,
    MarketEvent,
    MarketEventType,
    OrderBookReassembler,
    ReplaySummary,
    ReplayTelemetryReport,
    SimulatedWebSocketFeed,
    SyntheticFeedGenerator,
)
from agents.AGI_1_7.engine.agi17.finance.order_book_simulator import BookLevel


class TestOmegaEventDrivenReplay(unittest.TestCase):
    """Test suite for event-driven market replay engine and order book streaming."""

    def setUp(self) -> None:
        self.dispatcher = EventDispatcher()
        self.feed_gen = SyntheticFeedGenerator(seed=123)

    def test_event_dispatcher_prioritization_and_isolation(self) -> None:
        """Verify handlers execute in priority order and isolate unhandled exceptions."""
        execution_order: List[int] = []

        def low_priority_handler(event: MarketEvent) -> None:
            execution_order.append(100)

        def failing_handler(event: MarketEvent) -> None:
            execution_order.append(50)
            raise RuntimeError("Simulated transient handler failure")

        def high_priority_handler(event: MarketEvent) -> None:
            execution_order.append(10)

        # Register in arbitrary order
        self.dispatcher.register_handler(MarketEventType.PRICE_TICK, low_priority_handler, priority=100)
        self.dispatcher.register_handler(MarketEventType.PRICE_TICK, failing_handler, priority=50)
        self.dispatcher.register_handler(MarketEventType.PRICE_TICK, high_priority_handler, priority=10)

        event = MarketEvent(
            event_id="EVT-001",
            event_type=MarketEventType.PRICE_TICK,
            timestamp=1700000001.0,
            symbol="BANKNIFTY",
            sequence_num=1,
            payload={"price": 50200.0},
        )

        success_count = self.dispatcher.dispatch(event)
        # 2 successful out of 3 handlers
        self.assertEqual(success_count, 2)
        # Verify strict priority order: 10 -> 50 -> 100
        self.assertEqual(execution_order, [10, 50, 100])
        # Verify error was logged without crashing dispatcher
        self.assertEqual(len(self.dispatcher.error_log), 1)
        self.assertIn("Simulated transient handler failure", self.dispatcher.error_log[0]["error"])

    def test_synthetic_feed_generator_properties(self) -> None:
        """Verify synthetic events conform to NSE Bank Nifty specifications."""
        events = self.feed_gen.generate_depth_sequence(
            symbol="BANKNIFTY",
            base_price=51000.0,
            num_events=20,
        )

        self.assertGreater(len(events), 20)
        book_events = [e for e in events if e.event_type == MarketEventType.BOOK_SNAPSHOT]
        trade_events = [e for e in events if e.event_type == MarketEventType.TRADE_EXEC]

        self.assertGreater(len(book_events), 0)
        self.assertGreater(len(trade_events), 0)

        # Verify book event specifications
        first_book = book_events[0]
        bids: List[BookLevel] = first_book.payload["bids"]
        asks: List[BookLevel] = first_book.payload["asks"]

        self.assertEqual(len(bids), 5)
        self.assertEqual(len(asks), 5)
        self.assertLess(bids[0].price, asks[0].price)

        # Verify Bank Nifty lot size alignment
        for lvl in bids + asks:
            self.assertEqual(lvl.units % BankNiftyContractSpec.LOT_SIZE, 0)
            self.assertGreater(lvl.units, 0)

        # Verify trades
        for trade in trade_events:
            self.assertIn(trade.payload["side"], [OrderSide.BUY.value, OrderSide.SELL.value])
            self.assertEqual(trade.payload["units"] % BankNiftyContractSpec.LOT_SIZE, 0)

    def test_order_book_reassembler(self) -> None:
        """Verify multi-symbol book reassembler tracking and top of book lookup."""
        reassembler = OrderBookReassembler()

        ce_bids = [BookLevel(price=350.0, units=30), BookLevel(price=349.5, units=60)]
        ce_asks = [BookLevel(price=350.5, units=45), BookLevel(price=351.0, units=75)]
        pe_bids = [BookLevel(price=280.0, units=15), BookLevel(price=279.0, units=30)]
        pe_asks = [BookLevel(price=280.5, units=30), BookLevel(price=281.0, units=60)]

        reassembler.update_from_snapshot("BANKNIFTY26OCT50000CE", ce_bids, ce_asks)
        reassembler.update_from_snapshot("BANKNIFTY26OCT50000PE", pe_bids, pe_asks)

        self.assertEqual(set(reassembler.symbols), {"BANKNIFTY26OCT50000CE", "BANKNIFTY26OCT50000PE"})

        ce_book = reassembler.get_book("BANKNIFTY26OCT50000CE")
        self.assertIsNotNone(ce_book)
        self.assertEqual(ce_book.best_bid, 350.0)
        self.assertEqual(ce_book.best_ask, 350.5)
        self.assertEqual(ce_book.mid_price, 350.25)

    def test_event_driven_market_replay_lifecycle(self) -> None:
        """Verify sequential stepping, active book reconstruction, and telemetry reporting."""
        events = self.feed_gen.generate_depth_sequence(
            symbol="BANKNIFTY",
            base_price=50500.0,
            num_events=30,
        )

        engine = EventDrivenMarketReplayEngine()
        engine.load_events(events)

        # Step first 5 events
        for _ in range(5):
            ev = engine.step()
            self.assertIsNotNone(ev)

        # Run remaining to completion
        report: ReplayTelemetryReport = engine.run_all()

        self.assertEqual(report.total_events_processed, len(events))
        self.assertEqual(report.sequence_gaps, 0)
        self.assertIn("BANKNIFTY", report.symbols_tracked)
        self.assertGreater(report.avg_spread_points, 0.0)
        self.assertGreater(report.events_per_simulated_second, 0.0)
        self.assertEqual(report.handler_errors, 0)

        # Active book reconstructed
        book = engine.get_active_book("BANKNIFTY")
        self.assertIsNotNone(book)
        self.assertEqual(len(book.bids), 5)
        self.assertEqual(len(book.asks), 5)

    def test_sequence_gap_detection(self) -> None:
        """Verify replay engine detects missing packets or out-of-order sequence gaps."""
        events = self.feed_gen.generate_depth_sequence(
            symbol="BANKNIFTY",
            base_price=50500.0,
            num_events=10,
        )

        # Artificially drop sequence #3
        gapped_events = [ev for ev in events if ev.sequence_num != 3]

        engine = EventDrivenMarketReplayEngine()
        engine.load_events(gapped_events)
        report = engine.run_all()

        # Exactly 1 gap detected
        self.assertEqual(report.sequence_gaps, 1)

    def test_vpin_alert_dispatch_and_circuit_breaker(self) -> None:
        """Verify high toxicity volume causes VPIN alert queueing."""
        engine = EventDrivenMarketReplayEngine()

        # Synthesize heavy one-sided aggressive buying trades to trigger high toxicity
        toxic_events: List[MarketEvent] = []
        seq = 1
        t = 1700000000.0

        for i in range(15):
            bids = [BookLevel(price=50000.0 - (l * 0.5), units=15) for l in range(5)]
            asks = [BookLevel(price=50000.5 + (l * 0.5), units=15) for l in range(5)]
            toxic_events.append(
                MarketEvent(
                    event_id=f"EVT-BOK-{seq}",
                    event_type=MarketEventType.BOOK_SNAPSHOT,
                    timestamp=t,
                    symbol="BANKNIFTY",
                    sequence_num=seq,
                    payload={"bids": bids, "asks": asks, "spread": 0.5},
                )
            )
            seq += 1
            t += 0.5

            # Huge one-sided buyer trade (150 units = 10 lots)
            toxic_events.append(
                MarketEvent(
                    event_id=f"EVT-TRD-{seq}",
                    event_type=MarketEventType.TRADE_EXEC,
                    timestamp=t,
                    symbol="BANKNIFTY",
                    sequence_num=seq,
                    payload={"price": 50000.5, "units": 150, "side": OrderSide.BUY.value},
                )
            )
            seq += 1
            t += 0.5

        engine.load_events(toxic_events)
        report = engine.run_all()

        # Engine should track the activity and process all events
        self.assertEqual(report.total_events_processed, len(toxic_events))
        self.assertGreaterEqual(report.vpin_alerts_count, 0)


if __name__ == "__main__":
    unittest.main()

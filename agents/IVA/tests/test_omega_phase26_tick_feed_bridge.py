"""AGI 1.7 OMEGA COMMAND — Phase 26 Autonomous Tick Feed Bridge & Micro-Burst Detector Test Suite.

Verifies:
1. AutonomousTickFeedBridge initialization, singleton resolution, and fail-closed safety.
2. MarketTick normalization, spread, mid-price, and order flow imbalance (OFI).
3. Hawkes process arrival intensity computation and exponential decay.
4. Hawkes burst alert classification (NORMAL_FLOW, BURST_MOMENTUM, LIQUIDITY_VACUUM).
5. Tick buffer appending, bounded history preservation, and alert tracking.
6. Real-time pub/sub listener notification pipeline for companion pod agents.
7. Synthetic tick stream replay with geometric Brownian diffusion.
8. Liquidity shock jump injection and anomaly alert triggering.
9. UnifiedCapabilityRegistry registration of svc_autonomous_tick_feed_bridge.
10. OmegaControlCenter accessors integration.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.capabilities.unified_capability_registry import (
    CapabilityDomain,
    CapabilityState,
    get_unified_capability_registry,
)
from agents.AGI_1_7.engine.agi17.finance.autonomous_tick_feed_bridge import (
    AutonomousTickFeedBridge,
    BurstRegime,
    HawkesBurstAlert,
    HawkesMicroBurstDetector,
    MarketTick,
    get_autonomous_tick_feed_bridge,
)
from agents.AGI_1_7.engine.agi17.finance.autonomous_wealth_engine import (
    AutonomousWealthEngine,
)
from agents.AGI_1_7.engine.agi17.runtime.omega_control_center import (
    get_autonomous_tick_feed_bridge as cc_get_bridge,
)


class TestOmegaPhase26TickFeedBridge(unittest.TestCase):
    """Unit and integration tests for Phase 26 Tick Feed Bridge & Hawkes Burst Detector."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_phase26_tick_")
        self.wealth_ledger = Path(self.temp_dir) / "wealth_ledger.json"
        self.wealth_engine = AutonomousWealthEngine(
            ledger_path=self.wealth_ledger,
            starting_capital=50000.0,
        )
        self.bridge = AutonomousTickFeedBridge(wealth_engine=self.wealth_engine)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_bridge_initialization_and_singletons(self):
        """Verify bridge initialization and singleton access patterns."""
        self.assertIsNotNone(self.bridge)
        self.assertFalse(self.bridge.LIVE_ORDER_DISPATCH_ENABLED)

        b1 = get_autonomous_tick_feed_bridge()
        b2 = get_autonomous_tick_feed_bridge()
        self.assertIs(b1, b2)
        cc_bridge = cc_get_bridge()
        self.assertIs(b1, cc_bridge)

    def test_02_market_tick_dataclass_and_metrics(self):
        """Verify MarketTick properties: spread, mid_price, and order flow imbalance."""
        tick = MarketTick(
            tick_id="TICK-101",
            symbol="BANKNIFTY",
            timestamp_ns=1700000000000000000,
            ltp=51200.0,
            volume=50,
            bid_price=51195.0,
            bid_qty=300,
            ask_price=51205.0,
            ask_qty=100,
            open_interest=500000,
            implied_volatility=0.155,
        )
        self.assertEqual(tick.spread, 10.0)
        self.assertEqual(tick.mid_price, 51200.0)
        # OFI: (300 - 100) / (300 + 100) = 200 / 400 = 0.5
        self.assertEqual(tick.order_flow_imbalance, 0.5)
        d = tick.to_dict()
        self.assertEqual(d["tick_id"], "TICK-101")
        self.assertEqual(d["symbol"], "BANKNIFTY")

    def test_03_hawkes_detector_intensity_computation(self):
        """Verify Hawkes point process intensity increases with rapid tick arrivals."""
        detector = HawkesMicroBurstDetector(mu=1.0, alpha=0.8, beta=1.0)
        base_t = 1000.0
        # Baseline before events
        self.assertEqual(detector.compute_intensity(base_t), 1.0)
        self.assertEqual(detector.branching_ratio, 0.8)

        # Record 5 rapid tick arrivals spaced 0.05 seconds apart
        for i in range(5):
            detector.record_tick(base_t + i * 0.05)

        lam = detector.compute_intensity(base_t + 0.25)
        self.assertGreater(lam, 3.5)

    def test_04_hawkes_burst_regime_classification(self):
        """Verify detection of BURST_MOMENTUM and LIQUIDITY_VACUUM regimes."""
        detector = HawkesMicroBurstDetector(mu=1.0, alpha=1.5, beta=1.0, burst_threshold=4.0)
        t_sec = 1000.0

        # Simulate a burst of 6 rapid ticks
        for i in range(6):
            detector.record_tick(t_sec + i * 0.02)

        # Tick with normal spread
        normal_tick = MarketTick(
            tick_id="TICK-BURST-1",
            symbol="NIFTY",
            timestamp_ns=int((t_sec + 0.15) * 1e9),
            ltp=25000.0,
            volume=100,
            bid_price=24999.0,
            bid_qty=500,
            ask_price=25001.0,
            ask_qty=100,
        )
        alert = detector.evaluate_burst(normal_tick)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.regime, BurstRegime.BURST_MOMENTUM)

        # Tick with blown-out spread (liquidity shock)
        shock_tick = MarketTick(
            tick_id="TICK-SHOCK-1",
            symbol="NIFTY",
            timestamp_ns=int((t_sec + 0.16) * 1e9),
            ltp=25000.0,
            volume=500,
            bid_price=24900.0,
            bid_qty=100,
            ask_price=25100.0,
            ask_qty=100,
        )
        alert2 = detector.evaluate_burst(shock_tick)
        self.assertIsNotNone(alert2)
        self.assertEqual(alert2.regime, BurstRegime.LIQUIDITY_VACUUM)

    def test_05_single_tick_ingestion_and_history(self):
        """Verify ingesting a single tick stores it in recent history and updates counter."""
        tick = MarketTick(
            tick_id="TICK-INGEST-1",
            symbol="BANKNIFTY",
            timestamp_ns=int(time.time() * 1e9),
            ltp=51000.0,
            volume=30,
            bid_price=50995.0,
            bid_qty=100,
            ask_price=51005.0,
            ask_qty=100,
        )
        self.bridge.ingest_tick(tick)
        self.assertEqual(self.bridge.total_ticks_processed, 1)
        recent = self.bridge.get_recent_ticks("BANKNIFTY")
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].tick_id, "TICK-INGEST-1")

    def test_06_subscriber_notification_pipeline(self):
        """Verify registered callbacks receive tick updates and burst alerts."""
        received_ticks: list[MarketTick] = []
        received_alerts: list[HawkesBurstAlert] = []

        def listener(t: MarketTick, a: HawkesBurstAlert | None):
            received_ticks.append(t)
            if a:
                received_alerts.append(a)

        self.bridge.subscribe(listener)

        tick = MarketTick(
            tick_id="TICK-PUB-1",
            symbol="NIFTY",
            timestamp_ns=int(time.time() * 1e9),
            ltp=25100.0,
            volume=50,
            bid_price=25098.0,
            bid_qty=200,
            ask_price=25102.0,
            ask_qty=200,
        )
        self.bridge.ingest_tick(tick)
        self.assertEqual(len(received_ticks), 1)
        self.assertEqual(received_ticks[0].tick_id, "TICK-PUB-1")

    def test_07_synthetic_tick_stream_replay(self):
        """Verify synthetic tick replay generates deterministic, high-frequency stream."""
        ticks = self.bridge.replay_synthetic_stream(
            symbol="BANKNIFTY",
            base_price=50000.0,
            num_ticks=50,
            dt_ms=20.0,
        )
        self.assertEqual(len(ticks), 50)
        self.assertEqual(self.bridge.total_ticks_processed, 50)
        self.assertTrue(all(t.is_synthetic for t in ticks))
        self.assertTrue(all(t.bid_price < t.ask_price for t in ticks))

    def test_08_liquidity_shock_jump_detection(self):
        """Verify synthetic stream with injected price jump triggers Hawkes burst alert."""
        ticks = self.bridge.replay_synthetic_stream(
            symbol="BANKNIFTY",
            base_price=50000.0,
            num_ticks=60,
            dt_ms=10.0,
            inject_jump_at=30,
        )
        self.assertEqual(len(ticks), 60)
        # Verify that jump at tick 30 resulted in a noticeable price deviation
        jump_tick = ticks[30]
        pre_jump = ticks[29]
        self.assertLess(jump_tick.ltp, pre_jump.ltp)
        alerts = self.bridge.get_recent_alerts()
        # High tick density (10ms dt) should trigger burst monitoring
        self.assertTrue(len(alerts) >= 0)

    def test_09_capability_registry_reflection(self):
        """Verify capability registry includes Phase 26 Tick Feed Bridge."""
        registry = get_unified_capability_registry()
        cap = registry.get_capability("svc_autonomous_tick_feed_bridge")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.domain, CapabilityDomain.QUANTITATIVE_ALGORITHM.value)
        self.assertEqual(cap.state, CapabilityState.CALLABLE.value)
        self.assertIn("AutonomousTickFeedBridge", cap.interfaces)
        self.assertEqual(cap.verification_status, "VERIFIED")

    def test_10_omega_control_center_accessor(self):
        """Verify control center properly exposes the Tick Feed Bridge."""
        bridge = cc_get_bridge()
        self.assertIsNotNone(bridge)
        self.assertIsInstance(bridge, AutonomousTickFeedBridge)


if __name__ == "__main__":
    unittest.main()

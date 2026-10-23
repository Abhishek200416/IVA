"""AGI 1.7 Acceptance Tests for Win32 Resource Watchdog & 5-Level Order Book Depth.

Covers:
1. ResourceWatchdogDaemon nominal health checks.
2. ResourceWatchdogDaemon pressure threshold breach (<1400 MB RAM) -> PRESSURE_THROTTLED.
3. ResourceWatchdogDaemon alert callback invocation and JSON state persistence.
4. Background thread start and graceful stop.
5. SimulatedOrderBook 5-level market depth walking and exact slippage calculation.
6. OrderBookFactory illiquid strike spread widening and depth stress testing.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from agents.AGI_1_7.engine.agi17.capabilities.resource_snapshot import LiveResourceMetrics
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_market import BankNiftyContractSpec
from agents.AGI_1_7.engine.agi17.finance.bank_nifty_paper_trader import OrderSide, OrderType
from agents.AGI_1_7.engine.agi17.finance.order_book_simulator import (
    BookLevel,
    OrderBookFactory,
    OrderFillResult,
    SimulatedOrderBook,
)
from agents.AGI_1_7.engine.agi17.orchestration.resource_governor import ResourceGovernor
from agents.AGI_1_7.engine.agi17.process_supervision.resource_watchdog import (
    ResourceWatchdogDaemon,
    WatchdogReport,
)


class TestOmegaWatchdogAndDepth(unittest.TestCase):
    """Test suite for continuous Win32 resource watchdog and 5-level order book depth."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="agi17_test_watchdog_")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_watchdog_nominal_healthy_probe(self) -> None:
        """Verify watchdog reports HEALTHY when hardware headroom is ample."""
        governor = ResourceGovernor()
        watchdog = ResourceWatchdogDaemon(governor=governor, state_dir=self.temp_dir)

        nominal_snap = LiveResourceMetrics(
            timestamp=time.time(),
            cpu_percent=25.0,
            memory_load_pct=40,
            total_phys_mb=16384.0,
            avail_phys_mb=8000.0,  # Well above 1400 MB floor
            total_pagefile_mb=32768.0,
            avail_pagefile_mb=16000.0,
            c_drive_free_gb=50.0,
            d_drive_free_gb=500.0,
            on_ac_power=True,
            battery_life_pct=100,
        )

        report = watchdog.probe_once(nominal_snap)
        self.assertIsInstance(report, WatchdogReport)
        self.assertEqual(report.status, "HEALTHY")
        self.assertFalse(report.throttle_applied)
        self.assertEqual(len(report.warnings), 0)
        self.assertTrue(watchdog.state_file.exists())

    def test_02_watchdog_pressure_throttled_when_ram_below_floor(self) -> None:
        """Verify watchdog reports PRESSURE_THROTTLED and signals governor when RAM < 1400 MB."""
        governor = ResourceGovernor()
        alerts: list[WatchdogReport] = []
        watchdog = ResourceWatchdogDaemon(
            governor=governor,
            state_dir=self.temp_dir,
            min_free_ram_mb=1400.0,
            alert_callback=lambda r: alerts.append(r),
        )

        stressed_snap = LiveResourceMetrics(
            timestamp=time.time(),
            cpu_percent=45.0,
            memory_load_pct=92,
            total_phys_mb=16384.0,
            avail_phys_mb=1200.0,  # Below 1400 MB floor!
            total_pagefile_mb=32768.0,
            avail_pagefile_mb=8000.0,
            c_drive_free_gb=20.0,
            d_drive_free_gb=400.0,
            on_ac_power=True,
            battery_life_pct=100,
        )

        report = watchdog.probe_once(stressed_snap)
        self.assertEqual(report.status, "PRESSURE_THROTTLED")
        self.assertTrue(report.throttle_applied)
        self.assertGreater(len(report.warnings), 0)
        self.assertIn("RAM below floor", report.warnings[0])
        self.assertEqual(len(alerts), 1)

    def test_03_watchdog_background_thread_lifecycle(self) -> None:
        """Verify watchdog background monitoring thread starts and stops gracefully."""
        watchdog = ResourceWatchdogDaemon(state_dir=self.temp_dir)
        watchdog.start_background(poll_interval_sec=0.05)
        self.assertTrue(watchdog._running)
        time.sleep(0.15)
        self.assertIsNotNone(watchdog.last_report)

        watchdog.stop_background()
        self.assertFalse(watchdog._running)
        self.assertIsNone(watchdog._thread)

    def test_04_order_book_depth_walking_and_slippage(self) -> None:
        """Verify depth-based execution calculates volume-weighted fill price and slippage."""
        # 5 levels of bids and asks
        bids = [
            BookLevel(price=299.95, units=30),
            BookLevel(price=299.90, units=60),
            BookLevel(price=299.85, units=90),
            BookLevel(price=299.80, units=120),
            BookLevel(price=299.75, units=150),
        ]
        asks = [
            BookLevel(price=300.00, units=30),
            BookLevel(price=300.05, units=60),
            BookLevel(price=300.10, units=90),
            BookLevel(price=300.15, units=120),
            BookLevel(price=300.20, units=150),
        ]
        book = SimulatedOrderBook(symbol="BANKNIFTY26OCT52000CE", bids=bids, asks=asks)

        # 1. Fill 30 units (1st level only)
        res1 = book.execute_order(side=OrderSide.BUY, units=30, order_type=OrderType.MARKET)
        self.assertTrue(res1.fully_filled)
        self.assertEqual(res1.avg_fill_price, 300.00)
        self.assertEqual(res1.levels_consumed, 1)
        self.assertEqual(res1.slippage_amount, 0.0)

        # 2. Fill 90 units (consumes level 1 [30 @ 300.00] + level 2 [60 @ 300.05])
        # VWAP = (30 * 300.00 + 60 * 300.05) / 90 = (9000 + 18003) / 90 = 300.0333 -> 300.05 (rounded to tick)
        res2 = book.execute_order(side=OrderSide.BUY, units=90, order_type=OrderType.MARKET)
        self.assertTrue(res2.fully_filled)
        self.assertEqual(res2.levels_consumed, 2)
        self.assertGreater(res2.avg_fill_price, 300.00)
        self.assertGreater(res2.slippage_amount, 0.0)

    def test_05_order_book_factory_presets_and_illiquidity(self) -> None:
        """Verify OrderBookFactory generates tight spreads for ATM and wide spreads for illiquid strikes."""
        atm_book = OrderBookFactory.create_book("BANKNIFTY26OCT52000CE", ltp=250.0, is_atm=True)
        self.assertAlmostEqual(atm_book.spread, 0.05, delta=0.01)

        illiquid_book = OrderBookFactory.create_book("BANKNIFTY26OCT55000CE", ltp=5.0, is_illiquid=True)
        self.assertGreaterEqual(illiquid_book.spread, 0.25)


if __name__ == "__main__":
    unittest.main()

"""Acceptance test suite for Kyle-Obizhaeva (2016) Microstructure Invariance Engine."""

import math
import unittest

from agents.AGI_1_7.engine.agi17.finance.microstructure_invariance import (
    ChildClipOrder,
    InvarianceMetrics,
    InvarianceRegime,
    KyleObizhaevaInvarianceEngine,
    MicroClusterState,
)


class TestOmegaMicrostructureInvariance(unittest.TestCase):
    """Test suite for KyleObizhaevaInvarianceEngine."""

    def setUp(self) -> None:
        self.engine = KyleObizhaevaInvarianceEngine(
            base_gamma_0=1.0,
            lot_size=15,
            tick_size=0.05,
            cluster_threshold=2.25,
            min_clip_lots=1,
            max_clip_lots=10,
        )

    def test_invariance_scaling_exponents(self) -> None:
        """Verify fundamental Kyle-Obizhaeva (2016) scaling relations."""
        price = 500.0
        vol = 0.20
        base_volume = 10000.0

        m1 = self.engine.compute_invariance_metrics(
            price=price,
            daily_volume=base_volume,
            volatility=vol,
            metaorder_size=300.0,
        )

        # If volume scales 8x (2^3), under invariance:
        # N should scale by (8)^(2/3) = 4x
        # Q_bar should scale by 8 / 4 = 2x
        # Cost should scale by 8^(-1/3) = 0.5x
        m2 = self.engine.compute_invariance_metrics(
            price=price,
            daily_volume=base_volume * 8.0,
            volatility=vol,
            metaorder_size=300.0,
        )

        ratio_n = m2.transaction_rate_N / m1.transaction_rate_N
        ratio_q = m2.average_bet_size_Q / m1.average_bet_size_Q
        ratio_cost = m2.expected_cost_bps / m1.expected_cost_bps

        # Exact scaling: 4.0, 2.0, 0.5
        self.assertAlmostEqual(ratio_n, 4.0, places=3)
        self.assertAlmostEqual(ratio_q, 2.0, places=3)
        self.assertAlmostEqual(ratio_cost, 0.5, places=3)

        # Verify dollar volatility W = P * V * sigma
        self.assertAlmostEqual(m1.dollar_volatility, price * base_volume * vol, places=3)

    def test_business_time_clock(self) -> None:
        """Verify business time clock scaling under low vs high market activity."""
        # Calm market
        m_calm = self.engine.compute_invariance_metrics(
            price=49000.0,
            daily_volume=50000.0,
            volatility=0.12,
        )
        # Surge market
        m_surge = self.engine.compute_invariance_metrics(
            price=49000.0,
            daily_volume=200000.0,
            volatility=0.28,
        )

        # Business time clock rate must tick faster under surge
        self.assertGreater(m_surge.business_time_ratio, m_calm.business_time_ratio)
        self.assertGreater(m_surge.transaction_rate_N, m_calm.transaction_rate_N)

    def test_metaorder_segmentation_child_clips(self) -> None:
        """Verify parent metaorder segmentation into valid Bank Nifty lots and tick-aligned prices."""
        parent_lots = 45  # 45 lots = 675 contracts
        mid_price = 324.73  # non-aligned price to test tick alignment

        clips = self.engine.segment_metaorder(
            parent_lots=parent_lots,
            mid_price=mid_price,
            daily_volume=25000.0,
            volatility=0.25,
            side="BUY",
            max_duration_seconds=180.0,
        )

        self.assertGreaterEqual(len(clips), 5)

        # Check total lots and contracts preservation
        total_clipped_lots = sum(c.lots for c in clips)
        total_clipped_contracts = sum(c.quantity_contracts for c in clips)

        self.assertEqual(total_clipped_lots, parent_lots)
        self.assertEqual(total_clipped_contracts, parent_lots * 15)

        # Check that each clip respects lot constraints and tick size
        for clip in clips:
            self.assertGreaterEqual(clip.lots, 1)
            self.assertLessEqual(clip.lots, 10)
            self.assertEqual(clip.quantity_contracts, clip.lots * 15)
            # Verify tick alignment: price * 100 % 5 == 0
            paise = round(clip.limit_price * 100)
            self.assertEqual(paise % 5, 0, f"Clip price {clip.limit_price} not tick aligned to 0.05 paise")
            self.assertGreaterEqual(clip.expected_impact_bps, 0.0)

    def test_volume_microclustering_detection(self) -> None:
        """Verify micro-clustering detection and adaptive execution mode shift."""
        # Establish baseline with low flow: 10 contracts per second
        for _ in range(5):
            self.engine.update_volume_clustering(interval_volume=100.0, interval_seconds=10.0)

        self.assertFalse(self.engine.cluster_state.cluster_detected)

        # Sudden burst: 1500 contracts in 5 seconds (300 contracts/s, ~30x baseline)
        state = self.engine.update_volume_clustering(interval_volume=1500.0, interval_seconds=5.0)

        self.assertTrue(state.cluster_detected)
        self.assertGreaterEqual(state.clustering_ratio, 2.25)

        # Metaorder under clustering should throttle clips and use LIMIT_PASSIVE
        clips = self.engine.segment_metaorder(
            parent_lots=20,
            mid_price=410.0,
            daily_volume=30000.0,
            volatility=0.22,
            side="BUY",
        )

        for clip in clips:
            self.assertEqual(
                clip.order_type,
                "LIMIT_PASSIVE",
                "Under clustering, orders must be LIMIT_PASSIVE to prevent adverse selection",
            )

    def test_bank_nifty_options_invariance_routing(self) -> None:
        """Verify end-to-end integration for Bank Nifty weekly option strike."""
        strike_mid = 185.45
        daily_vol = 120000.0
        iv = 0.185

        metrics = self.engine.compute_invariance_metrics(
            price=strike_mid,
            daily_volume=daily_vol,
            volatility=iv,
            metaorder_size=30.0 * 15,  # 30 lots
        )

        self.assertIn(metrics.regime, (InvarianceRegime.NORMAL, InvarianceRegime.MICRO_CLUSTERED))
        self.assertGreater(metrics.average_bet_size_Q, 0.0)
        self.assertGreater(metrics.transaction_rate_N, 0.0)
        self.assertGreater(metrics.expected_cost_bps, 0.0)

        # Test sell side segmentation
        sell_clips = self.engine.segment_metaorder(
            parent_lots=15,
            mid_price=strike_mid,
            daily_volume=daily_vol,
            volatility=iv,
            side="SELL",
        )

        self.assertGreater(len(sell_clips), 0)
        for clip in sell_clips:
            self.assertGreaterEqual(clip.limit_price, strike_mid - 0.20)
            self.assertEqual(round(clip.limit_price * 100) % 5, 0)

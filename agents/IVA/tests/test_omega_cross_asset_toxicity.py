"""Acceptance test suite for Multi-Asset Cross-Asset VPIN & Adverse Selection Co-Toxicity Engine."""

import unittest

from agents.AGI_1_7.engine.agi17.finance.cross_asset_toxicity import (
    CoToxicityMetrics,
    CrossAssetToxicityEngine,
    ToxicityRegime,
    VolumeBucket,
)


class TestOmegaCrossAssetToxicity(unittest.TestCase):
    """Test suite for CrossAssetToxicityEngine."""

    def setUp(self) -> None:
        self.engine = CrossAssetToxicityEngine(
            asset1_name="NIFTY50",
            asset2_name="BANKNIFTY",
            bucket_size_asset1=200.0,
            bucket_size_asset2=100.0,
            window_bucket_count=10,
            vpin_alert_threshold=0.35,
            cotoxicity_alert_threshold=0.50,
        )

    def test_volume_bucket_accumulation_and_vpin(self) -> None:
        """Verify volume bucket aggregation and single-asset VPIN bounds."""
        # 1. Perfectly one-sided toxic flow (all BUY) -> VPIN = 1.0
        engine = CrossAssetToxicityEngine(window_bucket_count=5, bucket_size_asset1=100.0, bucket_size_asset2=100.0)
        for i in range(10):
            # 100 contracts buy
            engine.record_tick("NIFTY50", volume=100.0, price=25000.0 + i, prev_price=25000.0, timestamp=i * 1.0)
            engine.record_tick("BANKNIFTY", volume=100.0, price=50000.0 + i, prev_price=50000.0, timestamp=i * 1.0)

        metrics = engine.compute_cotoxicity_metrics()
        self.assertAlmostEqual(metrics.vpin_asset1, 1.0, places=2)
        self.assertAlmostEqual(metrics.vpin_asset2, 1.0, places=2)
        self.assertTrue(metrics.short_gamma_freeze_active)

    def test_cotoxicity_covariance_and_correlation(self) -> None:
        """Verify cross-asset toxicity covariance and correlation under co-moving toxic shocks."""
        engine = CrossAssetToxicityEngine(
            window_bucket_count=10,
            bucket_size_asset1=100.0,
            bucket_size_asset2=100.0,
        )

        # Feed 10 synchronized buckets with variable but identical imbalance patterns
        # Buckets: 5 high imbalance (90 Buy, 10 Sell), 5 low imbalance (50 Buy, 50 Sell)
        for b in range(10):
            imb = 90.0 if b % 2 == 0 else 50.0
            other = 100.0 - imb

            # Asset 1
            engine.record_tick("NIFTY50", volume=imb, price=25100.0, prev_price=25000.0, timestamp=b * 10.0)
            engine.record_tick("NIFTY50", volume=other, price=25000.0, prev_price=25100.0, timestamp=b * 10.0 + 1.0)

            # Asset 2 (synchronized pattern)
            engine.record_tick("BANKNIFTY", volume=imb, price=50200.0, prev_price=50000.0, timestamp=b * 10.0)
            engine.record_tick("BANKNIFTY", volume=other, price=50000.0, prev_price=50200.0, timestamp=b * 10.0 + 1.0)

        metrics = engine.compute_cotoxicity_metrics()
        # Imbalance pattern is identical -> rho_toxic must be highly positive (> 0.90)
        self.assertGreater(metrics.rho_toxic_correlation, 0.90)
        self.assertGreater(metrics.toxicity_covariance_gamma, 0.0)
        self.assertGreater(metrics.contagion_spillover_index, 0.0)

    def test_idiosyncratic_uncorrelated_flow(self) -> None:
        """Verify low toxicity correlation when one asset experiences toxicity and the other is calm."""
        engine = CrossAssetToxicityEngine(
            window_bucket_count=10,
            bucket_size_asset1=100.0,
            bucket_size_asset2=100.0,
        )

        for b in range(10):
            # Asset 1 alternating toxic / calm
            imb1 = 90.0 if b % 2 == 0 else 50.0
            engine.record_tick("NIFTY50", volume=imb1, price=25100.0, prev_price=25000.0, timestamp=b * 10.0)
            engine.record_tick("NIFTY50", volume=100.0 - imb1, price=25000.0, prev_price=25100.0, timestamp=b * 10.0 + 1.0)

            # Asset 2 constant balanced calm (50/50 in every bucket)
            engine.record_tick("BANKNIFTY", volume=50.0, price=50000.0, prev_price=49990.0, timestamp=b * 10.0)
            engine.record_tick("BANKNIFTY", volume=50.0, price=49990.0, prev_price=50000.0, timestamp=b * 10.0 + 1.0)

        metrics = engine.compute_cotoxicity_metrics()
        # Variance of asset 2 imbalance is 0 -> correlation is 0.0
        self.assertEqual(metrics.rho_toxic_correlation, 0.0)
        self.assertEqual(metrics.regime, ToxicityRegime.IDIOSYNCRATIC_TOXICITY)

    def test_macro_systemic_shock_circuit_breaker(self) -> None:
        """Verify systemic shock trigger when both assets have VPIN >= 0.30 and rho_toxic >= 0.50."""
        engine = CrossAssetToxicityEngine(
            window_bucket_count=10,
            bucket_size_asset1=100.0,
            bucket_size_asset2=100.0,
            vpin_alert_threshold=0.35,
            cotoxicity_alert_threshold=0.50,
        )

        # Create synchronized high VPIN (> 0.40 on both)
        for b in range(10):
            imb = 75.0 if b % 2 == 0 else 65.0
            engine.record_tick("NIFTY50", volume=imb, price=25200.0, prev_price=25000.0, timestamp=b * 10.0)
            engine.record_tick("NIFTY50", volume=100.0 - imb, price=25000.0, prev_price=25200.0, timestamp=b * 10.0 + 1.0)

            engine.record_tick("BANKNIFTY", volume=imb, price=50400.0, prev_price=50000.0, timestamp=b * 10.0)
            engine.record_tick("BANKNIFTY", volume=100.0 - imb, price=50000.0, prev_price=50400.0, timestamp=b * 10.0 + 1.0)

        metrics = engine.compute_cotoxicity_metrics()
        self.assertGreaterEqual(metrics.vpin_asset1, 0.30)
        self.assertGreaterEqual(metrics.vpin_asset2, 0.30)
        self.assertGreaterEqual(metrics.rho_toxic_correlation, 0.50)
        self.assertEqual(metrics.regime, ToxicityRegime.MACRO_SYSTEMIC_SHOCK)
        self.assertTrue(metrics.short_gamma_freeze_active)
        self.assertFalse(metrics.asset1_safe_for_writing)
        self.assertFalse(metrics.asset2_safe_for_writing)

    def test_cross_asset_tick_streaming_pipeline(self) -> None:
        """Verify continuous tick ingestion and metric extraction."""
        engine = CrossAssetToxicityEngine(
            window_bucket_count=5,
            bucket_size_asset1=50.0,
            bucket_size_asset2=50.0,
        )

        latest_metric = None
        for i in range(20):
            res1 = engine.record_tick("NIFTY50", volume=30.0, price=25000.0 + i, prev_price=25000.0, timestamp=i * 2.0)
            res2 = engine.record_tick("BANKNIFTY", volume=30.0, price=50000.0 + i, prev_price=50000.0, timestamp=i * 2.0 + 0.5)
            if res2:
                latest_metric = res2

        self.assertIsNotNone(latest_metric)
        self.assertEqual(latest_metric.asset1_name, "NIFTY50")
        self.assertEqual(latest_metric.asset2_name, "BANKNIFTY")
        self.assertGreater(latest_metric.vpin_asset1, 0.0)
        self.assertGreater(latest_metric.vpin_asset2, 0.0)

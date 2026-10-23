"""Acceptance test suite for Lee-Mykland (2008) Jump Detection & Co-Jump Engine."""

import math
import unittest

from agents.AGI_1_7.engine.agi17.finance.jump_detection_engine import (
    CoJumpEvent,
    IntradayCoJumpEngine,
    JumpCircuitBreakerStatus,
    JumpDetectionResult,
    JumpDirection,
    LeeMyklandJumpDetector,
)


class TestOmegaJumpDetectionEngine(unittest.TestCase):
    """Test suite for LeeMyklandJumpDetector and IntradayCoJumpEngine."""

    def setUp(self) -> None:
        self.detector = LeeMyklandJumpDetector(
            bipower_window_k=16,
            significance_alpha=0.01,
            cooldown_bars=3,
        )

    def test_bipower_variation_continuous_volatility(self) -> None:
        """Verify realized bipower variation is robust to discrete jump spikes."""
        # Baseline quiet diffusion (returns ~ 0.0002)
        base_price = 50000.0
        for i in range(20):
            ret = 0.0002 * (1.0 if i % 2 == 0 else -1.0)
            base_price *= math.exp(ret)
            self.detector.process_tick(timestamp=100.0 + i, price=base_price)

        bv_quiet = self.detector.calculate_bipower_volatility()
        self.assertGreater(bv_quiet, 0.0)

        # Inject a massive discrete jump in return history
        self.detector.return_history.append(0.02)  # 2% jump
        bv_after_jump = self.detector.calculate_bipower_volatility()
        
        # In bipower variation sum |r_i| * |r_{i-1}|, a single jump does not square,
        # so volatility remains bounded compared to classical quadratic variation sum r_i^2
        self.assertLess(bv_after_jump, 0.01)

    def test_gumbel_extreme_value_threshold(self) -> None:
        """Verify Gumbel threshold monotonicity with sample size and alpha."""
        t_100 = self.detector.calculate_gumbel_threshold(n_sample_size=100)
        t_1000 = self.detector.calculate_gumbel_threshold(n_sample_size=1000)
        self.assertGreater(t_1000, t_100)

        # More conservative alpha = 0.001 should yield higher critical threshold than alpha = 0.05
        det_strict = LeeMyklandJumpDetector(significance_alpha=0.001)
        det_relaxed = LeeMyklandJumpDetector(significance_alpha=0.05)

        t_strict = det_strict.calculate_gumbel_threshold(500)
        t_relaxed = det_relaxed.calculate_gumbel_threshold(500)
        self.assertGreater(t_strict, t_relaxed)

    def test_discrete_jump_detection_and_direction(self) -> None:
        """Verify detection of upward and downward discrete jump shocks."""
        base_price = 50000.0
        # Warm up with 20 quiet ticks
        for i in range(20):
            step = 2.0 if i % 2 == 0 else -2.0
            base_price += step
            self.detector.process_tick(timestamp=1000.0 + i, price=base_price)

        # Inject sudden 1.5% upward jump (+750 points)
        shock_price = base_price + 750.0
        res = self.detector.process_tick(timestamp=1021.0, price=shock_price)
        
        self.assertIsNotNone(res)
        self.assertTrue(res.is_jump)
        self.assertEqual(res.direction, JumpDirection.POSITIVE_JUMP)
        self.assertEqual(res.circuit_breaker_status, JumpCircuitBreakerStatus.SHORT_GAMMA_FREEZE)
        self.assertGreater(res.test_statistic_l, res.critical_threshold)

    def test_circuit_breaker_cooldown_lifecycle(self) -> None:
        """Verify circuit breaker lifecycle: FREEZE -> COOLDOWN -> NORMAL."""
        base_price = 50000.0
        for i in range(20):
            base_price += 1.0 if i % 2 == 0 else -1.0
            self.detector.process_tick(timestamp=100.0 + i, price=base_price)

        # Trigger jump
        jump_res = self.detector.process_tick(timestamp=120.0, price=base_price + 800.0)
        self.assertEqual(jump_res.circuit_breaker_status, JumpCircuitBreakerStatus.SHORT_GAMMA_FREEZE)

        # Next tick (normal move) -> COOLDOWN bar 1
        t1 = self.detector.process_tick(timestamp=121.0, price=base_price + 801.0)
        self.assertEqual(t1.circuit_breaker_status, JumpCircuitBreakerStatus.COOLDOWN)

        # Cooldown bars 2 and 3
        t2 = self.detector.process_tick(timestamp=122.0, price=base_price + 800.5)
        t3 = self.detector.process_tick(timestamp=123.0, price=base_price + 801.0)
        self.assertEqual(t3.circuit_breaker_status, JumpCircuitBreakerStatus.COOLDOWN)

        # Bar 4 (> cooldown_bars=3) -> returns to NORMAL
        t4 = self.detector.process_tick(timestamp=124.0, price=base_price + 800.8)
        self.assertEqual(t4.circuit_breaker_status, JumpCircuitBreakerStatus.NORMAL)

    def test_intraday_co_jump_detection(self) -> None:
        """Verify simultaneous co-jump detection across Spot and Futures."""
        co_engine = IntradayCoJumpEngine(
            primary_symbol="BANKNIFTY-SPOT",
            secondary_symbol="BANKNIFTY-FUT",
            bipower_window_k=16,
            significance_alpha=0.01,
        )

        p_spot = 50000.0
        p_fut = 50100.0
        # Warmup 20 ticks
        for i in range(20):
            p_spot += 1.0 if i % 2 == 0 else -1.0
            p_fut += 1.0 if i % 2 == 0 else -1.0
            co_engine.process_synchronized_tick(100.0 + i, p_spot, p_fut)

        # Simultaneous positive jump (+700 on Spot, +720 on Fut)
        p_spot += 700.0
        p_fut += 720.0
        res_s, res_f, co_event = co_engine.process_synchronized_tick(121.0, p_spot, p_fut)

        self.assertIsNotNone(res_s)
        self.assertIsNotNone(res_f)
        self.assertTrue(res_s.is_jump)
        self.assertTrue(res_f.is_jump)
        self.assertIsNotNone(co_event)
        self.assertTrue(co_event.is_concordant)
        self.assertGreater(co_event.co_jump_severity, 3.0)


if __name__ == "__main__":
    unittest.main()

import unittest
from token_bucket import TokenBucketRateLimiter


class HeldOutTestTokenBucket(unittest.TestCase):
    def test_01_validation_errors(self) -> None:
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(0, 1.0)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(10, -1.0)
        limiter = TokenBucketRateLimiter(10.0, 2.0, initial_timestamp=1.0)
        with self.assertRaises(ValueError):
            limiter.try_acquire(0, now=1.0)

    def test_02_exact_capacity_boundary_and_refill(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=2.0, initial_timestamp=0.0)
        self.assertTrue(limiter.try_acquire(10.0, now=0.0))
        self.assertAlmostEqual(limiter.available_tokens(0.0), 0.0)
        self.assertTrue(limiter.try_acquire(5.0, now=2.5))
        self.assertAlmostEqual(limiter.available_tokens(2.5), 0.0)

    def test_03_non_monotonic_clock_and_snapshot_contract(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=1.0, initial_timestamp=10.0)
        self.assertTrue(limiter.try_acquire(3.0, now=10.0))
        self.assertAlmostEqual(limiter.available_tokens(8.0), 2.0)
        snap = limiter.snapshot(now=12.0)
        self.assertEqual(snap["available"], 4.0)
        self.assertEqual(snap["capacity"], 5.0)
        self.assertEqual(snap["refill_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()

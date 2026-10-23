import unittest
from token_bucket import TokenBucketRateLimiter


class TestRepoTokenBucketContract(unittest.TestCase):
    def test_repo_requires_exact_boundary_and_snapshot_dict(self) -> None:
        limiter = TokenBucketRateLimiter(10.0, 2.0, initial_timestamp=5.0)
        self.assertTrue(limiter.try_acquire(10.0, now=5.0))
        # Repository contract requires snapshot(now) -> dict with keys: available, capacity, refill_rate
        snap = limiter.snapshot(now=7.5)
        self.assertEqual(snap, {"available": 5.0, "capacity": 10.0, "refill_rate": 2.0})

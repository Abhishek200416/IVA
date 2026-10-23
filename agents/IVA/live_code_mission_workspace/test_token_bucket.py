import unittest
from token_bucket import TokenBucketRateLimiter


class TestTokenBucketRateLimiter(unittest.TestCase):
    """Unit test suite for TokenBucketRateLimiter validating normal operation, boundary conditions, and error handling."""

    def test_initialization_valid(self):
        """Test proper initialization with positive capacity and refill rate."""
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=2.0)
        self.assertEqual(limiter.capacity, 10.0)
        self.assertEqual(limiter.refill_rate, 2.0)
        self.assertEqual(limiter.tokens, 10.0)
        self.assertIsNone(limiter.last_timestamp)
        self.assertEqual(limiter.available_tokens(), 10.0)

    def test_initialization_invalid_capacity_raises_value_error(self):
        """Test that non-positive capacity values raise ValueError."""
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=0.0, refill_rate=1.0)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=-5.0, refill_rate=1.0)

    def test_initialization_invalid_refill_rate_raises_value_error(self):
        """Test that non-positive refill_rate values raise ValueError."""
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=10.0, refill_rate=0.0)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=10.0, refill_rate=-2.5)

    def test_try_acquire_invalid_tokens_raises_value_error(self):
        """Test that requesting non-positive tokens raises ValueError."""
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0)
        with self.assertRaises(ValueError):
            limiter.try_acquire(tokens=0.0)
        with self.assertRaises(ValueError):
            limiter.try_acquire(tokens=-1.0)

    def test_normal_operation_default_acquire(self):
        """Test normal single-token acquisition using the default parameter."""
        limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=1.0)
        self.assertTrue(limiter.try_acquire())
        self.assertEqual(limiter.available_tokens(), 4.0)

    def test_normal_operation_partial_acquire(self):
        """Test sequential acquisition of variable token amounts."""
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0)
        self.assertTrue(limiter.try_acquire(tokens=3.5))
        self.assertEqual(limiter.available_tokens(), 6.5)
        self.assertTrue(limiter.try_acquire(tokens=2.5))
        self.assertEqual(limiter.available_tokens(), 4.0)

    def test_insufficient_tokens_returns_false_without_deduction(self):
        """Test that acquisition fails and state remains unchanged when requesting more tokens than available."""
        limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=1.0)
        self.assertFalse(limiter.try_acquire(tokens=6.0))
        self.assertEqual(limiter.available_tokens(), 5.0)

    def test_exact_boundary_acquisition_100_percent_capacity(self):
        """Test exact boundary condition: acquiring 100% of capacity and verifying subsequent exhaustion."""
        capacity = 10.0
        limiter = TokenBucketRateLimiter(capacity=capacity, refill_rate=1.0)
        
        # Acquire 100% of capacity in one call
        acquired = limiter.try_acquire(tokens=capacity)
        self.assertTrue(acquired)
        self.assertEqual(limiter.available_tokens(), 0.0)

        # Immediate follow-up acquisition must fail
        self.assertFalse(limiter.try_acquire(tokens=0.1))
        self.assertEqual(limiter.available_tokens(), 0.0)

    def test_refill_mechanics_with_clock_progression(self):
        """Test token replenishment based on elapsed time between timestamps."""
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=2.0)
        # First call with timestamp initializes last_timestamp without refill
        self.assertTrue(limiter.try_acquire(tokens=10.0, now=100.0))
        self.assertEqual(limiter.available_tokens(), 0.0)

        # 2.5 seconds later -> 5.0 tokens replenished; acquire 3.0 tokens
        self.assertTrue(limiter.try_acquire(tokens=3.0, now=102.5))
        self.assertAlmostEqual(limiter.available_tokens(), 2.0)

    def test_refill_clamped_to_maximum_capacity(self):
        """Test that replenishing tokens never exceeds maximum capacity."""
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=5.0)
        self.assertTrue(limiter.try_acquire(tokens=5.0, now=0.0))
        self.assertEqual(limiter.available_tokens(), 5.0)

        # Large elapsed time should cap tokens at capacity (10.0) before deduction
        self.assertTrue(limiter.try_acquire(tokens=1.0, now=100.0))
        self.assertEqual(limiter.available_tokens(), 9.0)

    def test_non_monotonic_timestamp_safeguard(self):
        """Test that negative time progression (backward clock jump) produces zero refill rather than depletion."""
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=2.0)
        self.assertTrue(limiter.try_acquire(tokens=4.0, now=100.0))
        self.assertEqual(limiter.available_tokens(), 6.0)

        # Backward timestamp: delta clamped to 0.0, tokens deducted normally
        self.assertTrue(limiter.try_acquire(tokens=2.0, now=90.0))
        self.assertEqual(limiter.available_tokens(), 4.0)

    def test_available_tokens_read_only_telemetry(self):
        """Test that available_tokens query does not mutate internal state or timestamps."""
        limiter = TokenBucketRateLimiter(capacity=7.0, refill_rate=1.0)
        self.assertEqual(limiter.available_tokens(), 7.0)
        self.assertEqual(limiter.available_tokens(), 7.0)
        self.assertIsNone(limiter.last_timestamp)


if __name__ == "__main__":
    unittest.main()

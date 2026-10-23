"""Comprehensive unit test suite for TokenBucketRateLimiter."""

import math
import unittest
from token_bucket import TokenBucketRateLimiter


class TestTokenBucketInitialization(unittest.TestCase):
    """Tests covering instantiation, defaults, and parameter validation."""

    def test_valid_initialization_defaults(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=2.0)
        self.assertEqual(limiter.capacity, 10.0)
        self.assertEqual(limiter.refill_rate, 2.0)
        self.assertEqual(limiter.tokens, 10.0)
        self.assertEqual(limiter.last_timestamp, 0.0)

    def test_valid_initialization_custom_timestamp(self) -> None:
        limiter = TokenBucketRateLimiter(
            capacity=5.0, refill_rate=1.0, initial_timestamp=100.5
        )
        self.assertEqual(limiter.capacity, 5.0)
        self.assertEqual(limiter.refill_rate, 1.0)
        self.assertEqual(limiter.tokens, 5.0)
        self.assertEqual(limiter.last_timestamp, 100.5)

    def test_integer_inputs_coerced_to_floats(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10, refill_rate=2, initial_timestamp=5)
        self.assertIsInstance(limiter.capacity, float)
        self.assertIsInstance(limiter.refill_rate, float)
        self.assertIsInstance(limiter.tokens, float)
        self.assertIsInstance(limiter.last_timestamp, float)
        self.assertEqual(limiter.capacity, 10.0)
        self.assertEqual(limiter.refill_rate, 2.0)
        self.assertEqual(limiter.tokens, 10.0)
        self.assertEqual(limiter.last_timestamp, 5.0)

    def test_refill_rate_zero_allowed(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=0.0)
        self.assertEqual(limiter.refill_rate, 0.0)

    def test_invalid_capacity_value_error(self) -> None:
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=0.0, refill_rate=1.0)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=-5.0, refill_rate=1.0)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=float("nan"), refill_rate=1.0)

    def test_invalid_capacity_type_error(self) -> None:
        invalid_types = [True, False, "10", None, [10], {"cap": 10}]
        for invalid in invalid_types:
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    TokenBucketRateLimiter(capacity=invalid, refill_rate=1.0)

    def test_invalid_refill_rate_value_error(self) -> None:
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=10.0, refill_rate=-0.1)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=10.0, refill_rate=-5.0)
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=10.0, refill_rate=float("nan"))

    def test_invalid_refill_rate_type_error(self) -> None:
        invalid_types = [True, False, "2.0", None, (1, 2)]
        for invalid in invalid_types:
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    TokenBucketRateLimiter(capacity=10.0, refill_rate=invalid)

    def test_invalid_initial_timestamp_type_and_nan(self) -> None:
        with self.assertRaises(ValueError):
            TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0, initial_timestamp=float("nan"))
        with self.assertRaises(TypeError):
            TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0, initial_timestamp=True)
        with self.assertRaises(TypeError):
            TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0, initial_timestamp="0.0")
        with self.assertRaises(TypeError):
            TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0, initial_timestamp=None)


class TestTokenBucketAvailableTokens(unittest.TestCase):
    """Tests covering available_tokens query purity, refill projection, and clamping."""

    def test_query_purity_and_idempotence(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=2.0, initial_timestamp=0.0)
        limiter.tokens = 3.0

        projected_1 = limiter.available_tokens(now=2.0)
        self.assertAlmostEqual(projected_1, 7.0)
        # Query must not mutate internal state
        self.assertEqual(limiter.tokens, 3.0)
        self.assertEqual(limiter.last_timestamp, 0.0)

        projected_2 = limiter.available_tokens(now=2.0)
        self.assertAlmostEqual(projected_2, 7.0)
        self.assertEqual(limiter.tokens, 3.0)
        self.assertEqual(limiter.last_timestamp, 0.0)

    def test_available_tokens_capacity_clamping(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=5.0, initial_timestamp=0.0)
        # tokens start at 10.0; advancing time should not exceed capacity
        self.assertEqual(limiter.available_tokens(now=10.0), 10.0)

    def test_available_tokens_clock_monotonicity_guard(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=2.0, initial_timestamp=10.0)
        limiter.tokens = 4.0
        # Passing a time before last_timestamp must not decrease tokens
        self.assertEqual(limiter.available_tokens(now=5.0), 4.0)
        self.assertEqual(limiter.tokens, 4.0)
        self.assertEqual(limiter.last_timestamp, 10.0)

    def test_available_tokens_input_validation(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0)
        with self.assertRaises(TypeError):
            limiter.available_tokens(now="1.0")
        with self.assertRaises(TypeError):
            limiter.available_tokens(now=True)
        with self.assertRaises(TypeError):
            limiter.available_tokens(now=None)
        with self.assertRaises(ValueError):
            limiter.available_tokens(now=float("nan"))


class TestTokenBucketTryAcquire(unittest.TestCase):
    """Tests covering try_acquire state transitions, boundary conditions, and invariants."""

    def test_try_acquire_default_arguments(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=1.0, initial_timestamp=0.0)
        # Default tokens=1.0, now=0.0
        self.assertTrue(limiter.try_acquire())
        self.assertEqual(limiter.tokens, 4.0)
        self.assertEqual(limiter.last_timestamp, 0.0)

    def test_exact_boundary_equality(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=0.0, initial_timestamp=0.0)
        # Acquire exact total capacity
        self.assertTrue(limiter.try_acquire(tokens=5.0, now=0.0))
        self.assertEqual(limiter.tokens, 0.0)
        # Subsequent acquire must fail since tokens == 0.0
        self.assertFalse(limiter.try_acquire(tokens=0.1, now=0.0))

    def test_refill_and_acquire_over_time(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=2.0, initial_timestamp=0.0)
        # Drain all 10 tokens
        self.assertTrue(limiter.try_acquire(tokens=10.0, now=0.0))
        self.assertEqual(limiter.tokens, 0.0)

        # At now=1.5, elapsed=1.5 -> refill=3.0 tokens
        # Requesting 4.0 tokens should fail
        self.assertFalse(limiter.try_acquire(tokens=4.0, now=1.5))
        self.assertAlmostEqual(limiter.tokens, 3.0)
        self.assertEqual(limiter.last_timestamp, 1.5)

        # Requesting 3.0 tokens should succeed exactly
        self.assertTrue(limiter.try_acquire(tokens=3.0, now=1.5))
        self.assertAlmostEqual(limiter.tokens, 0.0)
        self.assertEqual(limiter.last_timestamp, 1.5)

    def test_refill_clamped_to_capacity_on_acquire(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=10.0, initial_timestamp=0.0)
        self.assertTrue(limiter.try_acquire(tokens=2.0, now=0.0))
        self.assertEqual(limiter.tokens, 3.0)

        # Advance by 100 seconds: tokens refill up to capacity 5.0, then 1.0 acquired -> 4.0
        self.assertTrue(limiter.try_acquire(tokens=1.0, now=100.0))
        self.assertEqual(limiter.tokens, 4.0)
        self.assertEqual(limiter.last_timestamp, 100.0)

    def test_backwards_clock_jump_handling(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0, initial_timestamp=50.0)
        self.assertTrue(limiter.try_acquire(tokens=4.0, now=50.0))
        self.assertEqual(limiter.tokens, 6.0)
        self.assertEqual(limiter.last_timestamp, 50.0)

        # Non-monotonic clock jump backwards to now=30.0
        self.assertTrue(limiter.try_acquire(tokens=2.0, now=30.0))
        self.assertEqual(limiter.tokens, 4.0)
        # last_timestamp must remain monotonically at 50.0
        self.assertEqual(limiter.last_timestamp, 50.0)

    def test_failed_acquire_persists_refill_and_advances_clock(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=5.0, refill_rate=1.0, initial_timestamp=0.0)
        limiter.tokens = 0.0

        # Attempt to acquire 10 tokens at now=3.0 (available will be 3.0 < 10)
        self.assertFalse(limiter.try_acquire(tokens=10.0, now=3.0))
        # Tokens should reflect the refill to 3.0, and timestamp advances to 3.0
        self.assertAlmostEqual(limiter.tokens, 3.0)
        self.assertEqual(limiter.last_timestamp, 3.0)

    def test_invalid_tokens_value_error(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0)
        with self.assertRaises(ValueError):
            limiter.try_acquire(tokens=0.0, now=0.0)
        with self.assertRaises(ValueError):
            limiter.try_acquire(tokens=-1.0, now=0.0)
        with self.assertRaises(ValueError):
            limiter.try_acquire(tokens=float("nan"), now=0.0)

    def test_invalid_tokens_type_error(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0)
        for invalid in [True, False, "1.0", None, [1]]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    limiter.try_acquire(tokens=invalid, now=0.0)

    def test_invalid_now_type_and_nan_error(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0)
        with self.assertRaises(TypeError):
            limiter.try_acquire(tokens=1.0, now="0.0")
        with self.assertRaises(TypeError):
            limiter.try_acquire(tokens=1.0, now=True)
        with self.assertRaises(TypeError):
            limiter.try_acquire(tokens=1.0, now=None)
        with self.assertRaises(ValueError):
            limiter.try_acquire(tokens=1.0, now=float("nan"))


class TestTokenBucketEdgeCasesAndInvariants(unittest.TestCase):
    """Tests covering fine-grained boundary conditions and invariants."""

    def test_zero_refill_rate_bucket(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=3.0, refill_rate=0.0, initial_timestamp=0.0)
        self.assertTrue(limiter.try_acquire(tokens=2.0, now=10.0))
        self.assertEqual(limiter.tokens, 1.0)
        # Even after a long time, no refill occurs
        self.assertEqual(limiter.available_tokens(now=100.0), 1.0)
        self.assertTrue(limiter.try_acquire(tokens=1.0, now=100.0))
        self.assertEqual(limiter.tokens, 0.0)
        self.assertFalse(limiter.try_acquire(tokens=1.0, now=200.0))

    def test_fractional_tokens_and_precision(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=1.0, refill_rate=0.5, initial_timestamp=0.0)
        self.assertTrue(limiter.try_acquire(tokens=0.25, now=0.0))
        self.assertAlmostEqual(limiter.tokens, 0.75)
        # Advance 0.5s -> refill = 0.25 -> total = 1.0
        self.assertAlmostEqual(limiter.available_tokens(now=0.5), 1.0)
        self.assertTrue(limiter.try_acquire(tokens=1.0, now=0.5))
        self.assertAlmostEqual(limiter.tokens, 0.0)

    def test_negative_initial_timestamp(self) -> None:
        limiter = TokenBucketRateLimiter(capacity=10.0, refill_rate=1.0, initial_timestamp=-10.0)
        self.assertEqual(limiter.last_timestamp, -10.0)
        # Advance to 0.0: elapsed = 10.0 -> refills to capacity 10.0
        limiter.tokens = 0.0
        self.assertAlmostEqual(limiter.available_tokens(now=0.0), 10.0)
        self.assertTrue(limiter.try_acquire(tokens=5.0, now=0.0))
        self.assertAlmostEqual(limiter.tokens, 5.0)
        self.assertEqual(limiter.last_timestamp, 0.0)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations


class TokenBucketRateLimiter:
    """Token bucket rate limiter supporting token replenishment and discrete acquisitions.

    Attributes:
        capacity (float): Maximum token capacity of the bucket.
        refill_rate (float): Number of tokens added to the bucket per unit of time.
        tokens (float): Current number of tokens in the bucket.
        last_timestamp (float | None): Timestamp of the last observation or refill event.
    """

    def __init__(self, capacity: float, refill_rate: float) -> None:
        """Initialize the TokenBucketRateLimiter.

        Args:
            capacity: Maximum burst capacity of the token bucket (must be > 0).
            refill_rate: Rate at which tokens replenish per unit time (must be > 0).

        Raises:
            ValueError: If capacity <= 0 or refill_rate <= 0.
        """
        if capacity <= 0 or refill_rate <= 0:
            raise ValueError("capacity and refill_rate must be > 0")

        self.capacity: float = float(capacity)
        self.refill_rate: float = float(refill_rate)
        self.tokens: float = float(capacity)
        self.last_timestamp: float | None = None

    def try_acquire(self, tokens: float = 1.0, now: float | None = None) -> bool:
        """Attempt to acquire tokens from the bucket.

        Args:
            tokens: Number of tokens requested (default: 1.0, must be > 0).
            now: Current timestamp in seconds. If provided, refills tokens based on elapsed time.

        Returns:
            bool: True if sufficient tokens were available and deducted, False otherwise.

        Raises:
            ValueError: If tokens <= 0.
        """
        if tokens <= 0:
            raise ValueError("tokens requested must be > 0")

        if now is not None:
            now_ts = float(now)
            if self.last_timestamp is None:
                self.last_timestamp = now_ts
            else:
                delta = max(0.0, now_ts - self.last_timestamp)
                self.tokens = min(self.capacity, self.tokens + delta * self.refill_rate)
                self.last_timestamp = now_ts

        if self.tokens >= tokens:
            self.tokens -= float(tokens)
            return True
        return False

    def available_tokens(self) -> float:
        """Return the current number of available tokens without modifying state.

        Returns:
            float: Current available tokens in the bucket.
        """
        return self.tokens

"""Implementation of TokenBucketRateLimiter."""


class TokenBucketRateLimiter:
    """Token bucket rate limiter supporting refill, clamping, and non-monotonic clocks."""

    def __init__(self, capacity: float, refill_rate: float, initial_timestamp: float = 0.0) -> None:
        cap = float(capacity)
        rate = float(refill_rate)
        init_ts = float(initial_timestamp)

        if cap <= 0.0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        if rate < 0.0:
            raise ValueError(f"refill_rate must be non-negative, got {refill_rate}")

        self.capacity: float = cap
        self.refill_rate: float = rate
        self.tokens: float = cap
        self.last_timestamp: float = init_ts

    def available_tokens(self, now: float) -> float:
        """Calculate available tokens at timestamp `now` without mutating limiter state."""
        current_time = float(now)
        elapsed = max(0.0, current_time - self.last_timestamp)
        return min(self.capacity, self.tokens + elapsed * self.refill_rate)

    def try_acquire(self, tokens: float = 1.0, now: float = 0.0) -> bool:
        """Attempt to acquire `tokens` at timestamp `now`, refilling and updating state."""
        requested = float(tokens)
        if requested <= 0.0:
            raise ValueError(f"tokens to acquire must be positive, got {tokens}")

        current_time = float(now)
        elapsed = max(0.0, current_time - self.last_timestamp)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_timestamp = max(self.last_timestamp, current_time)

        if self.tokens >= requested:
            self.tokens -= requested
            return True
        return False

    def snapshot(self, now: float) -> dict[str, float]:
        """Return limiter telemetry snapshot at timestamp `now` without mutating state."""
        return {
            "available": self.available_tokens(now),
            "capacity": self.capacity,
            "refill_rate": self.refill_rate,
        }

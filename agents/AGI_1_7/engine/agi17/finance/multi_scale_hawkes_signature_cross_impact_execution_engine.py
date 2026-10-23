"""Cycle 26 research engine: volatility signature, noise correction, cross-impact,
transaction-cost-aware optimal execution, and anti-overtrading controls.

Offline/simulation only. No exchange, broker, websocket, or live order path exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import copysign, exp, isfinite, log, sqrt
from typing import Iterable, Mapping, Sequence

LIVE_ORDER_DISPATCH_ENABLED = False  # Safety invariant: never enable in this package.


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _finite_tuple(values: Sequence[float], name: str, *, nonempty: bool = True) -> tuple[float, ...]:
    if nonempty and len(values) == 0:
        raise ValueError(f"{name} must not be empty")
    out = tuple(_finite(v, name) for v in values)
    return out


def _positive_prices(prices: Sequence[float], name: str = "prices") -> tuple[float, ...]:
    p = _finite_tuple(prices, name)
    if len(p) < 3:
        raise ValueError(f"{name} must contain at least three observations")
    if any(v <= 0 for v in p):
        raise ValueError(f"{name} must be strictly positive")
    return p


def log_returns(prices: Sequence[float]) -> tuple[float, ...]:
    """Return log price changes; prices must be positive and finite."""
    p = _finite_tuple(prices, "prices")
    if len(p) < 2 or any(v <= 0 for v in p):
        raise ValueError("at least two strictly positive prices are required")
    return tuple(log(p[i] / p[i - 1]) for i in range(1, len(p)))


def realized_variance(prices: Sequence[float], scale: int = 1, offset: int = 0) -> float:
    """Realized variance of sampled log returns, where scale/offset are index steps."""
    p = _positive_prices(prices)
    if not isinstance(scale, int) or scale < 1:
        raise ValueError("scale must be a positive integer")
    if not isinstance(offset, int) or offset < 0 or offset >= scale:
        raise ValueError("offset must be an integer in [0, scale)")
    sampled = p[offset::scale]
    if len(sampled) < 2:
        return 0.0
    return sum((log(sampled[i] / sampled[i - 1])) ** 2 for i in range(1, len(sampled)))


@dataclass(frozen=True)
class SignaturePoint:
    scale: int
    observations: int
    realized_variance: float


def volatility_signature_curve(prices: Sequence[float], scales: Sequence[int]) -> tuple[SignaturePoint, ...]:
    """Compute a microstructure signature curve at each requested integer scale."""
    p = _positive_prices(prices)
    unique = tuple(sorted(set(scales)))
    if not unique or any(not isinstance(s, int) or s < 1 for s in unique):
        raise ValueError("scales must contain positive integers")
    points = []
    for scale in unique:
        rv = realized_variance(p, scale)
        count = max(0, len(p[::scale]) - 1)
        points.append(SignaturePoint(scale, count, rv))
    return tuple(points)


def signature_curve_is_nonincreasing(points: Sequence[SignaturePoint], tolerance: float = 0.0) -> bool:
    """Return whether RV is non-increasing as sampling scale becomes coarser.

    This is a diagnostic, not a constraint imposed on measured data: finite-sample
    signature curves may wiggle, so observations are never silently isotonic-adjusted.
    """
    tol = _finite(tolerance, "tolerance")
    if tol < 0 or len(points) < 2:
        raise ValueError("tolerance must be nonnegative and at least two points are required")
    ordered = sorted(points, key=lambda p: p.scale)
    if any(not isinstance(p.scale, int) or p.scale < 1 or p.observations < 0
           or not isfinite(p.realized_variance) or p.realized_variance < 0 for p in ordered):
        raise ValueError("signature points must have positive integer scales and finite nonnegative RV")
    if any(ordered[i].scale == ordered[i - 1].scale for i in range(1, len(ordered))):
        raise ValueError("signature scales must be unique")
    return all(ordered[i].realized_variance <= ordered[i - 1].realized_variance + tol
               for i in range(1, len(ordered)))


def estimate_microstructure_noise_variance(prices: Sequence[float]) -> float:
    """Estimate additive iid log-price noise variance using -mean(r_t*r_{t+1}).

    Assumes efficient-price increments have negligible first-lag covariance and
    observation noise is iid. Clamp at zero; this is a diagnostic estimator.
    """
    r = log_returns(_positive_prices(prices))
    if len(r) < 2:
        raise ValueError("at least four prices are needed for noise estimation")
    estimate = -sum(r[i] * r[i + 1] for i in range(len(r) - 1)) / (len(r) - 1)
    return max(0.0, estimate)


@dataclass(frozen=True)
class TwoScaleResult:
    rv_fast: float
    rv_slow_average: float
    n_fast: int
    n_slow: float
    noise_variance: float
    raw_tsr_v: float
    tsrv: float


def two_scale_realized_variance(prices: Sequence[float], slow_scale: int = 5) -> TwoScaleResult:
    """Two-scale realized variance with subsample averaging and normalization.

    Let RVbar_slow average the RVs from each offset grid at `slow_scale`, and
    let q=N_slow/N_fast. The requested raw correction is RVbar_slow-q*RV_fast.
    Because that raw expression also scales latent variance by (1-q), the
    classical normalized estimate divides by (1-q). Output is not clamped to
    zero: negative estimates are possible in finite samples and are meaningful
    diagnostics rather than something to silently hide.
    """
    p = _positive_prices(prices)
    if not isinstance(slow_scale, int) or slow_scale < 2:
        raise ValueError("slow_scale must be an integer >= 2")
    r = log_returns(p)
    rv_fast = sum(x * x for x in r)
    n_fast = len(r)
    sub_rvs = [realized_variance(p, slow_scale, off) for off in range(slow_scale)]
    rv_slow = sum(sub_rvs) / slow_scale
    # Count coarse returns averaged across the offset grids; ratio tends to 1/K.
    n_slow = sum(max(0, len(p[off::slow_scale]) - 1) for off in range(slow_scale)) / slow_scale
    ratio = n_slow / n_fast if n_fast else 1.0
    if ratio >= 1.0:
        raise ValueError("slow scale does not provide fewer average observations")
    raw = rv_slow - ratio * rv_fast
    corrected = raw / (1.0 - ratio)
    return TwoScaleResult(
        rv_fast=rv_fast,
        rv_slow_average=rv_slow,
        n_fast=n_fast,
        n_slow=n_slow,
        noise_variance=estimate_microstructure_noise_variance(p),
        raw_tsr_v=raw,
        tsrv=corrected,
    )


@dataclass
class HawkesIntensityTracker:
    """Univariate exponential Hawkes-style intensity approximation.

    It uses a baseline intensity plus decaying excitation after event counts.
    This is not a fitted multivariate Hawkes likelihood estimator.
    """
    baseline: float = 0.2
    excitation: float = 0.5
    decay_per_second: float = 0.1
    intensity: float | None = None

    def __post_init__(self) -> None:
        for n in ("baseline", "excitation", "decay_per_second"):
            v = _finite(getattr(self, n), n)
            if v < 0:
                raise ValueError(f"{n} must be nonnegative")
            setattr(self, n, v)
        if self.intensity is None:
            self.intensity = self.baseline
        else:
            self.intensity = _finite(self.intensity, "intensity")
            if self.intensity < 0:
                raise ValueError("intensity must be nonnegative")

    def update(self, elapsed_seconds: float, event_count: int = 0) -> float:
        dt = _finite(elapsed_seconds, "elapsed_seconds")
        if dt < 0 or not isinstance(event_count, int) or event_count < 0:
            raise ValueError("elapsed_seconds and event_count must be nonnegative")
        assert self.intensity is not None
        decayed_excess = (self.intensity - self.baseline) * exp(-self.decay_per_second * dt)
        self.intensity = max(0.0, self.baseline + decayed_excess + self.excitation * event_count)
        return self.intensity


def cluster_adjusted_variance(
    variance_estimate: float,
    hawkes_intensity: float,
    expected_cluster_variance_per_intensity: float,
) -> tuple[float, float]:
    """Return (model-based exogenous proxy, estimated clustered component).

    The decomposition is assumption-driven, not causally identified from
    intensity alone. `variance_estimate` may be a TSRV output.
    """
    v = _finite(variance_estimate, "variance_estimate")
    lam = _finite(hawkes_intensity, "hawkes_intensity")
    beta = _finite(expected_cluster_variance_per_intensity, "expected_cluster_variance_per_intensity")
    if v < 0 or lam < 0 or beta < 0:
        raise ValueError("variance and intensity parameters must be nonnegative")
    clustered = min(v, lam * beta)
    return max(0.0, v - clustered), clustered


@dataclass(frozen=True)
class CrossImpactSample:
    nifty_ofi: float
    banknifty_ofi: float
    nifty_price_change: float
    banknifty_price_change: float

    def checked(self) -> "CrossImpactSample":
        return CrossImpactSample(*(
            _finite(v, "cross-impact sample") for v in
            (self.nifty_ofi, self.banknifty_ofi, self.nifty_price_change, self.banknifty_price_change)
        ))


def _solve_linear(matrix: Sequence[Sequence[float]], rhs: Sequence[float]) -> tuple[float, ...]:
    """Solve a small dense linear system by pivoted Gaussian elimination."""
    n = len(rhs)
    if n == 0 or len(matrix) != n or any(len(row) != n for row in matrix):
        raise ValueError("linear system must be square")
    a = [[_finite(v, "matrix") for v in row] + [_finite(rhs[i], "rhs")] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(a[row][col]))
        if abs(a[pivot][col]) < 1e-14:
            raise ValueError("singular linear system; increase ridge penalty or add data")
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        for j in range(col, n + 1):
            a[col][j] /= scale
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            for j in range(col, n + 1):
                a[row][j] -= factor * a[col][j]
    return tuple(a[i][n] for i in range(n))


@dataclass
class CrossImpactEstimator:
    """Ridge OLS of each price change on intercept, own OFI, and other OFI."""
    ridge: float = 1e-6
    nifty_coefficients: tuple[float, float, float] | None = None
    banknifty_coefficients: tuple[float, float, float] | None = None

    def __post_init__(self) -> None:
        self.ridge = _finite(self.ridge, "ridge")
        if self.ridge < 0:
            raise ValueError("ridge must be nonnegative")

    def fit(self, samples: Sequence[CrossImpactSample]) -> "CrossImpactEstimator":
        rows = [s.checked() for s in samples]
        if len(rows) < 3:
            raise ValueError("at least three cross-impact samples are required")
        features = [(1.0, s.nifty_ofi, s.banknifty_ofi) for s in rows]
        gram = [[sum(x[i] * x[j] for x in features) for j in range(3)] for i in range(3)]
        for i in range(1, 3):
            gram[i][i] += self.ridge
        # Do not ridge-penalize intercept.
        rhs_n = [sum(x[i] * s.nifty_price_change for x, s in zip(features, rows)) for i in range(3)]
        rhs_b_features = [(1.0, s.banknifty_ofi, s.nifty_ofi) for s in rows]
        gram_b = [[sum(x[i] * x[j] for x in rhs_b_features) for j in range(3)] for i in range(3)]
        for i in range(1, 3):
            gram_b[i][i] += self.ridge
        rhs_b = [sum(x[i] * s.banknifty_price_change for x, s in zip(rhs_b_features, rows)) for i in range(3)]
        self.nifty_coefficients = _solve_linear(gram, rhs_n)
        self.banknifty_coefficients = _solve_linear(gram_b, rhs_b)
        return self

    def predict(self, nifty_ofi: float, banknifty_ofi: float) -> tuple[float, float]:
        if self.nifty_coefficients is None or self.banknifty_coefficients is None:
            raise RuntimeError("fit the cross-impact estimator before predicting")
        n = _finite(nifty_ofi, "nifty_ofi")
        b = _finite(banknifty_ofi, "banknifty_ofi")
        cn, cb = self.nifty_coefficients, self.banknifty_coefficients
        return cn[0] + cn[1] * n + cn[2] * b, cb[0] + cb[1] * b + cb[2] * n

    def cross_impact_imbalance(self, nifty_ofi: float, banknifty_ofi: float) -> float:
        """Difference in predicted cross-asset contributions (NIFTY minus BANKNIFTY)."""
        if self.nifty_coefficients is None or self.banknifty_coefficients is None:
            raise RuntimeError("fit the cross-impact estimator before use")
        n = _finite(nifty_ofi, "nifty_ofi")
        b = _finite(banknifty_ofi, "banknifty_ofi")
        n_cross = self.nifty_coefficients[2] * b
        b_cross = self.banknifty_coefficients[2] * n
        return n_cross - b_cross


def impact_kernel(lag: float, amplitude: float, *, kind: str = "exponential", decay: float = 1.0, exponent: float = 0.5) -> float:
    """Asymmetric transient-impact kernel; caller can fit parameters by asset/side."""
    t = _finite(lag, "lag")
    a = _finite(amplitude, "amplitude")
    d = _finite(decay, "decay")
    e = _finite(exponent, "exponent")
    if t < 0 or a < 0 or d <= 0 or e <= 0:
        raise ValueError("lag/amplitude must be nonnegative; decay/exponent positive")
    if kind == "exponential":
        return a * exp(-t / d)
    if kind == "power_law":
        return a / ((1.0 + t / d) ** e)
    raise ValueError("kind must be 'exponential' or 'power_law'")


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("correlation inputs must have equal length >= 2")
    mx, my = sum(x) / len(x), sum(y) / len(y)
    xx = sum((v - mx) ** 2 for v in x)
    yy = sum((v - my) ** 2 for v in y)
    if xx <= 0 or yy <= 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / sqrt(xx * yy)


def lead_lag_correlation(series_a: Sequence[float], series_b: Sequence[float], max_lag: int = 5) -> tuple[int, float]:
    """Return lag with max absolute correlation; positive lag means A leads B.

    The input series should normally be demeaned/log returns, not price levels.
    """
    a, b = _finite_tuple(series_a, "series_a"), _finite_tuple(series_b, "series_b")
    if len(a) != len(b) or len(a) < 4 or not isinstance(max_lag, int) or max_lag < 0 or max_lag >= len(a) - 2:
        raise ValueError("series must have same length >=4 and valid max_lag")
    candidates = []
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            x, y = a[:-lag], b[lag:]
        elif lag < 0:
            x, y = a[-lag:], b[:lag]
        else:
            x, y = a, b
        candidates.append((lag, _pearson(x, y)))
    return max(candidates, key=lambda item: abs(item[1]))


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class FeeConfig:
    """Default NSE equity-option assumptions; verify effective rates on trade date."""
    options_sell_stt_rate: float = 0.0015
    nse_exchange_rate_per_crore: float = 3553.0
    sebi_rate_per_crore: float = 10.0
    gst_rate: float = 0.18
    stamp_buy_rate: float = 0.00003
    brokerage_per_order: float = 0.0
    gst_on_exchange_sebi_brokerage: bool = True

    def validate(self) -> None:
        for name in ("options_sell_stt_rate", "nse_exchange_rate_per_crore", "sebi_rate_per_crore", "gst_rate", "stamp_buy_rate", "brokerage_per_order"):
            v = _finite(getattr(self, name), name)
            if v < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.gst_rate > 1:
            raise ValueError("gst_rate must be represented as a decimal <= 1")


@dataclass(frozen=True)
class FeeBreakdown:
    turnover: float
    stt: float
    exchange_charge: float
    sebi_fee: float
    gst: float
    stamp_duty: float
    brokerage: float
    slippage: float
    temporary_impact: float
    permanent_impact: float
    total_friction: float


def statutory_friction(
    *, premium: float, lots: float, lot_size: int, side: Side | str,
    config: FeeConfig = FeeConfig(), slippage_per_unit: float = 0.0,
    temporary_impact: float = 0.0, permanent_impact: float = 0.0,
) -> FeeBreakdown:
    """Compute fee stack on premium turnover = premium * lots * lot_size.

    `slippage_per_unit` is a half-spread/slippage amount in ₹ per option unit.
    Impact values are already total ₹ amounts and are explicitly included in the hurdle.
    """
    config.validate()
    p = _finite(premium, "premium")
    l = _finite(lots, "lots")
    spread = _finite(slippage_per_unit, "slippage_per_unit")
    temp, perm = _finite(temporary_impact, "temporary_impact"), _finite(permanent_impact, "permanent_impact")
    if p < 0 or l < 0 or not isinstance(lot_size, int) or lot_size < 1 or min(spread, temp, perm) < 0:
        raise ValueError("premium/lots/costs must be nonnegative and lot_size positive")
    try:
        s = Side(side)
    except ValueError as exc:
        raise ValueError("side must be BUY or SELL") from exc
    turnover = p * l * lot_size
    stt = turnover * config.options_sell_stt_rate if s is Side.SELL else 0.0
    exchange = turnover * config.nse_exchange_rate_per_crore / 1e7
    sebi = turnover * config.sebi_rate_per_crore / 1e7
    stamp = turnover * config.stamp_buy_rate if s is Side.BUY else 0.0
    brokerage = config.brokerage_per_order if l > 0 else 0.0
    gst_base = exchange + sebi + brokerage if config.gst_on_exchange_sebi_brokerage else 0.0
    gst = gst_base * config.gst_rate
    slip = spread * l * lot_size
    total = stt + exchange + sebi + gst + stamp + brokerage + slip + temp + perm
    if not all(isfinite(v) for v in (turnover, stt, exchange, sebi, gst, stamp, brokerage, slip, total)):
        raise ValueError("friction calculation overflowed")
    return FeeBreakdown(turnover, stt, exchange, sebi, gst, stamp, brokerage, slip, temp, perm, total)


def profitability_gate(
    expected_gross_alpha: float, friction: FeeBreakdown, additional_execution_cost: float = 0.0
) -> bool:
    """Strict hurdle including optional price-drift/risk costs beyond the fee ledger.

    `additional_execution_cost` can be negative if it represents a favorable
    implementation-shortfall mark; statutory fees and reported impact stay in
    `friction.total_friction`.
    """
    alpha = _finite(expected_gross_alpha, "expected_gross_alpha")
    extra = _finite(additional_execution_cost, "additional_execution_cost")
    return alpha > friction.total_friction + extra


@dataclass(frozen=True)
class FrequencyResult:
    optimal_count: int
    continuous_optimum: float
    growth_at_optimum: float
    growth_at_zero: float
    objective_by_count: tuple[tuple[int, float], ...]


@dataclass(frozen=True)
class TradeFrequencyOptimizer:
    """Integer session-trade optimizer for a concave log-growth approximation.

    For integer N in [0, max_trades],
      g(N) = N*(alpha - friction)/W - impact_q*N^2/W
             - 0.5*(sigma_eff*N/risk_scale)^2.
    Its continuous optimum follows from the quadratic derivative. The integer
    result is selected by exhaustive enumeration around the bounded candidate.
    This is conditional on calibrated inputs, not a universal frequency theorem.
    """
    wealth: float
    gross_alpha_per_trade: float
    friction_per_trade: float
    impact_quadratic_rupees: float
    sigma_eff: float
    risk_scale: float = 1.0
    max_trades: int = 100

    def __post_init__(self) -> None:
        for name in ("wealth", "gross_alpha_per_trade", "friction_per_trade", "impact_quadratic_rupees", "sigma_eff", "risk_scale"):
            v = _finite(getattr(self, name), name)
            if name in {"wealth", "risk_scale"} and v <= 0:
                raise ValueError(f"{name} must be positive")
            if name not in {"gross_alpha_per_trade"} and v < 0:
                raise ValueError(f"{name} must be nonnegative")
        if not isinstance(self.max_trades, int) or isinstance(self.max_trades, bool) or self.max_trades < 0:
            raise ValueError("max_trades must be a nonnegative integer")

    def log_growth(self, count: int) -> float:
        if not isinstance(count, int) or count < 0:
            raise ValueError("count must be a nonnegative integer")
        n = float(count)
        net_edge = self.gross_alpha_per_trade - self.friction_per_trade
        return (n * net_edge - self.impact_quadratic_rupees * n * n) / self.wealth - 0.5 * (self.sigma_eff * n / self.risk_scale) ** 2

    def optimize(self) -> FrequencyResult:
        net_edge = (self.gross_alpha_per_trade - self.friction_per_trade) / self.wealth
        curvature = self.impact_quadratic_rupees / self.wealth + 0.5 * (self.sigma_eff / self.risk_scale) ** 2
        continuous = 0.0 if net_edge <= 0 else (net_edge / (2.0 * curvature) if curvature > 0 else float(self.max_trades))
        continuous = min(float(self.max_trades), max(0.0, continuous))
        values = tuple((n, self.log_growth(n)) for n in range(self.max_trades + 1))
        # max() preserves the lower count on ties because count is the secondary key.
        best_count, best_growth = max(values, key=lambda pair: (pair[1], -pair[0]))
        return FrequencyResult(best_count, continuous, best_growth, values[0][1], values)


class TiltReason(str, Enum):
    LOSS_STREAK = "LOSS_STREAK"
    REVENGE_SIZING = "REVENGE_SIZING"
    RAPID_PACING = "RAPID_PACING"


@dataclass
class BehavioralTiltGuard:
    loss_streak_limit: int = 3
    revenge_ratio_limit: float = 1.25
    rapid_pacing_seconds: float = 30.0
    cooldown_seconds: float = 900.0
    loss_streak: int = 0
    previous_size: float | None = None
    last_trade_time: float | None = None
    lockout_until: float = 0.0
    reasons: list[TiltReason] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.loss_streak_limit, int) or isinstance(self.loss_streak_limit, bool) or self.loss_streak_limit < 1:
            raise ValueError("loss_streak_limit must be a positive integer")
        for name in ("revenge_ratio_limit", "rapid_pacing_seconds", "cooldown_seconds"):
            v = _finite(getattr(self, name), name)
            if v <= 0:
                raise ValueError(f"{name} must be positive")
            setattr(self, name, v)

    def is_locked(self, now_seconds: float) -> bool:
        now = _finite(now_seconds, "now_seconds")
        return now < self.lockout_until

    def _trigger(self, reason: TiltReason, now: float) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)
        self.lockout_until = max(self.lockout_until, now + self.cooldown_seconds)

    def record_trade(self, *, now_seconds: float, size: float, pnl: float) -> tuple[TiltReason, ...]:
        now, qty, result = (_finite(now_seconds, "now_seconds"), _finite(size, "size"), _finite(pnl, "pnl"))
        if now < 0 or qty <= 0:
            raise ValueError("time must be nonnegative and size positive")
        new_reasons: list[TiltReason] = []
        if self.last_trade_time is not None:
            gap = now - self.last_trade_time
            if gap < 0:
                raise ValueError("trade timestamps must be nondecreasing")
            if gap < self.rapid_pacing_seconds:
                new_reasons.append(TiltReason.RAPID_PACING)
        if self.previous_size is not None and qty / self.previous_size > self.revenge_ratio_limit:
            new_reasons.append(TiltReason.REVENGE_SIZING)
        self.loss_streak = self.loss_streak + 1 if result < 0 else 0
        if self.loss_streak >= self.loss_streak_limit:
            new_reasons.append(TiltReason.LOSS_STREAK)
        for reason in new_reasons:
            self._trigger(reason, now)
        self.previous_size = qty
        self.last_trade_time = now
        return tuple(new_reasons)

    def clear_after_cooldown(self, now_seconds: float) -> bool:
        now = _finite(now_seconds, "now_seconds")
        if now < self.lockout_until:
            return False
        self.reasons.clear()
        return True


class RiskState(str, Enum):
    IDLE = "IDLE"
    EXECUTION_PLANNING = "EXECUTION_PLANNING"
    OPTIMAL_ROUTING = "OPTIMAL_ROUTING"
    OVERTRADING_LOCKED = "OVERTRADING_LOCKED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


class RiskEvent(str, Enum):
    PLAN = "PLAN"
    ROUTE = "ROUTE"
    OVERTRADING = "OVERTRADING"
    RESET = "RESET"
    EMERGENCY = "EMERGENCY"
    RECOVERY_ACK = "RECOVERY_ACK"


@dataclass
class RiskStateMachine:
    state: RiskState = RiskState.IDLE
    emergency_latched: bool = False
    history: list[tuple[str, str]] = field(default_factory=list)

    def transition(self, event: RiskEvent) -> RiskState:
        if not isinstance(event, RiskEvent):
            raise ValueError("unknown risk event; fail closed")
        if self.emergency_latched and event is not RiskEvent.RECOVERY_ACK:
            self.history.append((event.value, "blocked_emergency_latch"))
            return self.state
        if event is RiskEvent.EMERGENCY:
            self.emergency_latched = True
            self.state = RiskState.EMERGENCY_UNWIND
        elif event is RiskEvent.RECOVERY_ACK and self.emergency_latched:
            self.emergency_latched = False
            self.state = RiskState.IDLE
        elif event is RiskEvent.PLAN and self.state is RiskState.IDLE:
            self.state = RiskState.EXECUTION_PLANNING
        elif event is RiskEvent.ROUTE and self.state is RiskState.EXECUTION_PLANNING:
            self.state = RiskState.OPTIMAL_ROUTING
        elif event is RiskEvent.OVERTRADING:
            self.state = RiskState.OVERTRADING_LOCKED
        elif event is RiskEvent.RESET and self.state is not RiskState.EMERGENCY_UNWIND:
            self.state = RiskState.IDLE
        self.history.append((event.value, self.state.value))
        return self.state


def _project_capped_simplex(values: Sequence[float], caps: Sequence[float], target: float) -> tuple[float, ...]:
    """Euclidean projection onto {x: 0<=x_i<=cap_i, sum x=target}."""
    if len(values) != len(caps) or not values:
        raise ValueError("values and caps must be nonempty and same length")
    if target < -1e-10 or target > sum(caps) + 1e-8:
        raise ValueError("target quantity is infeasible under capacity caps")
    target = min(sum(caps), max(0.0, target))
    if target == 0:
        return tuple(0.0 for _ in values)
    if abs(target - sum(caps)) < 1e-10:
        return tuple(float(c) for c in caps)
    lo = min(v - c for v, c in zip(values, caps)) - abs(target) - 1.0
    hi = max(values) + abs(target) + 1.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        total = sum(min(c, max(0.0, v - mid)) for v, c in zip(values, caps))
        if total > target:
            lo = mid
        else:
            hi = mid
    threshold = 0.5 * (lo + hi)
    out = tuple(min(c, max(0.0, v - threshold)) for v, c in zip(values, caps))
    # Correct tiny floating-point residue on an available coordinate.
    residue = target - sum(out)
    if abs(residue) > 1e-8:
        for i, (x, cap) in enumerate(zip(out, caps)):
            candidate = min(cap, max(0.0, x + residue))
            delta = candidate - x
            if abs(delta) > 0:
                lst = list(out)
                lst[i] = candidate
                out = tuple(lst)
                residue -= delta
                if abs(residue) <= 1e-8:
                    break
    return out


@dataclass(frozen=True)
class ExecutionConfig:
    temporary_impact_coeff: float = 0.02
    cubic_impact_coeff: float = 0.002
    permanent_impact_coeff: float = 0.0005
    risk_aversion: float = 0.05
    price_variance_per_step: float = 0.0004
    buy_participation: float = 0.30
    sell_participation: float = 0.20
    sell_impact_multiplier: float = 1.25
    slippage_bps: float = 2.0
    dislocation: float = 0.0
    kappa_dislocation: float = 4.0
    max_iterations: int = 1500
    tolerance: float = 1e-8

    def validate(self) -> None:
        nonnegative = ("temporary_impact_coeff", "cubic_impact_coeff", "permanent_impact_coeff", "risk_aversion", "price_variance_per_step", "slippage_bps", "dislocation", "kappa_dislocation", "tolerance")
        for name in nonnegative:
            v = _finite(getattr(self, name), name)
            if v < 0:
                raise ValueError(f"{name} must be nonnegative")
        for name in ("buy_participation", "sell_participation"):
            v = _finite(getattr(self, name), name)
            if not 0 < v <= 1:
                raise ValueError(f"{name} must be in (0,1]")
        sell_multiplier = _finite(self.sell_impact_multiplier, "sell_impact_multiplier")
        if sell_multiplier < 1:
            raise ValueError("sell_impact_multiplier must be >= 1 under conservative sell policy")
        if not isinstance(self.max_iterations, int) or self.max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")
        if self.dislocation > 1:
            raise ValueError("dislocation must lie in [0,1]")


@dataclass(frozen=True)
class ExecutionPlan:
    side: Side
    requested_lots: float
    lot_size: int
    scheduled_lots: tuple[float, ...]
    effective_capacities_lots: tuple[float, ...]
    expected_temporary_impact: float
    expected_permanent_impact: float
    expected_risk_cost: float
    expected_statutory_fees: float
    expected_slippage: float
    expected_price_drift_cost: float
    expected_total_cost: float
    objective_value: float
    iterations: int
    feasible: bool


def optimize_execution_schedule(
    *, total_lots: float,
    lot_size: int,
    premiums_by_step: Sequence[float],
    displayed_capacity_lots: Sequence[float],
    side: Side | str,
    config: ExecutionConfig = ExecutionConfig(),
    fee_config: FeeConfig = FeeConfig(),
) -> ExecutionPlan:
    """Solve a small convex AC-style schedule with projected gradient descent.

    Output is a continuous lot-equivalent research schedule. It is not rounded
    to exchange lots and is not an executable order instruction. Capacity is
    reduced on sells by configurable conservative policy. Taxes are linear in
    premium turnover; taxes alone do not mathematically alter the optimum when
    prices/capacities are identical, so sell-side participation/impact asymmetry
    is an explicit policy parameter rather than a claimed tax theorem.
    """
    config.validate()
    fee_config.validate()
    Q = _finite(total_lots, "total_lots")
    premiums = _finite_tuple(premiums_by_step, "premiums_by_step")
    capacities = _finite_tuple(displayed_capacity_lots, "displayed_capacity_lots")
    if Q <= 0 or not isinstance(lot_size, int) or lot_size < 1:
        raise ValueError("total_lots and lot_size must be positive")
    if len(premiums) != len(capacities) or not premiums:
        raise ValueError("premiums and capacities must have equal positive length")
    if any(p <= 0 for p in premiums) or any(c < 0 for c in capacities):
        raise ValueError("premiums must be positive; capacities nonnegative")
    try:
        s = Side(side)
    except ValueError as exc:
        raise ValueError("side must be BUY or SELL") from exc
    participation = config.buy_participation if s is Side.BUY else config.sell_participation
    eff_caps = tuple(c * participation for c in capacities)
    if sum(eff_caps) + 1e-9 < Q:
        raise ValueError("order is infeasible: total capacity is below requested lots")
    side_impact = 1.0 if s is Side.BUY else config.sell_impact_multiplier
    eta = config.temporary_impact_coeff * side_impact
    cubic = config.cubic_impact_coeff * side_impact
    spread_per_unit = (config.slippage_bps / 10000.0) * (1.0 + config.kappa_dislocation * config.dislocation)
    spread_per_lot = tuple(spread_per_unit * p * lot_size for p in premiums)
    reference_premium = premiums[0]
    price_drift_per_lot = tuple(
        ((p - reference_premium) if s is Side.BUY else (reference_premium - p)) * lot_size
        for p in premiums
    )
    fee_per_lot = []
    for p, sl in zip(premiums, spread_per_lot):
        fee = statutory_friction(premium=p, lots=1.0, lot_size=lot_size, side=s, config=fee_config, slippage_per_unit=sl / lot_size)
        # Brokerage is per child order, not per lot; keep it out of the linear gradient.
        fixed_brokerage_gst = (fee_config.brokerage_per_order * fee_config.gst_rate
                               if fee_config.gst_on_exchange_sebi_brokerage else 0.0)
        fee_per_lot.append(fee.total_friction - fee.brokerage - fixed_brokerage_gst)
    n = len(premiums)
    caps_safe = tuple(max(c, 1e-12) for c in eff_caps)
    # Conservative fixed step from an upper bound on the gradient Lipschitz scale.
    active_curvatures = [2 * eta / c + 6 * cubic * Q / (c * c)
                         for c in caps_safe if c > 1e-12]
    max_curvature = max(active_curvatures, default=0.0)
    risk_curvature = 2 * config.risk_aversion * config.price_variance_per_step * n * n
    step_size = 0.25 / max(1e-9, max_curvature + risk_curvature)
    x = _project_capped_simplex([Q / n] * n, eff_caps, Q)

    def components(schedule: Sequence[float]) -> tuple[float, float, float, float, float, float]:
        temp = sum(eta * z * z / c + cubic * z ** 3 / (c * c) for z, c in zip(schedule, caps_safe))
        remain = Q
        risk = 0.0
        for z in schedule:
            remain -= z
            risk += config.risk_aversion * config.price_variance_per_step * remain * remain
        fees = 0.0
        slip = 0.0
        for z, p, premium in zip(schedule, premiums, premiums):
            f = statutory_friction(premium=premium, lots=z, lot_size=lot_size, side=s, config=fee_config,
                                   slippage_per_unit=spread_per_unit * premium)
            fees += f.stt + f.exchange_charge + f.sebi_fee + f.gst + f.stamp_duty + f.brokerage
            slip += f.slippage
        perm = config.permanent_impact_coeff * side_impact * Q * Q
        price_drift = sum(z * drift for z, drift in zip(schedule, price_drift_per_lot))
        return temp, perm, risk, fees, slip, price_drift

    it = 0
    for it in range(1, config.max_iterations + 1):
        remain_after = []
        remain = Q
        for z in x:
            remain -= z
            remain_after.append(remain)
        grad = []
        for i, z in enumerate(x):
            temp_grad = 2 * eta * z / caps_safe[i] + 3 * cubic * z * z / (caps_safe[i] ** 2)
            risk_grad = -2 * config.risk_aversion * config.price_variance_per_step * sum(remain_after[i:])
            grad.append(temp_grad + risk_grad + fee_per_lot[i] + price_drift_per_lot[i])
        next_x = _project_capped_simplex([z - step_size * g for z, g in zip(x, grad)], eff_caps, Q)
        delta = max(abs(a - b) for a, b in zip(next_x, x))
        x = next_x
        if delta < config.tolerance:
            break

    temp, perm, risk, fees, slip, price_drift = components(x)
    total_cost = temp + perm + risk + fees + slip + price_drift
    return ExecutionPlan(
        side=s, requested_lots=Q, lot_size=lot_size, scheduled_lots=tuple(x),
        effective_capacities_lots=eff_caps, expected_temporary_impact=temp,
        expected_permanent_impact=perm, expected_risk_cost=risk,
        expected_statutory_fees=fees, expected_slippage=slip, expected_price_drift_cost=price_drift,
        expected_total_cost=total_cost, objective_value=total_cost,
        iterations=it, feasible=abs(sum(x) - Q) < 1e-6 and all(-1e-8 <= z <= c + 1e-8 for z, c in zip(x, eff_caps)),
    )


@dataclass
class SessionController:
    """Integrates frequency optimization, tilt lockout, and state transitions."""
    frequency_optimizer: TradeFrequencyOptimizer
    tilt_guard: BehavioralTiltGuard = field(default_factory=BehavioralTiltGuard)
    risk_machine: RiskStateMachine = field(default_factory=RiskStateMachine)
    daily_trades: int = 0
    overtrading_throttle_active: bool = False

    @property
    def optimal_daily_trades(self) -> int:
        return self.frequency_optimizer.optimize().optimal_count

    def can_enter(self, now_seconds: float, expected_alpha: float, friction: FeeBreakdown) -> bool:
        if (self.risk_machine.emergency_latched or self.overtrading_throttle_active
                or self.risk_machine.state in (RiskState.OVERTRADING_LOCKED, RiskState.EMERGENCY_UNWIND)):
            return False
        if self.tilt_guard.is_locked(now_seconds):
            return False
        if self.daily_trades >= self.optimal_daily_trades:
            self.overtrading_throttle_active = True
            self.risk_machine.transition(RiskEvent.OVERTRADING)
            return False
        return profitability_gate(expected_alpha, friction)

    def record_trade(self, *, now_seconds: float, size: float, pnl: float) -> tuple[TiltReason, ...]:
        self.daily_trades += 1
        return self.tilt_guard.record_trade(now_seconds=now_seconds, size=size, pnl=pnl)

    def reset_session(self) -> None:
        if self.risk_machine.emergency_latched:
            raise RuntimeError("cannot reset session while emergency is latched")
        self.daily_trades = 0
        self.overtrading_throttle_active = False
        self.tilt_guard.loss_streak = 0
        self.tilt_guard.previous_size = None
        self.tilt_guard.last_trade_time = None
        self.tilt_guard.lockout_until = 0.0
        self.tilt_guard.reasons.clear()
        self.risk_machine.transition(RiskEvent.RESET)


def dispatch_live_order(*args: object, **kwargs: object) -> None:
    """A deliberate fail-closed stub: this package never submits real orders."""
    raise RuntimeError("live order dispatch is permanently disabled; simulation only")

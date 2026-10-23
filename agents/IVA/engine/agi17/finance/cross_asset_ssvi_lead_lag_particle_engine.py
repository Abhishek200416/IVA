"""Cycle 35: cross-asset volatility surfaces and Hawkes-aware execution research engine.

Offline/paper simulation only. The module has no broker adapter or live-order path.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import random
import threading
import time
from typing import Any, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

LIVE_ORDER_DISPATCH_ENABLED = False


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Fail-closed barrier preventing live order submission under all circumstances."""
    raise RuntimeError("live order dispatch is permanently disabled; LIVE_ORDER_DISPATCH_ENABLED = False")


IST = ZoneInfo("Asia/Kolkata")
CRORE = 10_000_000.0


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _finite_vector(values: Sequence[float], name: str) -> list[float]:
    out = [_finite(v, name) for v in values]
    return out


def _normal_pdf_log(x: float, mean: float, sd: float) -> float:
    if sd <= 0 or not math.isfinite(sd):
        raise ValueError("sd must be finite and positive")
    z = (x - mean) / sd
    return -0.5 * z * z - math.log(sd) - 0.5 * math.log(2.0 * math.pi)


def _clamp(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))


def _matrix_square(matrix: Sequence[Sequence[float]], name: str) -> list[list[float]]:
    a = [_finite_vector(row, name) for row in matrix]
    if not a or any(len(row) != len(a) for row in a):
        raise ValueError(f"{name} must be a non-empty square matrix")
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            if abs(a[i][j] - a[j][i]) > 1e-9:
                raise ValueError(f"{name} must be symmetric")
    return a


def _quadratic_form(x: Sequence[float], matrix: Sequence[Sequence[float]]) -> float:
    return sum(x[i] * sum(matrix[i][j] * x[j] for j in range(len(x))) for i in range(len(x)))


def _matvec(matrix: Sequence[Sequence[float]], x: Sequence[float]) -> list[float]:
    return [sum(row[j] * x[j] for j in range(len(x))) for row in matrix]


def _jacobi_eigenvalues(matrix: Sequence[Sequence[float]], tol: float = 1e-12, max_iter: int = 2000) -> list[float]:
    """Eigenvalue approximation for small real symmetric matrices, no NumPy required."""
    a = _matrix_square(matrix, "matrix")
    n = len(a)
    for _ in range(max_iter):
        p, q, largest = 0, 0, 0.0
        for i in range(n):
            for j in range(i + 1, n):
                if abs(a[i][j]) > largest:
                    p, q, largest = i, j, abs(a[i][j])
        if largest < tol:
            break
        if abs(a[p][q]) < tol:
            continue
        tau = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
        t = (1.0 if tau >= 0 else -1.0) / (abs(tau) + math.sqrt(1.0 + tau * tau))
        c = 1.0 / math.sqrt(1.0 + t * t)
        s = t * c
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        a[p][p] = app - t * apq
        a[q][q] = aqq + t * apq
        a[p][q] = a[q][p] = 0.0
        for k in range(n):
            if k not in (p, q):
                akp, akq = a[k][p], a[k][q]
                a[k][p] = a[p][k] = c * akp - s * akq
                a[k][q] = a[q][k] = s * akp + c * akq
    else:
        raise ValueError("eigenvalue iteration failed to converge")
    return sorted(a[i][i] for i in range(n))


class SpreadType(str, Enum):
    CALENDAR = "CALENDAR"
    DIAGONAL = "DIAGONAL"
    VERTICAL = "VERTICAL"
    IRON_CONDOR = "IRON_CONDOR"


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class MarketRegime(str, Enum):
    NORMAL_LIQUIDITY = "NORMAL_LIQUIDITY"
    VOLATILITY_EXPANSION = "VOLATILITY_EXPANSION"
    LIQUIDITY_VACUUM = "LIQUIDITY_VACUUM"


class RiskState(str, Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    LOCKED = "LOCKED"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


# ---------------------------------------------------------------------------
# SSVI / volatility surfaces
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SSVIParams:
    """A SSVI-like total-variance slice using the parameterization in Cycle 35."""
    theta: float
    rho: float
    phi: float
    psi: float = 0.0

    def __post_init__(self) -> None:
        for name in ("theta", "rho", "phi", "psi"):
            _finite(getattr(self, name), name)
        if self.theta <= 0:
            raise ValueError("theta must be positive")
        if not -1.0 < self.rho < 1.0:
            raise ValueError("rho must be strictly between -1 and 1")
        if self.phi <= 0:
            raise ValueError("phi must be positive")
        if self.wing_slope_max >= 2.0:
            raise ValueError("wing slope b*(1+abs(rho)) must be < 2")

    @property
    def b(self) -> float:
        return self.theta * self.phi

    @property
    def wing_slope_max(self) -> float:
        return self.b * (1.0 + abs(self.rho))

    def total_variance(self, k: float) -> float:
        k = _finite(k, "log_moneyness")
        inner = self.phi * k + self.psi
        value = self.theta * (
            1.0 + self.rho * self.phi * k + math.sqrt(inner * inner + 1.0 - self.rho * self.rho)
        )
        if value <= 0 or not math.isfinite(value):
            raise ValueError("surface produced non-positive or non-finite total variance")
        return value

    def implied_volatility(self, k: float, expiry_years: float) -> float:
        expiry_years = _finite(expiry_years, "expiry_years")
        if expiry_years <= 0:
            raise ValueError("expiry_years must be positive")
        return math.sqrt(self.total_variance(k) / expiry_years)

    def first_derivative(self, k: float, h: float = 1e-4) -> float:
        if h <= 0:
            raise ValueError("h must be positive")
        return (self.total_variance(k + h) - self.total_variance(k - h)) / (2.0 * h)

    def second_derivative(self, k: float, h: float = 1e-4) -> float:
        if h <= 0:
            raise ValueError("h must be positive")
        return (self.total_variance(k + h) - 2.0 * self.total_variance(k) + self.total_variance(k - h)) / (h * h)

    def butterfly_g(self, k: float, h: float = 1e-4) -> float:
        """Sampled Gatheral-style density condition; finite differences are diagnostic."""
        w = self.total_variance(k)
        wp = self.first_derivative(k, h)
        wpp = self.second_derivative(k, h)
        g = (1.0 - k * wp / (2.0 * w)) ** 2 - (wp * wp / 4.0) * (1.0 / w + 0.25) + 0.5 * wpp
        return g

    def butterfly_nonnegative(self, strikes: Sequence[float], tolerance: float = 1e-7) -> bool:
        if tolerance < 0:
            raise ValueError("tolerance cannot be negative")
        return all(self.butterfly_g(k) >= -tolerance for k in strikes)


@dataclass(frozen=True)
class SurfaceSlice:
    expiry_years: float
    params: SSVIParams

    def __post_init__(self) -> None:
        _finite(self.expiry_years, "expiry_years")
        if self.expiry_years <= 0:
            raise ValueError("expiry_years must be positive")


@dataclass
class VolatilitySurface:
    name: str
    slices: Sequence[SurfaceSlice]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("surface name cannot be empty")
        if len(self.slices) < 1:
            raise ValueError("surface requires at least one slice")
        self.slices = tuple(sorted(self.slices, key=lambda s: s.expiry_years))
        times = [s.expiry_years for s in self.slices]
        if len(set(times)) != len(times):
            raise ValueError("surface expiries must be unique")

    @property
    def expiries(self) -> tuple[float, ...]:
        return tuple(s.expiry_years for s in self.slices)

    def _bracket(self, expiry_years: float) -> tuple[SurfaceSlice, SurfaceSlice, float]:
        expiry_years = _finite(expiry_years, "expiry_years")
        if expiry_years <= 0:
            raise ValueError("expiry_years must be positive")
        if expiry_years <= self.slices[0].expiry_years:
            return self.slices[0], self.slices[0], 0.0
        if expiry_years >= self.slices[-1].expiry_years:
            return self.slices[-1], self.slices[-1], 0.0
        for left, right in zip(self.slices, self.slices[1:]):
            if left.expiry_years <= expiry_years <= right.expiry_years:
                weight = (expiry_years - left.expiry_years) / (right.expiry_years - left.expiry_years)
                return left, right, weight
        raise RuntimeError("expiry bracket not found")

    def total_variance(self, k: float, expiry_years: float) -> float:
        left, right, alpha = self._bracket(expiry_years)
        wl = left.params.total_variance(k)
        if left is right:
            return wl
        wr = right.params.total_variance(k)
        return (1.0 - alpha) * wl + alpha * wr

    def implied_volatility(self, k: float, expiry_years: float) -> float:
        return math.sqrt(self.total_variance(k, expiry_years) / expiry_years)

    def calendar_violations(self, strikes: Sequence[float], tolerance: float = 1e-10) -> tuple[tuple[float, float, float, float], ...]:
        if tolerance < 0:
            raise ValueError("tolerance cannot be negative")
        out = []
        for left, right in zip(self.slices, self.slices[1:]):
            for k in strikes:
                wl, wr = left.params.total_variance(k), right.params.total_variance(k)
                if wr + tolerance < wl:
                    out.append((left.expiry_years, right.expiry_years, float(k), wr - wl))
        return tuple(out)

    def assert_calendar_no_arbitrage(self, strikes: Sequence[float], tolerance: float = 1e-10) -> None:
        violations = self.calendar_violations(strikes, tolerance)
        if violations:
            raise ValueError(f"calendar total-variance monotonicity violated at {len(violations)} grid points")

    def butterfly_violations(self, strikes: Sequence[float], tolerance: float = 1e-7) -> tuple[tuple[float, float, float], ...]:
        out = []
        for surface_slice in self.slices:
            for k in strikes:
                g = surface_slice.params.butterfly_g(k)
                if g < -tolerance:
                    out.append((surface_slice.expiry_years, float(k), g))
        return tuple(out)

    def sampled_no_arbitrage(self, strikes: Sequence[float], calendar_tolerance: float = 1e-10,
                             butterfly_tolerance: float = 1e-7) -> dict[str, Any]:
        cal = self.calendar_violations(strikes, calendar_tolerance)
        bfly = self.butterfly_violations(strikes, butterfly_tolerance)
        return {"calendar_ok": not cal, "butterfly_ok": not bfly,
                "calendar_violations": len(cal), "butterfly_violations": len(bfly),
                "sampled_only": True}


def cross_asset_smile_basis(nifty: VolatilitySurface, banknifty: VolatilitySurface,
                            beta_vol: float, strikes: Sequence[float], expiry_years: float) -> tuple[float, ...]:
    beta_vol = _finite(beta_vol, "beta_vol")
    return tuple(banknifty.implied_volatility(k, expiry_years) - beta_vol * nifty.implied_volatility(k, expiry_years)
                 for k in strikes)


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_price(spot: float, strike: float, expiry_years: float, volatility: float,
                        is_call: bool = True, rate: float = 0.0) -> float:
    spot, strike, expiry_years, volatility, rate = map(float, (spot, strike, expiry_years, volatility, rate))
    if not all(math.isfinite(v) for v in (spot, strike, expiry_years, volatility, rate)):
        raise ValueError("pricing inputs must be finite")
    if spot <= 0 or strike <= 0 or expiry_years < 0 or volatility < 0:
        raise ValueError("invalid pricing inputs")
    if expiry_years == 0 or volatility == 0:
        intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
        return intrinsic if expiry_years == 0 else max((spot - strike * math.exp(-rate * expiry_years)) if is_call else (strike * math.exp(-rate * expiry_years) - spot), 0.0)
    sqrt_t = math.sqrt(expiry_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility * volatility) * expiry_years) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t
    if is_call:
        return spot * normal_cdf(d1) - strike * math.exp(-rate * expiry_years) * normal_cdf(d2)
    return strike * math.exp(-rate * expiry_years) * normal_cdf(-d2) - spot * normal_cdf(-d1)


# ---------------------------------------------------------------------------
# Statutory friction and profitability gating
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OptionLeg:
    side: TradeSide | str
    premium: float
    quantity: float
    brokerage: float = 0.0
    half_spread_per_unit: float = 0.0
    impact_per_unit: float = 0.0
    label: str = ""

    def __post_init__(self) -> None:
        side = self.side.value if isinstance(self.side, TradeSide) else str(self.side).upper()
        if side not in (TradeSide.BUY.value, TradeSide.SELL.value):
            raise ValueError("side must be BUY or SELL")
        object.__setattr__(self, "side", TradeSide(side))
        for name in ("premium", "quantity", "brokerage", "half_spread_per_unit", "impact_per_unit"):
            _finite(getattr(self, name), name)
        if self.premium < 0 or self.quantity < 0 or self.brokerage < 0 or self.half_spread_per_unit < 0 or self.impact_per_unit < 0:
            raise ValueError("premium, quantity, brokerage, spread, and impact must be nonnegative")

    @property
    def turnover(self) -> float:
        return self.premium * self.quantity


@dataclass(frozen=True)
class FeeBreakdown:
    buy_turnover: float
    sell_turnover: float
    total_turnover: float
    stt: float
    stamp_duty: float
    exchange_fee: float
    sebi_fee: float
    brokerage: float
    gst: float
    slippage: float
    impact: float
    total_statutory: float
    total_friction: float


@dataclass(frozen=True)
class StatutoryFeeConfig:
    options_sell_stt: float = 0.0015
    options_buy_stamp_duty: float = 0.00003
    exchange_per_crore: float = 3553.0
    sebi_per_crore: float = 10.0
    gst_rate: float = 0.18

    def __post_init__(self) -> None:
        for name in ("options_sell_stt", "options_buy_stamp_duty", "exchange_per_crore", "sebi_per_crore", "gst_rate"):
            val = _finite(getattr(self, name), name)
            if val < 0:
                raise ValueError(f"{name} cannot be negative")


class MultiLegFeeCalculator:
    def __init__(self, config: StatutoryFeeConfig = StatutoryFeeConfig()) -> None:
        self.config = config

    def calculate(self, legs: Sequence[OptionLeg]) -> FeeBreakdown:
        if not legs:
            raise ValueError("at least one option leg is required")
        buy_turnover = sum(leg.turnover for leg in legs if leg.side is TradeSide.BUY)
        sell_turnover = sum(leg.turnover for leg in legs if leg.side is TradeSide.SELL)
        total_turnover = buy_turnover + sell_turnover
        stt = sell_turnover * self.config.options_sell_stt
        stamp = buy_turnover * self.config.options_buy_stamp_duty
        exchange = total_turnover * self.config.exchange_per_crore / CRORE
        sebi = total_turnover * self.config.sebi_per_crore / CRORE
        brokerage = sum(leg.brokerage for leg in legs)
        gst = (exchange + sebi + brokerage) * self.config.gst_rate
        slippage = sum(leg.half_spread_per_unit * leg.quantity for leg in legs)
        impact = sum(leg.impact_per_unit * leg.quantity for leg in legs)
        statutory = stt + stamp + exchange + sebi + gst + brokerage
        return FeeBreakdown(buy_turnover, sell_turnover, total_turnover, stt, stamp, exchange,
                            sebi, brokerage, gst, slippage, impact, statutory, statutory + slippage + impact)


@dataclass(frozen=True)
class ProfitabilityResult:
    expected_gross_alpha: float
    fees: FeeBreakdown
    additional_hurdle: float
    expected_net_alpha: float
    qualifies: bool
    rejection_reason: str


def evaluate_profitability(expected_gross_alpha: float, legs: Sequence[OptionLeg],
                           additional_hurdle: float = 0.0,
                           calculator: Optional[MultiLegFeeCalculator] = None) -> ProfitabilityResult:
    expected_gross_alpha = _finite(expected_gross_alpha, "expected_gross_alpha")
    additional_hurdle = _finite(additional_hurdle, "additional_hurdle")
    if additional_hurdle < 0:
        raise ValueError("additional_hurdle must be nonnegative")
    fees = (calculator or MultiLegFeeCalculator()).calculate(legs)
    net = expected_gross_alpha - fees.total_friction
    qualifies = net > additional_hurdle  # strict by specification
    reason = "PASS" if qualifies else "NET_ALPHA_NOT_ABOVE_HURDLE"
    return ProfitabilityResult(expected_gross_alpha, fees, additional_hurdle, net, qualifies, reason)


@dataclass(frozen=True)
class SurfaceOptionLeg:
    """A marked option leg used to price a calendar/diagonal/vertical/condor."""
    surface_name: str
    side: TradeSide | str
    strike: float
    expiry_years: float
    is_call: bool
    market_premium: float
    quantity: float
    brokerage: float = 0.0
    half_spread_per_unit: float = 0.0
    impact_per_unit: float = 0.0
    label: str = ""

    def __post_init__(self) -> None:
        if not self.surface_name:
            raise ValueError("surface_name is required")
        side = self.side.value if isinstance(self.side, TradeSide) else str(self.side).upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        object.__setattr__(self, "side", TradeSide(side))
        for name in ("strike", "expiry_years", "market_premium", "quantity", "brokerage", "half_spread_per_unit", "impact_per_unit"):
            _finite(getattr(self, name), name)
        if self.strike <= 0 or self.expiry_years <= 0 or self.market_premium < 0 or self.quantity < 0:
            raise ValueError("strike/expiry must be positive; premium/quantity nonnegative")
        if min(self.brokerage, self.half_spread_per_unit, self.impact_per_unit) < 0:
            raise ValueError("brokerage, spread and impact must be nonnegative")


@dataclass(frozen=True)
class SurfaceSpreadAnalysis:
    structure: SpreadType
    fair_premiums: tuple[float, ...]
    market_premiums: tuple[float, ...]
    gross_model_alpha: float
    profitability: ProfitabilityResult
    surface_no_arbitrage_ok: bool
    surface_diagnostics: Mapping[str, Mapping[str, Any]]


class SurfaceSpreadAnalyzer:
    """Prices marked option legs from supplied surfaces and applies all modeled costs.

    The model-implied edge is a relative-value mark, not a realized or statistically
    forecast return. Users must supply coherent market marks and calibrated surfaces.
    """
    DEFAULT_LOG_MONEYNESS_GRID = tuple(i / 4.0 for i in range(-8, 9))

    def __init__(self, fee_calculator: Optional[MultiLegFeeCalculator] = None) -> None:
        self.fee_calculator = fee_calculator or MultiLegFeeCalculator()

    def analyze(self, structure: SpreadType | str, surfaces: Mapping[str, VolatilitySurface],
                spots: Mapping[str, float], legs: Sequence[SurfaceOptionLeg],
                additional_hurdle: float = 0.0, check_sampled_arbitrage: bool = True) -> SurfaceSpreadAnalysis:
        structure_value = structure if isinstance(structure, SpreadType) else SpreadType(str(structure).upper())
        if len(legs) < 2:
            raise ValueError("a spread requires at least two legs")
        if _finite(additional_hurdle, "additional_hurdle") < 0:
            raise ValueError("additional_hurdle must be nonnegative")
        diagnostics: dict[str, Mapping[str, Any]] = {}
        used_surfaces = {leg.surface_name for leg in legs}
        for name in used_surfaces:
            if name not in surfaces:
                raise ValueError(f"surface {name!r} was not supplied")
            if check_sampled_arbitrage:
                diag = surfaces[name].sampled_no_arbitrage(self.DEFAULT_LOG_MONEYNESS_GRID)
                diagnostics[name] = diag
            else:
                diagnostics[name] = {"calendar_ok": True, "butterfly_ok": True, "sampled_only": False}
        noarb_ok = all(bool(d.get("calendar_ok")) and bool(d.get("butterfly_ok")) for d in diagnostics.values())
        fair, market, model_alpha, fee_legs = [], [], 0.0, []
        for leg in legs:
            if leg.surface_name not in spots:
                raise ValueError(f"spot for {leg.surface_name!r} was not supplied")
            spot = _finite(spots[leg.surface_name], "spot")
            if spot <= 0:
                raise ValueError("spot must be positive")
            surface = surfaces[leg.surface_name]
            k = math.log(leg.strike / spot)
            iv = surface.implied_volatility(k, leg.expiry_years)
            fair_premium = black_scholes_price(spot, leg.strike, leg.expiry_years, iv, leg.is_call)
            fair.append(fair_premium)
            market.append(leg.market_premium)
            sign = 1.0 if leg.side is TradeSide.BUY else -1.0
            model_alpha += sign * (fair_premium - leg.market_premium) * leg.quantity
            fee_legs.append(OptionLeg(leg.side, leg.market_premium, leg.quantity, leg.brokerage,
                                      leg.half_spread_per_unit, leg.impact_per_unit, leg.label))
        profit = evaluate_profitability(model_alpha, fee_legs, additional_hurdle, self.fee_calculator)
        if not noarb_ok:
            profit = ProfitabilityResult(profit.expected_gross_alpha, profit.fees, profit.additional_hurdle,
                                         profit.expected_net_alpha, False, "SURFACE_NO_ARBITRAGE_DIAGNOSTIC_FAILED")
        return SurfaceSpreadAnalysis(structure_value, tuple(fair), tuple(market), model_alpha, profit, noarb_ok, diagnostics)

    def analyze_calendar(self, *args: Any, **kwargs: Any) -> SurfaceSpreadAnalysis:
        return self.analyze(SpreadType.CALENDAR, *args, **kwargs)

    def analyze_diagonal(self, *args: Any, **kwargs: Any) -> SurfaceSpreadAnalysis:
        return self.analyze(SpreadType.DIAGONAL, *args, **kwargs)


# ---------------------------------------------------------------------------
# Hawkes transient cross-impact and Almgren-Chriss execution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HawkesEvent:
    timestamp: float
    weight: float = 1.0
    source: str = ""

    def __post_init__(self) -> None:
        _finite(self.timestamp, "timestamp")
        _finite(self.weight, "weight")
        if self.weight < 0:
            raise ValueError("event weight must be nonnegative")


@dataclass
class HawkesCrossImpactModel:
    baseline_intensity: float = 0.2
    alpha: float = 0.8
    beta: float = 1.5
    eta: float = 0.02
    decay_rate: float = 2.0
    events: list[HawkesEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in ("baseline_intensity", "alpha", "beta", "eta", "decay_rate"):
            val = _finite(getattr(self, name), name)
            if val < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.beta <= 0 or self.decay_rate <= 0:
            raise ValueError("beta and decay_rate must be positive")

    def record_event(self, timestamp: float, weight: float = 1.0, source: str = "") -> None:
        event = HawkesEvent(timestamp, weight, source)
        if self.events and event.timestamp < self.events[-1].timestamp:
            raise ValueError("Hawkes event timestamps must be nondecreasing")
        self.events.append(event)

    def intensity(self, now: float, source: Optional[str] = None) -> float:
        now = _finite(now, "now")
        total = self.baseline_intensity
        for event in self.events:
            if event.timestamp <= now and (source is None or event.source == source):
                total += self.alpha * event.weight * math.exp(-self.beta * (now - event.timestamp))
        return total

    def transient_kernel(self, elapsed: float, now: Optional[float] = None) -> float:
        elapsed = _finite(elapsed, "elapsed")
        if elapsed < 0:
            raise ValueError("elapsed must be nonnegative")
        base = self.eta * math.exp(-self.decay_rate * elapsed)
        if now is None:
            return base
        return base * (1.0 + self.intensity(now))


@dataclass(frozen=True)
class LeadLagSignal:
    score: float
    lag_seconds: float
    expected_drift_per_second: float
    source: str = ""

    def __post_init__(self) -> None:
        _finite(self.score, "score")
        _finite(self.lag_seconds, "lag_seconds")
        _finite(self.expected_drift_per_second, "expected_drift_per_second")
        if not 0.05 <= self.lag_seconds <= 0.5:
            raise ValueError("lead-lag latency must lie in [0.05, 0.5] seconds")

    def drift(self) -> float:
        return self.expected_drift_per_second * _clamp(self.score, -1.0, 1.0) * math.exp(-self.lag_seconds / 0.25)


@dataclass(frozen=True)
class ExecutionPlan:
    inventory_path: tuple[float, ...]
    child_quantities: tuple[float, ...]
    interval_temporary_costs: tuple[float, ...]
    expected_impact_cost: float
    inventory_risk_cost: float
    signal_cost_adjustment: float
    objective_value: float
    effective_intensity: tuple[float, ...]


def _solve_tridiagonal(lower: Sequence[float], diagonal: Sequence[float], upper: Sequence[float], rhs: Sequence[float]) -> list[float]:
    n = len(diagonal)
    if not (len(lower) == len(upper) == len(rhs) == n):
        raise ValueError("tridiagonal arrays must have identical lengths")
    if n == 0:
        return []
    b = list(map(float, diagonal))
    d = list(map(float, rhs))
    u = list(map(float, upper))
    l = list(map(float, lower))
    for i in range(n):
        if abs(b[i]) < 1e-15:
            raise ValueError("singular tridiagonal system")
        if i > 0:
            factor = l[i] / b[i - 1]
            b[i] -= factor * u[i - 1]
            d[i] -= factor * d[i - 1]
    if abs(b[-1]) < 1e-15:
        raise ValueError("singular tridiagonal system")
    out = [0.0] * n
    out[-1] = d[-1] / b[-1]
    for i in range(n - 2, -1, -1):
        if abs(b[i]) < 1e-15:
            raise ValueError("singular tridiagonal system")
        out[i] = (d[i] - u[i] * out[i + 1]) / b[i]
    return out


class AlmgrenChrissPlanner:
    """Discrete convex AC planner with Hawkes-modulated temporary/cross impact.

    It solves the tridiagonal first-order conditions for an objective containing
    temporary impact, inventory variance risk, and a lead-lag drift linear term.
    A monotone feasibility projection is applied to keep remaining inventory in [0,Q].
    """
    def plan(self, quantity: float, horizon_seconds: float, steps: int, side: TradeSide | str,
             volatility: float, risk_aversion: float, temporary_impact: float,
             cross_impact_coefficient: float, hawkes: HawkesCrossImpactModel,
             signal: Optional[LeadLagSignal] = None, start_time: float = 0.0) -> ExecutionPlan:
        values = [quantity, horizon_seconds, volatility, risk_aversion, temporary_impact,
                  cross_impact_coefficient, start_time]
        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError("execution parameters must be finite")
        side_val = side.value if isinstance(side, TradeSide) else str(side).upper()
        if side_val not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if quantity < 0 or horizon_seconds <= 0 or steps < 1 or volatility < 0 or risk_aversion < 0:
            raise ValueError("invalid quantity, horizon, steps, volatility, or risk aversion")
        if temporary_impact <= 0 or cross_impact_coefficient < 0:
            raise ValueError("temporary impact must be positive and cross-impact coefficient nonnegative")
        dt = horizon_seconds / steps
        side_sign = 1.0 if side_val == "BUY" else -1.0
        drift = signal.drift() if signal is not None else 0.0
        intensities, eta = [], []
        for i in range(1, steps + 1):
            t = start_time + i * dt
            lam = hawkes.intensity(t)
            intensities.append(lam)
            kernel = hawkes.transient_kernel(dt, t)
            eta.append(temporary_impact + cross_impact_coefficient * kernel)
        if steps == 1:
            path = [float(quantity), 0.0]
        else:
            n = steps - 1
            lower = [0.0] * n
            diagonal = [0.0] * n
            upper = [0.0] * n
            rhs = [0.0] * n
            risk_coeff = risk_aversion * volatility * volatility * dt
            # Objective: sum_i eta_i/dt * (x_i-x_{i-1})^2 + risk*x_i^2 + side*drift*dt*x_i.
            for j in range(1, steps):
                row = j - 1
                eta_left, eta_right = eta[j - 1], eta[j]
                diagonal[row] = eta_left / dt + eta_right / dt + risk_coeff
                if j > 1:
                    lower[row] = -eta_left / dt
                if j < steps - 1:
                    upper[row] = -eta_right / dt
                linear = side_sign * drift * dt
                rhs[row] = -0.5 * linear
                if j == 1:
                    rhs[row] += eta_left / dt * quantity
            interior = _solve_tridiagonal(lower, diagonal, upper, rhs)
            # Project unconstrained minimizer into a valid monotone remaining-inventory path.
            path_vals = [float(quantity)]
            current = float(quantity)
            for x in interior:
                current = _clamp(x, 0.0, current)
                path_vals.append(current)
            path_vals.append(0.0)
            path = path_vals
        children = [max(0.0, path[i] - path[i + 1]) for i in range(steps)]
        temporary_costs = [eta[i] / dt * children[i] * children[i] for i in range(steps)]
        inv_risk_cost = sum(risk_aversion * volatility * volatility * dt * path[i] ** 2 for i in range(steps))
        signal_adjustment = sum(side_sign * drift * dt * path[i] for i in range(steps))
        return ExecutionPlan(tuple(path), tuple(children), tuple(temporary_costs), sum(temporary_costs),
                             inv_risk_cost, signal_adjustment, sum(temporary_costs) + inv_risk_cost + signal_adjustment,
                             tuple(intensities))


# ---------------------------------------------------------------------------
# Sequential Monte Carlo particle filter
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MicrostructureObservation:
    absolute_return: float
    spread_ratio: float
    depth_ratio: float
    jump_count: int = 0

    def __post_init__(self) -> None:
        for name in ("absolute_return", "spread_ratio", "depth_ratio"):
            _finite(getattr(self, name), name)
        if self.absolute_return < 0 or self.spread_ratio <= 0 or self.depth_ratio < 0:
            raise ValueError("observation requires return>=0, spread>0, depth>=0")
        if isinstance(self.jump_count, bool) or int(self.jump_count) != self.jump_count or self.jump_count < 0:
            raise ValueError("jump_count must be a nonnegative integer")


@dataclass
class Particle:
    volatility: float
    jump_intensity: float
    beta_resilience: float
    regime: MarketRegime
    weight: float = 1.0


@dataclass(frozen=True)
class ParticleFilterResult:
    regime_probabilities: Mapping[str, float]
    classified_regime: MarketRegime
    effective_sample_size: float
    resampled: bool
    mean_volatility: float
    mean_jump_intensity: float
    mean_beta_resilience: float


class MultiRegimeParticleFilter:
    """Dependency-free SMC filter; model likelihood scales are configurable."""
    def __init__(self, particles: int = 200, seed: int = 35,
                 resample_fraction: float = 0.5) -> None:
        if particles < 100:
            raise ValueError("particle filter requires at least 100 particles")
        if not 0 < resample_fraction <= 1:
            raise ValueError("resample_fraction must be in (0,1]")
        self.count = particles
        self.resample_fraction = resample_fraction
        self.rng = random.Random(seed)
        self.particles: list[Particle] = []
        regimes = list(MarketRegime)
        for i in range(particles):
            regime = regimes[i % len(regimes)]
            v, j, b = self._sample_state(regime)
            self.particles.append(Particle(v, j, b, regime, 1.0 / particles))
        self.last_result: Optional[ParticleFilterResult] = None
        self.observations_seen = 0

    def _sample_state(self, regime: MarketRegime) -> tuple[float, float, float]:
        if regime is MarketRegime.NORMAL_LIQUIDITY:
            return self.rng.uniform(0.003, 0.016), self.rng.uniform(0.01, 0.25), self.rng.uniform(0.8, 3.0)
        if regime is MarketRegime.VOLATILITY_EXPANSION:
            return self.rng.uniform(0.015, 0.055), self.rng.uniform(0.2, 1.3), self.rng.uniform(0.45, 1.8)
        return self.rng.uniform(0.04, 0.13), self.rng.uniform(0.8, 3.0), self.rng.uniform(0.1, 0.9)

    def _transition(self, regime: MarketRegime) -> MarketRegime:
        r = self.rng.random()
        if regime is MarketRegime.NORMAL_LIQUIDITY:
            if r < 0.04:
                return MarketRegime.VOLATILITY_EXPANSION
            return regime
        if regime is MarketRegime.VOLATILITY_EXPANSION:
            if r < 0.08:
                return MarketRegime.LIQUIDITY_VACUUM
            if r < 0.18:
                return MarketRegime.NORMAL_LIQUIDITY
            return regime
        if r < 0.22:
            return MarketRegime.VOLATILITY_EXPANSION
        return regime

    @staticmethod
    def _poisson_loglik(count: int, rate: float) -> float:
        rate = max(rate, 1e-12)
        return count * math.log(rate) - rate - math.lgamma(count + 1.0)

    def _log_likelihood(self, particle: Particle, obs: MicrostructureObservation) -> float:
        expected_abs_return = max(particle.volatility * math.sqrt(2.0 / math.pi), 1e-5)
        return_sd = max(0.002, expected_abs_return * 0.65)
        regime_spread = {
            MarketRegime.NORMAL_LIQUIDITY: (1.0, 0.45),
            MarketRegime.VOLATILITY_EXPANSION: (1.7, 0.70),
            MarketRegime.LIQUIDITY_VACUUM: (4.0, 1.25),
        }[particle.regime]
        regime_depth = {
            MarketRegime.NORMAL_LIQUIDITY: (1.0, 0.32),
            MarketRegime.VOLATILITY_EXPANSION: (0.62, 0.27),
            MarketRegime.LIQUIDITY_VACUUM: (0.20, 0.17),
        }[particle.regime]
        return (
            _normal_pdf_log(obs.absolute_return, expected_abs_return, return_sd)
            + _normal_pdf_log(obs.spread_ratio, regime_spread[0], regime_spread[1])
            + _normal_pdf_log(obs.depth_ratio, regime_depth[0], regime_depth[1])
            + self._poisson_loglik(obs.jump_count, particle.jump_intensity)
        )

    def _systematic_resample(self) -> None:
        n = self.count
        cumulative = []
        total = 0.0
        for p in self.particles:
            total += p.weight
            cumulative.append(total)
        if total <= 0 or not math.isfinite(total):
            raise RuntimeError("particle weights are degenerate")
        cumulative = [c / total for c in cumulative]
        start = self.rng.random() / n
        new_particles: list[Particle] = []
        idx = 0
        for i in range(n):
            u = start + i / n
            while idx < n - 1 and u > cumulative[idx]:
                idx += 1
            p = self.particles[idx]
            new_particles.append(Particle(p.volatility, p.jump_intensity, p.beta_resilience, p.regime, 1.0 / n))
        self.particles = new_particles

    def update(self, observation: MicrostructureObservation) -> ParticleFilterResult:
        if not isinstance(observation, MicrostructureObservation):
            raise TypeError("observation must be MicrostructureObservation")
        # State transition and small parameter drift before observation weighting.
        for p in self.particles:
            p.regime = self._transition(p.regime)
            target_v, target_j, target_b = self._sample_state(p.regime)
            p.volatility = _clamp(0.9 * p.volatility + 0.1 * target_v, 0.001, 0.2)
            p.jump_intensity = _clamp(0.85 * p.jump_intensity + 0.15 * target_j, 1e-4, 5.0)
            p.beta_resilience = _clamp(0.9 * p.beta_resilience + 0.1 * target_b, 0.02, 8.0)
        log_weights = [math.log(max(p.weight, 1e-300)) + self._log_likelihood(p, observation) for p in self.particles]
        max_log = max(log_weights)
        weights = [math.exp(v - max_log) for v in log_weights]
        norm = sum(weights)
        if not math.isfinite(norm) or norm <= 0:
            weights = [1.0 / self.count] * self.count
        else:
            weights = [v / norm for v in weights]
        for p, w in zip(self.particles, weights):
            p.weight = w
        probs = {r.value: sum(p.weight for p in self.particles if p.regime is r) for r in MarketRegime}
        ess = 1.0 / sum(p.weight * p.weight for p in self.particles)
        mean_v = sum(p.weight * p.volatility for p in self.particles)
        mean_j = sum(p.weight * p.jump_intensity for p in self.particles)
        mean_b = sum(p.weight * p.beta_resilience for p in self.particles)
        resampled = ess < self.count * self.resample_fraction
        if resampled:
            self._systematic_resample()
        self.observations_seen += 1
        regime = MarketRegime(max(probs, key=probs.get))
        result = ParticleFilterResult(dict(probs), regime, ess, resampled, mean_v, mean_j, mean_b)
        self.last_result = result
        return result


# ---------------------------------------------------------------------------
# Anti-overtrading and safety controls
# ---------------------------------------------------------------------------

@dataclass
class AntiOvertradingThrottler:
    alpha: float
    cost_per_trade: float
    risk_per_trade: float
    daily_trade_cap: int = field(init=False)
    trades_today: int = 0
    consecutive_losses: int = 0
    cooldown_until: float = 0.0
    last_fill_timestamp: Optional[float] = None
    previous_fill_size: Optional[float] = None
    lockout_reason: str = ""

    def __post_init__(self) -> None:
        self.alpha, self.cost_per_trade, self.risk_per_trade = map(float, (self.alpha, self.cost_per_trade, self.risk_per_trade))
        if not all(math.isfinite(v) for v in (self.alpha, self.cost_per_trade, self.risk_per_trade)):
            raise ValueError("throttler inputs must be finite")
        if self.cost_per_trade < 0 or self.risk_per_trade <= 0:
            raise ValueError("cost must be nonnegative and risk positive")
        self.daily_trade_cap = self.optimal_daily_trade_cap(self.alpha, self.cost_per_trade, self.risk_per_trade)

    @staticmethod
    def optimal_daily_trade_cap(alpha: float, cost: float, risk: float) -> int:
        alpha, cost, risk = map(float, (alpha, cost, risk))
        if not all(math.isfinite(v) for v in (alpha, cost, risk)) or cost < 0 or risk <= 0:
            raise ValueError("invalid alpha/cost/risk")
        return max(0, int(math.floor((alpha - cost) / risk + 0.5)))

    def can_enter(self, now: Optional[float] = None) -> tuple[bool, str]:
        now = time.time() if now is None else _finite(now, "now")
        if now < self.cooldown_until:
            return False, self.lockout_reason or "COOLDOWN"
        if self.trades_today >= self.daily_trade_cap:
            return False, "DAILY_TRADE_CAP"
        return True, "PASS"

    def record_fill(self, timestamp: float, size: float, pnl: float) -> Optional[str]:
        timestamp, size, pnl = map(float, (timestamp, size, pnl))
        if not all(math.isfinite(v) for v in (timestamp, size, pnl)) or size <= 0:
            raise ValueError("fill timestamp/pnl must be finite and size positive")
        reason = None
        if self.last_fill_timestamp is not None and timestamp < self.last_fill_timestamp:
            raise ValueError("fill timestamps must be nondecreasing")
        if self.previous_fill_size is not None and size > self.previous_fill_size * 1.25:
            reason = "REVENGE_SIZING"
        elif self.last_fill_timestamp is not None and timestamp - self.last_fill_timestamp < 30.0:
            reason = "RAPID_PACING"
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
        if self.consecutive_losses >= 3:
            reason = "LOSS_STREAK"
        self.last_fill_timestamp = timestamp
        self.previous_fill_size = size
        self.trades_today += 1
        if reason:
            self.cooldown_until = max(self.cooldown_until, timestamp + 900.0)
            self.lockout_reason = reason
        return reason

    def reset_day(self) -> None:
        self.trades_today = 0
        self.consecutive_losses = 0
        self.last_fill_timestamp = None
        self.previous_fill_size = None
        if self.lockout_reason not in ("EMERGENCY_UNWIND",):
            self.cooldown_until = 0.0
            self.lockout_reason = ""

    def cooldown_remaining(self, now: Optional[float] = None) -> float:
        now = time.time() if now is None else _finite(now, "now")
        if not math.isfinite(self.cooldown_until):
            return math.inf
        return max(0.0, self.cooldown_until - now)


# ---------------------------------------------------------------------------
# Integrated orchestration + local telemetry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SurfaceBasisSnapshot:
    strikes: tuple[float, ...]
    basis: tuple[float, ...]
    max_abs_basis: float


class Cycle35Engine:
    def __init__(self, nifty_surface: Optional[VolatilitySurface] = None,
                 banknifty_surface: Optional[VolatilitySurface] = None,
                 particle_filter: Optional[MultiRegimeParticleFilter] = None,
                 hawkes: Optional[HawkesCrossImpactModel] = None,
                 throttler: Optional[AntiOvertradingThrottler] = None,
                 fee_calculator: Optional[MultiLegFeeCalculator] = None,
                 seed: int = 35) -> None:
        self.nifty_surface = nifty_surface or self._default_surface("NIFTY 50", [0.018, 0.028, 0.045], rho=-0.35)
        self.banknifty_surface = banknifty_surface or self._default_surface("BANKNIFTY", [0.022, 0.034, 0.055], rho=-0.45)
        self.particle_filter = particle_filter if particle_filter is not None else MultiRegimeParticleFilter(200, seed=seed)
        self.hawkes = hawkes if hawkes is not None else HawkesCrossImpactModel()
        self.throttler = throttler if throttler is not None else AntiOvertradingThrottler(100.0, 10.0, 5.0)
        self.fee_calculator = fee_calculator if fee_calculator is not None else MultiLegFeeCalculator()
        self.planner = AlmgrenChrissPlanner()
        self.risk_state = RiskState.NORMAL
        self.emergency_latched = False
        self.last_basis: Optional[SurfaceBasisSnapshot] = None
        self.last_execution: Optional[ExecutionPlan] = None
        self.last_profitability: Optional[ProfitabilityResult] = None
        self.last_observation: Optional[MicrostructureObservation] = None
        self.created_at = time.time()
        self.heartbeat = 0
        self._lock = threading.RLock()

    @staticmethod
    def _default_surface(name: str, thetas: Sequence[float], rho: float) -> VolatilitySurface:
        expiries = (0.05, 0.12, 0.25)
        slices = [SurfaceSlice(t, SSVIParams(theta, rho, phi=0.45, psi=0.0)) for t, theta in zip(expiries, thetas)]
        return VolatilitySurface(name, slices)

    def update_observation(self, observation: MicrostructureObservation) -> ParticleFilterResult:
        with self._lock:
            self.last_observation = observation
            result = self.particle_filter.update(observation)
            if result.classified_regime is MarketRegime.LIQUIDITY_VACUUM:
                self.risk_state = RiskState.CAUTION if not self.emergency_latched else RiskState.EMERGENCY_UNWIND
            elif self.risk_state is RiskState.CAUTION and not self.emergency_latched:
                self.risk_state = RiskState.NORMAL
            self.heartbeat += 1
            return result

    def surface_basis(self, strikes: Sequence[float], expiry_years: float, beta_vol: float = 1.0) -> SurfaceBasisSnapshot:
        with self._lock:
            basis = cross_asset_smile_basis(self.nifty_surface, self.banknifty_surface, beta_vol, strikes, expiry_years)
            result = SurfaceBasisSnapshot(tuple(float(k) for k in strikes), basis, max((abs(v) for v in basis), default=0.0))
            self.last_basis = result
            self.heartbeat += 1
            return result

    def record_hawkes_event(self, timestamp: float, weight: float = 1.0, source: str = "") -> float:
        with self._lock:
            self.hawkes.record_event(timestamp, weight, source)
            self.heartbeat += 1
            return self.hawkes.intensity(timestamp)

    def plan_execution(self, quantity: float, horizon_seconds: float, steps: int, side: TradeSide | str,
                       volatility: float, risk_aversion: float, temporary_impact: float,
                       cross_impact_coefficient: float, signal: Optional[LeadLagSignal] = None,
                       start_time: float = 0.0) -> ExecutionPlan:
        with self._lock:
            plan = self.planner.plan(quantity, horizon_seconds, steps, side, volatility, risk_aversion,
                                     temporary_impact, cross_impact_coefficient, self.hawkes, signal, start_time)
            self.last_execution = plan
            self.heartbeat += 1
            return plan

    def evaluate_spread(self, expected_gross_alpha: float, legs: Sequence[OptionLeg],
                        additional_hurdle: float = 0.0, now: Optional[float] = None) -> ProfitabilityResult:
        with self._lock:
            now = time.time() if now is None else _finite(now, "now")
            additional_hurdle = _finite(additional_hurdle, "additional_hurdle")
            if additional_hurdle < 0:
                raise ValueError("additional_hurdle must be nonnegative")
            if self.risk_state is RiskState.LOCKED and now >= self.throttler.cooldown_until and self.trades_available():
                self.risk_state = RiskState.NORMAL
                self.throttler.lockout_reason = ""
            can_enter, _reason = self.throttler.can_enter(now)
            fees = self.fee_calculator.calculate(legs)
            net = _finite(expected_gross_alpha, "expected_gross_alpha") - fees.total_friction
            qualifies = can_enter and not self.emergency_latched and net > additional_hurdle
            if not can_enter or self.emergency_latched or net <= additional_hurdle:
                # Preserve the diagnostic net estimate while keeping qualifies false; there is no order path.
                result = ProfitabilityResult(float(expected_gross_alpha), fees, float(additional_hurdle), net, False,
                                             "EMERGENCY_UNWIND" if self.emergency_latched else (_reason if not can_enter else "NET_ALPHA_NOT_ABOVE_HURDLE"))
            else:
                result = ProfitabilityResult(float(expected_gross_alpha), fees, float(additional_hurdle), net, True, "PASS")
            self.last_profitability = result
            self.heartbeat += 1
            return result

    def trades_available(self) -> bool:
        return self.throttler.trades_today < self.throttler.daily_trade_cap

    def record_fill(self, timestamp: float, size: float, pnl: float) -> Optional[str]:
        with self._lock:
            reason = self.throttler.record_fill(timestamp, size, pnl)
            if reason:
                self.risk_state = RiskState.LOCKED
            self.heartbeat += 1
            return reason

    def emergency_unwind(self) -> None:
        with self._lock:
            self.emergency_latched = True
            self.risk_state = RiskState.EMERGENCY_UNWIND
            self.throttler.lockout_reason = "EMERGENCY_UNWIND"
            self.throttler.cooldown_until = float("inf")
            self.heartbeat += 1

    def recovery_ack(self, verified: bool) -> bool:
        with self._lock:
            if not verified:
                return False
            self.emergency_latched = False
            self.risk_state = RiskState.NORMAL
            self.throttler.cooldown_until = 0.0
            self.throttler.lockout_reason = ""
            self.heartbeat += 1
            return True

    def telemetry(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            stamp = datetime.fromtimestamp(now, timezone.utc).astimezone(IST)
            pf = self.particle_filter.last_result
            latest_intensity = self.hawkes.intensity(now)
            basis = self.last_basis
            execution = self.last_execution
            profitability = self.last_profitability
            return {
                "cycle": 35,
                "timestamp_ist": stamp.isoformat(),
                "epoch_seconds": now,
                "heartbeat": self.heartbeat,
                "risk_state": self.risk_state.value,
                "emergency_latched": self.emergency_latched,
                "live_order_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
                "paper_simulation_only": True,
                "surfaces": {
                    self.nifty_surface.name: [{"expiry_years": s.expiry_years, **asdict(s.params)} for s in self.nifty_surface.slices],
                    self.banknifty_surface.name: [{"expiry_years": s.expiry_years, **asdict(s.params)} for s in self.banknifty_surface.slices],
                },
                "surface_basis": None if basis is None else {"strikes": list(basis.strikes), "values": list(basis.basis), "max_abs_basis": basis.max_abs_basis},
                "hawkes_intensity": latest_intensity,
                "particle_filter": None if pf is None else {
                    "regime_probabilities": dict(pf.regime_probabilities), "classified_regime": pf.classified_regime.value,
                    "effective_sample_size": pf.effective_sample_size, "resampled": pf.resampled,
                    "mean_volatility": pf.mean_volatility, "mean_jump_intensity": pf.mean_jump_intensity,
                    "mean_beta_resilience": pf.mean_beta_resilience,
                },
                "execution_plan": None if execution is None else {
                    "inventory_path": list(execution.inventory_path), "child_quantities": list(execution.child_quantities),
                    "expected_impact_cost": execution.expected_impact_cost, "inventory_risk_cost": execution.inventory_risk_cost,
                    "objective_value": execution.objective_value,
                },
                "profitability": None if profitability is None else {
                    "expected_gross_alpha": profitability.expected_gross_alpha,
                    "expected_net_alpha": profitability.expected_net_alpha,
                    "total_friction": profitability.fees.total_friction,
                    "qualifies": profitability.qualifies, "reason": profitability.rejection_reason,
                },
                "trading_controls": {
                    "daily_trade_cap": self.throttler.daily_trade_cap,
                    "trades_today": self.throttler.trades_today,
                    "cooldown_remaining_seconds": (None if not math.isfinite(self.throttler.cooldown_remaining(now))
                                                    else self.throttler.cooldown_remaining(now)),
                    "lockout_reason": self.throttler.lockout_reason,
                },
            }


@dataclass
class DashboardHandle:
    server: ThreadingHTTPServer
    thread: threading.Thread
    stop_event: threading.Event

    @property
    def address(self) -> tuple[str, int]:
        return self.server.server_address[0], self.server.server_address[1]

    @property
    def base_url(self) -> str:
        host, port = self.address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.stop_event.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)


def start_dashboard(engine: Cycle35Engine, host: str = "127.0.0.1", port: int = 8088,
                    sse_interval_seconds: float = 0.25) -> DashboardHandle:
    """Start a local JSON/SSE dashboard in a daemon thread; port 0 selects an ephemeral port."""
    if not 0.02 <= sse_interval_seconds <= 60:
        raise ValueError("SSE interval must be in [0.02, 60] seconds")
    stop_event = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, payload: Mapping[str, Any], status: int = 200) -> None:
            raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json({"healthy": True, "cycle": 35, "live_order_dispatch_enabled": False,
                                 "risk_state": engine.risk_state.value, "heartbeat": engine.heartbeat})
            elif self.path == "/telemetry":
                self._send_json(engine.telemetry())
            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    while not stop_event.is_set():
                        payload = json.dumps(engine.telemetry(), separators=(",", ":"), allow_nan=False)
                        self.wfile.write(("event: telemetry\ndata: " + payload + "\n\n").encode("utf-8"))
                        self.wfile.flush()
                        if stop_event.wait(sse_interval_seconds):
                            break
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            else:
                self._send_json({"error": "not found"}, 404)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.allow_reuse_address = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return DashboardHandle(server, thread, stop_event)


def default_option_legs() -> tuple[OptionLeg, ...]:
    """Small synthetic four-leg structure for examples/tests; not a recommendation."""
    return (
        OptionLeg(TradeSide.SELL, 110.0, 25, brokerage=20.0, half_spread_per_unit=0.15, impact_per_unit=0.05, label="sell_call"),
        OptionLeg(TradeSide.BUY, 45.0, 25, brokerage=20.0, half_spread_per_unit=0.10, impact_per_unit=0.03, label="buy_call_wing"),
        OptionLeg(TradeSide.SELL, 95.0, 25, brokerage=20.0, half_spread_per_unit=0.15, impact_per_unit=0.05, label="sell_put"),
        OptionLeg(TradeSide.BUY, 38.0, 25, brokerage=20.0, half_spread_per_unit=0.10, impact_per_unit=0.03, label="buy_put_wing"),
    )

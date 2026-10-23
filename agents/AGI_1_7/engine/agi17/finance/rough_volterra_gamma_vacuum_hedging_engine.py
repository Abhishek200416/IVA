"""Cycle 37: Rough microstructure, quadratic OFI and gamma-vacuum hedging.

Standard-library-only, deterministic-friendly research reference. No broker adapter
or live order submission is provided. Prices, sensitivities and risk limits must be
calibrated and validated before operational use.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping, Sequence, Optional
from zoneinfo import ZoneInfo
import json
import math
import threading
import time

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
SAFETY_EPOCH = "epoch_10k"
IST = ZoneInfo("Asia/Kolkata")
_EPS = 1e-12


def _finite(value: float, name: str) -> float:
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite")
    return v


def _vector(values: Sequence[float], name: str, expected: Optional[int] = None) -> list[float]:
    out = [_finite(x, name) for x in values]
    if expected is not None and len(out) != expected:
        raise ValueError(f"{name} must have length {expected}")
    return out


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("vector dimensions do not match")
    return sum(x * y for x, y in zip(a, b))


def _norm2(a: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def _clip(x: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, x))


def _safe_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True, allow_nan=False)


@dataclass
class RoughVolterraKernel:
    """Finite exponential-sum approximation of K(t)=t^(H-1/2)/Gamma(H+1/2).

    Geometric nodes and midpoint quadrature are based on the Laplace representation
    of a power-law kernel. Accuracy is expected only over the configured time range.
    Each step updates M latent filters, so update cost is O(M), not O(history length).
    """
    H: float = 0.08
    factors: int = 12
    gamma_min: float = 0.02
    gamma_max: float = 200.0
    baseline_variance: float = 0.0004
    state_clip: float = 12.0
    gammas: list[float] = field(init=False)
    omegas: list[float] = field(init=False)
    states: list[float] = field(init=False)
    last_variance: float = field(init=False)
    cumulative_time: float = 0.0

    def __post_init__(self) -> None:
        self.H = _finite(self.H, "H")
        self.gamma_min = _finite(self.gamma_min, "gamma_min")
        self.gamma_max = _finite(self.gamma_max, "gamma_max")
        self.baseline_variance = _finite(self.baseline_variance, "baseline_variance")
        if not 0.0 < self.H < 0.5:
            raise ValueError("H must lie strictly between 0 and 0.5")
        if self.factors < 8:
            raise ValueError("at least 8 exponential factors are required")
        if self.gamma_min <= 0 or self.gamma_max <= self.gamma_min:
            raise ValueError("invalid gamma range")
        if self.baseline_variance <= 0 or self.state_clip <= 0:
            raise ValueError("variance and state_clip must be positive")
        alpha = 0.5 - self.H
        x0, x1 = math.log(self.gamma_min), math.log(self.gamma_max)
        dx = (x1 - x0) / self.factors
        const = math.sin(math.pi * alpha) / math.pi
        self.gammas = []
        self.omegas = []
        for i in range(self.factors):
            x = x0 + (i + 0.5) * dx
            g = math.exp(x)
            self.gammas.append(g)
            self.omegas.append(const * math.exp(alpha * x) * dx)
        self.states = [0.0] * self.factors
        self.last_variance = self.baseline_variance

    def exact_kernel(self, t: float) -> float:
        t = _finite(t, "t")
        if t <= 0:
            raise ValueError("kernel time must be positive")
        return t ** (self.H - 0.5) / math.gamma(self.H + 0.5)

    def approximate_kernel(self, t: float) -> float:
        t = _finite(t, "t")
        if t < 0:
            raise ValueError("kernel time must be nonnegative")
        if t == 0:
            return math.inf
        return sum(w * math.exp(-g * t) for w, g in zip(self.omegas, self.gammas))

    def kernel_relative_error(self, t: float) -> float:
        exact = self.exact_kernel(t)
        return abs(self.approximate_kernel(t) - exact) / exact

    @property
    def memory_half_life(self) -> float:
        return math.log(2.0) / min(self.gammas)

    @property
    def rough_log_variance_state(self) -> float:
        return sum(w * s for w, s in zip(self.omegas, self.states))

    def update(self, dt: float, *, drift: float = 0.0, vol_of_vol: float = 1.0,
               normal_shock: float = 0.0, jump: float = 0.0) -> float:
        """Advance one step using a caller-supplied standard-normal shock for replayability."""
        dt = _finite(dt, "dt")
        drift = _finite(drift, "drift")
        vol_of_vol = _finite(vol_of_vol, "vol_of_vol")
        normal_shock = _finite(normal_shock, "normal_shock")
        jump = _finite(jump, "jump")
        if dt <= 0 or vol_of_vol < 0:
            raise ValueError("dt must be positive and vol_of_vol nonnegative")
        innovation = drift * dt + vol_of_vol * math.sqrt(dt) * normal_shock + jump
        self.states = [
            _clip(math.exp(-g * dt) * s + innovation, -self.state_clip, self.state_clip)
            for s, g in zip(self.states, self.gammas)
        ]
        exponent = _clip(self.rough_log_variance_state, -self.state_clip, self.state_clip)
        self.last_variance = self.baseline_variance * math.exp(exponent)
        self.cumulative_time += dt
        return self.last_variance

    def variance_at(self, log_moneyness: float = 0.0, *, wing_slope: float = 1.5,
                    wing_start: float = 1.5) -> float:
        k = _finite(log_moneyness, "log_moneyness")
        wing_slope = _finite(wing_slope, "wing_slope")
        wing_start = _finite(wing_start, "wing_start")
        if wing_slope <= 0 or wing_start < 0:
            raise ValueError("wing_slope must be positive and wing_start nonnegative")
        w = self.last_variance * (1.0 + 0.05 * abs(k))
        if abs(k) >= wing_start:
            w = min(w, wing_slope * abs(k))
        return max(0.0, w)

    def roger_lee_bound_ok(self, k: float, total_variance: float, wing_slope: float = 1.5,
                           wing_start: float = 1.5, tolerance: float = 1e-10) -> bool:
        k, w, slope, start = (_finite(k, "k"), _finite(total_variance, "total_variance"),
                              _finite(wing_slope, "wing_slope"), _finite(wing_start, "wing_start"))
        if w < 0 or slope <= 0 or start < 0 or tolerance < 0:
            raise ValueError("invalid wing-bound inputs")
        return True if abs(k) < start else w <= slope * abs(k) + tolerance


@dataclass
class QuadraticOFICointegration:
    """Multi-asset linear + quadratic OFI and error-correction signal."""
    assets: tuple[str, ...] = ("NIFTY", "BANKNIFTY", "HDFCBANK", "ICICIBANK", "SBIN", "RELIANCE")
    weights: Optional[list[float]] = None
    quadratic: Optional[list[list[float]]] = None
    alpha_ec: float = 0.2
    lambda_q: float = 0.1
    last_ofi: list[float] = field(init=False)
    last_score: float = 0.0
    price_history: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.assets)
        if n == 0 or len(set(self.assets)) != n:
            raise ValueError("assets must be nonempty and unique")
        self.weights = _vector(self.weights if self.weights is not None else [1.0 / n] * n, "weights", n)
        self.quadratic = self.quadratic if self.quadratic is not None else [[0.0] * n for _ in range(n)]
        if len(self.quadratic) != n or any(len(row) != n for row in self.quadratic):
            raise ValueError("quadratic matrix must be square with asset dimension")
        self.quadratic = [_vector(row, "quadratic") for row in self.quadratic]
        for i in range(n):
            for j in range(n):
                if abs(self.quadratic[i][j] - self.quadratic[j][i]) > 1e-9:
                    raise ValueError("quadratic matrix must be symmetric")
        self.alpha_ec = _finite(self.alpha_ec, "alpha_ec")
        self.lambda_q = _finite(self.lambda_q, "lambda_q")
        if not 0 <= self.alpha_ec <= 1:
            raise ValueError("alpha_ec must be in [0,1]")
        self.last_ofi = [0.0] * n

    def update(self, ofi_by_asset: Mapping[str, float]) -> float:
        x = [0.0] * len(self.assets)
        for i, asset in enumerate(self.assets):
            x[i] = _finite(ofi_by_asset.get(asset, 0.0), f"OFI[{asset}]")
        linear = _dot(self.weights, x)
        quad = sum(x[i] * self.quadratic[i][j] * x[j]
                   for i in range(len(x)) for j in range(len(x)))
        self.last_ofi = x
        self.last_score = linear + quad
        return self.last_score

    def error_correction_signal(self, index_price: float, constituent_prices: Mapping[str, float],
                                beta_ci: Mapping[str, float], mu_coint: float = 0.0) -> dict[str, float]:
        spot = _finite(index_price, "index_price")
        if spot <= 0:
            raise ValueError("index_price must be positive")
        mu = _finite(mu_coint, "mu_coint")
        rhs = mu
        for name, beta in beta_ci.items():
            p = _finite(constituent_prices.get(name, 0.0), f"price[{name}]")
            b = _finite(beta, f"beta[{name}]")
            if p <= 0:
                raise ValueError(f"constituent price {name} must be positive")
            rhs += b * math.log(p)
        spread = math.log(spot) - rhs
        delta = -self.alpha_ec * spread + self.lambda_q * self.last_score
        return {"spread": spread, "expected_log_delta": delta, "q_ofi": self.last_score}

    @staticmethod
    def leadership_metric(leader_flow: float, follower_flow: float, epsilon: float = 1e-12) -> float:
        a, b, e = _finite(leader_flow, "leader_flow"), _finite(follower_flow, "follower_flow"), _finite(epsilon, "epsilon")
        if e <= 0:
            raise ValueError("epsilon must be positive")
        return _clip((abs(a) - abs(b)) / (abs(a) + abs(b) + e), -1.0, 1.0)


@dataclass(frozen=True)
class GammaHedgeResult:
    weights: tuple[float, ...]
    objective: float
    delta_net: float
    gamma_net: float
    converged: bool
    iterations: int
    feasible: bool
    message: str = ""


@dataclass
class GammaVacuumHedger:
    """Projected-gradient gamma targeting with box constraints and delta-neutral projection.

    The equality projection is solved by a monotone scalar bisection. If delta neutrality
    is infeasible under the supplied execution bounds, the solver fails closed.
    """
    lambda_spread: float = 0.2
    lambda_vacuum: float = 0.4
    epsilon: float = 1e-8
    tolerance: float = 1e-7
    max_iterations: int = 1200

    def __post_init__(self) -> None:
        for name in ("lambda_spread", "lambda_vacuum", "epsilon", "tolerance"):
            setattr(self, name, _finite(getattr(self, name), name))
        if self.lambda_spread < 0 or self.lambda_vacuum < 0 or self.epsilon <= 0 or self.tolerance <= 0:
            raise ValueError("invalid gamma hedge regularization or tolerance")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")

    @staticmethod
    def _project_box_delta(v: Sequence[float], deltas: Sequence[float], lo: Sequence[float],
                           hi: Sequence[float], tol: float = 1e-12) -> Optional[list[float]]:
        d = list(deltas)
        lower_value = sum(di * (lo[i] if di >= 0 else hi[i]) for i, di in enumerate(d))
        upper_value = sum(di * (hi[i] if di >= 0 else lo[i]) for i, di in enumerate(d))
        if lower_value > tol or upper_value < -tol:
            return None
        def at(lam: float) -> list[float]:
            return [_clip(v[i] - lam * d[i], lo[i], hi[i]) for i in range(len(v))]
        left, right = -1.0, 1.0
        for _ in range(100):
            if _dot(d, at(left)) >= 0 and _dot(d, at(right)) <= 0:
                break
            left *= 2.0
            right *= 2.0
        else:
            return None
        out = at(0.0)
        for _ in range(90):
            mid = (left + right) * 0.5
            out = at(mid)
            residual = _dot(d, out)
            if abs(residual) <= tol:
                break
            if residual > 0:
                left = mid
            else:
                right = mid
        return out if abs(_dot(d, out)) <= max(tol * 10.0, 1e-9) else None

    def objective(self, weights: Sequence[float], gammas: Sequence[float], gamma_target: float,
                  spreads: Sequence[float], depths: Sequence[float]) -> float:
        n = len(weights)
        if not (len(gammas) == len(spreads) == len(depths) == n):
            raise ValueError("gamma hedge vectors must have same length")
        u = _vector(weights, "weights", n)
        g = _vector(gammas, "gammas", n)
        s = _vector(spreads, "spreads", n)
        d = _vector(depths, "depths", n)
        if any(x < 0 for x in u) or any(x < 0 for x in s) or any(x < 0 for x in d):
            raise ValueError("weights, spreads and depths must be nonnegative")
        tgt = _finite(gamma_target, "gamma_target")
        gamma_error = tgt - _dot(g, u)
        return 0.5 * gamma_error * gamma_error + self.lambda_spread * sum(si * abs(ui) for si, ui in zip(s, u)) + self.lambda_vacuum * sum(ui * ui / (di + self.epsilon) for ui, di in zip(u, d))

    def optimize(self, *, deltas: Sequence[float], gammas: Sequence[float], spreads: Sequence[float],
                 depths: Sequence[float], gamma_target: float, max_units: Sequence[float],
                 min_units: Optional[Sequence[float]] = None) -> GammaHedgeResult:
        d = _vector(deltas, "deltas")
        n = len(d)
        if n == 0:
            raise ValueError("at least one option is required")
        g = _vector(gammas, "gammas", n)
        s = _vector(spreads, "spreads", n)
        dep = _vector(depths, "depths", n)
        hi = _vector(max_units, "max_units", n)
        lo = _vector(min_units if min_units is not None else [0.0] * n, "min_units", n)
        tgt = _finite(gamma_target, "gamma_target")
        if any(x < 0 for x in s) or any(x < 0 for x in dep) or any(x < 0 for x in lo) or any(x < 0 for x in hi):
            raise ValueError("spreads, depths and units must be nonnegative")
        if any(lo[i] > hi[i] for i in range(n)):
            raise ValueError("min_units must not exceed max_units")
        init = [(lo[i] + hi[i]) * 0.5 for i in range(n)]
        u = self._project_box_delta(init, d, lo, hi)
        if u is None:
            zero = [0.0] * n
            finite_objective = self.objective(zero, g, tgt, s, dep)
            # Finite diagnostic fields keep dashboard JSON valid even on infeasible inputs.
            return GammaHedgeResult(tuple(zero), finite_objective, 0.0, 0.0, False, 0, False, "delta-neutral constraint infeasible under bounds")
        min_depth = min(dep) + self.epsilon
        lipschitz = _dot(g, g) + 2.0 * self.lambda_vacuum / min_depth + 1e-9
        base_step = 0.9 / lipschitz
        prev_obj = self.objective(u, g, tgt, s, dep)
        converged = False
        iterations = 0
        for iterations in range(1, self.max_iterations + 1):
            err = tgt - _dot(g, u)
            grad = [-err * g[i] + self.lambda_spread * s[i] + 2.0 * self.lambda_vacuum * u[i] / (dep[i] + self.epsilon) for i in range(n)]
            step = base_step
            candidate = [u[i] - step * grad[i] for i in range(n)]
            projected = self._project_box_delta(candidate, d, lo, hi)
            if projected is None:
                return GammaHedgeResult(tuple(u), prev_obj, _dot(d, u), _dot(g, u), False, iterations, False, "projection infeasible")
            obj = self.objective(projected, g, tgt, s, dep)
            # Backtracking is local to this iteration: never permanently shrink future steps.
            backtrack = 0
            while obj > prev_obj + 1e-12 and backtrack < 30:
                step *= 0.5
                candidate = [u[i] - step * grad[i] for i in range(n)]
                projected = self._project_box_delta(candidate, d, lo, hi)
                if projected is None:
                    return GammaHedgeResult(tuple(u), prev_obj, _dot(d, u), _dot(g, u), False, iterations, False, "projection infeasible")
                obj = self.objective(projected, g, tgt, s, dep)
                backtrack += 1
            diff = _norm2([projected[i] - u[i] for i in range(n)])
            u = projected
            if diff <= self.tolerance and abs(_dot(d, u)) <= 1e-4:
                prev_obj = obj
                converged = True
                break
            prev_obj = obj
        delta_net, gamma_net = _dot(d, u), _dot(g, u)
        feasible = abs(delta_net) <= 1e-4 and all(lo[i] - 1e-9 <= u[i] <= hi[i] + 1e-9 for i in range(n))
        return GammaHedgeResult(tuple(u), prev_obj, delta_net, gamma_net, converged and feasible, iterations, feasible, "converged" if converged and feasible else "iteration limit or tolerance not met")


@dataclass(frozen=True)
class OptionLeg:
    symbol: str
    side: str
    premium: float
    quantity: float
    half_spread_per_unit: float = 0.0
    impact_per_unit: float = 0.0


@dataclass(frozen=True)
class CostBreakdown:
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
    total: float


@dataclass
class StatutoryCostCalculator:
    sell_stt_rate: float = 0.0015
    buy_stamp_rate: float = 0.00003
    exchange_per_crore: float = 3553.0
    sebi_per_crore: float = 10.0
    gst_rate: float = 0.18
    brokerage_per_leg: float = 20.0
    def __post_init__(self) -> None:
        for name in ("sell_stt_rate", "buy_stamp_rate", "exchange_per_crore", "sebi_per_crore", "gst_rate", "brokerage_per_leg"):
            setattr(self, name, _finite(getattr(self, name), name))
        if any(getattr(self, name) < 0 for name in ("sell_stt_rate", "buy_stamp_rate", "exchange_per_crore", "sebi_per_crore", "gst_rate", "brokerage_per_leg")):
            raise ValueError("fee rates must be nonnegative")

    def calculate(self, legs: Sequence[OptionLeg]) -> CostBreakdown:
        buy_turnover = sell_turnover = slippage = impact = 0.0
        for leg in legs:
            side = str(leg.side).upper()
            p, q = _finite(leg.premium, "premium"), _finite(leg.quantity, "quantity")
            hs, im = _finite(leg.half_spread_per_unit, "half_spread_per_unit"), _finite(leg.impact_per_unit, "impact_per_unit")
            if side not in ("BUY", "SELL"):
                raise ValueError("leg side must be BUY or SELL")
            if p < 0 or q < 0 or hs < 0 or im < 0:
                raise ValueError("premium, quantity, spread and impact must be nonnegative")
            turnover = p * q
            if side == "BUY":
                buy_turnover += turnover
            else:
                sell_turnover += turnover
            slippage += hs * q
            impact += im * q
        total_turnover = buy_turnover + sell_turnover
        stt = sell_turnover * self.sell_stt_rate
        stamp = buy_turnover * self.buy_stamp_rate
        exchange = total_turnover * self.exchange_per_crore / 1e7
        sebi = total_turnover * self.sebi_per_crore / 1e7
        brokerage = len(legs) * self.brokerage_per_leg
        gst = self.gst_rate * (exchange + sebi + brokerage)
        values = [buy_turnover, sell_turnover, total_turnover, stt, stamp, exchange, sebi, brokerage, gst, slippage, impact]
        if any(not math.isfinite(v) for v in values):
            raise ValueError("fee calculation overflow")
        return CostBreakdown(buy_turnover, sell_turnover, total_turnover, stt, stamp, exchange, sebi, brokerage, gst, slippage, impact, sum(values[3:]))

    @staticmethod
    def profitability_gate(gross_expected_alpha: float, costs: CostBreakdown, safety_buffer: float = 0.0) -> dict[str, Any]:
        gross = _finite(gross_expected_alpha, "gross_expected_alpha")
        safety = _finite(safety_buffer, "safety_buffer")
        if safety < 0:
            raise ValueError("safety_buffer must be nonnegative")
        net = gross - costs.total - safety
        return {"gross_expected_alpha": gross, "total_friction": costs.total, "safety_buffer": safety,
                "expected_net_alpha": net, "approved": net > 0.0}


@dataclass
class AntiOvertradingThrottler:
    max_trades_per_session: int = 15
    loss_limit: int = 3
    revenge_ratio: float = 1.25
    min_fill_interval: float = 30.0
    base_cooldown: float = 900.0
    theta_rough: float = 1.0
    sigma_baseline: float = 0.02
    trade_count: int = 0
    consecutive_losses: int = 0
    last_fill_time: Optional[float] = None
    last_fill_size: Optional[float] = None
    cooldown_until: float = 0.0
    lockout_reason: str = ""

    def __post_init__(self) -> None:
        for name in ("revenge_ratio", "min_fill_interval", "base_cooldown", "theta_rough", "sigma_baseline"):
            setattr(self, name, _finite(getattr(self, name), name))
        if self.max_trades_per_session < 0 or self.loss_limit < 1:
            raise ValueError("invalid trade cap or loss limit")
        if self.revenge_ratio <= 1 or self.min_fill_interval < 0 or self.base_cooldown < 0 or self.theta_rough < 0 or self.sigma_baseline <= 0:
            raise ValueError("invalid throttler parameters")

    @staticmethod
    def optimal_trade_cap(alpha: float, cost: float, risk: float) -> int:
        a, c, r = _finite(alpha, "alpha"), _finite(cost, "cost"), _finite(risk, "risk")
        if r <= 0:
            raise ValueError("risk denominator must be positive")
        return max(0, int(math.floor((a - c) / r + 0.5)))

    def cooldown_duration(self, sigma_rough: float) -> float:
        s = _finite(sigma_rough, "sigma_rough")
        if s < 0:
            raise ValueError("sigma_rough must be nonnegative")
        return self.base_cooldown * (1.0 + self.theta_rough * s / self.sigma_baseline)

    def lockout(self, now: float, reason: str, sigma_rough: float = 0.0) -> float:
        t = _finite(now, "now")
        self.cooldown_until = max(self.cooldown_until, t + self.cooldown_duration(sigma_rough))
        self.lockout_reason = str(reason)
        return self.cooldown_until

    def record_fill(self, *, now: float, size: float, pnl: float, sigma_rough: float = 0.0) -> Optional[str]:
        t, q, p = _finite(now, "now"), _finite(size, "size"), _finite(pnl, "pnl")
        if q <= 0:
            raise ValueError("fill size must be positive")
        if self.last_fill_time is not None and t < self.last_fill_time:
            raise ValueError("fill times must be nondecreasing")
        if self.last_fill_size is not None and q > self.last_fill_size * self.revenge_ratio:
            self.lockout(t, "revenge_sizing", sigma_rough)
            reason = "revenge_sizing"
        elif self.last_fill_time is not None and t - self.last_fill_time < self.min_fill_interval:
            self.lockout(t, "rapid_pacing", sigma_rough)
            reason = "rapid_pacing"
        else:
            reason = None
        self.trade_count += 1
        self.consecutive_losses = self.consecutive_losses + 1 if p < 0 else 0
        if self.consecutive_losses >= self.loss_limit:
            self.lockout(t, "loss_streak", sigma_rough)
            reason = "loss_streak"
        self.last_fill_time, self.last_fill_size = t, q
        return reason

    def can_enter(self, now: float) -> bool:
        t = _finite(now, "now")
        return self.trade_count < self.max_trades_per_session and t >= self.cooldown_until

    def remaining_cooldown(self, now: float) -> float:
        return max(0.0, self.cooldown_until - _finite(now, "now"))


@dataclass
class Cycle37ExecutionEngine:
    rough: RoughVolterraKernel = field(default_factory=RoughVolterraKernel)
    qofi: QuadraticOFICointegration = field(default_factory=QuadraticOFICointegration)
    hedger: GammaVacuumHedger = field(default_factory=GammaVacuumHedger)
    costs: StatutoryCostCalculator = field(default_factory=StatutoryCostCalculator)
    throttler: AntiOvertradingThrottler = field(default_factory=AntiOvertradingThrottler)
    latest_hedge: Optional[GammaHedgeResult] = None
    latest_costs: Optional[CostBreakdown] = None
    latest_gate: Optional[dict[str, Any]] = None
    risk_state: str = "MONITORING"
    telemetry_extra: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def update_tick(self, *, dt: float, ofi: Mapping[str, float], normal_shock: float = 0.0,
                    jump: float = 0.0, drift: float = 0.0, vol_of_vol: float = 1.0) -> dict[str, Any]:
        with self._lock:
            variance = self.rough.update(dt, drift=drift, vol_of_vol=vol_of_vol,
                                         normal_shock=normal_shock, jump=jump)
            q = self.qofi.update(ofi)
            self.risk_state = "LIQUIDITY_VACUUM" if abs(jump) > 1.0 or abs(q) > 5.0 else "MONITORING"
            return {"rough_variance": variance, "rough_log_variance_state": self.rough.rough_log_variance_state,
                    "q_ofi": q, "risk_state": self.risk_state}

    def optimize_gamma(self, **kwargs: Any) -> GammaHedgeResult:
        with self._lock:
            result = self.hedger.optimize(**kwargs)
            self.latest_hedge = result
            if not result.feasible:
                self.risk_state = "HEDGE_INFEASIBLE"
            return result

    def evaluate_spread(self, legs: Sequence[OptionLeg], gross_expected_alpha: float,
                        safety_buffer: float = 0.0, now: Optional[float] = None) -> dict[str, Any]:
        with self._lock:
            costs = self.costs.calculate(legs)
            gate = self.costs.profitability_gate(gross_expected_alpha, costs, safety_buffer)
            t = time.time() if now is None else _finite(now, "now")
            gate["approved"] = bool(gate["approved"] and self.throttler.can_enter(t) and self.risk_state not in ("LIQUIDITY_VACUUM", "HEDGE_INFEASIBLE", "EMERGENCY_UNWIND"))
            if not gate["approved"] and gate["expected_net_alpha"] > 0:
                gate["blocked_reason"] = "risk_or_throttle_gate"
                gate["expected_net_alpha"] = 0.0
            elif not gate["approved"]:
                gate["blocked_reason"] = "friction_hurdle"
            else:
                gate["blocked_reason"] = ""
            self.latest_costs, self.latest_gate = costs, gate
            return {"costs": asdict(costs), "gate": dict(gate)}

    def record_paper_fill(self, *, now: float, size: float, pnl: float) -> Optional[str]:
        with self._lock:
            reason = self.throttler.record_fill(now=now, size=size, pnl=pnl,
                                                sigma_rough=math.sqrt(self.rough.last_variance))
            if reason:
                self.risk_state = "OVERTRADING_LOCKED"
            return reason

    def telemetry(self, now: Optional[datetime] = None) -> dict[str, Any]:
        with self._lock:
            dt = now or datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ist = dt.astimezone(IST)
            return {
                "timestamp_ist": ist.isoformat(), "timestamp_epoch": dt.timestamp(),
                "rough": {"H": self.rough.H, "factors": self.rough.factors,
                          "variance": self.rough.last_variance, "log_variance_state": self.rough.rough_log_variance_state,
                          "memory_half_life": self.rough.memory_half_life},
                "qofi": {"assets": list(self.qofi.assets), "vector": list(self.qofi.last_ofi), "score": self.qofi.last_score},
                "gamma_hedge": asdict(self.latest_hedge) if self.latest_hedge else None,
                "costs": asdict(self.latest_costs) if self.latest_costs else None,
                "profitability_gate": dict(self.latest_gate) if self.latest_gate else None,
                "risk_state": self.risk_state,
                "throttler": {"trade_count": self.throttler.trade_count,
                              "max_trades_per_session": self.throttler.max_trades_per_session,
                              "consecutive_losses": self.throttler.consecutive_losses,
                              "cooldown_remaining": self.throttler.remaining_cooldown(dt.timestamp()),
                              "lockout_reason": self.throttler.lockout_reason},
                "LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
                "REAL_BROKER_FILLS_LOCKED": REAL_BROKER_FILLS_LOCKED,
                "safety_epoch": SAFETY_EPOCH,
                "extra": dict(self.telemetry_extra),
            }


class _DashboardHandler(BaseHTTPRequestHandler):
    engine: Cycle37ExecutionEngine
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            payload = {"ok": True, "risk_state": self.engine.risk_state,
                       "LIVE_ORDER_DISPATCH_ENABLED": LIVE_ORDER_DISPATCH_ENABLED,
                       "REAL_BROKER_FILLS_LOCKED": REAL_BROKER_FILLS_LOCKED}
            self._json(200, payload)
        elif self.path == "/telemetry":
            self._json(200, self.engine.telemetry())
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                for _ in range(3):
                    payload = _safe_json(self.engine.telemetry())
                    self.wfile.write((f"event: telemetry\ndata: {payload}\n\n").encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self._json(404, {"error": "not found"})
    def _json(self, status: int, payload: Any) -> None:
        raw = _safe_json(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def log_message(self, format: str, *args: Any) -> None:
        return


class DashboardServer:
    """Local-only threaded HTTP/SSE server; binds to loopback by default."""
    def __init__(self, engine: Cycle37ExecutionEngine, host: str = "127.0.0.1", port: int = 8088):
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("dashboard must bind to loopback for safe default operation")
        if not 0 <= int(port) <= 65535:
            raise ValueError("invalid port")
        self.engine, self.host, self.port = engine, host, int(port)
        handler = type("Cycle37DashboardHandler", (_DashboardHandler,), {"engine": engine})
        self.server = ThreadingHTTPServer((host, self.port), handler)
        self.server.daemon_threads = True
        self._thread: Optional[threading.Thread] = None
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self._thread:
            self._thread.join(timeout=2.0)


def start_dashboard(engine: Cycle37ExecutionEngine, host: str = "127.0.0.1", port: int = 8088) -> DashboardServer:
    server = DashboardServer(engine, host, port)
    server.start()
    return server


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("live order dispatch is permanently disabled in Cycle 37 paper mode")

"""Cycle 30: Global macro shock transmission, SVI conditioning, telemetry and cooldown.

Offline research reference only. No broker connectivity or live order dispatch exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from math import exp, isfinite, log, sqrt
from typing import Any, Callable, Dict, Iterable, Iterator, Mapping, Optional, Sequence, Tuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
from zoneinfo import ZoneInfo

LIVE_ORDER_DISPATCH_ENABLED = False
DASHBOARD_PORT = 8088
IST = ZoneInfo("Asia/Kolkata")
CRORE_RUPEES = 10_000_000.0


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _nonnegative(value: float, name: str) -> float:
    value = _finite(value, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class MacroFactors:
    """Innovations in native units: yield in percentage points, others in pct points.

    The caller must keep units consistent with MacroTransmissionModel.std_scales.
    These are innovations, not levels or forecasts.
    """
    dy_us10y: float
    ddxy: float
    dbrent: float
    dvix: float

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            _finite(value, key)

    def vector(self) -> Tuple[float, float, float, float]:
        return (self.dy_us10y, self.ddxy, self.dbrent, self.dvix)

    def norm(self) -> float:
        return sqrt(sum(x * x for x in self.vector()))

    def z_scores(self, scales: Sequence[float]) -> Tuple[float, float, float, float]:
        if len(scales) != 4:
            raise ValueError("scales must have four entries")
        checked = tuple(_finite(s, "scale") for s in scales)
        if any(s <= 0 for s in checked):
            raise ValueError("all macro scales must be positive")
        return tuple(x / s for x, s in zip(self.vector(), checked))  # type: ignore[return-value]


@dataclass(frozen=True)
class SVIParameters:
    """Raw SVI total variance w(k) = a + b*(rho*x + sqrt(x^2 + sigma^2))."""
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            _finite(value, key)
        if self.b < 0:
            raise ValueError("SVI b must be nonnegative")
        if not -1.0 < self.rho < 1.0:
            raise ValueError("SVI rho must be strictly between -1 and 1")
        if self.sigma <= 0:
            raise ValueError("SVI sigma must be positive")
        if self.minimum_total_variance() < -1e-12:
            raise ValueError("SVI parameters imply negative minimum total variance")

    def minimum_total_variance(self) -> float:
        return self.a + self.b * self.sigma * sqrt(max(0.0, 1.0 - self.rho * self.rho))

    def total_variance(self, k: float) -> float:
        k = _finite(k, "log-moneyness")
        x = k - self.m
        result = self.a + self.b * (self.rho * x + sqrt(x * x + self.sigma * self.sigma))
        if result < -1e-10:
            raise ValueError("computed SVI total variance is negative")
        return max(0.0, result)

    def implied_volatility(self, k: float, tau_years: float) -> float:
        tau_years = _finite(tau_years, "tau_years")
        if tau_years <= 0:
            raise ValueError("tau_years must be positive")
        return sqrt(self.total_variance(k) / tau_years)

    def to_dict(self) -> Dict[str, float]:
        return {key: float(value) for key, value in asdict(self).items()}


@dataclass(frozen=True)
class MacroModelConfig:
    """Standardization scales and factor-to-SVI sensitivities.

    Sensitivity rows are ordered [da, db, drho, dm, dsigma], columns follow
    MacroFactors.vector(). Defaults are illustrative, not estimated market betas.
    """
    std_scales: Tuple[float, float, float, float] = (0.05, 0.5, 2.0, 3.0)
    crude_banknifty_curvature_multiplier: float = 1.35
    sensitivity_nifty: Tuple[Tuple[float, ...], ...] = (
        (0.0015, 0.0010, 0.0007, 0.0040),
        (0.0002, 0.0004, 0.0005, 0.0020),
        (0.0020, -0.0120, -0.0010, -0.0030),
        (0.0010, 0.0030, 0.0010, 0.0010),
        (0.0005, 0.0010, 0.0010, 0.0020),
    )
    sensitivity_banknifty: Tuple[Tuple[float, ...], ...] = (
        (0.0018, 0.0012, 0.0010, 0.0045),
        (0.0003, 0.0005, 0.0005, 0.0022),
        (0.0022, -0.0140, -0.0011, -0.0033),
        (0.0011, 0.0032, 0.0011, 0.0010),
        (0.0006, 0.0011, 0.0012, 0.0022),
    )

    def __post_init__(self) -> None:
        if len(self.std_scales) != 4 or any(not isfinite(float(x)) or x <= 0 for x in self.std_scales):
            raise ValueError("std_scales must contain four positive finite numbers")
        if self.crude_banknifty_curvature_multiplier < 1 or not isfinite(self.crude_banknifty_curvature_multiplier):
            raise ValueError("crude BankNIFTY multiplier must be finite and >= 1")
        for matrix in (self.sensitivity_nifty, self.sensitivity_banknifty):
            if len(matrix) != 5 or any(len(row) != 4 for row in matrix):
                raise ValueError("each sensitivity matrix must be 5 x 4")
            if any(not isfinite(float(v)) for row in matrix for v in row):
                raise ValueError("sensitivity values must be finite")


@dataclass(frozen=True)
class SurfaceTransmission:
    index_name: str
    z_scores: Tuple[float, float, float, float]
    index_return_signal: float
    shifts: Mapping[str, float]
    svi: SVIParameters
    skew_tilt: float
    put_call_iv_diff: float


class MacroTransmissionModel:
    """Linear factor transmission to index proxy signals and raw SVI parameters."""
    PARAMS = ("a", "b", "rho", "m", "sigma")

    def __init__(self, config: MacroModelConfig = MacroModelConfig()) -> None:
        self.config = config
        self._base = {
            "NIFTY": SVIParameters(a=0.020, b=0.080, rho=-0.25, m=0.0, sigma=0.20),
            "BANKNIFTY": SVIParameters(a=0.024, b=0.095, rho=-0.28, m=0.0, sigma=0.22),
        }
        # A separate simple index proxy beta vector; not a return prediction.
        self._index_betas = {
            "NIFTY": (0.12, -0.08, -0.025, -0.18),
            "BANKNIFTY": (0.10, -0.11, -0.018, -0.21),
        }

    @property
    def base_surfaces(self) -> Mapping[str, SVIParameters]:
        return dict(self._base)

    def transmit(self, factors: MacroFactors, index_name: str) -> SurfaceTransmission:
        name = index_name.upper()
        if name not in self._base:
            raise ValueError("index_name must be NIFTY or BANKNIFTY")
        z = factors.z_scores(self.config.std_scales)
        base = self._base[name]
        matrix = self.config.sensitivity_nifty if name == "NIFTY" else self.config.sensitivity_banknifty
        raw_shifts = [sum(coef * zi for coef, zi in zip(row, z)) for row in matrix]
        # DXY appreciation is a put-skew stress proxy: steepen curvature and make rho more negative.
        if factors.ddxy > 0:
            raw_shifts[1] += 0.0015 * z[1]
            raw_shifts[2] -= 0.0040 * z[1]
        # Crude sensitivity to BANKNIFTY curvature is 1.35x the NIFTY oil contribution.
        if name == "BANKNIFTY" and factors.dbrent > 0:
            oil_contribution_nifty = self.config.sensitivity_nifty[1][2] * z[2]
            raw_shifts[1] += (self.config.crude_banknifty_curvature_multiplier - 1.0) * oil_contribution_nifty
        shifts = dict(zip(self.PARAMS, raw_shifts))
        b = max(0.0, base.b + shifts["b"])
        rho = _clamp(base.rho + shifts["rho"], -0.98, 0.98)
        sigma = max(0.03, base.sigma + shifts["sigma"])
        m = base.m + shifts["m"]
        a = base.a + shifts["a"]
        minimum_required_a = -b * sigma * sqrt(max(0.0, 1.0 - rho * rho)) + 1e-9
        a = max(a, minimum_required_a)
        surface = SVIParameters(a=a, b=b, rho=rho, m=m, sigma=sigma)
        # Symmetric log-moneyness diagnostics: slope proxy and put-minus-call IV.
        k = 0.15
        put_iv = surface.implied_volatility(-k, 30.0 / 365.0)
        call_iv = surface.implied_volatility(k, 30.0 / 365.0)
        skew_tilt = (put_iv - call_iv)
        return SurfaceTransmission(
            index_name=name,
            z_scores=z,
            index_return_signal=sum(beta * zi for beta, zi in zip(self._index_betas[name], z)),
            shifts=shifts,
            svi=surface,
            skew_tilt=skew_tilt,
            put_call_iv_diff=put_iv - call_iv,
        )

    def transmit_both(self, factors: MacroFactors) -> Dict[str, SurfaceTransmission]:
        return {name: self.transmit(factors, name) for name in ("NIFTY", "BANKNIFTY")}


class OperationalStage(str, Enum):
    STAGE_0_NORMAL = "STAGE_0_NORMAL"
    STAGE_1_CAUTION = "STAGE_1_CAUTION"
    STAGE_2_QUARANTINE = "STAGE_2_QUARANTINE"
    STAGE_3_EMERGENCY_UNWIND = "STAGE_3_EMERGENCY_UNWIND"


@dataclass(frozen=True)
class CooldownConfig:
    tau_min_seconds: float = 60.0
    tau_base_seconds: float = 300.0
    kappa_shock: float = 1.5
    sigma_macro: float = 1.0
    max_cooldown_seconds: float = 24.0 * 3600.0
    caution_z_threshold: float = 1.5
    quarantine_z_threshold: float = 3.5
    emergency_depth_ratio: float = 0.10
    caution_alpha_multiplier: float = 1.25
    caution_band_multiplier: float = 1.5

    def __post_init__(self) -> None:
        vals = asdict(self)
        for key, val in vals.items():
            _finite(val, key)
        if self.tau_min_seconds <= 0 or self.tau_base_seconds <= 0 or self.sigma_macro <= 0:
            raise ValueError("cooldown scales and sigma_macro must be positive")
        if self.kappa_shock < 0 or self.max_cooldown_seconds < self.tau_min_seconds:
            raise ValueError("invalid cooldown constants")
        if not 0 <= self.emergency_depth_ratio <= 1:
            raise ValueError("emergency depth ratio must be in [0,1]")
        if self.caution_z_threshold < 0 or self.quarantine_z_threshold <= self.caution_z_threshold:
            raise ValueError("invalid shock thresholds")
        if self.caution_alpha_multiplier < 1 or self.caution_band_multiplier < 1:
            raise ValueError("caution multipliers must be >= 1")


@dataclass
class DynamicCooldownController:
    config: CooldownConfig = field(default_factory=CooldownConfig)
    stage: OperationalStage = OperationalStage.STAGE_0_NORMAL
    cooldown_until_epoch: float = 0.0
    emergency_latched: bool = False
    last_shock_norm: float = 0.0
    last_reason: str = "initial"

    def cooldown_seconds(self, shock_norm: float) -> float:
        shock_norm = _nonnegative(shock_norm, "shock_norm")
        raw = self.config.tau_base_seconds * (1.0 + self.config.kappa_shock * shock_norm / self.config.sigma_macro)
        return _clamp(raw, self.config.tau_min_seconds, self.config.max_cooldown_seconds)

    def remaining(self, now_epoch: Optional[float] = None) -> float:
        now = time.time() if now_epoch is None else _finite(now_epoch, "now_epoch")
        return max(0.0, self.cooldown_until_epoch - now)

    def evaluate(
        self,
        factors: MacroFactors,
        model: MacroTransmissionModel,
        now_epoch: Optional[float] = None,
        high_volatility_clustering: bool = False,
        market_disruption: bool = False,
        depth_ratio: float = 1.0,
    ) -> OperationalStage:
        now = time.time() if now_epoch is None else _finite(now_epoch, "now_epoch")
        depth_ratio = _finite(depth_ratio, "depth_ratio")
        if not 0 <= depth_ratio <= 1:
            raise ValueError("depth_ratio must be in [0,1]")
        z = factors.z_scores(model.config.std_scales)
        shock_norm = sqrt(sum(x * x for x in z))
        self.last_shock_norm = shock_norm
        if self.emergency_latched:
            self.stage = OperationalStage.STAGE_3_EMERGENCY_UNWIND
            self.last_reason = "emergency_latched"
            return self.stage
        if market_disruption or depth_ratio <= self.config.emergency_depth_ratio:
            self.emergency_latched = True
            self.stage = OperationalStage.STAGE_3_EMERGENCY_UNWIND
            self.last_reason = "market_disruption_or_liquidity_collapse"
            self.cooldown_until_epoch = max(self.cooldown_until_epoch, now + self.cooldown_seconds(shock_norm))
            return self.stage
        if shock_norm >= self.config.quarantine_z_threshold or high_volatility_clustering:
            self.stage = OperationalStage.STAGE_2_QUARANTINE
            self.last_reason = "extreme_macro_shock_or_volatility_clustering"
            self.cooldown_until_epoch = max(self.cooldown_until_epoch, now + self.cooldown_seconds(shock_norm))
            return self.stage
        # Once quarantine is entered, a residual timer keeps entries blocked even
        # if the instantaneous shock falls back into the caution band.
        if self.remaining(now) > 0:
            self.stage = OperationalStage.STAGE_2_QUARANTINE
            self.last_reason = "cooldown_active"
            return self.stage
        if shock_norm >= self.config.caution_z_threshold:
            self.stage = OperationalStage.STAGE_1_CAUTION
            self.last_reason = "macro_innovation_caution"
            return self.stage
        self.stage = OperationalStage.STAGE_0_NORMAL
        self.last_reason = "shock_normalized_and_cooldown_expired"
        return self.stage

    def recovery_ack(self, *, verified: bool, now_epoch: Optional[float] = None) -> OperationalStage:
        if not verified:
            raise PermissionError("recovery requires an independently verified acknowledgement")
        now = time.time() if now_epoch is None else _finite(now_epoch, "now_epoch")
        self.emergency_latched = False
        self.cooldown_until_epoch = max(self.cooldown_until_epoch, now)
        self.stage = OperationalStage.STAGE_2_QUARANTINE
        self.last_reason = "verified_recovery_ack_cooldown"
        return self.stage

    @property
    def new_entries_allowed(self) -> bool:
        return self.stage in (OperationalStage.STAGE_0_NORMAL, OperationalStage.STAGE_1_CAUTION) and not self.emergency_latched

    @property
    def band_multiplier(self) -> float:
        if self.stage is OperationalStage.STAGE_1_CAUTION:
            return self.config.caution_band_multiplier
        return 1.0

    @property
    def alpha_hurdle_multiplier(self) -> float:
        if self.stage is OperationalStage.STAGE_1_CAUTION:
            return self.config.caution_alpha_multiplier
        return 1.0

    @property
    def passive_risk_hedge_only(self) -> bool:
        return self.stage in (OperationalStage.STAGE_2_QUARANTINE, OperationalStage.STAGE_3_EMERGENCY_UNWIND)


@dataclass(frozen=True)
class OptionLeg:
    symbol: str
    side: str
    premium: float
    quantity: int

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be blank")
        if self.side.upper() not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        _nonnegative(self.premium, "premium")
        if isinstance(self.quantity, bool) or int(self.quantity) != self.quantity or self.quantity < 0:
            raise ValueError("quantity must be a nonnegative integer")

    @property
    def turnover(self) -> float:
        return self.premium * self.quantity


@dataclass(frozen=True)
class FrictionBreakdown:
    buy_turnover: float
    sell_turnover: float
    total_premium_turnover: float
    stt: float
    exchange_fee: float
    sebi_fee: float
    brokerage: float
    gst: float
    stamp_duty: float
    slippage: float
    cross_impact: float
    total: float

    def to_dict(self) -> Dict[str, float]:
        return {k: float(v) for k, v in asdict(self).items()}


@dataclass(frozen=True)
class StatutoryCostConfig:
    options_sell_stt_rate: float = 0.0015
    exchange_fee_per_crore: float = 3553.0
    sebi_fee_per_crore: float = 10.0
    gst_rate: float = 0.18
    buyer_stamp_rate: float = 0.00003
    gst_on: Tuple[str, ...] = ("exchange_fee", "sebi_fee", "brokerage")

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            if key == "gst_on":
                continue
            _nonnegative(value, key)
        if self.gst_rate > 1 or self.options_sell_stt_rate > 1 or self.buyer_stamp_rate > 1:
            raise ValueError("rates must be fractions, e.g. 0.0015")
        allowed = {"exchange_fee", "sebi_fee", "brokerage"}
        if any(item not in allowed for item in self.gst_on):
            raise ValueError("gst_on contains unsupported component")


class StatutoryFrictionCalculator:
    """Itemized premium-turnover tax and configurable spread/impact calculator."""
    def __init__(self, config: StatutoryCostConfig = StatutoryCostConfig()) -> None:
        self.config = config

    def calculate(
        self,
        legs: Sequence[OptionLeg],
        *,
        base_half_spread_per_unit: float = 0.0,
        kappa_shock: float = 0.0,
        shock_stress: float = 0.0,
        brokerage_per_order: float = 0.0,
        cross_impact_hurdle: float = 0.0,
    ) -> FrictionBreakdown:
        if not legs:
            raise ValueError("at least one option leg is required")
        half_spread = _nonnegative(base_half_spread_per_unit, "base_half_spread_per_unit")
        kappa = _nonnegative(kappa_shock, "kappa_shock")
        stress = _nonnegative(shock_stress, "shock_stress")
        brokerage = _nonnegative(brokerage_per_order, "brokerage_per_order")
        cross_impact = _nonnegative(cross_impact_hurdle, "cross_impact_hurdle")
        spread = half_spread * (1.0 + kappa * stress)
        buy_turnover = sum(leg.turnover for leg in legs if leg.side.upper() == "BUY")
        sell_turnover = sum(leg.turnover for leg in legs if leg.side.upper() == "SELL")
        total_turnover = buy_turnover + sell_turnover
        stt = sell_turnover * self.config.options_sell_stt_rate
        stamp = buy_turnover * self.config.buyer_stamp_rate
        exchange = total_turnover * self.config.exchange_fee_per_crore / CRORE_RUPEES
        sebi = total_turnover * self.config.sebi_fee_per_crore / CRORE_RUPEES
        gst_base = 0.0
        if "exchange_fee" in self.config.gst_on:
            gst_base += exchange
        if "sebi_fee" in self.config.gst_on:
            gst_base += sebi
        if "brokerage" in self.config.gst_on:
            gst_base += brokerage
        gst = gst_base * self.config.gst_rate
        slippage = sum(leg.quantity for leg in legs) * spread
        total = stt + exchange + sebi + brokerage + gst + stamp + slippage + cross_impact
        components = (buy_turnover, sell_turnover, total_turnover, stt, exchange, sebi, brokerage, gst, stamp, slippage, cross_impact, total)
        if not all(isfinite(v) and v >= 0 for v in components):
            raise ValueError("fee computation produced invalid values")
        return FrictionBreakdown(buy_turnover, sell_turnover, total_turnover, stt, exchange, sebi, brokerage, gst, stamp, slippage, cross_impact, total)

    @staticmethod
    def passes_profitability_gate(expected_gross_alpha: float, friction: FrictionBreakdown, extra_risk_hurdle: float = 0.0) -> bool:
        alpha = _finite(expected_gross_alpha, "expected_gross_alpha")
        hurdle = _nonnegative(extra_risk_hurdle, "extra_risk_hurdle")
        return alpha > friction.total + hurdle


@dataclass
class TradeFrequencyConfig:
    alpha_per_trade: float = 1000.0
    friction_per_trade: float = 250.0
    risk_penalty: float = 250.0
    minimum_cooldown_seconds: float = 900.0
    max_daily_trades: int = 100
    loss_streak_limit: int = 3
    revenge_ratio: float = 1.25
    minimum_fill_spacing_seconds: float = 30.0

    def __post_init__(self) -> None:
        for key, value in asdict(self).items():
            if key == "max_daily_trades" or key == "loss_streak_limit":
                if isinstance(value, bool) or int(value) != value or value < 0:
                    raise ValueError(f"{key} must be a nonnegative integer")
            else:
                _nonnegative(value, key)
        if self.risk_penalty <= 0 or self.minimum_cooldown_seconds <= 0 or self.revenge_ratio <= 1 or self.minimum_fill_spacing_seconds <= 0:
            raise ValueError("risk penalty, cooldown, pacing, and revenge ratio are invalid")
        if self.loss_streak_limit < 1:
            raise ValueError("loss_streak_limit must be >= 1")


class AntiOvertradingThrottler:
    def __init__(self, config: Optional[TradeFrequencyConfig] = None) -> None:
        self.config = config if config is not None else TradeFrequencyConfig()
        self.daily_trade_count = 0
        self.consecutive_losses = 0
        self.cooldown_until_epoch = 0.0
        self.last_fill_epoch: Optional[float] = None
        self.last_fill_size: Optional[float] = None
        self.lockout_reasons: list[str] = []

    def optimal_daily_trade_cap(self, alpha: Optional[float] = None, friction: Optional[float] = None, risk: Optional[float] = None) -> int:
        a = self.config.alpha_per_trade if alpha is None else _finite(alpha, "alpha")
        c = self.config.friction_per_trade if friction is None else _finite(friction, "friction")
        r = self.config.risk_penalty if risk is None else _finite(risk, "risk")
        if c < 0 or r <= 0:
            raise ValueError("friction must be nonnegative and risk must be positive")
        # User-specified approximation N*=max(0, round((alpha-c)/risk)); positive half rounds up.
        raw = (a - c) / r
        return min(self.config.max_daily_trades, max(0, int(raw + 0.5)))

    def _trigger_lockout(self, now_epoch: float, reason: str) -> None:
        self.cooldown_until_epoch = max(self.cooldown_until_epoch, now_epoch + self.config.minimum_cooldown_seconds)
        if reason not in self.lockout_reasons:
            self.lockout_reasons.append(reason)

    def record_fill(self, now_epoch: float, size: float) -> bool:
        now = _finite(now_epoch, "now_epoch")
        size = _nonnegative(size, "size")
        if size <= 0:
            raise ValueError("fill size must be positive")
        if self.last_fill_epoch is not None:
            delta = now - self.last_fill_epoch
            if delta < 0:
                raise ValueError("fill timestamps must be monotonic")
            if delta < self.config.minimum_fill_spacing_seconds:
                self._trigger_lockout(now, "rapid_fill_pacing")
            if self.last_fill_size is not None and size / self.last_fill_size > self.config.revenge_ratio:
                self._trigger_lockout(now, "revenge_sizing")
        self.last_fill_epoch, self.last_fill_size = now, size
        self.daily_trade_count += 1
        return self.is_locked(now)

    def record_outcome(self, pnl: float, now_epoch: float) -> bool:
        pnl = _finite(pnl, "pnl")
        now = _finite(now_epoch, "now_epoch")
        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.config.loss_streak_limit:
                self._trigger_lockout(now, "consecutive_losses")
        elif pnl > 0:
            self.consecutive_losses = 0
        return self.is_locked(now)

    def is_locked(self, now_epoch: Optional[float] = None) -> bool:
        now = time.time() if now_epoch is None else _finite(now_epoch, "now_epoch")
        return now < self.cooldown_until_epoch

    def may_enter(self, now_epoch: float, *, expected_alpha: float, friction: FrictionBreakdown, extra_risk_hurdle: float = 0.0) -> bool:
        now = _finite(now_epoch, "now_epoch")
        cap = self.optimal_daily_trade_cap()
        return (
            not self.is_locked(now)
            and self.daily_trade_count < cap
            and StatutoryFrictionCalculator.passes_profitability_gate(expected_alpha, friction, extra_risk_hurdle)
        )

    @property
    def active_cooldown_remaining(self) -> float:
        return max(0.0, self.cooldown_until_epoch - time.time())


class JumpRegime(str, Enum):
    NORMAL = "NORMAL"
    MACRO_STRESS = "MACRO_STRESS"
    EXTREME_SHOCK = "EXTREME_SHOCK"


@dataclass
class JumpIntensityFilter:
    baseline_intensity: float = 0.05
    news_intensity: float = 0.0
    decay_rate: float = 0.25
    filtered_intensity: float = 0.05
    last_update_epoch: Optional[float] = None
    regime: JumpRegime = JumpRegime.NORMAL

    def __post_init__(self) -> None:
        for key in ("baseline_intensity", "news_intensity", "decay_rate", "filtered_intensity"):
            _nonnegative(getattr(self, key), key)
        if self.decay_rate <= 0:
            raise ValueError("decay_rate must be positive")

    def update(self, shock_norm: float, now_epoch: float, news_urgency: float = 0.0) -> float:
        shock = _nonnegative(shock_norm, "shock_norm")
        now = _finite(now_epoch, "now_epoch")
        urgency = _clamp(_finite(news_urgency, "news_urgency"), 0.0, 1.0)
        if self.last_update_epoch is not None and now < self.last_update_epoch:
            raise ValueError("timestamps must be monotonic")
        dt = 0.0 if self.last_update_epoch is None else now - self.last_update_epoch
        decayed_news = self.news_intensity * exp(-self.decay_rate * dt)
        incoming = urgency * max(0.0, shock)
        self.news_intensity = decayed_news + incoming
        target = self.baseline_intensity + self.news_intensity + 0.1 * shock
        # Exponential filtering helps suppress one-frame signal jitter.
        weight = 1.0 if self.last_update_epoch is None else 1.0 - exp(-max(dt, 1e-9) / 5.0)
        self.filtered_intensity = (1 - weight) * self.filtered_intensity + weight * target
        self.regime = JumpRegime.EXTREME_SHOCK if shock >= 3.5 else JumpRegime.MACRO_STRESS if shock >= 1.5 or self.news_intensity >= 1.0 else JumpRegime.NORMAL
        self.last_update_epoch = now
        return self.filtered_intensity


class Cycle30ExecutionEngine:
    """Orchestrates macro transmission, cooldown/risk, costs, and telemetry.

    The engine generates analysis and paper decisions only; there is no live broker path.
    """
    def __init__(
        self,
        macro_model: Optional[MacroTransmissionModel] = None,
        cooldown: Optional[DynamicCooldownController] = None,
        costs: Optional[StatutoryFrictionCalculator] = None,
        throttler: Optional[AntiOvertradingThrottler] = None,
        jump_filter: Optional[JumpIntensityFilter] = None,
    ) -> None:
        self.macro_model = macro_model if macro_model is not None else MacroTransmissionModel()
        self.cooldown = cooldown if cooldown is not None else DynamicCooldownController()
        self.costs = costs if costs is not None else StatutoryFrictionCalculator()
        self.throttler = throttler if throttler is not None else AntiOvertradingThrottler()
        self.jump_filter = jump_filter if jump_filter is not None else JumpIntensityFilter()
        self.heartbeat_count = 0
        self.last_payload: Optional[Dict[str, Any]] = None

    def evaluate_spread(
        self,
        legs: Sequence[OptionLeg],
        expected_gross_alpha: float,
        now_epoch: float,
        *,
        base_half_spread_per_unit: float = 0.0,
        kappa_slippage: float = 0.0,
        cross_impact_hurdle: float = 0.0,
        extra_risk_hurdle: float = 0.0,
    ) -> Dict[str, Any]:
        if self.cooldown.emergency_latched or self.cooldown.stage is OperationalStage.STAGE_3_EMERGENCY_UNWIND:
            return {"approved": False, "reason": "emergency_unwind_latched", "costs": None, "net_expected_alpha": None}
        if self.cooldown.stage is OperationalStage.STAGE_2_QUARANTINE:
            return {"approved": False, "reason": "stage_2_quarantine", "costs": None, "net_expected_alpha": None}
        cost = self.costs.calculate(
            legs,
            base_half_spread_per_unit=base_half_spread_per_unit,
            kappa_shock=kappa_slippage,
            shock_stress=self.cooldown.last_shock_norm,
            cross_impact_hurdle=cross_impact_hurdle,
        )
        hurdle = _nonnegative(extra_risk_hurdle, "extra_risk_hurdle")
        if self.cooldown.stage is OperationalStage.STAGE_1_CAUTION:
            hurdle *= self.cooldown.alpha_hurdle_multiplier
        passed = self.throttler.may_enter(now_epoch, expected_alpha=expected_gross_alpha, friction=cost, extra_risk_hurdle=hurdle)
        return {
            "approved": passed,
            "reason": "alpha_clears_friction_and_risk_hurdle" if passed else "friction_risk_throttle_or_frequency_gate",
            "costs": cost.to_dict(),
            "net_expected_alpha": float(expected_gross_alpha - cost.total),
            "strict_hurdle": float(cost.total + hurdle),
        }

    def telemetry_payload(
        self,
        factors: MacroFactors,
        now: Optional[datetime] = None,
        *,
        base_surfaces: Optional[Mapping[str, SVIParameters]] = None,
        spread_recommendations: Optional[Sequence[Mapping[str, Any]]] = None,
        high_volatility_clustering: bool = False,
        market_disruption: bool = False,
        depth_ratio: float = 1.0,
        news_urgency: float = 0.0,
    ) -> Dict[str, Any]:
        dt = datetime.now(timezone.utc) if now is None else now
        if dt.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        utc_dt = dt.astimezone(timezone.utc)
        epoch = utc_dt.timestamp()
        stage = self.cooldown.evaluate(
            factors, self.macro_model, epoch,
            high_volatility_clustering=high_volatility_clustering,
            market_disruption=market_disruption,
            depth_ratio=depth_ratio,
        )
        surfaces = self.macro_model.transmit_both(factors)
        self.jump_filter.update(self.cooldown.last_shock_norm, epoch, news_urgency)
        z = factors.z_scores(self.macro_model.config.std_scales)
        stress = self.cooldown.last_shock_norm
        payload = {
            "schema_version": "1.0",
            "timestamp_ist": utc_dt.astimezone(IST).isoformat(),
            "timestamp_epoch": epoch,
            "dashboard_port": DASHBOARD_PORT,
            "macro_factors": {
                "innovations": dict(zip(("dy_us10y", "ddxy", "dbrent", "dvix"), factors.vector())),
                "z_scores": dict(zip(("dy_us10y", "ddxy", "dbrent", "dvix"), z)),
                "z_norm": stress,
            },
            "svi_surfaces": {
                name: {
                    "parameters": surf.svi.to_dict(),
                    "parameter_shifts": dict(surf.shifts),
                    "index_return_signal": surf.index_return_signal,
                    "smile_skew_tilt": surf.skew_tilt,
                    "put_call_iv_differential": surf.put_call_iv_diff,
                    "z_scores": surf.z_scores,
                }
                for name, surf in surfaces.items()
            },
            "jump_filter": {
                "filtered_intensity": self.jump_filter.filtered_intensity,
                "news_intensity": self.jump_filter.news_intensity,
                "regime": self.jump_filter.regime.value,
            },
            "recommended_spreads": list(spread_recommendations or []),
            "operational": {
                "heartbeat": "OK",
                "heartbeat_count": self.heartbeat_count + 1,
                "stage": stage.value,
                "cooldown_remaining_seconds": self.cooldown.remaining(epoch),
                "cooldown_until_epoch": self.cooldown.cooldown_until_epoch,
                "new_entries_allowed": self.cooldown.new_entries_allowed,
                "passive_risk_hedge_only": self.cooldown.passive_risk_hedge_only,
                "delta_band_multiplier": self.cooldown.band_multiplier,
                "alpha_hurdle_multiplier": self.cooldown.alpha_hurdle_multiplier,
                "last_reason": self.cooldown.last_reason,
                "daily_trade_count": self.throttler.daily_trade_count,
                "daily_trade_cap": self.throttler.optimal_daily_trade_cap(),
                "tilt_cooldown_remaining_seconds": max(0.0, self.throttler.cooldown_until_epoch - epoch),
                "tilt_lockout_reasons": list(self.throttler.lockout_reasons),
                "risk_state": stage.value,
                "LIVE_ORDER_DISPATCH_ENABLED": False,
            },
        }
        # JSON strictness: all values are ordinary finite JSON-compatible values.
        json.dumps(payload, allow_nan=False)
        self.heartbeat_count += 1
        self.last_payload = payload
        return payload

    @staticmethod
    def json_poll(payload: Mapping[str, Any]) -> str:
        return json.dumps(payload, separators=(",", ":"), allow_nan=False)

    @staticmethod
    def sse_frame(payload: Mapping[str, Any], event: str = "telemetry", event_id: Optional[str] = None) -> str:
        if not event or any(ch in event for ch in "\r\n"):
            raise ValueError("SSE event must be nonempty and single-line")
        lines = []
        if event_id is not None:
            id_text = str(event_id)
            if any(ch in id_text for ch in "\r\n"):
                raise ValueError("SSE id must be single-line")
            lines.append(f"id: {id_text}")
        lines.append(f"event: {event}")
        lines.append("data: " + Cycle30ExecutionEngine.json_poll(payload))
        return "\n".join(lines) + "\n\n"

    def stream(self, snapshots: Iterable[Tuple[MacroFactors, datetime]]) -> Iterator[str]:
        """Yield SSE frames for supplied snapshots; does not sleep or block."""
        for factors, now in snapshots:
            yield self.sse_frame(self.telemetry_payload(factors, now))


def build_demo_factors() -> MacroFactors:
    """Deterministic high-shock macro innovations for the example script."""
    return MacroFactors(dy_us10y=0.12, ddxy=1.8, dbrent=5.0, dvix=12.0)


SnapshotProvider = Callable[[], Mapping[str, Any]]


def create_dashboard_server(
    engine: Cycle30ExecutionEngine,
    snapshot_provider: SnapshotProvider,
    *,
    host: str = "127.0.0.1",
    port: int = DASHBOARD_PORT,
    stream_interval_seconds: float = 1.0,
) -> ThreadingHTTPServer:
    """Create an optional local JSON/SSE dashboard server using stdlib HTTP.

    `snapshot_provider` returns a mapping with required key `factors` (MacroFactors),
    optional key `now` (timezone-aware datetime), and optional telemetry kwargs such
    as `news_urgency`, `depth_ratio`, `market_disruption`, `high_volatility_clustering`,
    and `spread_recommendations`. The server is not started automatically.
    """
    interval = _finite(stream_interval_seconds, "stream_interval_seconds")
    if interval <= 0:
        raise ValueError("stream_interval_seconds must be positive")

    def make_payload() -> Dict[str, Any]:
        snap = snapshot_provider()
        if not isinstance(snap, Mapping) or not isinstance(snap.get("factors"), MacroFactors):
            raise ValueError("snapshot_provider must return mapping with MacroFactors under 'factors'")
        now_value = snap.get("now", datetime.now(timezone.utc))
        allowed = {
            "base_surfaces", "spread_recommendations", "high_volatility_clustering",
            "market_disruption", "depth_ratio", "news_urgency",
        }
        kwargs = {key: value for key, value in snap.items() if key in allowed}
        return engine.telemetry_payload(snap["factors"], now_value, **kwargs)

    class DashboardHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            # Avoid noisy access logs in the local dashboard service.
            return

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path == "/health":
                payload = {"status": "ok", "port": self.server.server_port, "live_order_dispatch_enabled": False}
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/telemetry":
                try:
                    body = json.dumps(make_payload(), separators=(",", ":"), allow_nan=False).encode("utf-8")
                except Exception as exc:
                    body = json.dumps({"error": str(exc)}).encode("utf-8")
                    self.send_response(503)
                else:
                    self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    while True:
                        frame = Cycle30ExecutionEngine.sse_frame(make_payload())
                        self.wfile.write(frame.encode("utf-8"))
                        self.wfile.flush()
                        time.sleep(interval)
                except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                    return
                return
            body = b'{"error":"not found","routes":["/health","/telemetry","/events"]}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class DashboardHTTPServer(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    return DashboardHTTPServer((host, int(port)), DashboardHandler)

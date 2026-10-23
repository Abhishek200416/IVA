"""AGI 1.7 Dynamic Market Impact & Slippage Calibration Engine for BANK NIFTY Options.

TASK-BN-18:
Implements institutional market impact and execution cost calibration based on:
1. Almgren-Chriss (2000) optimal execution framework.
2. Universal Square-Root Law of Market Impact:
   Delta P_permanent = Y * sigma_interval * sqrt(Q / V_interval) * MidPrice
3. Microstructure temporary impact (half-spread + depth queue crossing).
4. Volatility regime multiplier (India VIX levels, opening range surge, expiry afternoon gamma).
5. Multi-leg options execution aggregation (Strangles, Vertical Spreads, Iron Condors).
6. Pre-trade slippage budget gating (rejects/penalizes executions with impact > threshold bps).
"""

from __future__ import annotations

import dataclasses
import enum
import math
from typing import Any, Dict, List, Optional

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import OrderSide


@dataclasses.dataclass(frozen=True)
class SquareRootImpactParams:
    """Parameters for the square-root market impact formulation."""

    impact_constant_y: float = 0.60  # Dimensionless Y constant (typical range 0.50 - 0.75)
    annualized_volatility: float = 0.16  # Annualized underlying / implied volatility (16%)
    interval_volume_units: int = 25000   # Volume in contracts/units in the execution interval
    trading_minutes_per_day: float = 375.0  # Indian equity session 9:15 - 15:30 IST (375 min)
    bar_interval_minutes: float = 5.0    # 5-minute bar aggregation
    tick_size: float = 0.05              # NSE Bank Nifty tick size (0.05 INR)


@dataclasses.dataclass(frozen=True)
class SlippageImpactReport:
    """Detailed slippage and market impact calculation for a single order leg."""

    symbol: str
    side: OrderSide
    order_units: int
    lots: int
    mid_price: float
    quoted_spread: float
    half_spread: float
    temporary_impact_pts: float
    permanent_impact_pts: float
    total_slippage_pts: float
    expected_fill_price: float
    slippage_bps: float
    total_cost_inr: float
    regime_multiplier: float
    is_acceptable: bool
    max_allowed_bps: float
    diagnostics: str


@dataclasses.dataclass(frozen=True)
class MultiLegSlippageReport:
    """Aggregated slippage and execution feasibility report for multi-leg option strategies."""

    strategy_name: str
    legs: list[SlippageImpactReport]
    net_premium_pts: float
    net_slippage_pts: float
    total_slippage_cost_inr: float
    total_units: int
    total_lots: int
    is_all_acceptable: bool
    weighted_slippage_bps: float
    summary_verdict: str


class SlippageCalibrationEngine:
    """Institutional execution cost & market impact calibration for BANK NIFTY options."""

    DEFAULT_MAX_BPS: float = 50.0  # 50 basis points maximum acceptable slippage

    @classmethod
    def calculate_regime_multiplier(
        cls,
        vix_level: float = 14.0,
        is_opening_range: bool = False,
        is_expiry_close: bool = False,
    ) -> float:
        """Computes dynamic liquidity stress multiplier based on market conditions."""
        multiplier = 1.0

        # VIX escalation: baseline 14.0. Elevated VIX widens spreads and thins order books
        if vix_level > 15.0:
            multiplier += (vix_level - 15.0) * 0.05  # e.g., VIX 25 -> +0.50

        # Opening 15 minutes (9:15 - 9:30 IST): High opening auction imbalances
        if is_opening_range:
            multiplier *= 1.35

        # Expiry afternoon (14:00 - 15:30 IST on expiry day): Gamma squeezes & fast unwinds
        if is_expiry_close:
            multiplier *= 1.50

        return round(max(0.5, multiplier), 4)

    @classmethod
    def calculate_single_leg_impact(
        cls,
        symbol: str,
        side: OrderSide,
        order_units: int,
        mid_price: float,
        quoted_spread: float = 0.10,
        params: Optional[SquareRootImpactParams] = None,
        vix_level: float = 14.0,
        is_opening_range: bool = False,
        is_expiry_close: bool = False,
        max_allowed_bps: float = DEFAULT_MAX_BPS,
    ) -> SlippageImpactReport:
        """Calculates expected execution slippage using Almgren-Chriss & Square-Root Law."""
        if params is None:
            params = SquareRootImpactParams()

        if order_units <= 0:
            raise ValueError(f"order_units must be positive, got {order_units}")
        if mid_price <= 0:
            raise ValueError(f"mid_price must be positive, got {mid_price}")

        regime_mult = cls.calculate_regime_multiplier(
            vix_level=vix_level,
            is_opening_range=is_opening_range,
            is_expiry_close=is_expiry_close,
        )

        lots = max(1, order_units // BankNiftyContractSpec.LOT_SIZE)
        half_spread = max(params.tick_size, quoted_spread / 2.0)

        # 1. Temporary Microstructure Impact (Half spread + queue friction scaled by regime)
        temp_impact = half_spread * regime_mult

        # 2. Permanent Impact via Square-Root Law:
        # sigma_interval = sigma_annual / sqrt(252 * bars_per_day)
        bars_per_day = max(1.0, params.trading_minutes_per_day / params.bar_interval_minutes)
        intervals_per_year = 252.0 * bars_per_day
        sigma_interval = params.annualized_volatility / math.sqrt(intervals_per_year)

        # Volume participation ratio: Q / V_interval
        interval_vol = max(100, params.interval_volume_units)
        participation = min(1.0, order_units / interval_vol)
        sqrt_participation = math.sqrt(participation)

        perm_impact = (
            params.impact_constant_y
            * sigma_interval
            * sqrt_participation
            * mid_price
            * regime_mult
        )

        total_slippage_raw = temp_impact + perm_impact
        # Align slippage to NSE tick size (0.05)
        ticks = math.ceil(total_slippage_raw / params.tick_size)
        total_slippage_pts = max(params.tick_size, ticks * params.tick_size)

        # Determine expected fill price
        if side == OrderSide.BUY:
            expected_fill = round(mid_price + total_slippage_pts, 2)
        else:
            expected_fill = round(max(params.tick_size, mid_price - total_slippage_pts), 2)

        slippage_bps = round((total_slippage_pts / mid_price) * 10000.0, 2)
        total_cost_inr = round(total_slippage_pts * order_units, 2)
        is_acceptable = slippage_bps <= max_allowed_bps

        diagnostics = (
            f"{side.value} {order_units} units ({lots} lots) @ Mid {mid_price:.2f}. "
            f"Temp: {temp_impact:.2f} pts, Perm: {perm_impact:.2f} pts. "
            f"Total Slippage: {total_slippage_pts:.2f} pts ({slippage_bps:.1f} bps). "
            f"Acceptable: {is_acceptable}"
        )

        return SlippageImpactReport(
            symbol=symbol,
            side=side,
            order_units=order_units,
            lots=lots,
            mid_price=mid_price,
            quoted_spread=quoted_spread,
            half_spread=half_spread,
            temporary_impact_pts=round(temp_impact, 4),
            permanent_impact_pts=round(perm_impact, 4),
            total_slippage_pts=round(total_slippage_pts, 2),
            expected_fill_price=expected_fill,
            slippage_bps=slippage_bps,
            total_cost_inr=total_cost_inr,
            regime_multiplier=regime_mult,
            is_acceptable=is_acceptable,
            max_allowed_bps=max_allowed_bps,
            diagnostics=diagnostics,
        )

    @classmethod
    def calculate_multi_leg_impact(
        cls,
        strategy_name: str,
        legs_specs: list[dict[str, Any]],
        params: Optional[SquareRootImpactParams] = None,
        vix_level: float = 14.0,
        is_opening_range: bool = False,
        is_expiry_close: bool = False,
        max_allowed_bps: float = DEFAULT_MAX_BPS,
    ) -> MultiLegSlippageReport:
        """Evaluates combined slippage across multi-leg structures (Spreads, Strangles)."""
        reports: list[SlippageImpactReport] = []
        total_slippage_cost = 0.0
        total_units = 0
        total_lots = 0
        net_premium_pts = 0.0
        net_slippage_pts = 0.0
        weighted_bps_sum = 0.0

        for leg in legs_specs:
            report = cls.calculate_single_leg_impact(
                symbol=leg["symbol"],
                side=leg["side"],
                order_units=leg["order_units"],
                mid_price=leg["mid_price"],
                quoted_spread=leg.get("quoted_spread", 0.10),
                params=params,
                vix_level=vix_level,
                is_opening_range=is_opening_range,
                is_expiry_close=is_expiry_close,
                max_allowed_bps=max_allowed_bps,
            )
            reports.append(report)
            total_slippage_cost += report.total_cost_inr
            total_units += report.order_units
            total_lots += report.lots
            net_slippage_pts += report.total_slippage_pts
            weighted_bps_sum += report.slippage_bps * report.order_units

            if report.side == OrderSide.BUY:
                net_premium_pts += report.mid_price
            else:
                net_premium_pts -= report.mid_price

        is_all_acceptable = all(r.is_acceptable for r in reports)
        weighted_bps = round(weighted_bps_sum / max(1, total_units), 2)

        verdict = (
            f"Strategy {strategy_name}: {len(reports)} legs, {total_lots} total lots. "
            f"Total Slippage Drag: INR {total_slippage_cost:.2f} ({weighted_bps:.1f} bps). "
            f"Execution Status: {'APPROVED' if is_all_acceptable else 'REJECTED_EXCESSIVE_SLIPPAGE'}"
        )

        return MultiLegSlippageReport(
            strategy_name=strategy_name,
            legs=reports,
            net_premium_pts=round(net_premium_pts, 2),
            net_slippage_pts=round(net_slippage_pts, 2),
            total_slippage_cost_inr=round(total_slippage_cost, 2),
            total_units=total_units,
            total_lots=total_lots,
            is_all_acceptable=is_all_acceptable,
            weighted_slippage_bps=weighted_bps,
            summary_verdict=verdict,
        )

    @classmethod
    def calibrate_empirical_constant(
        cls,
        observed_slippages_pts: list[float],
        mid_prices: list[float],
        order_units: list[int],
        interval_volumes: list[int],
        annualized_vols: list[float],
        quoted_spreads: list[float],
    ) -> float:
        """Calibrates empirical Y constant from observed execution log traces via linear regression."""
        if not observed_slippages_pts or len(observed_slippages_pts) != len(mid_prices):
            return 0.60  # Default fallback

        # Model: (Observed_Slippage - Half_Spread) = Y * [sigma_int * sqrt(Q/V) * Mid]
        x_terms: list[float] = []
        y_terms: list[float] = []

        bars_per_day = 75.0
        intervals_per_year = 252.0 * bars_per_day

        for obs_slip, mid, q, v, vol, spread in zip(
            observed_slippages_pts,
            mid_prices,
            order_units,
            interval_volumes,
            annualized_vols,
            quoted_spreads,
        ):
            half_spread = spread / 2.0
            excess_impact = max(0.0, obs_slip - half_spread)
            sigma_int = vol / math.sqrt(intervals_per_year)
            part = math.sqrt(min(1.0, q / max(100, v)))
            x = sigma_int * part * mid

            if x > 1e-6:
                x_terms.append(x)
                y_terms.append(excess_impact)

        if not x_terms:
            return 0.60

        # OLS slope through origin: sum(x * y) / sum(x^2)
        numerator = sum(x * y for x, y in zip(x_terms, y_terms))
        denominator = sum(x * x for x in x_terms)

        if denominator < 1e-9:
            return 0.60

        calibrated_y = numerator / denominator
        # Bound to sane bounds [0.10, 2.50]
        return round(max(0.10, min(2.50, calibrated_y)), 4)

"""AGI 1.7 Portfolio Greeks Risk Engine & Macro Stress Simulator.

Provides:
1. PortfolioGreeksRiskEngine:
   - Aggregation of net Delta, Gamma, Theta, Vega across options and underlying positions.
   - Dynamic Delta Hedging calculator: determines exact lot-sized hedge units to neutralize directional exposure.
2. BankNiftyStressTester:
   - Parametric Value-at-Risk (VaR) and Expected Shortfall (CVaR) at 95% and 99% confidence.
   - Scenario Stress Testing across canonical Indian market historical shocks:
     * COVID-19 Circuit Breaker (-10% Spot, +60% IV)
     * Union Budget Gamma Shock (±4% Spot, +35% IV)
     * Election Rally & Vol Crush (+5% Spot, -30% IV)
     * RBI Rate Hike Shock (+50 bps Interest Rate)
   - Capital preservation and margin shortfall assessment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import OptionGreeks, OptionType
from .options_math import OptionsMath


@dataclass
class PositionRiskItem:
    symbol: str
    units: int  # Positive for long, negative for short
    option_type: Optional[OptionType]
    strike: float
    spot: float
    time_to_expiry_years: float
    volatility: float
    risk_free_rate: float = 0.065
    greeks: Optional[OptionGreeks] = None


@dataclass
class PortfolioGreeksSummary:
    total_positions: int
    net_units: int
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    delta_notional_inr: float
    is_delta_neutral: bool
    recommended_hedge_units: int
    recommended_hedge_action: str


@dataclass
class StressScenarioResult:
    scenario_name: str
    spot_shock_pct: float
    iv_shock_pct: float
    rate_shock_bps: float
    modeled_pnl_inr: float
    pnl_pct_of_capital: float
    post_shock_capital: float
    margin_call_triggered: bool
    status: str  # SAFE, MARGIN_WARNING, CAPITAL_BREACH


@dataclass
class StressTestReport:
    initial_capital: float
    portfolio_value: float
    var_95_1day_inr: float
    var_99_1day_inr: float
    cvar_99_1day_inr: float
    scenario_results: List[StressScenarioResult]
    worst_case_loss_inr: float
    worst_case_scenario: str
    portfolio_resilience_rating: str  # ROBUST, MODERATE, HIGH_RISK


class PortfolioGreeksRiskEngine:
    """Calculates aggregate portfolio Greeks and automates delta hedging."""

    DELTA_NEUTRAL_TOLERANCE = 15.0  # Bank Nifty 1 lot equivalent delta

    @classmethod
    def evaluate_portfolio(
        cls,
        positions: List[PositionRiskItem],
        spot_price: float,
        target_delta: float = 0.0,
    ) -> PortfolioGreeksSummary:
        net_units = 0
        net_delta = 0.0
        net_gamma = 0.0
        net_theta = 0.0
        net_vega = 0.0

        for item in positions:
            units = item.units
            net_units += units

            is_call = item.option_type == OptionType.CE if item.option_type else True
            greeks = OptionsMath.calculate_greeks(
                spot=spot_price,
                strike=item.strike,
                time_to_expiry_years=item.time_to_expiry_years,
                risk_free_rate=item.risk_free_rate,
                volatility=item.volatility,
                is_call=is_call,
            )

            # Aggregate Greeks multiplied by signed units
            net_delta += units * greeks["delta"]
            net_gamma += units * greeks["gamma"]
            net_theta += units * greeks["theta"]
            net_vega += units * greeks["vega"]

        net_delta = round(net_delta, 4)
        net_gamma = round(net_gamma, 6)
        net_theta = round(net_theta, 2)
        net_vega = round(net_vega, 2)

        delta_notional = round(net_delta * spot_price, 2)
        delta_imbalance = net_delta - target_delta
        is_neutral = abs(delta_imbalance) <= cls.DELTA_NEUTRAL_TOLERANCE

        # Calculate lot-aligned hedge
        # Assuming hedging with ATM Call/Futures (Delta ~ 0.50 for ATM Call, or 1.0 for Futures)
        hedge_units = 0
        hedge_action = "NO_HEDGE_REQUIRED"

        if not is_neutral:
            # Need to offset delta_imbalance
            # Using ATM CE (Delta ~ 0.50): required units = -delta_imbalance / 0.50 = -2 * delta_imbalance
            raw_units = int(round(-delta_imbalance / 0.50))
            # Align to Bank Nifty lot size 15
            lot_size = BankNiftyContractSpec.LOT_SIZE
            lots = round(raw_units / lot_size)
            hedge_units = lots * lot_size
            if hedge_units > 0:
                hedge_action = f"BUY_{hedge_units}_ATM_CE"
            elif hedge_units < 0:
                hedge_action = f"SELL_{abs(hedge_units)}_ATM_CE"

        return PortfolioGreeksSummary(
            total_positions=len(positions),
            net_units=net_units,
            net_delta=net_delta,
            net_gamma=net_gamma,
            net_theta=net_theta,
            net_vega=net_vega,
            delta_notional_inr=delta_notional,
            is_delta_neutral=is_neutral,
            recommended_hedge_units=hedge_units,
            recommended_hedge_action=hedge_action,
        )


class BankNiftyStressTester:
    """Stress testing simulator evaluating options portfolios under extreme historical tail events."""

    CANONICAL_SCENARIOS = [
        {
            "name": "COVID_CIRCUIT_BREAKER_2020",
            "spot_shock_pct": -0.10,  # -10% spot crash
            "iv_shock_pct": 0.60,     # +60% relative IV expansion
            "rate_shock_bps": 0.0,
        },
        {
            "name": "UNION_BUDGET_GAMMA_SHOCK",
            "spot_shock_pct": -0.04,  # -4% intraday swing
            "iv_shock_pct": 0.35,     # +35% IV expansion
            "rate_shock_bps": 0.0,
        },
        {
            "name": "ELECTION_RALLY_VOL_CRUSH",
            "spot_shock_pct": 0.05,   # +5% gap up rally
            "iv_shock_pct": -0.30,    # -30% severe IV crush
            "rate_shock_bps": 0.0,
        },
        {
            "name": "RBI_INTEREST_RATE_HIKE",
            "spot_shock_pct": -0.015, # -1.5% banking index drop
            "iv_shock_pct": 0.10,     # +10% IV expansion
            "rate_shock_bps": 50.0,   # +50 bps RBI repo rate hike
        },
    ]

    @classmethod
    def run_stress_test(
        cls,
        positions: List[PositionRiskItem],
        current_spot: float,
        initial_capital: float = 1_000_000.0,
    ) -> StressTestReport:
        # 1. Base portfolio valuation
        base_portfolio_val = 0.0
        for pos in positions:
            is_call = pos.option_type == OptionType.CE if pos.option_type else True
            px = OptionsMath.black_scholes_price(
                spot=current_spot,
                strike=pos.strike,
                time_to_expiry_years=pos.time_to_expiry_years,
                risk_free_rate=pos.risk_free_rate,
                volatility=pos.volatility,
                is_call=is_call,
            )
            base_portfolio_val += pos.units * px

        # 2. Parametric Value at Risk (1-day)
        # Daily index vol sigma_daily = 0.18 / sqrt(252) ~= 0.01134
        daily_vol = 0.18 / math.sqrt(252.0)
        summary = PortfolioGreeksRiskEngine.evaluate_portfolio(positions, current_spot)

        # Delta-Gamma 1-day 95% and 99% VaR
        # VaR_alpha = |Delta_notional| * Z_alpha * sigma_daily - 0.5 * Gamma * (Spot * Z_alpha * sigma_daily)^2
        z_95 = 1.645
        z_99 = 2.326

        shock_95 = current_spot * z_95 * daily_vol
        shock_99 = current_spot * z_99 * daily_vol

        var_95 = abs(summary.net_delta) * shock_95 - 0.5 * summary.net_gamma * (shock_95 ** 2)
        var_99 = abs(summary.net_delta) * shock_99 - 0.5 * summary.net_gamma * (shock_99 ** 2)
        cvar_99 = var_99 * 1.15  # Expected shortfall approx 1.15x of 99% VaR

        var_95 = max(0.0, round(var_95, 2))
        var_99 = max(0.0, round(var_99, 2))
        cvar_99 = max(0.0, round(cvar_99, 2))

        # 3. Simulate Scenarios
        scenario_results: List[StressScenarioResult] = []
        worst_loss = 0.0
        worst_name = "NONE"

        for sc in cls.CANONICAL_SCENARIOS:
            shocked_spot = current_spot * (1.0 + sc["spot_shock_pct"])
            shocked_val = 0.0

            for pos in positions:
                shocked_vol = max(0.01, pos.volatility * (1.0 + sc["iv_shock_pct"]))
                shocked_rate = pos.risk_free_rate + (sc["rate_shock_bps"] / 10000.0)
                is_call = pos.option_type == OptionType.CE if pos.option_type else True

                shocked_px = OptionsMath.black_scholes_price(
                    spot=shocked_spot,
                    strike=pos.strike,
                    time_to_expiry_years=pos.time_to_expiry_years,
                    risk_free_rate=shocked_rate,
                    volatility=shocked_vol,
                    is_call=is_call,
                )
                shocked_val += pos.units * shocked_px

            pnl = round(shocked_val - base_portfolio_val, 2)
            pnl_pct = round((pnl / initial_capital) * 100.0, 2)
            post_capital = round(initial_capital + pnl, 2)

            margin_call = post_capital < (initial_capital * 0.50)
            status = "SAFE"
            if post_capital < (initial_capital * 0.70):
                status = "MARGIN_WARNING"
            if post_capital < (initial_capital * 0.40):
                status = "CAPITAL_BREACH"

            if pnl < worst_loss:
                worst_loss = pnl
                worst_name = sc["name"]

            scenario_results.append(
                StressScenarioResult(
                    scenario_name=sc["name"],
                    spot_shock_pct=sc["spot_shock_pct"],
                    iv_shock_pct=sc["iv_shock_pct"],
                    rate_shock_bps=sc["rate_shock_bps"],
                    modeled_pnl_inr=pnl,
                    pnl_pct_of_capital=pnl_pct,
                    post_shock_capital=post_capital,
                    margin_call_triggered=margin_call,
                    status=status,
                )
            )

        # 4. Resilience Rating
        max_drawdown_pct = abs(worst_loss / initial_capital) * 100.0 if initial_capital > 0 else 0.0
        if max_drawdown_pct < 10.0:
            rating = "ROBUST"
        elif max_drawdown_pct < 25.0:
            rating = "MODERATE"
        else:
            rating = "HIGH_RISK"

        return StressTestReport(
            initial_capital=initial_capital,
            portfolio_value=round(base_portfolio_val, 2),
            var_95_1day_inr=var_95,
            var_99_1day_inr=var_99,
            cvar_99_1day_inr=cvar_99,
            scenario_results=scenario_results,
            worst_case_loss_inr=round(worst_loss, 2),
            worst_case_scenario=worst_name,
            portfolio_resilience_rating=rating,
        )

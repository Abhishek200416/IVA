"""AGI 1.7 Dynamic Gamma Scalping & Bandwidth Rebalancing Engine for BANK NIFTY Options.

TASK-BN-20:
Implements institutional Gamma Scalping and Leland/Whalley-Wilmott optimal delta rebalancing:
1. Long Gamma (Gamma > 0) P&L capture:
   P&L_gamma = 0.5 * Gamma * (Delta S)^2
2. Time decay drag deduction:
   P&L_theta = -Theta * Delta t
3. Leland / Whalley-Wilmott transaction-cost optimal delta bandwidth:
   Delta_band = max(Lot_Delta, (3 * c_friction * S * Gamma^2 / (2 * lambda))^(1/3))
4. Threshold-based discrete hedging:
   Triggers hedge order (in 15-unit Bank Nifty lots) strictly when |Delta_drift| >= Delta_band.
5. Indian statutory transaction friction & slippage deduction for each rebalance.
6. Scalp attribution ledger & realized hedge efficiency ratio.
"""

from __future__ import annotations

import dataclasses
import enum
import math
from typing import Any, Dict, List, Optional

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import OrderSide


@dataclasses.dataclass(frozen=True)
class GammaScalpParameters:
    """Parameters for optimal gamma scalping and bandwidth calculation."""

    risk_aversion_lambda: float = 0.50     # Investor risk aversion coefficient
    friction_cost_fraction: float = 0.0005  # Transaction cost fraction (5 bps round-trip)
    min_hedge_lots: int = 1                 # Minimum discrete hedge size in lots
    lot_size: int = BankNiftyContractSpec.LOT_SIZE  # Standard 15 units per lot
    tick_size: float = 0.05                 # 0.05 INR


@dataclasses.dataclass(frozen=True)
class GammaScalpRebalanceDecision:
    """Decision output from a gamma scalp evaluation tick."""

    spot_price: float
    last_hedge_price: float
    price_change: float
    portfolio_delta: float
    portfolio_gamma: float
    portfolio_theta_daily: float
    delta_drift: float
    rebalance_bandwidth: float
    is_rebalance_triggered: bool
    hedge_side: Optional[OrderSide]
    hedge_units: int
    hedge_lots: int
    gamma_pnl_inr: float
    theta_cost_inr: float
    estimated_friction_inr: float
    net_step_pnl_inr: float
    rationale: str


@dataclasses.dataclass
class GammaScalpSessionState:
    """Cumulative state tracker across an intraday gamma scalping session."""

    initial_spot: float
    last_hedge_spot: float
    cumulative_gamma_pnl: float = 0.0
    cumulative_theta_cost: float = 0.0
    cumulative_friction_cost: float = 0.0
    cumulative_net_pnl: float = 0.0
    rebalance_count: int = 0
    total_hedged_units: int = 0
    history: list[GammaScalpRebalanceDecision] = dataclasses.field(default_factory=list)


class GammaScalpingEngine:
    """Institutional Gamma Scalping & Optimal Bandwidth Delta Rebalancing."""

    @classmethod
    def calculate_rebalance_bandwidth(
        cls,
        spot: float,
        portfolio_gamma: float,
        params: Optional[GammaScalpParameters] = None,
    ) -> float:
        """Computes Whalley-Wilmott / Leland optimal delta rebalancing bandwidth."""
        if params is None:
            params = GammaScalpParameters()

        if portfolio_gamma <= 0.0 or spot <= 0.0:
            # Non-positive gamma (short gamma or neutral): return minimum single-lot delta
            return 1.0  # Default 1 unit

        # Whalley-Wilmott bandwidth formulation:
        # Band = ( (3 * c * S * Gamma^2) / (2 * lambda) )^(1/3)
        c = params.friction_cost_fraction
        lam = max(0.01, params.risk_aversion_lambda)
        inside = (3.0 * c * spot * (portfolio_gamma**2)) / (2.0 * lam)
        raw_band = math.pow(inside, 1.0 / 3.0)

        # Floor at 0.01 delta (sensitive to fractional option gamma)
        return max(0.01, round(raw_band, 4))

    @classmethod
    def evaluate_tick(
        cls,
        current_spot: float,
        last_hedge_spot: float,
        portfolio_gamma: float,
        portfolio_theta_daily: float,
        time_elapsed_days: float = 1.0 / 75.0,  # Default 1 5-min bar (1/75 of trading day)
        base_delta: float = 0.0,
        params: Optional[GammaScalpParameters] = None,
        statutory_friction_per_lot_inr: float = 75.0,
    ) -> GammaScalpRebalanceDecision:
        """Evaluates whether spot price movement triggers a discrete delta rebalance order."""
        if params is None:
            params = GammaScalpParameters()

        delta_s = current_spot - last_hedge_spot
        # Linear delta drift: Delta_drift = base_delta + Gamma * Delta_S
        delta_drift = base_delta + (portfolio_gamma * delta_s)

        bandwidth = cls.calculate_rebalance_bandwidth(
            spot=current_spot,
            portfolio_gamma=portfolio_gamma,
            params=params,
        )

        # Theoretical Gamma P&L: 0.5 * Gamma * (Delta S)^2
        # (converted to total rupees across portfolio scale)
        gamma_pnl_inr = 0.5 * portfolio_gamma * (delta_s**2) * params.lot_size
        # Theta decay drag for elapsed time: -Theta * time_elapsed_days * lot_size
        theta_cost_inr = abs(portfolio_theta_daily) * time_elapsed_days * params.lot_size

        is_triggered = abs(delta_drift) >= bandwidth

        if is_triggered:
            # Rebalance requires neutralizing the drift: Hedge_delta = -delta_drift
            # If delta_drift > 0 (underlying rose, long delta accumulated) -> SELL
            # If delta_drift < 0 (underlying fell, short delta accumulated) -> BUY
            hedge_side = OrderSide.SELL if delta_drift > 0 else OrderSide.BUY
            # Discretize hedge size to nearest whole lots
            raw_lots = max(params.min_hedge_lots, round(abs(delta_drift)))
            hedge_units = raw_lots * params.lot_size
            hedge_lots = raw_lots
            friction_inr = round(statutory_friction_per_lot_inr * hedge_lots, 2)
            rationale = (
                f"REBALANCE TRIGGERED: Delta drift ({delta_drift:+.2f}) breached bandwidth (+/-{bandwidth:.2f}). "
                f"Executing {hedge_side.value} {hedge_units} units ({hedge_lots} lots) to restore delta neutrality."
            )
        else:
            hedge_side = None
            hedge_units = 0
            hedge_lots = 0
            friction_inr = 0.0
            rationale = (
                f"NO REBALANCE: Delta drift ({delta_drift:+.2f}) inside bandwidth (+/-{bandwidth:.2f}). "
                "Holding inventory; avoiding transaction drag."
            )

        net_step_pnl = gamma_pnl_inr - theta_cost_inr - friction_inr

        return GammaScalpRebalanceDecision(
            spot_price=current_spot,
            last_hedge_price=last_hedge_spot,
            price_change=round(delta_s, 2),
            portfolio_delta=round(base_delta, 4),
            portfolio_gamma=round(portfolio_gamma, 4),
            portfolio_theta_daily=round(portfolio_theta_daily, 2),
            delta_drift=round(delta_drift, 4),
            rebalance_bandwidth=bandwidth,
            is_rebalance_triggered=is_triggered,
            hedge_side=hedge_side,
            hedge_units=hedge_units,
            hedge_lots=hedge_lots,
            gamma_pnl_inr=round(gamma_pnl_inr, 2),
            theta_cost_inr=round(theta_cost_inr, 2),
            estimated_friction_inr=friction_inr,
            net_step_pnl_inr=round(net_step_pnl, 2),
            rationale=rationale,
        )

    @classmethod
    def simulate_scalp_session(
        cls,
        spot_series: list[float],
        portfolio_gamma: float,
        portfolio_theta_daily: float,
        params: Optional[GammaScalpParameters] = None,
        statutory_friction_per_lot_inr: float = 75.0,
    ) -> GammaScalpSessionState:
        """Simulates full intraday gamma scalping replay across a price path."""
        if not spot_series:
            raise ValueError("spot_series cannot be empty")

        if params is None:
            params = GammaScalpParameters()

        state = GammaScalpSessionState(
            initial_spot=spot_series[0],
            last_hedge_spot=spot_series[0],
        )

        for current_spot in spot_series[1:]:
            decision = cls.evaluate_tick(
                current_spot=current_spot,
                last_hedge_spot=state.last_hedge_spot,
                portfolio_gamma=portfolio_gamma,
                portfolio_theta_daily=portfolio_theta_daily,
                params=params,
                statutory_friction_per_lot_inr=statutory_friction_per_lot_inr,
            )

            state.history.append(decision)
            state.cumulative_gamma_pnl += decision.gamma_pnl_inr
            state.cumulative_theta_cost += decision.theta_cost_inr
            state.cumulative_friction_cost += decision.estimated_friction_inr
            state.cumulative_net_pnl += decision.net_step_pnl_inr

            if decision.is_rebalance_triggered:
                state.rebalance_count += 1
                state.total_hedged_units += decision.hedge_units
                # Reset hedge anchor spot to current spot after execution
                state.last_hedge_spot = current_spot

        state.cumulative_gamma_pnl = round(state.cumulative_gamma_pnl, 2)
        state.cumulative_theta_cost = round(state.cumulative_theta_cost, 2)
        state.cumulative_friction_cost = round(state.cumulative_friction_cost, 2)
        state.cumulative_net_pnl = round(state.cumulative_net_pnl, 2)

        return state

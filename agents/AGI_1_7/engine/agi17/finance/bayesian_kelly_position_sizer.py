"""Bayesian Posterior Learning & Fractional Kelly Position Sizer.

Implements institutional options position sizing combining:
1. Beta-Binomial Bayesian conjugate prior updating for win rate:
   p_hat = (alpha_0 + wins) / (alpha_0 + beta_0 + wins + losses)
2. Fractional Kelly optimal capital allocation:
   f_kelly = (p_hat * b - (1 - p_hat)) / b
   f* = kappa * max(0.0, f_kelly), where kappa in (0, 1] (Quarter to Half Kelly)
3. Continuous Drawdown Governor dampener:
   g_DD(DD) = exp(-lambda_DD * max(0.0, DD - DD_soft)) in (0, 1]
   with hard halt at DD >= DD_hard.
4. Capital Allocation & SEBI Integer Lot Quantization:
   C_alloc = C_equity * f* * g_DD(DD)
   Lots = floor(C_alloc / Margin_lot)
   Contracts = Lots * lot_size (Bank Nifty = 15, Nifty 50 = 25)

Zero external dependencies outside standard library math and dataclasses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class SizingRegime(str, Enum):
    """Position sizing regime based on statistical edge and drawdown state."""
    OPTIMAL_KELLY = "OPTIMAL_KELLY"
    DRAWDOWN_THROTTLED = "DRAWDOWN_THROTTLED"
    NEGATIVE_EDGE_NO_ALLOCATION = "NEGATIVE_EDGE_NO_ALLOCATION"
    HARD_DRAWDOWN_HALT = "HARD_DRAWDOWN_HALT"
    CAPITAL_EXHAUSTED = "CAPITAL_EXHAUSTED"


@dataclass
class BayesianTradeHistory:
    """Tracks prior beliefs and empirical trade outcomes for Bayesian updating."""
    alpha_prior: float = 10.0  # Pseudo-wins in prior
    beta_prior: float = 10.0   # Pseudo-losses in prior
    wins: int = 0
    losses: int = 0

    @property
    def total_trades(self) -> int:
        return self.wins + self.losses

    @property
    def posterior_mean(self) -> float:
        """Posterior expected win probability E[p | data]."""
        total = self.alpha_prior + self.beta_prior + self.total_trades
        if total <= 0.0:
            return 0.50
        return (self.alpha_prior + self.wins) / total


@dataclass(frozen=True)
class DrawdownGovernorConfig:
    """Parameters governing continuous drawdown protection."""
    soft_threshold: float = 0.02   # 2% drawdown soft threshold
    decay_rate: float = 30.0       # Exponential dampening factor
    hard_stop: float = 0.06        # 6% absolute drawdown kill switch


@dataclass(frozen=True)
class KellySizingResult:
    """Detailed position sizing guidance and risk metrics."""
    regime: SizingRegime
    posterior_win_prob: float
    payoff_ratio: float
    full_kelly_fraction: float
    fractional_kelly_fraction: float
    drawdown_governor_factor: float
    effective_allocation_fraction: float
    allocated_capital_inr: float
    quantized_lots: int
    quantized_contracts: int
    margin_utilized_inr: float
    cash_buffer_remaining_inr: float
    rationale: List[str] = field(default_factory=list)


class BayesianKellyPositionSizer:
    """Institutional Bayesian Fractional Kelly Position Sizing Engine."""

    def __init__(
        self,
        default_alpha_prior: float = 12.0,
        default_beta_prior: float = 8.0,
        drawdown_config: Optional[DrawdownGovernorConfig] = None,
        max_capital_allocation_fraction: float = 0.40,
    ) -> None:
        self.history = BayesianTradeHistory(
            alpha_prior=max(1.0, float(default_alpha_prior)),
            beta_prior=max(1.0, float(default_beta_prior)),
        )
        self.dd_config = drawdown_config or DrawdownGovernorConfig()
        self.max_cap_fraction = max(0.05, min(0.90, float(max_capital_allocation_fraction)))

    def record_trade_outcome(self, is_win: bool) -> None:
        """Record trade result to update Beta-Binomial conjugate posterior."""
        if is_win:
            self.history.wins += 1
        else:
            self.history.losses += 1

    def compute_posterior_win_probability(self) -> float:
        """Get current Bayesian posterior expected win probability."""
        return round(self.history.posterior_mean, 4)

    def compute_fractional_kelly(
        self,
        payoff_ratio: float,
        kappa: float = 0.25,
    ) -> Tuple[float, float]:
        """Compute Full Kelly and Fractional Kelly optimal capital fractions.
        
        Full Kelly: f = (p * b - (1 - p)) / b
        Fractional: f* = kappa * max(0, f)
        Returns: (full_kelly, fractional_kelly)
        """
        b = max(0.1, float(payoff_ratio))
        p = self.compute_posterior_win_probability()
        q = 1.0 - p

        edge = (p * b) - q
        if edge <= 0.0:
            return 0.0, 0.0

        full_kelly = edge / b
        k = max(0.05, min(1.0, float(kappa)))
        fractional_kelly = full_kelly * k

        # Cap fractional Kelly at configured risk ceiling
        bounded_fractional = min(self.max_cap_fraction, fractional_kelly)
        return round(full_kelly, 4), round(bounded_fractional, 4)

    def compute_drawdown_governor(self, current_drawdown: float) -> Tuple[float, bool]:
        """Compute continuous exponential drawdown dampening factor g_DD in (0, 1].
        
        g_DD = exp(-lambda_DD * max(0, DD - DD_soft))
        Returns: (governor_factor, is_hard_stop)
        """
        dd = max(0.0, float(current_drawdown))
        if dd >= self.dd_config.hard_stop:
            return 0.0, True

        excess_dd = max(0.0, dd - self.dd_config.soft_threshold)
        governor = math.exp(-self.dd_config.decay_rate * excess_dd)
        return round(max(0.01, min(1.0, governor)), 4), False

    def calculate_position_size(
        self,
        equity_inr: float,
        margin_per_lot_inr: float,
        lot_size_contracts: int = 15,
        payoff_ratio: float = 2.0,
        current_drawdown: float = 0.0,
        kappa: float = 0.25,
    ) -> KellySizingResult:
        """Compute optimal risk-adjusted position size and integer lot quantization."""
        equity = max(0.0, float(equity_inr))
        margin_lot = max(1.0, float(margin_per_lot_inr))
        lot_size = max(1, int(lot_size_contracts))
        rationale: List[str] = []

        if equity <= margin_lot:
            rationale.append(f"Insufficient equity (INR {equity:,.2f}) to meet minimum lot margin (INR {margin_lot:,.2f}).")
            return KellySizingResult(
                regime=SizingRegime.CAPITAL_EXHAUSTED,
                posterior_win_prob=self.compute_posterior_win_probability(),
                payoff_ratio=payoff_ratio,
                full_kelly_fraction=0.0,
                fractional_kelly_fraction=0.0,
                drawdown_governor_factor=0.0,
                effective_allocation_fraction=0.0,
                allocated_capital_inr=0.0,
                quantized_lots=0,
                quantized_contracts=0,
                margin_utilized_inr=0.0,
                cash_buffer_remaining_inr=equity,
                rationale=rationale,
            )

        # 1. Check Drawdown Governor
        g_dd, is_hard_stop = self.compute_drawdown_governor(current_drawdown)
        if is_hard_stop:
            rationale.append(
                f"HARD DRAWDOWN HALT active: current drawdown {current_drawdown * 100:.2f}% "
                f">= hard stop {self.dd_config.hard_stop * 100:.2f}%. Trading suspended."
            )
            return KellySizingResult(
                regime=SizingRegime.HARD_DRAWDOWN_HALT,
                posterior_win_prob=self.compute_posterior_win_probability(),
                payoff_ratio=payoff_ratio,
                full_kelly_fraction=0.0,
                fractional_kelly_fraction=0.0,
                drawdown_governor_factor=0.0,
                effective_allocation_fraction=0.0,
                allocated_capital_inr=0.0,
                quantized_lots=0,
                quantized_contracts=0,
                margin_utilized_inr=0.0,
                cash_buffer_remaining_inr=equity,
                rationale=rationale,
            )

        # 2. Compute Fractional Kelly Fraction
        full_f, frac_f = self.compute_fractional_kelly(payoff_ratio, kappa)
        p_hat = self.compute_posterior_win_probability()

        if frac_f <= 0.0:
            rationale.append(
                f"Negative or zero statistical edge: p={p_hat:.3f}, b={payoff_ratio:.2f}. "
                "Kelly criterion mandates 0% allocation."
            )
            return KellySizingResult(
                regime=SizingRegime.NEGATIVE_EDGE_NO_ALLOCATION,
                posterior_win_prob=p_hat,
                payoff_ratio=payoff_ratio,
                full_kelly_fraction=full_f,
                fractional_kelly_fraction=0.0,
                drawdown_governor_factor=g_dd,
                effective_allocation_fraction=0.0,
                allocated_capital_inr=0.0,
                quantized_lots=0,
                quantized_contracts=0,
                margin_utilized_inr=0.0,
                cash_buffer_remaining_inr=equity,
                rationale=rationale,
            )

        # 3. Apply Drawdown Governor Scaling
        effective_fraction = round(frac_f * g_dd, 4)
        allocated_capital = round(equity * effective_fraction, 2)

        # 4. Integer Lot Discretization
        lots = int(math.floor(allocated_capital / margin_lot))
        contracts = lots * lot_size
        margin_used = round(lots * margin_lot, 2)
        cash_buffer = round(equity - margin_used, 2)

        regime = (
            SizingRegime.DRAWDOWN_THROTTLED
            if g_dd < 0.95
            else SizingRegime.OPTIMAL_KELLY
        )

        rationale.append(
            f"Posterior win rate p={p_hat:.1%} (from {self.history.wins}W / {self.history.losses}L), payoff b={payoff_ratio:.2f}."
        )
        rationale.append(
            f"Full Kelly: {full_f:.1%}, Fractional Kelly ({kappa:.0%} scaling): {frac_f:.1%}."
        )
        if g_dd < 1.0:
            rationale.append(
                f"Drawdown governor throttled allocation by {g_dd:.1%} (current DD {current_drawdown * 100:.2f}%)."
            )
        rationale.append(
            f"Sized {lots} lots ({contracts} contracts), utilizing INR {margin_used:,.2f} of INR {equity:,.2f} equity."
        )

        return KellySizingResult(
            regime=regime,
            posterior_win_prob=p_hat,
            payoff_ratio=payoff_ratio,
            full_kelly_fraction=full_f,
            fractional_kelly_fraction=frac_f,
            drawdown_governor_factor=g_dd,
            effective_allocation_fraction=effective_fraction,
            allocated_capital_inr=allocated_capital,
            quantized_lots=lots,
            quantized_contracts=contracts,
            margin_utilized_inr=margin_used,
            cash_buffer_remaining_inr=cash_buffer,
            rationale=rationale,
        )


__all__ = [
    "SizingRegime",
    "BayesianTradeHistory",
    "DrawdownGovernorConfig",
    "KellySizingResult",
    "BayesianKellyPositionSizer",
]

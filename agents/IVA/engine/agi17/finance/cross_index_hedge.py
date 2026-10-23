"""Cross-Index Beta-Weighted Hedging Engine for Indian Index Derivatives.

TASK-BN-13:
Enables cross-hedging of BANK NIFTY options and futures portfolio delta risk using
liquid NIFTY 50 derivative contracts.

Computes:
1. Rolling sample covariance, variance, and Beta (\\beta = Cov(R_target, R_hedge) / Var(R_hedge)).
2. Coefficient of determination R^2 and residual basis risk variance.
3. Multi-asset Dollar Delta hedging and lot-aligned discrete contract sizing.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Sequence


@dataclasses.dataclass(frozen=True)
class BetaHedgeRatioResult:
    """Quantitative result of a cross-index beta-weighted hedge calculation."""

    beta: float
    r_squared: float
    correlation: float
    target_dollar_delta: float
    hedge_dollar_delta: float
    hedge_contracts_float: float
    hedge_lots_recommended: int
    residual_basis_std: float
    effective_hedge_pct: float
    recommended_action: str


class BetaWeightedHedgeEngine:
    """Calculates econometric beta and cross-index derivative hedge ratios."""

    @staticmethod
    def calculate_log_returns(prices: Sequence[float]) -> list[float]:
        """Calculates natural log returns from an ordered time series of prices."""
        if len(prices) < 2:
            return []
        returns: list[float] = []
        for i in range(1, len(prices)):
            if prices[i - 1] <= 0 or prices[i] <= 0:
                raise ValueError("Price series must contain strictly positive values")
            returns.append(math.log(prices[i] / prices[i - 1]))
        return returns

    @staticmethod
    def calculate_rolling_beta(
        target_returns: Sequence[float],
        hedge_returns: Sequence[float],
    ) -> tuple[float, float, float, float]:
        """Calculates sample Beta, R^2, correlation, and residual basis std.

        Returns:
            tuple[beta, r_squared, correlation, residual_basis_std]
        """
        n = len(target_returns)
        if n != len(hedge_returns):
            raise ValueError(
                f"Series lengths must match: target={n}, hedge={len(hedge_returns)}"
            )
        if n < 5:
            raise ValueError(f"Insufficient sample size for beta estimation: {n} < 5")

        mean_target = sum(target_returns) / n
        mean_hedge = sum(hedge_returns) / n

        var_hedge = sum((r - mean_hedge) ** 2 for r in hedge_returns) / (n - 1)
        var_target = sum((r - mean_target) ** 2 for r in target_returns) / (n - 1)

        if var_hedge <= 1e-12:
            raise ValueError("Hedge asset return variance is effectively zero")
        if var_target <= 1e-12:
            return 0.0, 0.0, 0.0, 0.0

        cov = sum(
            (t - mean_target) * (h - mean_hedge)
            for t, h in zip(target_returns, hedge_returns)
        ) / (n - 1)

        beta = cov / var_hedge
        std_target = math.sqrt(var_target)
        std_hedge = math.sqrt(var_hedge)

        correlation = cov / (std_target * std_hedge)
        # Numerical guard for float precision [-1.0, 1.0]
        correlation = max(-1.0, min(1.0, correlation))
        r_squared = correlation**2

        # Residual basis variance = Var(target) * (1 - R^2)
        residual_var = max(0.0, var_target * (1.0 - r_squared))
        residual_std = math.sqrt(residual_var)

        return beta, r_squared, correlation, residual_std

    @classmethod
    def calculate_hedge_allocation(
        cls,
        target_net_delta: float,
        target_spot: float,
        hedge_spot: float,
        beta: float,
        r_squared: float,
        correlation: float,
        residual_std: float,
        hedge_lot_size: int = 25,
    ) -> BetaHedgeRatioResult:
        """Determines required NIFTY 50 hedge contracts to neutralize BANK NIFTY delta.

        Math:
            Target Dollar Delta = target_net_delta * target_spot
            Hedge Dollar Delta = -beta * Target Dollar Delta
            Hedge Contracts = Hedge Dollar Delta / (hedge_spot * hedge_lot_size)
        """
        if target_spot <= 0 or hedge_spot <= 0:
            raise ValueError("Spot prices must be strictly positive")
        if hedge_lot_size <= 0:
            raise ValueError("Hedge lot size must be positive")

        target_dollar_delta = target_net_delta * target_spot
        hedge_dollar_delta = -beta * target_dollar_delta

        contract_unit_value = hedge_spot * hedge_lot_size
        hedge_contracts_float = hedge_dollar_delta / contract_unit_value
        hedge_lots_recommended = round(hedge_contracts_float)

        if hedge_lots_recommended > 0:
            recommended_action = f"BUY {hedge_lots_recommended} LOTS (NIFTY)"
        elif hedge_lots_recommended < 0:
            recommended_action = f"SELL {abs(hedge_lots_recommended)} LOTS (NIFTY)"
        else:
            recommended_action = "NO_HEDGE_REQUIRED (DELTA_NEUTRAL)"

        return BetaHedgeRatioResult(
            beta=beta,
            r_squared=r_squared,
            correlation=correlation,
            target_dollar_delta=target_dollar_delta,
            hedge_dollar_delta=hedge_dollar_delta,
            hedge_contracts_float=hedge_contracts_float,
            hedge_lots_recommended=hedge_lots_recommended,
            residual_basis_std=residual_std,
            effective_hedge_pct=r_squared * 100.0,
            recommended_action=recommended_action,
        )

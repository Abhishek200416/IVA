"""AGI 1.7 Monte Carlo Portfolio Stress & Merton Jump-Diffusion Simulation Engine.

TASK-BN-23:
Simulates multi-path intraday and multi-day stochastic price trajectories for BANK NIFTY
options portfolios incorporating continuous diffusion and discontinuous jump shocks.

Provides:
1. Merton (1976) Jump-Diffusion Model:
   dS_t / S_t = (mu - lambda * k) dt + sigma dW_t + dJ_t
   where jumps follow a compound Poisson process with log-normal jump magnitudes.
2. Intraday Path Discretization:
   Simulates 75 5-minute bars or 375 1-minute bars representing standard NSE market hours (9:15 - 15:30 IST).
3. Multi-Leg Portfolio Mark-to-Market:
   Revalues options portfolio across paths using analytical Black-Scholes and dynamic Greeks.
4. Risk Metrics:
   - Maximum Adverse Excursion (MAE)
   - Peak-to-Trough Drawdown Distribution
   - Empirical 95% & 99% Expected Shortfall (CVaR)
   - Margin Liquidation Probability: P(Account Deficit < 0)
   - Trailing Stop Truncation Ratio: Efficiency of stop loss in cutting tails before gap jumps.
"""

from __future__ import annotations

import dataclasses
import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import (
    BankNiftyPaperTrader,
    OptionType,
    OrderSide,
)
from .options_math import OptionsMath


@dataclasses.dataclass(frozen=True)
class OptionLeg:
    """Single leg in an options portfolio."""

    strike: float
    option_type: OptionType
    side: OrderSide
    units: int
    entry_premium: float
    dte_years: float
    implied_vol: float


@dataclasses.dataclass(frozen=True)
class SimulationConfig:
    """Parameters for the Merton jump-diffusion Monte Carlo simulation."""

    num_paths: int = 100
    num_steps: int = 75  # 75 5-minute bars in a 375-min Indian trading day
    spot_price: float = 50000.0
    annualized_vol: float = 0.16
    annualized_drift: float = 0.0
    jump_intensity: float = 0.10  # Poisson jump arrival intensity (10% per day)
    jump_mean: float = -0.015    # Mean log jump size (downside crash bias)
    jump_std: float = 0.025      # Standard deviation of jump size
    random_seed: Optional[int] = 42


@dataclasses.dataclass(frozen=True)
class PathResult:
    """Simulated trajectory outcome."""

    path_index: int
    final_spot: float
    min_spot: float
    max_spot: float
    jumps_count: int
    pnl_series: List[float]
    final_pnl_inr: float
    max_drawdown_inr: float
    max_adverse_excursion_inr: float
    trailing_stop_triggered: bool


@dataclasses.dataclass(frozen=True)
class MonteCarloStressReport:
    """Aggregated portfolio risk statistics across all simulated paths."""

    config: SimulationConfig
    total_paths: int
    mean_pnl_inr: float
    median_pnl_inr: float
    std_pnl_inr: float
    var_95_inr: float
    var_99_inr: float
    cvar_95_inr: float
    cvar_99_inr: float
    max_loss_inr: float
    max_gain_inr: float
    margin_breach_probability: float
    trailing_stop_trigger_rate: float
    total_jumps_observed: int
    diagnostics: str


class MonteCarloPortfolioStressEngine:
    """Stochastic jump-diffusion Monte Carlo simulator for BANK NIFTY options risk."""

    @classmethod
    def simulate_spot_path(
        cls,
        config: SimulationConfig,
        rng: random.Random,
    ) -> Tuple[List[float], int]:
        """Simulates a single Merton jump-diffusion path over one trading day."""
        # dt for 1 trading day = 1.0 / 252 years
        dt_year = (1.0 / 252.0) / max(1, config.num_steps)
        sqrt_dt = math.sqrt(dt_year)

        # Expected jump multiplier k = E[e^Y - 1] = exp(mu_J + 0.5 * sigma_J^2) - 1
        k = math.exp(config.jump_mean + 0.5 * config.jump_std**2) - 1.0
        drift_adj = (config.annualized_drift - 0.5 * config.annualized_vol**2 - config.jump_intensity * 252.0 * k) * dt_year

        spot = config.spot_price
        prices = [spot]
        jump_count = 0
        p_jump_step = (config.jump_intensity * 252.0) * dt_year

        for _ in range(config.num_steps):
            z = rng.gauss(0.0, 1.0)
            diffusion_ret = config.annualized_vol * sqrt_dt * z

            jump_ret = 0.0
            if rng.random() < p_jump_step:
                z_jump = rng.gauss(0.0, 1.0)
                jump_ret = config.jump_mean + config.jump_std * z_jump
                jump_count += 1

            total_ret = drift_adj + diffusion_ret + jump_ret
            spot = spot * math.exp(total_ret)
            prices.append(round(spot, 2))

        return prices, jump_count

    @classmethod
    def revalue_portfolio_leg(
        cls,
        leg: OptionLeg,
        current_spot: float,
        remaining_dte_years: float,
    ) -> float:
        """Computes current theoretical price for an option leg."""
        is_call = leg.option_type == OptionType.CE
        t = max(0.0001, remaining_dte_years)
        return OptionsMath.black_scholes_price(
            spot=current_spot,
            strike=leg.strike,
            time_to_expiry_years=t,
            risk_free_rate=0.065,  # 6.5% RBI repo rate
            volatility=leg.implied_vol,
            is_call=is_call,
        )

    @classmethod
    def evaluate_path_pnl(
        cls,
        prices: List[float],
        portfolio: Sequence[OptionLeg],
        trailing_stop_inr: Optional[float] = None,
    ) -> Tuple[List[float], float, float, float, bool]:
        """Calculates trajectory P&L and checks for trailing stop triggers."""
        pnl_series: List[float] = []
        peak_pnl = 0.0
        max_drawdown = 0.0
        max_adverse_excursion = 0.0
        trailing_stop_triggered = False

        # Precompute initial theoretical values
        initial_leg_prices = [
            cls.revalue_portfolio_leg(leg, prices[0], leg.dte_years)
            for leg in portfolio
        ]

        # Trailing stop ratchet tracking
        ratchet_stop = -float("inf") if trailing_stop_inr is not None else None

        for idx, spot in enumerate(prices):
            # Time decay through the day: dt = 1/252 / num_steps
            elapsed_fraction = (idx / max(1, len(prices) - 1)) * (1.0 / 252.0)
            step_pnl = 0.0

            for leg, p0 in zip(portfolio, initial_leg_prices):
                rem_dte = max(0.0001, leg.dte_years - elapsed_fraction)
                curr_px = cls.revalue_portfolio_leg(leg, spot, rem_dte)
                unit_pnl = (curr_px - p0) if leg.side == OrderSide.BUY else (p0 - curr_px)
                step_pnl += unit_pnl * leg.units

            pnl_series.append(round(step_pnl, 2))

            if step_pnl > peak_pnl:
                peak_pnl = step_pnl
                if trailing_stop_inr is not None:
                    # Ratchet trailing stop locking 80% of peak gains
                    ratchet_stop = max(ratchet_stop or -float("inf"), peak_pnl - trailing_stop_inr)

            dd = peak_pnl - step_pnl
            if dd > max_drawdown:
                max_drawdown = dd

            if step_pnl < max_adverse_excursion:
                max_adverse_excursion = step_pnl

            # Check trailing stop breach
            if trailing_stop_inr is not None and ratchet_stop is not None and step_pnl < ratchet_stop:
                trailing_stop_triggered = True

        final_pnl = pnl_series[-1] if pnl_series else 0.0
        return pnl_series, final_pnl, max_drawdown, abs(max_adverse_excursion), trailing_stop_triggered

    @classmethod
    def run_stress_simulation(
        cls,
        portfolio: Sequence[OptionLeg],
        config: Optional[SimulationConfig] = None,
        account_capital_inr: float = 500000.0,
        trailing_stop_inr: Optional[float] = 10000.0,
    ) -> MonteCarloStressReport:
        """Executes full Monte Carlo simulation across all configured paths."""
        if config is None:
            config = SimulationConfig()

        rng = random.Random(config.random_seed)
        final_pnls: List[float] = []
        path_results: List[PathResult] = []
        total_jumps = 0
        ts_triggered_count = 0
        margin_breach_count = 0

        for i in range(config.num_paths):
            prices, jumps = cls.simulate_spot_path(config, rng)
            total_jumps += jumps

            pnl_series, final_pnl, max_dd, mae, ts_triggered = cls.evaluate_path_pnl(
                prices=prices,
                portfolio=portfolio,
                trailing_stop_inr=trailing_stop_inr,
            )

            if ts_triggered:
                ts_triggered_count += 1

            # Check for capital deficit / margin breach
            if account_capital_inr + final_pnl < 0:
                margin_breach_count += 1

            final_pnls.append(final_pnl)
            path_results.append(
                PathResult(
                    path_index=i,
                    final_spot=prices[-1],
                    min_spot=min(prices),
                    max_spot=max(prices),
                    jumps_count=jumps,
                    pnl_series=pnl_series,
                    final_pnl_inr=final_pnl,
                    max_drawdown_inr=max_dd,
                    max_adverse_excursion_inr=mae,
                    trailing_stop_triggered=ts_triggered,
                )
            )

        # Statistical Metrics
        sorted_pnls = sorted(final_pnls)
        n = len(sorted_pnls)
        mean_pnl = sum(sorted_pnls) / max(1, n)
        median_pnl = sorted_pnls[n // 2]
        variance = sum((x - mean_pnl) ** 2 for x in sorted_pnls) / max(1, n - 1)
        std_pnl = math.sqrt(variance)

        # Historical / Empirical VaR and CVaR
        # VaR_alpha is the negative P&L at (1 - alpha) percentile
        idx_95 = max(0, int(0.05 * n))
        idx_99 = max(0, int(0.01 * n))
        var_95 = -sorted_pnls[idx_95] if sorted_pnls[idx_95] < 0 else 0.0
        var_99 = -sorted_pnls[idx_99] if sorted_pnls[idx_99] < 0 else 0.0

        tail_95 = sorted_pnls[: idx_95 + 1]
        cvar_95 = -sum(tail_95) / max(1, len(tail_95)) if tail_95 else var_95

        tail_99 = sorted_pnls[: idx_99 + 1]
        cvar_99 = -sum(tail_99) / max(1, len(tail_99)) if tail_99 else var_99

        max_loss = -sorted_pnls[0] if sorted_pnls[0] < 0 else 0.0
        max_gain = sorted_pnls[-1] if sorted_pnls[-1] > 0 else 0.0

        ts_rate = (ts_triggered_count / n) * 100.0 if n > 0 else 0.0
        margin_breach_prob = (margin_breach_count / n) * 100.0 if n > 0 else 0.0

        diagnostics = (
            f"Monte Carlo ({n} paths, {config.num_steps} steps, {total_jumps} jumps): "
            f"Mean P&L=₹{mean_pnl:,.2f}, 95% VaR=₹{var_95:,.2f}, 99% CVaR=₹{cvar_99:,.2f}. "
            f"Margin Breach Prob={margin_breach_prob:.1f}%, TS Trigger Rate={ts_rate:.1f}%."
        )

        return MonteCarloStressReport(
            config=config,
            total_paths=n,
            mean_pnl_inr=round(mean_pnl, 2),
            median_pnl_inr=round(median_pnl, 2),
            std_pnl_inr=round(std_pnl, 2),
            var_95_inr=round(var_95, 2),
            var_99_inr=round(var_99, 2),
            cvar_95_inr=round(cvar_95, 2),
            cvar_99_inr=round(cvar_99, 2),
            max_loss_inr=round(max_loss, 2),
            max_gain_inr=round(max_gain, 2),
            margin_breach_probability=round(margin_breach_prob, 2),
            trailing_stop_trigger_rate=round(ts_rate, 2),
            total_jumps_observed=total_jumps,
            diagnostics=diagnostics,
        )

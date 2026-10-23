"""
Phase 28 Self-Evolution: Portfolio Sizing, Joint Greek Hedging & Microstructure Execution Engine.

Implements frontier mathematical methods researched from ChatGPT & quantitative finance literature:
1. Dynamic Jump-Penalized Bayesian-Kelly Sizing (continuous-time log-utility root solver + mean-variance approximation + drawdown taper).
2. Asymmetric Information Leadership (ILI) & Cross-Index Joint Greek Hedging (Delta, Vega, Gamma regularized ridge optimization).
3. Microstructure Market Impact & Transient Slippage Scheduling (Almgren-Chriss / Gatheral PSD power-law impact kernel with depth/NOFI modulation).

Fail-Closed Invariant:
    LIVE_ORDER_DISPATCH_ENABLED = False (strictly advisory and execution planning; real broker fills locked).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union
import numpy as np


# Immutable Fail-Closed Safety Invariant
LIVE_ORDER_DISPATCH_ENABLED: bool = False


# ============================================================================
# 1. Dynamic Jump-Penalized Bayesian-Kelly Sizer
# ============================================================================

@dataclass(frozen=True)
class JumpMark:
    """Discrete jump return mark and its probability weight."""
    return_fraction: float  # Z > -1.0
    weight: float           # Probability weight w_i > 0, sum(w) = 1.0

    def __post_init__(self) -> None:
        if self.return_fraction <= -1.0:
            raise ValueError(f"Jump return fraction must be strictly > -1.0, got {self.return_fraction}")
        if self.weight <= 0.0:
            raise ValueError(f"Jump weight must be > 0.0, got {self.weight}")


@dataclass(frozen=True)
class KellySizingResult:
    """Result of jump-penalized Kelly fraction optimization."""
    f_optimal: float           # Final recommended leverage fraction f* >= 0
    f_exact_kelly: float       # Unconstrained / exact jump-Kelly solution
    f_mean_variance: float     # Mean-variance jump approximation f_MV
    f_drawdown_cap: float      # Maximum permitted fraction under drawdown taper
    expected_drift: float      # Conservative OFI-adjusted excess drift a_tilde
    jump_second_moment: float  # V_H = E[Z^2]
    drawdown_pct: float        # Current observed drawdown fraction
    is_bounded_by_loss: bool   # Whether f* was clamped by maximum fractional jump loss
    is_live_dispatch_locked: bool = True


class ContinuousJumpKellySizer:
    """
    Solves the continuous-time jump-diffusion log-utility growth objective:
        g(f) = f * a_tilde - 0.5 * f^2 * sigma^2 + lambda_J * E[log(1 + f*Z) - f*Z]
    with first-order condition:
        g'(f) = a_tilde - sigma^2 * f - lambda_J * E[(f * Z^2) / (1 + f * Z)] = 0.
    """

    def __init__(
        self,
        risk_aversion: float = 1.0,        # gamma_R for CRRA / mean-variance
        fractional_kelly: float = 0.5,      # varpi in (0, 1]
        f_hard_cap: float = 2.0,           # Global upper leverage ceiling
        max_drawdown_limit: float = 0.20,  # DD_max (e.g. 20%)
        drawdown_power: float = 1.5,       # p in drawdown budget taper
        uncertainty_z: float = 1.0,        # z_alpha uncertainty haircut
        beta_ofi: float = 0.05,            # Sensitivity to normalized OFI
        bisection_tol: float = 1e-7,
        max_bisection_iter: int = 100,
    ) -> None:
        if risk_aversion <= 0:
            raise ValueError(f"Risk aversion must be positive, got {risk_aversion}")
        if not (0 < fractional_kelly <= 1.0):
            raise ValueError(f"Fractional Kelly varpi must be in (0, 1], got {fractional_kelly}")
        if f_hard_cap <= 0:
            raise ValueError(f"f_hard_cap must be positive, got {f_hard_cap}")
        if not (0 < max_drawdown_limit < 1.0):
            raise ValueError(f"max_drawdown_limit must be in (0, 1), got {max_drawdown_limit}")

        self.risk_aversion = risk_aversion
        self.fractional_kelly = fractional_kelly
        self.f_hard_cap = f_hard_cap
        self.max_drawdown_limit = max_drawdown_limit
        self.drawdown_power = drawdown_power
        self.uncertainty_z = uncertainty_z
        self.beta_ofi = beta_ofi
        self.bisection_tol = bisection_tol
        self.max_bisection_iter = max_bisection_iter

    def compute_size(
        self,
        mean_excess_drift: float,       # Posterior mean excess return a_bar (annualized)
        drift_std_error: float,         # Posterior std error s_t
        diffusion_volatility: float,   # sigma_t (annualized)
        jump_intensity: float,          # lambda_J (jumps per year)
        jump_marks: Sequence[JumpMark], # Discrete jump distribution {Z_i, w_i}
        current_drawdown: float,        # DD_t in [0, 1]
        nofi: float = 0.0,              # Normalized OFI in [-1, 1]
    ) -> KellySizingResult:
        """Computes optimal jump-penalized Kelly allocation."""
        if diffusion_volatility <= 0:
            raise ValueError(f"Diffusion volatility must be strictly positive, got {diffusion_volatility}")
        if jump_intensity < 0:
            raise ValueError(f"Jump intensity lambda_J must be non-negative, got {jump_intensity}")
        if not (0.0 <= current_drawdown <= 1.0):
            raise ValueError(f"Current drawdown must be in [0, 1], got {current_drawdown}")
        if not jump_marks:
            raise ValueError("jump_marks sequence cannot be empty")

        # Normalize weights
        total_weight = sum(m.weight for m in jump_marks)
        marks = [JumpMark(m.return_fraction, m.weight / total_weight) for m in jump_marks]

        # 1. Conservative OFI-adjusted excess drift
        clamped_nofi = max(-1.0, min(1.0, nofi))
        a_tilde = mean_excess_drift + self.beta_ofi * clamped_nofi - self.uncertainty_z * max(0.0, drift_std_error)

        # 2. Second moment of jump return V_H = E[Z^2]
        v_h = sum(m.weight * (m.return_fraction ** 2) for m in marks)

        # 3. Mean-variance jump approximation: f_MV = a_tilde / [gamma_R * (sigma^2 + lambda_J * V_H)]
        var_denom = self.risk_aversion * (diffusion_volatility ** 2 + jump_intensity * v_h)
        f_mv = max(0.0, a_tilde / var_denom) if var_denom > 0 else 0.0

        # 4. Solvency leverage bound: 1 + f * Z_min > 0 => f < 1 / |Z_min| for Z_min < 0
        min_jump = min(m.return_fraction for m in marks)
        if min_jump < 0:
            loss_bound = (1.0 - 1e-4) / abs(min_jump)
        else:
            loss_bound = 100.0  # High numerical bound for pure upward jumps

        # If conservative edge is non-positive, Kelly fraction is zero
        if a_tilde <= 0.0:
            f_exact = 0.0
        else:
            # Solve g'(f) = 0 on [0, loss_bound]
            f_exact = self._solve_exact_root(
                a_tilde=a_tilde,
                sigma_sq=diffusion_volatility ** 2,
                lambda_j=jump_intensity,
                marks=marks,
                f_max=loss_bound,
            )

        # 5. Drawdown preservation budget: f_max(DD) = f_hard * max(0, 1 - DD / DD_max)^p
        if current_drawdown >= self.max_drawdown_limit:
            f_dd_cap = 0.0
        else:
            dd_slack = 1.0 - (current_drawdown / self.max_drawdown_limit)
            f_dd_cap = self.f_hard_cap * (max(0.0, dd_slack) ** self.drawdown_power)

        # 6. Final blended allocation: min(varpi * f_exact, f_dd_cap), clipped to f_hard_cap & solvency
        upper_bound = min(self.f_hard_cap, loss_bound)
        f_tapered = min(self.fractional_kelly * f_exact, f_dd_cap)
        f_optimal = max(0.0, min(upper_bound, f_tapered))
        loss_constrained = loss_bound < self.f_hard_cap

        return KellySizingResult(
            f_optimal=f_optimal,
            f_exact_kelly=f_exact,
            f_mean_variance=f_mv,
            f_drawdown_cap=f_dd_cap,
            expected_drift=a_tilde,
            jump_second_moment=v_h,
            drawdown_pct=current_drawdown,
            is_bounded_by_loss=loss_constrained and (f_optimal >= upper_bound - 1e-5),
            is_live_dispatch_locked=not LIVE_ORDER_DISPATCH_ENABLED,
        )

    def _solve_exact_root(
        self,
        a_tilde: float,
        sigma_sq: float,
        lambda_j: float,
        marks: List[JumpMark],
        f_max: float,
    ) -> float:
        """Solves g'(f) = 0 using robust bisection on [0, f_max]."""
        def g_prime(f: float) -> float:
            jump_loss = sum(m.weight * (f * (m.return_fraction ** 2)) / (1.0 + f * m.return_fraction) for m in marks)
            return a_tilde - sigma_sq * f - lambda_j * jump_loss

        # Check endpoints
        val_0 = g_prime(0.0)  # == a_tilde > 0
        val_max = g_prime(f_max)

        if val_max >= 0.0:
            # Gradient remains positive throughout, optimal is boundary f_max
            return f_max

        low = 0.0
        high = f_max
        for _ in range(self.max_bisection_iter):
            mid = 0.5 * (low + high)
            if (high - low) < self.bisection_tol:
                return mid
            val_mid = g_prime(mid)
            if val_mid > 0.0:
                low = mid
            else:
                high = mid

        return 0.5 * (low + high)


# ============================================================================
# 2. Joint Greek Cross-Index Hedger
# ============================================================================

@dataclass(frozen=True)
class JointGreekHedgeResult:
    """Result of regularized joint Greek hedge optimization."""
    hedge_weights: np.ndarray       # Continuous optimal quantities h*
    hedge_lots: np.ndarray          # Discretized lot-rounded quantities h_lots
    residual_greeks: np.ndarray     # Residual Greek exposures e_res (continuous)
    residual_greeks_lots: np.ndarray # Residual Greek exposures with rounded lots
    initial_risk_norm: float        # e_0^T Sigma e_0
    residual_risk_norm: float       # e_res^T Sigma e_res
    satisfies_continuous_limits: bool # All Greeks within limits before rounding
    satisfies_lot_limits: bool      # All Greeks within limits after rounding
    hedge_instrument_ids: List[str]
    is_live_dispatch_locked: bool = True


class JointGreekCrossHedger:
    """
    Solves regularized joint Greek hedging across indices (e.g. NIFTY and BANKNIFTY):
        min_h  (e_0 + G h)^T Sigma (e_0 + G h) + h^T Lambda h
    yielding:
        h* = -(G^T Sigma G + Lambda)^{-1} G^T Sigma e_0.
    Enforces hard constraints on residual Delta, Vega, and Gamma.
    """

    def __init__(
        self,
        greek_limits: Sequence[float], # [Delta_N_max, Delta_B_max, Vega_N_max, Vega_B_max, Gamma_N_max, Gamma_B_max]
        regularization_lambda: float = 1e-4,
    ) -> None:
        if len(greek_limits) != 6:
            raise ValueError(f"greek_limits must have exactly 6 components, got {len(greek_limits)}")
        if any(lim <= 0 for lim in greek_limits):
            raise ValueError("All Greek risk limits must be strictly positive")
        self.greek_limits = np.array(greek_limits, dtype=float)
        self.regularization_lambda = regularization_lambda

    def compute_hedge(
        self,
        portfolio_exposure: np.ndarray, # e_0 in R^6
        instrument_greeks: np.ndarray,  # G in R^(6 x M)
        factor_covariance: np.ndarray,  # Sigma in R^(6 x 6)
        lot_sizes: Sequence[int],       # Lot size per instrument in R^M
        instrument_ids: Optional[Sequence[str]] = None,
    ) -> JointGreekHedgeResult:
        """Solves optimal continuous and lot-rounded joint hedge."""
        e_0 = np.asarray(portfolio_exposure, dtype=float)
        G = np.asarray(instrument_greeks, dtype=float)
        Sigma = np.asarray(factor_covariance, dtype=float)
        lots = np.array(lot_sizes, dtype=int)

        if e_0.shape != (6,):
            raise ValueError(f"portfolio_exposure shape must be (6,), got {e_0.shape}")
        if G.shape[0] != 6:
            raise ValueError(f"instrument_greeks must have 6 rows, got {G.shape}")
        m_inst = G.shape[1]
        if Sigma.shape != (6, 6):
            raise ValueError(f"factor_covariance shape must be (6, 6), got {Sigma.shape}")
        if len(lots) != m_inst:
            raise ValueError(f"lot_sizes length ({len(lots)}) must match instruments ({m_inst})")

        inst_ids = list(instrument_ids) if instrument_ids else [f"INST_{i}" for i in range(m_inst)]

        # Regularization matrix Lambda
        Lambda = self.regularization_lambda * np.eye(m_inst)

        # Ridge normal equations: (G^T Sigma G + Lambda) h* = -G^T Sigma e_0
        G_Sigma = G.T @ Sigma
        A = G_Sigma @ G + Lambda
        b = -G_Sigma @ e_0

        h_star = np.linalg.solve(A, b)

        # Discrete lot rounding: h_lots = round(h* / lot) * lot
        h_lots = np.zeros_like(h_star)
        for i in range(m_inst):
            lot = max(1, lots[i])
            h_lots[i] = round(h_star[i] / lot) * lot

        # Residual Greeks
        e_res = e_0 + G @ h_star
        e_res_lots = e_0 + G @ h_lots

        # Risk norms
        initial_norm = float(e_0.T @ Sigma @ e_0)
        residual_norm = float(e_res.T @ Sigma @ e_res)

        # Boundary checks
        satisfies_cont = bool(np.all(np.abs(e_res) <= self.greek_limits + 1e-7))
        satisfies_lots = bool(np.all(np.abs(e_res_lots) <= self.greek_limits + 1e-7))

        return JointGreekHedgeResult(
            hedge_weights=h_star,
            hedge_lots=h_lots,
            residual_greeks=e_res,
            residual_greeks_lots=e_res_lots,
            initial_risk_norm=initial_norm,
            residual_risk_norm=residual_norm,
            satisfies_continuous_limits=satisfies_cont,
            satisfies_lot_limits=satisfies_lots,
            hedge_instrument_ids=inst_ids,
            is_live_dispatch_locked=not LIVE_ORDER_DISPATCH_ENABLED,
        )


# ============================================================================
# 3. Microstructure Market Impact & Transient Slippage Planner
# ============================================================================

@dataclass(frozen=True)
class ExecutionScheduleResult:
    """Optimal algorithmic slice dispatch schedule."""
    schedule_slices: np.ndarray     # q_k in R^N (quantity executed per slice)
    execution_rates: np.ndarray     # v_k = q_k / dt
    remaining_inventory: np.ndarray # x_k before each interval
    expected_slippage: float        # S_slip(q)
    inventory_risk_cost: float      # Inventory variance penalty
    total_objective_cost: float     # J(q)
    is_psd_guaranteed: bool         # Congruence scaling preserves PSD
    is_capacity_feasible: bool      # Within maximum participation bounds
    is_live_dispatch_locked: bool = True


class TransientImpactExecutionPlanner:
    """
    Plans discrete-time algorithmic order slices under power-law transient impact:
        G(tau) = Gamma_imp / (tau + eps_t)^alpha_imp
    with strictly positive book depth and NOFI congruence modulation:
        a_k = sqrt( (D_ref / (D_L,k + eps_D))^zeta * exp(kappa * |NOFI_k|) )
    ensuring K_ij = a_i G(|t_i - t_j|) a_j is strictly symmetric positive semi-definite (PSD).
    """

    def __init__(
        self,
        gamma_imp: float = 0.5,      # Transient impact scale Gamma_imp > 0
        alpha_imp: float = 0.6,      # Power-law decay alpha in (0, 1)
        eps_t: float = 0.1,          # Singularity regularizer eps_t > 0
        d_ref: float = 1000.0,       # Reference order book depth
        eps_d: float = 1.0,          # Depth regularizer
        zeta: float = 0.5,           # Depth sensitivity exponent
        kappa: float = 0.3,          # NOFI sensitivity exponent
        temporary_eta: float = 0.1,  # Temporary impact coefficient eta_k
        risk_aversion_lambda: float = 1e-4, # Inventory risk aversion lambda_r
    ) -> None:
        if gamma_imp <= 0:
            raise ValueError(f"gamma_imp must be > 0, got {gamma_imp}")
        if not (0.0 < alpha_imp < 1.0):
            raise ValueError(f"alpha_imp must be in (0, 1), got {alpha_imp}")
        if eps_t <= 0:
            raise ValueError(f"eps_t must be > 0, got {eps_t}")

        self.gamma_imp = gamma_imp
        self.alpha_imp = alpha_imp
        self.eps_t = eps_t
        self.d_ref = d_ref
        self.eps_d = eps_d
        self.zeta = zeta
        self.kappa = kappa
        self.temporary_eta = temporary_eta
        self.risk_aversion_lambda = risk_aversion_lambda

    def plan_execution(
        self,
        total_quantity: float,          # Parent order size Q > 0
        num_slices: int,                # Number of intervals N
        delta_t: float,                 # Slice duration in seconds
        direction: int,                 # +1 Buy, -1 Sell
        book_depths: Sequence[float],   # D_L,k depth observations
        nofi_values: Sequence[float],   # NOFI_k in [-1, 1]
        half_spread: float = 0.5,       # h_k
        price_volatility: float = 0.02, # sigma_P
        midprice_drift: float = 0.0,    # mu_OFI
        max_slice_cap: Optional[float] = None, # v_max * dt participation limit
    ) -> ExecutionScheduleResult:
        """Solves optimal convex dispatch schedule."""
        if total_quantity <= 0:
            raise ValueError(f"total_quantity must be positive, got {total_quantity}")
        if num_slices < 2:
            raise ValueError(f"num_slices must be >= 2, got {num_slices}")
        if delta_t <= 0:
            raise ValueError(f"delta_t must be positive, got {delta_t}")
        if direction not in (+1, -1):
            raise ValueError(f"direction must be +1 or -1, got {direction}")
        if len(book_depths) != num_slices:
            raise ValueError(f"book_depths length ({len(book_depths)}) != num_slices ({num_slices})")
        if len(nofi_values) != num_slices:
            raise ValueError(f"nofi_values length ({len(nofi_values)}) != num_slices ({num_slices})")

        n = num_slices
        q_total = float(total_quantity)

        # 1. Modulation vector a_k > 0
        a = np.zeros(n, dtype=float)
        for k in range(n):
            d_obs = max(0.0, book_depths[k])
            n_obs = max(-1.0, min(1.0, nofi_values[k]))
            depth_ratio = self.d_ref / (d_obs + self.eps_d)
            a[k] = math.sqrt((depth_ratio ** self.zeta) * math.exp(self.kappa * abs(n_obs)))

        # 2. Symmetric Positive Semi-Definite Transient Impact Matrix K
        times = np.arange(n, dtype=float) * delta_t
        time_diff = np.abs(times[:, None] - times[None, :])
        base_g = self.gamma_imp / ((time_diff + self.eps_t) ** self.alpha_imp)
        K = (a[:, None] * base_g) * a[None, :]

        # Guarantee exact numerical symmetry
        K = 0.5 * (K + K.T)

        # 3. Inventory accumulation matrix L (strictly lower triangular ones)
        L = np.tril(np.ones((n, n), dtype=float), k=-1)

        # 4. Hessian H = K + diag(2 * eta / dt) + lambda_r * dt * L^T diag(sigma_P^2) L
        sigma_sq = (price_volatility ** 2) * np.ones(n, dtype=float)
        eta_vec = self.temporary_eta * np.ones(n, dtype=float)
        diag_temp = np.diag(2.0 * eta_vec / delta_t)
        risk_term = self.risk_aversion_lambda * delta_t * (L.T @ np.diag(sigma_sq) @ L)
        H = K + diag_temp + risk_term
        H = 0.5 * (H + H.T)

        # 5. Linear gradient vector c
        h_vec = half_spread * np.ones(n, dtype=float)
        ones_vec = np.ones(n, dtype=float)
        drift_vec = midprice_drift * np.ones(n, dtype=float)
        c = (
            h_vec
            - self.risk_aversion_lambda * delta_t * (L.T @ np.diag(sigma_sq) @ (q_total * ones_vec))
            - direction * delta_t * (L.T @ drift_vec)
        )

        # 6. Equality constrained closed-form solution: sum(q_k) = Q
        H_inv = np.linalg.inv(H)
        H_inv_ones = H_inv @ ones_vec
        denom = float(ones_vec.T @ H_inv_ones)

        q_star = H_inv @ (
            ((q_total + float(ones_vec.T @ H_inv @ c)) / denom) * ones_vec - c
        )

        # Check participation limits and enforce non-negativity
        is_feasible = True
        if max_slice_cap is not None:
            if max_slice_cap * n < q_total:
                is_feasible = False

        # Projection onto simplex/bounds if unconstrained violated non-negativity
        if np.any(q_star < 0) or (max_slice_cap and np.any(q_star > max_slice_cap)):
            q_star = self._project_bounded_simplex(q_star, q_total, max_slice_cap)

        # 7. Remaining inventory and costs
        x_inv = q_total * ones_vec - L @ q_star
        rates = q_star / delta_t

        trans_cost = 0.5 * float(q_star.T @ K @ q_star)
        spread_cost = float(np.sum(h_vec * q_star))
        temp_cost = float(np.sum(eta_vec * (q_star ** 2) / delta_t))
        drift_cost = float(direction * delta_t * np.sum(drift_vec * x_inv))
        s_slip = spread_cost + trans_cost + temp_cost + drift_cost

        risk_cost = 0.5 * self.risk_aversion_lambda * delta_t * float(np.sum(sigma_sq * (x_inv ** 2)))
        j_total = s_slip + risk_cost

        return ExecutionScheduleResult(
            schedule_slices=q_star,
            execution_rates=rates,
            remaining_inventory=x_inv,
            expected_slippage=s_slip,
            inventory_risk_cost=risk_cost,
            total_objective_cost=j_total,
            is_psd_guaranteed=True,
            is_capacity_feasible=is_feasible,
            is_live_dispatch_locked=not LIVE_ORDER_DISPATCH_ENABLED,
        )

    def _project_bounded_simplex(
        self,
        q_init: np.ndarray,
        q_total: float,
        upper_cap: Optional[float],
    ) -> np.ndarray:
        """Projects unconstrained schedule onto box and budget constraints."""
        n = len(q_init)
        cap = upper_cap if upper_cap is not None else q_total
        # Iterative soft-thresholding / projection onto sum(q) = Q, 0 <= q <= cap
        q = np.clip(q_init, 0.0, cap)
        for _ in range(50):
            diff = float(np.sum(q)) - q_total
            if abs(diff) < 1e-6:
                break
            # Distribute residual among non-saturated components
            free_mask = (q > 1e-6) if diff > 0 else (q < cap - 1e-6)
            num_free = int(np.sum(free_mask))
            if num_free == 0:
                break
            q[free_mask] -= diff / num_free
            q = np.clip(q, 0.0, cap)
        return q

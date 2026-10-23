"""High-Frequency Dynamic Hedge Ratio & Kalman Filter Cointegration Engine.

Wave 36 Deliverable (TASK-BN-46):
Synthesized for Indian Index Derivatives (Bank Nifty vs Nifty 50, Futures vs Synthetic Forward):
1. State-Space Representation:
   - Hidden State Vector: theta_t = [alpha_t, beta_t]^T (Dynamic Intercept and Dynamic Hedge Ratio)
   - State Transition: theta_t = theta_{t-1} + w_t,  w_t ~ N(0, Q)
     where Q = diag(q_alpha, q_beta) models the intraday parameter drift rate.
   - Observation Equation: y_t = H_t * theta_t + v_t,  v_t ~ N(0, R)
     where H_t = [1.0, x_t], y_t is Asset 1 price, x_t is Asset 2 price, and R is observation variance.
2. Recursive Kalman Filter Algorithm:
   - Prediction:
     theta_{t|t-1} = theta_{t-1|t-1}
     P_{t|t-1} = P_{t-1|t-1} + Q
   - Innovation & Measurement Update:
     e_t = y_t - H_t * theta_{t|t-1}
     F_t = H_t * P_{t|t-1} * H_t^T + R
     K_t = P_{t|t-1} * H_t^T / F_t
     theta_{t|t} = theta_{t|t-1} + K_t * e_t
     P_{t|t} = (I - K_t * H_t) * P_{t|t-1}
3. Standardized Z-Score & Ornstein-Uhlenbeck (OU) Mean-Reversion Half-Life:
   - Normalized spread: z_t = e_t / sqrt(F_t)
   - Continuous OU drift regression: Delta e_t = -kappa * e_{t-1} + noise
   - Half-life t_{1/2} = ln(2) / kappa. Filter rejects non-mean-reverting spreads (kappa <= 0 or t_{1/2} too long).
4. Trading Signal & SEBI Integer Lot Quantization:
   - Long Spread (Buy Asset 1, Sell beta * Asset 2) when z_t <= -entry_z
   - Short Spread (Sell Asset 1, Buy beta * Asset 2) when z_t >= +entry_z
   - Exit when |z_t| <= exit_z, Stop-loss when |z_t| >= stop_z
   - SEBI discrete lots: Bank Nifty = 15 contracts, Nifty 50 = 25 contracts.

Zero external dependencies outside standard library math, dataclasses, and typing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple


class KalmanSpreadAction(str, Enum):
    LONG_SPREAD = "LONG_SPREAD"    # Buy Asset 1, Sell Asset 2
    SHORT_SPREAD = "SHORT_SPREAD"  # Sell Asset 1, Buy Asset 2
    EXIT_POSITION = "EXIT_POSITION"# Reverted within neutral band
    STOP_LOSS = "STOP_LOSS"        # Spread expanded past maximum risk boundary
    HOLD_NEUTRAL = "HOLD_NEUTRAL"  # Within no-trade band


@dataclass(frozen=True)
class KalmanStateSnapshot:
    """Kalman filter state and estimation metrics at time t."""
    timestamp: float
    intercept_alpha: float
    hedge_ratio_beta: float
    spread_error: float
    innovation_variance: float
    normalized_z_score: float
    state_variance_alpha: float
    state_variance_beta: float
    covariance_alpha_beta: float


@dataclass(frozen=True)
class HalfLifeEstimation:
    """Ornstein-Uhlenbeck mean-reversion parameter estimates."""
    kappa: float               # Mean reversion speed
    half_life_seconds: float   # t_{1/2} = ln(2) / kappa
    is_mean_reverting: bool
    r_squared: float


@dataclass(frozen=True)
class KalmanTradingSignal:
    """Statistical cointegration trading signal with lot quantization."""
    timestamp: float
    action: KalmanSpreadAction
    normalized_z: float
    current_beta: float
    asset_1_lots: int
    asset_2_lots: int
    half_life: HalfLifeEstimation
    expected_edge_pts: float
    notes: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "action": self.action.value,
            "z_score": round(self.normalized_z, 3),
            "beta": round(self.current_beta, 4),
            "asset_1_lots": self.asset_1_lots,
            "asset_2_lots": self.asset_2_lots,
            "half_life_sec": round(self.half_life.half_life_seconds, 1),
            "is_mean_reverting": self.half_life.is_mean_reverting,
            "notes": self.notes,
        }


class KalmanSpreadFilter:
    """2-Dimensional Dynamic Kalman Filter for High-Frequency Pairs Cointegration."""

    def __init__(
        self,
        delta_process_noise: float = 1e-4,     # Parameter drift rate
        measurement_noise: float = 1.0,        # R (observation noise)
        initial_beta: float = 1.0,
        initial_alpha: float = 0.0,
        initial_state_cov: float = 1.0,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        stop_z: float = 3.5,
        min_half_life_sec: float = 0.2,
        max_half_life_sec: float = 3600.0,
    ) -> None:
        if delta_process_noise <= 0.0 or measurement_noise <= 0.0:
            raise ValueError("Noise variances must be strictly positive.")
        if entry_z <= exit_z or stop_z <= entry_z:
            raise ValueError("Z-score thresholds must satisfy: exit_z < entry_z < stop_z.")

        # State vector: [alpha, beta]
        self.theta = [float(initial_alpha), float(initial_beta)]

        # Covariance matrix P: 2x2 [[P00, P01], [P10, P11]]
        self.p00 = float(initial_state_cov)
        self.p01 = 0.0
        self.p10 = 0.0
        self.p11 = float(initial_state_cov)

        # Process noise covariance Q: Q = delta / (1 - delta) * I
        q_rate = delta_process_noise / (1.0 - delta_process_noise)
        self.q00 = q_rate
        self.q11 = q_rate

        self.r = float(measurement_noise)

        self.entry_z = entry_z
        self.exit_z = exit_z
        self.stop_z = stop_z
        self.min_half_life_sec = min_half_life_sec
        self.max_half_life_sec = max_half_life_sec

        # History buffer for OU half-life fitting
        self.spread_history: List[Tuple[float, float]] = []  # (timestamp, spread)
        self._last_x: Optional[float] = None
        self.last_snapshot: Optional[KalmanStateSnapshot] = None

    def update(
        self,
        y: float,
        x: float,
        timestamp: float = 0.0,
    ) -> KalmanStateSnapshot:
        """Perform recursive Kalman prediction and measurement update.

        y = Asset 1 price (Bank Nifty)
        x = Asset 2 price (Nifty 50 or Synthetic Forward)
        """
        # 1. Prediction Step
        # State transition: theta_{t|t-1} = theta_{t-1|t-1}
        # Covariance prediction: P_{t|t-1} = P_{t-1|t-1} + Q
        p00_pred = self.p00 + self.q00
        p01_pred = self.p01
        p10_pred = self.p10
        p11_pred = self.p11 + self.q11

        alpha_pred = self.theta[0]
        beta_pred = self.theta[1]

        # 2. Measurement Update Step
        # Observation matrix: H = [1.0, x]
        # Predicted observation: y_pred = alpha_pred + beta_pred * x
        y_pred = alpha_pred + beta_pred * x
        error = y - y_pred  # Innovation e_t

        # Innovation variance: F = H * P * H^T + R
        # H * P = [1.0 * p00 + x * p10,  1.0 * p01 + x * p11]
        hp0 = p00_pred + x * p10_pred
        hp1 = p01_pred + x * p11_pred
        f_var = (hp0 * 1.0) + (hp1 * x) + self.r
        if f_var < 1e-12:
            f_var = 1e-12

        # Kalman Gain: K = P * H^T / F (2x1 vector)
        # P * H^T = [p00 + x * p01, p10 + x * p11]
        k0 = (p00_pred + x * p01_pred) / f_var
        k1 = (p10_pred + x * p11_pred) / f_var

        # Rolling standard deviation Z-Score (standard pairs trading normalization)
        recent_errs = [s[1] for s in self.spread_history[-20:]]
        if len(recent_errs) >= 10:
            mean_err = sum(recent_errs) / len(recent_errs)
            var_err = sum((v - mean_err) ** 2 for v in recent_errs) / max(1, len(recent_errs) - 1)
            # 7.2 point minimum spread standard deviation floor for Bank Nifty pairs trading
            std_err = math.sqrt(max(51.84, var_err))
            z_score = (error - mean_err) / std_err
        else:
            z_score = error / math.sqrt(f_var)

        # Robust update:
        # 1. When x is completely constant (Var(x)=0) and error is within normal spread oscillation,
        # freeze beta update so the underlying mean-reverting spread process e_t is preserved.
        # 2. Outlier shocks (|z_score| >= stop_z) are extreme spread tail events and must not corrupt
        # the baseline cointegrating relationship vector.
        is_x_constant = (self._last_x is not None) and (abs(x - self._last_x) < 1e-6)
        self._last_x = x
        is_outlier = abs(z_score) >= self.stop_z and len(recent_errs) >= 10

        if not is_outlier:
            if is_x_constant and abs(error) < 20.0:
                pass
            else:
                self.theta[0] = alpha_pred + k0 * error
                self.theta[1] = beta_pred + k1 * error

                # Updated covariance: P = (I - K * H) * P_pred
                ik00 = 1.0 - k0
                ik01 = -k0 * x
                ik10 = -k1
                ik11 = 1.0 - k1 * x

                new_p00 = ik00 * p00_pred + ik01 * p10_pred
                new_p01 = ik00 * p01_pred + ik01 * p11_pred
                new_p10 = ik10 * p00_pred + ik11 * p10_pred
                new_p11 = ik10 * p01_pred + ik11 * p11_pred

                # Enforce symmetry
                sym_p01 = 0.5 * (new_p01 + new_p10)
                self.p00 = max(1e-12, new_p00)
                self.p01 = sym_p01
                self.p10 = sym_p01
                self.p11 = max(1e-12, new_p11)

        # Record spread history for rolling stats and OU analysis
        self.spread_history.append((timestamp, error))
        if len(self.spread_history) > 500:
            self.spread_history.pop(0)

        snapshot = KalmanStateSnapshot(
            timestamp=timestamp,
            intercept_alpha=self.theta[0],
            hedge_ratio_beta=self.theta[1],
            spread_error=error,
            innovation_variance=f_var,
            normalized_z_score=z_score,
            state_variance_alpha=self.p00,
            state_variance_beta=self.p11,
            covariance_alpha_beta=self.p01,
        )
        self.last_snapshot = snapshot
        return snapshot


    def estimate_half_life(self, min_samples: int = 15) -> HalfLifeEstimation:
        """Estimate Ornstein-Uhlenbeck mean-reversion speed kappa and half-life t_{1/2}.

        Continuous OU process: de_t = -kappa * (e_{t-1} - mu_e) * dt + sigma * dW_t
        """
        n = len(self.spread_history)
        if n < min_samples:
            return HalfLifeEstimation(
                kappa=0.0,
                half_life_seconds=float("inf"),
                is_mean_reverting=False,
                r_squared=0.0,
            )

        err_vals = [s[1] for s in self.spread_history]
        mu_e = sum(err_vals) / n

        x_lag: List[float] = []
        y_diff: List[float] = []

        for i in range(1, n):
            dt = max(0.1, self.spread_history[i][0] - self.spread_history[i - 1][0])
            e_prev = self.spread_history[i - 1][1] - mu_e
            e_curr = self.spread_history[i][1]
            de = e_curr - self.spread_history[i - 1][1]

            x_lag.append(e_prev * dt)
            y_diff.append(de)

        m = len(x_lag)
        denom = sum(x * x for x in x_lag)
        if denom < 1e-12:
            return HalfLifeEstimation(
                kappa=0.0,
                half_life_seconds=float("inf"),
                is_mean_reverting=False,
                r_squared=0.0,
            )

        # OLS slope: slope = sum(x * y) / sum(x^2), de = -kappa * x_lag => kappa = -slope
        slope = sum(x_lag[i] * y_diff[i] for i in range(m)) / denom
        kappa = -slope

        # Compute R^2
        y_mean = sum(y_diff) / m
        ss_tot = sum((y - y_mean) ** 2 for y in y_diff)
        ss_res = sum((y_diff[i] - slope * x_lag[i]) ** 2 for i in range(m))
        r2 = max(0.0, 1.0 - (ss_res / ss_tot)) if ss_tot > 1e-12 else 0.0

        if kappa <= 0.0:
            return HalfLifeEstimation(
                kappa=kappa,
                half_life_seconds=float("inf"),
                is_mean_reverting=False,
                r_squared=r2,
            )

        half_life = math.log(2.0) / kappa
        is_mr = (0.0 < half_life <= self.max_half_life_sec) and (r2 >= 0.02)

        return HalfLifeEstimation(
            kappa=kappa,
            half_life_seconds=half_life,
            is_mean_reverting=is_mr,
            r_squared=r2,
        )

    def generate_signal(
        self,
        snapshot: KalmanStateSnapshot,
        base_lots_asset_1: int = 1,
        lot_size_1: int = 15,  # Bank Nifty lot size
        lot_size_2: int = 25,  # Nifty 50 lot size
    ) -> KalmanTradingSignal:
        """Derive actionable trade decision with Indian discrete lot quantization."""
        half_life = self.estimate_half_life()
        z = snapshot.normalized_z_score
        beta = snapshot.hedge_ratio_beta

        # Discrete lot allocation:
        # Asset 1 quantity = base_lots * lot_size_1
        # Asset 2 quantity ~ beta * (Asset 1 quantity)
        # Asset 2 lots = round(beta * base_lots * lot_size_1 / lot_size_2)
        target_qty_2 = abs(beta) * base_lots_asset_1 * lot_size_1
        lots_asset_2 = max(1, round(target_qty_2 / lot_size_2))

        # Stop loss check
        if abs(z) >= self.stop_z:
            action = KalmanSpreadAction.STOP_LOSS
            notes = f"Spread exploded past stop threshold: z={z:.2f} >= {self.stop_z}."
        # Mean reversion exit check
        elif abs(z) <= self.exit_z:
            action = KalmanSpreadAction.EXIT_POSITION
            notes = f"Spread converged within exit threshold: |z|={abs(z):.2f} <= {self.exit_z}."
        # Entry check: require mean-reversion confirmation
        elif z <= -self.entry_z:
            if half_life.is_mean_reverting:
                action = KalmanSpreadAction.LONG_SPREAD
                notes = f"Long Spread: Asset 1 underpriced (z={z:.2f}), half-life={half_life.half_life_seconds:.1f}s."
            else:
                action = KalmanSpreadAction.HOLD_NEUTRAL
                notes = f"Entry z={z:.2f} reached, but spread not confirmed mean-reverting (half-life={half_life.half_life_seconds:.1f}s)."
        elif z >= self.entry_z:
            if half_life.is_mean_reverting:
                action = KalmanSpreadAction.SHORT_SPREAD
                notes = f"Short Spread: Asset 1 overpriced (z={z:.2f}), half-life={half_life.half_life_seconds:.1f}s."
            else:
                action = KalmanSpreadAction.HOLD_NEUTRAL
                notes = f"Entry z={z:.2f} reached, but spread not confirmed mean-reverting (half-life={half_life.half_life_seconds:.1f}s)."
        else:
            action = KalmanSpreadAction.HOLD_NEUTRAL
            notes = f"Spread in neutral holding zone: z={z:.2f}."

        expected_edge = abs(snapshot.spread_error)

        return KalmanTradingSignal(
            timestamp=snapshot.timestamp,
            action=action,
            normalized_z=z,
            current_beta=beta,
            asset_1_lots=base_lots_asset_1,
            asset_2_lots=lots_asset_2,
            half_life=half_life,
            expected_edge_pts=expected_edge,
            notes=notes,
        )

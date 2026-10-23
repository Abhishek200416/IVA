"""
Phase 28 Self-Evolution: Hawkes-Driven Log-Forward Variance & Calendar Roll Engine.

Implements frontier mathematical methods researched from ChatGPT & quantitative finance literature:
1. Log Forward Variance Parameterization:
       x_t(tau) = ln(xi_t(tau))  ==>  xi_t(tau) = exp(x_t(tau)) > 0
   with total ATM variance:
       theta_t(tau) = integral_0^tau exp(x_t(u)) du
   strictly guaranteeing calendar-monotonicity (d theta / d tau = xi_t(tau) > 0)
   and structurally eliminating ATM calendar arbitrage without post-hoc regression.
2. Discrete-State Calendar Roll Engine State Machine:
   Handles fractional/boundary-aligned rolls, horizon consumption (NEEDS_REBOOTSTRAP),
   and terminal interval preservation.
3. Hawkes Jump-Penalized Variance Risk Premium (VRP) & Roll Policy:
   Evaluates Theta-to-Gamma carry ratios across near and next maturities under Hawkes
   jump hazard lambda_J(t) and jump volatility V_H.

Fail-Closed Safety Invariant:
    LIVE_ORDER_DISPATCH_ENABLED = False (strictly advisory and execution planning; real broker fills locked).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np


# Immutable Fail-Closed Safety Invariant
LIVE_ORDER_DISPATCH_ENABLED: bool = False


# ============================================================================
# 1. State Machine Definitions
# ============================================================================

class CalendarState(str, Enum):
    ACTIVE = "ACTIVE"
    NEEDS_REBOOTSTRAP = "NEEDS_REBOOTSTRAP"
    EMERGENCY_DELEVERAGE = "EMERGENCY_DELEVERAGE"


class CalendarTransition(str, Enum):
    INITIALIZED = "INITIALIZED"
    LOG_RATE_UPDATE = "LOG_RATE_UPDATE"
    CALENDAR_ROLLED = "CALENDAR_ROLLED"
    REBOOTSTRAPPED = "REBOOTSTRAPPED"
    EMERGENCY_TRIGGERED = "EMERGENCY_TRIGGERED"


@dataclass(frozen=True)
class CalendarEvent:
    """Event emitted during calendar-roll state machine transitions."""
    transition: CalendarTransition
    state: CalendarState
    asof: float
    dt: float = 0.0
    message: str = ""
    is_live_dispatch_locked: bool = True


# ============================================================================
# 2. Log-Forward Variance Curve with Structural Monotonicity
# ============================================================================

class LogForwardVarianceCurve:
    """
    Maintains continuous log-forward-variance piecewise-constant intervals:
        xi_t(tau) = exp(x_i) > 0 for tau in [tau_i, tau_{i+1})
    yielding exact analytical total variance:
        theta_t(tau) = sum_{k=0}^{m-1} exp(x_k) (tau_{k+1} - tau_k) + exp(x_m) (tau - tau_m)
    guaranteeing d theta / d tau > 0 for all tau > 0.
    """

    def __init__(
        self,
        asof: float,
        tau_edges: Sequence[float],
        log_xi: Sequence[float],
    ) -> None:
        self.asof = float(asof)
        self.state = CalendarState.ACTIVE
        self._validate_and_set(tau_edges, log_xi)

    def _validate_and_set(
        self,
        tau_edges: Sequence[float],
        log_xi: Sequence[float],
    ) -> None:
        edges = np.array(tau_edges, dtype=float)
        logs = np.array(log_xi, dtype=float)

        if len(edges) < 2:
            raise ValueError(f"tau_edges must contain at least 2 points, got {len(edges)}")
        if not math.isclose(edges[0], 0.0, abs_tol=1e-9):
            raise ValueError(f"tau_edges must start at 0.0, got {edges[0]}")
        if np.any(np.diff(edges) <= 0.0):
            raise ValueError(f"tau_edges must be strictly increasing, got {edges}")
        if len(logs) != len(edges) - 1:
            raise ValueError(f"log_xi length ({len(logs)}) must equal len(tau_edges) - 1 ({len(edges) - 1})")
        if not np.all(np.isfinite(logs)):
            raise ValueError("log_xi must contain only finite real values")

        self.tau_edges = edges
        self.log_xi = logs

    @property
    def horizon(self) -> float:
        """Maximum modeled time-to-maturity."""
        return float(self.tau_edges[-1])

    @property
    def xi(self) -> np.ndarray:
        """Instantaneous forward variance rates xi = exp(log_xi) > 0."""
        return np.exp(self.log_xi)

    def total_variance(self, tau: float) -> float:
        """
        Computes exact ATM total variance theta(tau) = integral_0^tau xi(u) du.
        Strictly non-decreasing with tau.
        """
        if self.state == CalendarState.NEEDS_REBOOTSTRAP:
            raise RuntimeError("Curve horizon is expired and requires rebootstrap")
        if tau < 0.0:
            raise ValueError(f"Maturity tau must be non-negative, got {tau}")
        if math.isclose(tau, 0.0, abs_tol=1e-12):
            return 0.0

        target_tau = min(tau, self.horizon)
        accum_theta = 0.0

        for i in range(len(self.log_xi)):
            t_left = self.tau_edges[i]
            t_right = self.tau_edges[i + 1]
            xi_val = math.exp(self.log_xi[i])

            if target_tau >= t_right:
                accum_theta += xi_val * (t_right - t_left)
            else:
                accum_theta += xi_val * (target_tau - t_left)
                break

        # Extrapolate flat forward rate if tau exceeds maximum modeled horizon
        if tau > self.horizon:
            terminal_xi = math.exp(self.log_xi[-1])
            accum_theta += terminal_xi * (tau - self.horizon)

        return accum_theta

    def update_log_rates(self, new_log_xi: Sequence[float]) -> CalendarEvent:
        """Atomic update of log-forward-variance rates from market calibration."""
        if self.state == CalendarState.NEEDS_REBOOTSTRAP:
            raise RuntimeError("Cannot update rates on an expired curve; call rebootstrap first")

        logs = np.array(new_log_xi, dtype=float)
        if len(logs) != len(self.log_xi):
            raise ValueError(f"New log_xi length ({len(logs)}) must match existing grid length ({len(self.log_xi)})")
        if not np.all(np.isfinite(logs)):
            raise ValueError("new_log_xi must contain only finite real values")

        self.log_xi = logs
        return CalendarEvent(
            transition=CalendarTransition.LOG_RATE_UPDATE,
            state=self.state,
            asof=self.asof,
            message=f"Updated {len(logs)} log forward rates",
            is_live_dispatch_locked=not LIVE_ORDER_DISPATCH_ENABLED,
        )

    def roll_calendar(
        self,
        dt: float,
        tail_log_xi: Optional[float] = None,
    ) -> CalendarEvent:
        """
        Advances the calendar by dt > 0.
        Consumes expired front fraction, shifts surviving boundaries by -dt,
        and appends terminal interval to maintain horizon.
        """
        if dt <= 0.0:
            raise ValueError(f"Calendar advancement dt must be strictly positive, got {dt}")

        self.asof += dt

        # If dt exceeds or matches total horizon, old curve is fully consumed
        if dt >= self.horizon - 1e-9:
            self.state = CalendarState.NEEDS_REBOOTSTRAP
            return CalendarEvent(
                transition=CalendarTransition.CALENDAR_ROLLED,
                state=CalendarState.NEEDS_REBOOTSTRAP,
                asof=self.asof,
                dt=dt,
                message=f"Advancement dt={dt:.4f} exceeded horizon {self.horizon:.4f}; rebootstrap required",
                is_live_dispatch_locked=not LIVE_ORDER_DISPATCH_ENABLED,
            )

        # Shift surviving edges
        shifted_edges = self.tau_edges - dt
        surviving_mask = shifted_edges > 1e-9
        new_edges = [0.0] + list(shifted_edges[surviving_mask])

        # Slice surviving forward rates
        first_surviving_idx = int(np.searchsorted(self.tau_edges, dt, side="right")) - 1
        surviving_logs = list(self.log_xi[first_surviving_idx:])

        # Align length: if length mismatch, preserve or append terminal rate
        target_len = len(new_edges) - 1
        while len(surviving_logs) < target_len:
            tail_rate = tail_log_xi if tail_log_xi is not None else surviving_logs[-1]
            surviving_logs.append(tail_rate)
        if len(surviving_logs) > target_len:
            surviving_logs = surviving_logs[:target_len]

        # Preserve terminal horizon
        if new_edges[-1] < self.horizon - 1e-9:
            new_edges.append(self.horizon)
            tail_rate = tail_log_xi if tail_log_xi is not None else surviving_logs[-1]
            surviving_logs.append(tail_rate)

        self.tau_edges = np.array(new_edges, dtype=float)
        self.log_xi = np.array(surviving_logs, dtype=float)
        self.state = CalendarState.ACTIVE

        return CalendarEvent(
            transition=CalendarTransition.CALENDAR_ROLLED,
            state=CalendarState.ACTIVE,
            asof=self.asof,
            dt=dt,
            message=f"Calendar rolled by dt={dt:.4f}; new horizon={self.horizon:.4f}",
            is_live_dispatch_locked=not LIVE_ORDER_DISPATCH_ENABLED,
        )

    def rebootstrap(
        self,
        asof: float,
        tau_edges: Sequence[float],
        log_xi: Sequence[float],
    ) -> CalendarEvent:
        """Re-initializes fresh tenor grid and forward rates after horizon expiration."""
        self.asof = float(asof)
        self._validate_and_set(tau_edges, log_xi)
        self.state = CalendarState.ACTIVE
        return CalendarEvent(
            transition=CalendarTransition.REBOOTSTRAPPED,
            state=CalendarState.ACTIVE,
            asof=self.asof,
            message=f"Rebootstrapped {len(self.log_xi)} forward intervals up to horizon {self.horizon:.4f}",
            is_live_dispatch_locked=not LIVE_ORDER_DISPATCH_ENABLED,
        )

    def snapshot(self) -> Dict[str, Any]:
        """Returns structured dictionary of curve state."""
        theta_nodes = [self.total_variance(t) for t in self.tau_edges]
        return {
            "asof": self.asof,
            "state": self.state.value,
            "horizon": self.horizon,
            "tau_edges": self.tau_edges.tolist(),
            "log_xi": self.log_xi.tolist(),
            "xi": self.xi.tolist(),
            "theta_edges": theta_nodes,
            "is_live_dispatch_locked": not LIVE_ORDER_DISPATCH_ENABLED,
        }


# ============================================================================
# 3. Hawkes-Penalized Variance Risk Premium & Calendar Roll Policy
# ============================================================================

class RollDecision(str, Enum):
    HOLD = "HOLD"
    PRE_ROLL_ALERT = "PRE_ROLL_ALERT"
    EXECUTE_ROLL = "EXECUTE_ROLL"
    EMERGENCY_DELEVERAGE = "EMERGENCY_DELEVERAGE"


@dataclass(frozen=True)
class CalendarRollEvaluation:
    """Quantitative decision output for calendar spread rolls."""
    decision: RollDecision
    roll_criterion: float          # Raw carry-risk trade-off score
    penalized_vrp_near: float      # VRP_near - jump penalty
    penalized_vrp_next: float      # VRP_next - jump penalty
    jump_hazard_penalty: float     # kappa_jump * lambda_J * (V_H / sigma_ref^2)
    near_carry_ratio: float        # Theta_near / Gamma_near
    next_carry_ratio: float        # Theta_next / Gamma_next
    pin_risk_flag: bool            # True if near maturity tau < min_pin_tau
    reason: str
    is_live_dispatch_locked: bool = True


class HawkesCalendarRollPolicy:
    """
    Evaluates calendar spread health between near-expiry (tau_near) and next-expiry (tau_next):
        RollCriterion = (Theta_near / (Gamma_near + eps)) - (Theta_next / (Gamma_next + eps))
                        - kappa_jump * lambda_J * (V_H / sigma_ref^2)
    with explicit pin risk and jump cluster gating.
    """

    def __init__(
        self,
        pin_cutoff_tau: float = 2.0 / 252.0,      # 2 trading days
        roll_threshold: float = 0.50,            # Trigger threshold for EXECUTE_ROLL
        alert_threshold: float = 1.00,           # Threshold for PRE_ROLL_ALERT
        jump_hazard_weight: float = 1.50,        # kappa_jump penalty
        reference_volatility: float = 0.15,      # sigma_ref
        emergency_lambda_threshold: float = 15.0, # Immediate deleverage on massive jump cluster
    ) -> None:
        self.pin_cutoff_tau = pin_cutoff_tau
        self.roll_threshold = roll_threshold
        self.alert_threshold = alert_threshold
        self.jump_hazard_weight = jump_hazard_weight
        self.reference_volatility = reference_volatility
        self.emergency_lambda_threshold = emergency_lambda_threshold

    def evaluate_roll(
        self,
        tau_near: float,              # Near expiry maturity in years
        tau_next: float,              # Next expiry maturity in years
        iv_near: float,               # Near implied volatility
        iv_next: float,               # Next implied volatility
        expected_rv_near: float,      # Near expected realized volatility
        expected_rv_next: float,      # Next expected realized volatility
        theta_near: float,            # Daily decay ($)
        theta_next: float,
        gamma_near: float,            # Curvature ($/pt^2)
        gamma_next: float,
        jump_intensity: float,        # lambda_J from Hawkes engine
        jump_second_moment: float,    # V_H = E[Z^2]
        underlying_spot_gap: float = 0.0, # Near-strike spot distance (pin risk proxy)
    ) -> CalendarRollEvaluation:
        """Evaluates calendar roll criteria and returns actionable decision."""
        if tau_near <= 0.0 or tau_next <= tau_near:
            raise ValueError(f"Maturities must satisfy 0 < tau_near < tau_next, got {tau_near}, {tau_next}")

        eps = 1e-6
        # 1. Carry efficiency ratios: Theta / Gamma
        near_carry = abs(theta_near) / (abs(gamma_near) + eps)
        next_carry = abs(theta_next) / (abs(gamma_next) + eps)

        # 2. Localized VRP
        vrp_near_raw = (iv_near ** 2) - (expected_rv_near ** 2)
        vrp_next_raw = (iv_next ** 2) - (expected_rv_next ** 2)

        # 3. Jump hazard penalty
        ref_var = self.reference_volatility ** 2
        jump_penalty = self.jump_hazard_weight * max(0.0, jump_intensity) * (max(0.0, jump_second_moment) / ref_var)

        penalized_vrp_near = vrp_near_raw - jump_penalty
        penalized_vrp_next = vrp_next_raw - jump_penalty

        # 4. Roll criterion
        roll_crit = near_carry - next_carry - jump_penalty

        # 5. Pin risk check
        is_pin_risk = tau_near <= self.pin_cutoff_tau

        # Decision tree
        if jump_intensity >= self.emergency_lambda_threshold:
            decision = RollDecision.EMERGENCY_DELEVERAGE
            reason = f"Hawkes jump intensity {jump_intensity:.2f} exceeded emergency threshold {self.emergency_lambda_threshold:.2f}"
        elif is_pin_risk:
            decision = RollDecision.EXECUTE_ROLL
            reason = f"Near expiry {tau_near * 252:.1f} days is inside pin risk cutoff {self.pin_cutoff_tau * 252:.1f} days"
        elif roll_crit <= self.roll_threshold:
            decision = RollDecision.EXECUTE_ROLL
            reason = f"Roll criterion {roll_crit:.3f} fell below threshold {self.roll_threshold:.3f}"
        elif roll_crit <= self.alert_threshold:
            decision = RollDecision.PRE_ROLL_ALERT
            reason = f"Roll criterion {roll_crit:.3f} entered pre-roll alert zone ({self.roll_threshold:.3f}, {self.alert_threshold:.3f}]"
        else:
            decision = RollDecision.HOLD
            reason = f"Near carry ratio {near_carry:.2f} remains attractive relative to next carry {next_carry:.2f}"

        return CalendarRollEvaluation(
            decision=decision,
            roll_criterion=roll_crit,
            penalized_vrp_near=penalized_vrp_near,
            penalized_vrp_next=penalized_vrp_next,
            jump_hazard_penalty=jump_penalty,
            near_carry_ratio=near_carry,
            next_carry_ratio=next_carry,
            pin_risk_flag=is_pin_risk,
            reason=reason,
            is_live_dispatch_locked=not LIVE_ORDER_DISPATCH_ENABLED,
        )


# ============================================================================
# 4. Cycle 16 Reference Architecture Integration & Re-exports
# ============================================================================

from agents.AGI_1_7.engine.agi17.finance.term_structure_calendar_roller import (
    EngineState,
    RollPolicy,
    RollSnapshot,
    next_roll_state,
    propagate_log_forward_variance,
    calendar_monotonicity_violation,
    expected_hazard_count,
    expected_hazard_count_interval,
    localized_forward_vrp_hazard_adjusted,
    pin_risk_score,
    hazard_adjusted_vrp,
    calendar_roll_score,
)

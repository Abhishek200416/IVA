"""
Cycle 22 — Online Multi-Factor Jump-Diffusion Particle Filtering & Real-Time Implied Volatility Calibration Engine
Under Macro Shock Regimes (RBI Policy & Union Budget Events).

Mathematical Architecture:
1. State-Space Jump-Diffusion Model:
   dS_t = mu S_t dt + sqrt(V_t) S_t dW_t^{(S)} + S_{t^-} (e^{J_t} - 1) dN_t
   dV_t = kappa (theta - V_t) dt + xi sqrt(V_t) dW_t^{(V)}
   Corr(dW^{(S)}, dW^{(V)}) = rho in [-1, 1]
   Compound Poisson / Hawkes jump process N_t with event proximity modulation:
   lambda_t = lambda_base + alpha_H * sum_{t_i < t} exp(-beta_H * (t - t_i)) + lambda_macro * exp(-tau_event^2 / (2 * sigma_event^2))
   Log jump size J_t ~ Normal(mu_J, sigma_J^2)

2. Sequential Monte Carlo (SMC) Particle Filter:
   Latent state vector: x_t = [ln S_t, V_t, lambda_t, J_t]
   Effective Sample Size: N_eff = 1 / sum((w_t^{(i)})^2)
   Resampling threshold: N_eff < N_p / 2 (Systematic / Stratified Resampling)
   Regularization jittering / Roughening to prevent particle degeneracy.

3. Merton Jump-Diffusion Semi-Analytical Option Pricing & IV Inversion:
   C_Merton(S, K, tau, r, sigma, lambda, mu_J, sigma_J) = sum_{n=0}^M (exp(-lambda' tau) * (lambda' tau)^n / n!) * C_BS(S, K, tau, r_n, sigma_n)
   where lambda' = lambda * (1 + k_J), k_J = exp(mu_J + 0.5 * sigma_J^2) - 1.

4. Indian Market Statutory Frictions (NSE Basis):
   Options turnover basis = Premium * Quantity
   STT = 0.15% on sell turnover, Exchange Fee = 0.03553% (Rs 3553/crore), GST = 18%, Stamp Duty = 0.003% on buy turnover.

5. 5-State Discrete Risk Machine:
   IDLE -> FILTERING_ACTIVE -> SURFACE_CALIBRATED | DEGENERACY_SPIKE_HALT | EMERGENCY_UNWIND.
   Fail-Closed Invariant: LIVE_ORDER_DISPATCH_ENABLED = False locked.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
try:
    from scipy.optimize import brentq
except ImportError:
    def brentq(f: Any, a: float, b: float, xtol: float = 1e-6, maxiter: int = 100) -> float:
        fa, fb = f(a), f(b)
        if fa * fb > 0:
            raise ValueError("Root not bracketed")
        for _ in range(maxiter):
            mid = 0.5 * (a + b)
            if abs(b - a) < xtol:
                return mid
            fmid = f(mid)
            if abs(fmid) < 1e-12:
                return mid
            if fa * fmid < 0:
                b, fb = mid, fmid
            else:
                a, fa = mid, fmid
        return 0.5 * (a + b)


def std_norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function via math.erf."""
    return 0.5 * (1.0 + math.erf(x / 1.4142135623730951))


LIVE_ORDER_DISPATCH_ENABLED: bool = False


class FilterRiskState(str, enum.Enum):
    IDLE = "IDLE"
    FILTERING_ACTIVE = "FILTERING_ACTIVE"
    SURFACE_CALIBRATED = "SURFACE_CALIBRATED"
    DEGENERACY_SPIKE_HALT = "DEGENERACY_SPIKE_HALT"
    EMERGENCY_UNWIND = "EMERGENCY_UNWIND"


@dataclass(frozen=True)
class MacroEventMetadata:
    event_id: str
    event_name: str
    scheduled_time: float  # In years or normalized days
    macro_lambda_boost: float = 5.0
    event_window_sigma: float = 0.02  # Time spread in years (~7 days)
    expected_jump_mean: float = -0.02  # Downside skew bias during anticipation
    expected_jump_std: float = 0.04


@dataclass
class JumpDiffusionParameters:
    mu: float = 0.05
    kappa: float = 2.0
    theta: float = 0.04
    xi: float = 0.3
    rho: float = -0.6
    lambda_base: float = 1.0
    mu_J: float = -0.01
    sigma_J: float = 0.03

    def validate(self) -> None:
        if self.kappa <= 0.0:
            raise ValueError(f"kappa must be positive, got {self.kappa}")
        if self.theta <= 0.0:
            raise ValueError(f"theta must be positive, got {self.theta}")
        if self.xi <= 0.0:
            raise ValueError(f"xi must be positive, got {self.xi}")
        if not (-1.0 <= self.rho <= 1.0):
            raise ValueError(f"rho must be in [-1, 1], got {self.rho}")
        if self.lambda_base < 0.0:
            raise ValueError(f"lambda_base must be >= 0, got {self.lambda_base}")
        if self.sigma_J <= 0.0:
            raise ValueError(f"sigma_J must be positive, got {self.sigma_J}")


def calculate_indian_statutory_friction(
    premium: float,
    lots: int,
    lot_size: int = 50,
    is_sell: bool = True,
    brokerage_per_order: float = 20.0,
    half_spread_fraction: float = 0.002,
) -> Dict[str, float]:
    """
    Computes exact statutory friction for NSE index options based on options premium turnover.
    Basis:
    - Premium Turnover = premium * lots * lot_size
    - STT = 0.15% on sell turnover (post-Oct 2024 SEBI revised rate)
    - Exchange turnover charges = 0.03553% (Rs 3,553 per crore)
    - SEBI charges = Rs 10 per crore (0.0001%)
    - Stamp duty = 0.003% on buy turnover
    - GST = 18% on (Brokerage + Exchange turnover charges + SEBI charges)
    """
    if premium < 0.0:
        raise ValueError(f"Premium must be non-negative, got {premium}")
    if lots <= 0 or lot_size <= 0:
        raise ValueError("Lots and lot size must be strictly positive")

    turnover = float(premium * lots * lot_size)
    stt = 0.0015 * turnover if is_sell else 0.0
    exchange_fee = 0.0003553 * turnover
    sebi_fee = 0.000001 * turnover
    stamp_duty = 0.00003 * turnover if not is_sell else 0.0
    brokerage = float(brokerage_per_order)
    gst = 0.18 * (brokerage + exchange_fee + sebi_fee)

    statutory_total = stt + exchange_fee + sebi_fee + stamp_duty + brokerage + gst
    spread_slippage = turnover * half_spread_fraction
    total_hurdle = statutory_total + spread_slippage

    return {
        "turnover": turnover,
        "stt": stt,
        "exchange_fee": exchange_fee,
        "sebi_fee": sebi_fee,
        "stamp_duty": stamp_duty,
        "brokerage": brokerage,
        "gst": gst,
        "statutory_total": statutory_total,
        "spread_slippage": spread_slippage,
        "total_hurdle": total_hurdle,
    }


def black_scholes_price(
    S: float,
    K: float,
    tau: float,
    r: float,
    sigma: float,
    is_call: bool = True,
) -> float:
    """Standard Black-Scholes-Merton European option pricing."""
    if tau <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
        intrinsic = max(0.0, S - K) if is_call else max(0.0, K - S)
        return float(intrinsic)

    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * tau) / (sigma * math.sqrt(tau))
    d2 = d1 - sigma * math.sqrt(tau)

    if is_call:
        price = S * std_norm_cdf(d1) - K * math.exp(-r * tau) * std_norm_cdf(d2)
    else:
        price = K * math.exp(-r * tau) * std_norm_cdf(-d2) - S * std_norm_cdf(-d1)
    return float(max(0.0, price))


def merton_jump_diffusion_price(
    S: float,
    K: float,
    tau: float,
    r: float,
    sigma: float,
    lambda_j: float,
    mu_J: float,
    sigma_J: float,
    is_call: bool = True,
    max_terms: int = 40,
    tolerance: float = 1e-9,
) -> float:
    """
    Merton (1976) jump-diffusion semi-analytical European option pricing via Poisson series.
    """
    if tau <= 0.0 or S <= 0.0 or K <= 0.0:
        return float(max(0.0, S - K if is_call else K - S))

    if lambda_j <= 1e-12:
        return black_scholes_price(S, K, tau, r, sigma, is_call=is_call)

    k_J = math.exp(mu_J + 0.5 * sigma_J * sigma_J) - 1.0
    lambda_prime = lambda_j * (1.0 + k_J)

    total_price = 0.0
    poisson_factor = math.exp(-lambda_prime * tau)
    poisson_term = poisson_factor

    for n in range(max_terms):
        if n > 0:
            poisson_term = poisson_term * (lambda_prime * tau) / n

        sigma_n = math.sqrt(max(1e-8, sigma * sigma + (n * sigma_J * sigma_J) / tau))
        r_n = r - lambda_j * k_J + (n * math.log(1.0 + k_J)) / tau
        bs_n = black_scholes_price(S, K, tau, r_n, sigma_n, is_call=is_call)

        inc = poisson_term * bs_n
        total_price += inc
        if inc < tolerance and n >= 5:
            break

    return float(total_price)


def implied_volatility_inversion(
    target_price: float,
    S: float,
    K: float,
    tau: float,
    r: float,
    is_call: bool = True,
    vol_min: float = 0.01,
    vol_max: float = 3.0,
) -> float:
    """Robust Brent inversion recovering Black-Scholes implied volatility from market price."""
    intrinsic = max(0.0, S - K) if is_call else max(0.0, K - S)
    if target_price <= intrinsic + 1e-7:
        return vol_min

    def objective(v: float) -> float:
        return black_scholes_price(S, K, tau, r, v, is_call=is_call) - target_price

    try:
        f_min = objective(vol_min)
        f_max = objective(vol_max)
        if f_min * f_max > 0:
            return vol_min if abs(f_min) < abs(f_max) else vol_max
        iv = brentq(objective, vol_min, vol_max, xtol=1e-6, maxiter=100)
        return float(iv)
    except Exception:
        return vol_min


class SMCParticleFilter:
    """
    Sequential Monte Carlo (SMC) Particle Filter for Latent Jump-Diffusion State.
    Latent state per particle i: x_t^{(i)} = [ln S_t, V_t, lambda_t, J_t].
    """

    def __init__(
        self,
        params: JumpDiffusionParameters,
        n_particles: int = 1000,
        random_seed: Optional[int] = 42,
    ) -> None:
        self.params = params
        self.params.validate()
        self.n_particles = n_particles
        self.rng = np.random.default_rng(random_seed)

        # Particles state array: [n_particles, 4] -> (ln_S, V, lambda, J)
        self.particles = np.zeros((n_particles, 4), dtype=np.float64)
        self.weights = np.ones(n_particles, dtype=np.float64) / n_particles
        self.effective_sample_size: float = float(n_particles)
        self.is_initialized: bool = False

    def initialize(self, initial_spot: float, initial_vol: float = 0.20) -> None:
        if initial_spot <= 0.0:
            raise ValueError(f"initial_spot must be positive, got {initial_spot}")

        ln_s0 = math.log(initial_spot)
        v0 = initial_vol * initial_vol

        self.particles[:, 0] = self.rng.normal(ln_s0, 0.01, self.n_particles)
        self.particles[:, 1] = np.maximum(1e-6, self.rng.normal(v0, 0.02 * v0, self.n_particles))
        self.particles[:, 2] = np.maximum(0.1, self.rng.normal(self.params.lambda_base, 0.2, self.n_particles))
        self.particles[:, 3] = np.zeros(self.n_particles, dtype=np.float64)

        self.weights.fill(1.0 / self.n_particles)
        self.effective_sample_size = float(self.n_particles)
        self.is_initialized = True

    def propagate(
        self,
        dt: float,
        macro_event: Optional[MacroEventMetadata] = None,
        current_time: float = 0.0,
    ) -> None:
        """Propagate particles forward by dt under correlated jump-diffusion dynamics."""
        if not self.is_initialized:
            raise RuntimeError("Filter must be initialized before propagation")
        if dt <= 0.0:
            raise ValueError(f"dt must be positive, got {dt}")

        sq_dt = math.sqrt(dt)

        # Correlated Brownian increments
        z1 = self.rng.normal(0.0, 1.0, self.n_particles)
        z2 = self.rng.normal(0.0, 1.0, self.n_particles)
        dw_s = z1 * sq_dt
        dw_v = (self.params.rho * z1 + math.sqrt(max(0.0, 1.0 - self.params.rho**2)) * z2) * sq_dt

        # CIR Stochastic Variance propagation with truncation reflection
        v_curr = self.particles[:, 1]
        v_drift = self.params.kappa * (self.params.theta - v_curr) * dt
        v_diff = self.params.xi * np.sqrt(np.maximum(1e-8, v_curr)) * dw_v
        v_next = np.maximum(1e-6, v_curr + v_drift + v_diff)
        self.particles[:, 1] = v_next

        # Dynamic intensity with macro event proximity modulation
        base_lambda = self.params.lambda_base
        if macro_event is not None:
            tau_event = macro_event.scheduled_time - current_time
            event_boost = macro_event.macro_lambda_boost * math.exp(
                - (tau_event**2) / (2.0 * macro_event.event_window_sigma**2)
            )
            base_lambda += event_boost

        self.particles[:, 2] = np.maximum(0.05, base_lambda + 0.1 * self.rng.normal(0.0, 1.0, self.n_particles))

        # Poisson jumps realization
        jump_prob = np.clip(self.particles[:, 2] * dt, 0.0, 0.95)
        jump_occurred = self.rng.uniform(0.0, 1.0, self.n_particles) < jump_prob

        mu_j = self.params.mu_J
        if macro_event is not None and abs(macro_event.scheduled_time - current_time) < macro_event.event_window_sigma:
            mu_j = macro_event.expected_jump_mean

        jump_sizes = np.zeros(self.n_particles, dtype=np.float64)
        n_jumps = int(np.sum(jump_occurred))
        if n_jumps > 0:
            jump_sizes[jump_occurred] = self.rng.normal(mu_j, self.params.sigma_J, n_jumps)
        self.particles[:, 3] = jump_sizes

        # Spot log-price update
        mu = self.params.mu
        k_j = math.exp(mu_j + 0.5 * self.params.sigma_J**2) - 1.0
        drift_compensator = self.particles[:, 2] * k_j
        s_drift = (mu - 0.5 * v_curr - drift_compensator) * dt
        s_diff = np.sqrt(np.maximum(1e-8, v_curr)) * dw_s
        self.particles[:, 0] += s_drift + s_diff + jump_sizes

    def update_measurement(
        self,
        observed_spot: float,
        spot_noise_std: float = 0.005,
        observed_iv: Optional[float] = None,
        iv_noise_std: float = 0.015,
    ) -> None:
        """Update particle weights using log-sum-exp stable observation likelihood."""
        if observed_spot <= 0.0:
            raise ValueError(f"observed_spot must be positive, got {observed_spot}")

        obs_ln_s = math.log(observed_spot)
        pred_ln_s = self.particles[:, 0]

        # Log-likelihood for spot price
        log_lik_spot = -0.5 * math.log(2.0 * math.pi * spot_noise_std**2) - (
            (obs_ln_s - pred_ln_s) ** 2
        ) / (2.0 * spot_noise_std**2)

        # Log-likelihood for implied volatility snapshot
        if observed_iv is not None and observed_iv > 0.0:
            pred_vol = np.sqrt(np.maximum(1e-6, self.particles[:, 1]))
            log_lik_iv = -0.5 * math.log(2.0 * math.pi * iv_noise_std**2) - (
                (observed_iv - pred_vol) ** 2
            ) / (2.0 * iv_noise_std**2)
            log_lik = log_lik_spot + log_lik_iv
        else:
            log_lik = log_lik_spot

        # Safe update with prior log weights
        prior_log_w = np.log(np.maximum(1e-300, self.weights))
        unnorm_log_w = prior_log_w + log_lik
        max_log_w = np.max(unnorm_log_w)
        norm_w = np.exp(unnorm_log_w - max_log_w)
        sum_norm_w = float(np.sum(norm_w))

        if sum_norm_w <= 1e-300 or not np.isfinite(sum_norm_w):
            # Degenerate weights fallback to uniform
            self.weights.fill(1.0 / self.n_particles)
        else:
            self.weights = norm_w / sum_norm_w

        # Compute effective sample size
        sum_sq = float(np.sum(self.weights**2))
        self.effective_sample_size = 1.0 / sum_sq if sum_sq > 0.0 else 0.0

        # Systematic resampling if N_eff < N_p / 2
        if self.effective_sample_size < (self.n_particles / 2.0):
            self.systematic_resample()

    def systematic_resample(self, jitter_std: float = 0.005) -> None:
        """Systematic stratified resampling with domain-preserving regularization jitter."""
        n = self.n_particles
        u = (self.rng.uniform(0.0, 1.0) + np.arange(n)) / n
        cdf = np.cumsum(self.weights)
        cdf[-1] = 1.0  # Numerical guard

        indices = np.searchsorted(cdf, u)
        self.particles = self.particles[indices].copy()

        # Regularization jittering respecting boundary invariants
        self.particles[:, 0] += self.rng.normal(0.0, jitter_std, n)  # ln S
        self.particles[:, 1] = np.maximum(1e-6, self.particles[:, 1] + self.rng.normal(0.0, jitter_std * 0.1, n))  # V >= 0
        self.particles[:, 2] = np.maximum(0.05, self.particles[:, 2] + self.rng.normal(0.0, jitter_std * 0.2, n))  # lambda >= 0

        self.weights.fill(1.0 / n)
        self.effective_sample_size = float(n)

    def get_state_estimates(self) -> Dict[str, float]:
        """Weighted posterior mean and standard deviations of latent state."""
        w = self.weights
        est_spot = float(np.exp(np.sum(w * self.particles[:, 0])))
        est_vol = float(np.sqrt(np.maximum(1e-8, np.sum(w * self.particles[:, 1]))))
        est_lambda = float(np.sum(w * self.particles[:, 2]))
        jump_magnitude = float(np.sum(w * self.particles[:, 3]))

        return {
            "estimated_spot": est_spot,
            "estimated_vol": est_vol,
            "estimated_lambda": est_lambda,
            "jump_magnitude": jump_magnitude,
            "effective_sample_size": self.effective_sample_size,
        }


class RealTimeJumpDiffusionCalibrator:
    """
    Real-time calibration of Jump-Diffusion Implied Volatility Surface and Macro Regimes.
    """

    def __init__(self, filter_engine: SMCParticleFilter) -> None:
        self.filter = filter_engine

    def calibrate_surface_slice(
        self,
        spot: float,
        strikes: np.ndarray,
        tau: float,
        r: float = 0.065,
        macro_event: Optional[MacroEventMetadata] = None,
        current_time: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Calibrates model implied volatility across moneyness under macro regime anticipation.
        """
        if spot <= 0.0 or tau <= 0.0:
            raise ValueError("Spot and tau must be positive")

        estimates = self.filter.get_state_estimates()
        sigma = estimates["estimated_vol"]
        lambda_j = estimates["estimated_lambda"]
        mu_j = self.filter.params.mu_J
        sigma_j = self.filter.params.sigma_J

        # Macro anticipation wing steepening
        is_event_regime = False
        if macro_event is not None:
            tau_event = macro_event.scheduled_time - current_time
            if abs(tau_event) < macro_event.event_window_sigma * 2.5:
                is_event_regime = True
                mu_j = macro_event.expected_jump_mean
                sigma_j = macro_event.expected_jump_std

        iv_curve = []
        prices = []
        moneyness = []

        for k in strikes:
            call_price = merton_jump_diffusion_price(
                S=spot,
                K=float(k),
                tau=tau,
                r=r,
                sigma=sigma,
                lambda_j=lambda_j,
                mu_J=mu_j,
                sigma_J=sigma_j,
                is_call=True,
            )
            iv = implied_volatility_inversion(
                target_price=call_price,
                S=spot,
                K=float(k),
                tau=tau,
                r=r,
                is_call=True,
            )
            prices.append(call_price)
            iv_curve.append(iv)
            moneyness.append(math.log(float(k) / spot))

        iv_arr = np.array(iv_curve, dtype=np.float64)
        mon_arr = np.array(moneyness, dtype=np.float64)

        # Skew slope: d(IV) / d(ln(K/S)) around ATM
        atm_idx = np.argmin(np.abs(mon_arr))
        if 0 < atm_idx < len(iv_arr) - 1:
            skew_slope = float((iv_arr[atm_idx + 1] - iv_arr[atm_idx - 1]) / (mon_arr[atm_idx + 1] - mon_arr[atm_idx - 1]))
        else:
            skew_slope = 0.0

        return {
            "strikes": strikes,
            "moneyness": mon_arr,
            "call_prices": np.array(prices, dtype=np.float64),
            "implied_volatilities": iv_arr,
            "atm_implied_vol": float(iv_arr[atm_idx]),
            "skew_slope": skew_slope,
            "is_event_regime": is_event_regime,
            "calibrated_lambda": lambda_j,
            "calibrated_mu_J": mu_j,
            "calibrated_sigma_J": sigma_j,
        }


class JumpDiffusionMacroEngine:
    """
    Cycle 22 Discrete 5-State Risk Engine and Macro Shock Governor.
    Fail-Closed Invariant: LIVE_ORDER_DISPATCH_ENABLED = False.
    """

    def __init__(
        self,
        params: Optional[JumpDiffusionParameters] = None,
        n_particles: int = 1000,
        degeneracy_threshold_fraction: float = 0.10,
    ) -> None:
        self.params = params or JumpDiffusionParameters()
        self.filter = SMCParticleFilter(self.params, n_particles=n_particles)
        self.calibrator = RealTimeJumpDiffusionCalibrator(self.filter)
        self.degeneracy_threshold = n_particles * degeneracy_threshold_fraction

        self.state: FilterRiskState = FilterRiskState.IDLE
        self.emergency_latched: bool = False
        self.recovery_acknowledged: bool = False
        self.last_surface_calibration: Optional[Dict[str, Any]] = None

    def initialize(self, initial_spot: float, initial_vol: float = 0.20) -> None:
        self.filter.initialize(initial_spot, initial_vol)
        self.state = FilterRiskState.FILTERING_ACTIVE

    def step(
        self,
        observed_spot: float,
        dt: float,
        observed_iv: Optional[float] = None,
        macro_event: Optional[MacroEventMetadata] = None,
        current_time: float = 0.0,
    ) -> Dict[str, Any]:
        """Perform one online filter step and risk state evaluation."""
        if self.emergency_latched:
            self.state = FilterRiskState.EMERGENCY_UNWIND
            return {
                "state": self.state.value,
                "error": "Emergency unwind latched. Awaiting recovery acknowledgement.",
                "estimates": None,
            }

        if not self.filter.is_initialized:
            self.initialize(observed_spot)

        try:
            self.filter.propagate(dt=dt, macro_event=macro_event, current_time=current_time)
            self.filter.update_measurement(observed_spot=observed_spot, observed_iv=observed_iv)
        except Exception as exc:
            self.trigger_emergency_unwind(f"Filter step exception: {exc}")
            return {
                "state": self.state.value,
                "error": str(exc),
                "estimates": None,
            }

        estimates = self.filter.get_state_estimates()

        # Check particle degeneracy halt
        if estimates["effective_sample_size"] < self.degeneracy_threshold:
            self.state = FilterRiskState.DEGENERACY_SPIKE_HALT
            return {
                "state": self.state.value,
                "warning": "Effective sample size dropped below critical threshold",
                "estimates": estimates,
            }

        self.state = FilterRiskState.FILTERING_ACTIVE
        return {
            "state": self.state.value,
            "estimates": estimates,
        }

    def calibrate_surface(
        self,
        spot: float,
        strikes: np.ndarray,
        tau: float,
        r: float = 0.065,
        macro_event: Optional[MacroEventMetadata] = None,
        current_time: float = 0.0,
    ) -> Dict[str, Any]:
        """Calibrate real-time IV surface and update state."""
        if self.emergency_latched:
            self.state = FilterRiskState.EMERGENCY_UNWIND
            raise RuntimeError("Cannot calibrate surface while emergency unwind is latched")

        if self.state == FilterRiskState.DEGENERACY_SPIKE_HALT:
            raise RuntimeError("Cannot calibrate surface during degeneracy spike halt")

        res = self.calibrator.calibrate_surface_slice(
            spot=spot,
            strikes=strikes,
            tau=tau,
            r=r,
            macro_event=macro_event,
            current_time=current_time,
        )
        self.last_surface_calibration = res
        self.state = FilterRiskState.SURFACE_CALIBRATED
        return res

    def evaluate_frictional_alpha(
        self,
        gross_alpha_rupees: float,
        option_premium: float,
        lots: int,
        lot_size: int = 50,
        is_sell: bool = True,
    ) -> Dict[str, Any]:
        """Computes friction-deducted net alpha for an options trade."""
        cost_breakdown = calculate_indian_statutory_friction(
            premium=option_premium,
            lots=lots,
            lot_size=lot_size,
            is_sell=is_sell,
        )
        net_alpha = gross_alpha_rupees - cost_breakdown["total_hurdle"]
        is_viable = net_alpha > 0.0

        return {
            "gross_alpha": gross_alpha_rupees,
            "net_alpha": net_alpha,
            "cost_breakdown": cost_breakdown,
            "is_frictional_hurdle_cleared": is_viable,
        }

    def trigger_emergency_unwind(self, reason: str) -> None:
        self.emergency_latched = True
        self.recovery_acknowledged = False
        self.state = FilterRiskState.EMERGENCY_UNWIND

    def acknowledge_recovery(self) -> bool:
        if self.emergency_latched:
            self.emergency_latched = False
            self.recovery_acknowledged = True
            self.state = FilterRiskState.IDLE
            return True
        return False

    def dispatch_live_order(self, *args: Any, **kwargs: Any) -> None:
        """Fail-Closed Safety Invariant."""
        if not LIVE_ORDER_DISPATCH_ENABLED:
            raise PermissionError(
                "GATE_LIVE_ORDER_LOCKED: LIVE_ORDER_DISPATCH_ENABLED is False. "
                "Real broker order execution is permanently locked in paper simulation mode."
            )

"""Multivariate Marked Hawkes, Multi-Level OFI & Jump-Diffusion Engine.

Anchored in Phase 28 Autonomous Self-Evolution Architecture:
1. Multivariate Hawkes Point Process with multi-exponential kernels (fast/slow decay channels).
2. Exact event-time discrete state recursion preserving sub-millisecond timestamps.
3. Spectral radius stability check rho(K) <= 0.90 on the integrated branching ratio matrix.
4. Depth-normalized Multi-Level Order Flow Imbalance (MLOFI) across L order book levels.
5. Coupled Jump-Diffusion second-moment horizon risk forecasting V_H.
6. Scenario-based Gamma-Zone and Expiry exposure tracking for NIFTY 50 and BANKNIFTY.

Fail-Closed Safety Invariant:
- Out-of-order events (dt < 0) are strictly rejected.
- Non-finite or non-positive baseline intensities raise validation errors.
- Unstable branching matrices rho(K) >= 1.0 are rejected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class MarketDataQuality(str, Enum):
    VALID = "VALID"
    STALE = "STALE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    NON_FINITE_INTENSITY = "NON_FINITE_INTENSITY"
    UNSTABLE_BRANCHING = "UNSTABLE_BRANCHING"


@dataclass(frozen=True)
class HawkesEvent:
    timestamp: float          # Epoch seconds (float)
    event_type: int           # 0 = Buy trade, 1 = Sell trade, 2 = Book update
    price: float = 0.0
    size: float = 0.0
    contract_id: str = "NIFTY_FUT"


@dataclass
class OrderBookLevel:
    bid_price: float
    bid_size: float
    ask_price: float
    ask_size: float


@dataclass
class MicrostructureRiskSnapshot:
    timestamp: float
    intensities: List[float]               # lambda_i for each event type
    total_intensity: float
    fast_excitation_sum: float
    slow_excitation_sum: float
    branching_spectral_radius: float
    is_stable: bool
    multilevel_ofi: float
    normalized_ofi: float                  # in [-1, 1] range
    conditional_jump_volatility: float      # V_H second-moment annualized
    scenario_gamma_exposure: float
    data_quality: MarketDataQuality


class MultivariateHawkesOFIJumpEngine:
    """Production-grade multivariate Hawkes with multi-level OFI and jump diffusion."""

    def __init__(
        self,
        num_types: int = 2,
        num_kernels: int = 2,
        base_rates: Optional[List[float]] = None,
        decay_rates: Optional[List[List[List[float]]]] = None,
        excitation_amplitudes: Optional[List[List[List[float]]]] = None,
        max_branching_ratio: float = 0.90,
    ) -> None:
        self.d = num_types
        self.M = num_kernels
        self.max_branching_ratio = max_branching_ratio

        # Default base rates mu_i > 0
        self.mu = base_rates or [0.5 for _ in range(self.d)]
        if len(self.mu) != self.d:
            raise ValueError(f"Expected {self.d} base rates, got {len(self.mu)}")
        for i, val in enumerate(self.mu):
            if val <= 0:
                raise ValueError(f"Base rate mu[{i}] must be strictly positive, got {val}")

        # Default multi-exponential decay kernels: M=2 (fast burst beta=3.0, slow cluster beta=0.5)
        # Dimensions: [i, j, m]
        if decay_rates is None:
            self.beta = [
                [[3.0 if m == 0 else 0.5 for m in range(self.M)] for _ in range(self.d)]
                for _ in range(self.d)
            ]
        else:
            if len(decay_rates) != self.d or any(len(row) != self.d or any(len(k) != self.M for k in row) for row in decay_rates):
                raise ValueError(f"decay_rates shape must be [{self.d}, {self.d}, {self.M}]")
            for i in range(self.d):
                for j in range(self.d):
                    for m in range(self.M):
                        if decay_rates[i][j][m] <= 0:
                            raise ValueError(f"Decay rate beta[{i}][{j}][{m}] must be strictly positive, got {decay_rates[i][j][m]}")
            self.beta = decay_rates

        # Default excitation amplitudes alpha[i, j, m] >= 0
        if excitation_amplitudes is None:
            self.alpha = [
                [[0.3 if m == 0 else 0.1 for m in range(self.M)] for _ in range(self.d)]
                for _ in range(self.d)
            ]
        else:
            if len(excitation_amplitudes) != self.d or any(len(row) != self.d or any(len(k) != self.M for k in row) for row in excitation_amplitudes):
                raise ValueError(f"excitation_amplitudes shape must be [{self.d}, {self.d}, {self.M}]")
            for i in range(self.d):
                for j in range(self.d):
                    for m in range(self.M):
                        if excitation_amplitudes[i][j][m] < 0:
                            raise ValueError(f"Excitation amplitude alpha[{i}][{j}][{m}] must be non-negative, got {excitation_amplitudes[i][j][m]}")
            self.alpha = excitation_amplitudes

        # Validate stability
        self.spectral_radius, self.is_stable = self._compute_spectral_radius()
        if not self.is_stable:
            raise ValueError(
                f"Hawkes branching matrix is unstable: rho(K)={self.spectral_radius:.4f} >= {self.max_branching_ratio}"
            )

        # State tensor X[i, j, m]
        self.X: List[List[List[float]]] = [
            [[0.0 for _ in range(self.M)] for _ in range(self.d)]
            for _ in range(self.d)
        ]
        self.last_timestamp: float = 0.0
        self.event_count: int = 0

    def _compute_spectral_radius(self) -> Tuple[float, bool]:
        """Compute the spectral radius of the integrated excitation matrix K_{ij} = sum_m (alpha_{ijm} / beta_{ijm})."""
        K = [[0.0 for _ in range(self.d)] for _ in range(self.d)]
        for i in range(self.d):
            for j in range(self.d):
                total_k = 0.0
                for m in range(self.M):
                    b = max(1e-6, self.beta[i][j][m])
                    a = max(0.0, self.alpha[i][j][m])
                    total_k += a / b
                K[i][j] = total_k

        # For 2x2 case, closed-form eigenvalues:
        if self.d == 2:
            k11 = K[0][0]
            k12 = K[0][1]
            k21 = K[1][0]
            k22 = K[1][1]
            trace = k11 + k22
            det = (k11 * k22) - (k12 * k21)
            disc = max(0.0, (trace ** 2) - (4.0 * det))
            lambda1 = (trace + math.sqrt(disc)) / 2.0
            lambda2 = (trace - math.sqrt(disc)) / 2.0
            rho = max(abs(lambda1), abs(lambda2))
        else:
            # Power iteration approximation for general d
            v = [1.0 / math.sqrt(self.d) for _ in range(self.d)]
            rho = 0.0
            for _ in range(30):
                w = [sum(K[i][j] * v[j] for j in range(self.d)) for i in range(self.d)]
                norm = math.sqrt(sum(x * x for x in w))
                if norm < 1e-12:
                    rho = 0.0
                    break
                rho = norm
                v = [x / norm for x in w]

        rho_rounded = round(rho, 4)
        is_stable = rho_rounded <= round(self.max_branching_ratio, 4)
        return rho_rounded, is_stable

    def process_event(self, event: HawkesEvent) -> Tuple[List[float], MarketDataQuality]:
        """Process incoming market event with exact continuous-time exponential decay.
        
        Exact recursion:
            dt = t_{k+1} - t_k
            X_{ijm, k+1} = e^{-beta_{ijm} dt} * X_{ijm, k} + alpha_{ijm} (if excited by j)
            lambda_i(t_{k+1}^+) = mu_i + sum_{j, m} X_{ijm, k+1}
        """
        if self.event_count > 0:
            dt = event.timestamp - self.last_timestamp
            if dt < 0:
                return self.current_intensities(), MarketDataQuality.OUT_OF_ORDER
        else:
            dt = 0.0

        # Exact exponential decay
        if dt > 0:
            for i in range(self.d):
                for j in range(self.d):
                    for m in range(self.M):
                        self.X[i][j][m] *= math.exp(-self.beta[i][j][m] * dt)

        # Compute pre-event intensities
        intensities: List[float] = []
        for i in range(self.d):
            lambda_i = self.mu[i] + sum(self.X[i][j][m] for j in range(self.d) for m in range(self.M))
            if not math.isfinite(lambda_i) or lambda_i <= 0:
                return [0.0] * self.d, MarketDataQuality.NON_FINITE_INTENSITY
            intensities.append(lambda_i)

        # Event exciting state
        j_event = event.event_type
        if 0 <= j_event < self.d:
            for i in range(self.d):
                for m in range(self.M):
                    self.X[i][j_event][m] += self.alpha[i][j_event][m]

        self.last_timestamp = event.timestamp
        self.event_count += 1
        return intensities, MarketDataQuality.VALID

    def current_intensities(self) -> List[float]:
        """Calculate instantaneous intensities without processing a new event."""
        res: List[float] = []
        for i in range(self.d):
            val = self.mu[i] + sum(self.X[i][j][m] for j in range(self.d) for m in range(self.M))
            res.append(val)
        return res

    @staticmethod
    def compute_multilevel_ofi(
        prev_book: List[OrderBookLevel],
        curr_book: List[OrderBookLevel],
        depth_levels: int = 5,
        decay_factor: float = 0.5,
        epsilon: float = 1e-6,
    ) -> Tuple[float, float]:
        """Compute depth-weighted multi-level order flow imbalance (MLOFI) and depth-normalized OFI (NOFI).
        
        Cont, Kukanov & Stoikov (2014) formulation extended to L levels:
        w_ell = e^{-decay_factor * (ell - 1)}
        e_{ell, k} = 1(P_k^B >= P_{k-1}^B) Q_k^B - 1(P_k^B <= P_{k-1}^B) Q_{k-1}^B
                     - 1(P_k^A <= P_{k-1}^A) Q_k^A + 1(P_k^A >= P_{k-1}^A) Q_{k-1}^A
        NOFI_k = MLOFI_k / (epsilon + sum w_ell * (Q_ell^B + Q_ell^A))
        """
        L = min(len(prev_book), len(curr_book), depth_levels)
        if L == 0:
            return 0.0, 0.0

        mlofi = 0.0
        total_depth = 0.0

        for ell in range(L):
            w = math.exp(-decay_factor * ell)
            p_prev = prev_book[ell]
            p_curr = curr_book[ell]

            # Bid side contribution
            if p_curr.bid_price > p_prev.bid_price:
                delta_b = p_curr.bid_size
            elif p_curr.bid_price == p_prev.bid_price:
                delta_b = p_curr.bid_size - p_prev.bid_size
            else:
                delta_b = -p_prev.bid_size

            # Ask side contribution
            if p_curr.ask_price < p_prev.ask_price:
                delta_a = p_curr.ask_size
            elif p_curr.ask_price == p_prev.ask_price:
                delta_a = p_curr.ask_size - p_prev.ask_size
            else:
                delta_a = -p_prev.ask_size

            level_ofi = delta_b - delta_a
            mlofi += w * level_ofi
            total_depth += w * (p_curr.bid_size + p_curr.ask_size)

        safe_denom = max(1e-12, epsilon) + max(0.0, total_depth)
        nofi = mlofi / safe_denom
        if not math.isfinite(nofi):
            nofi = 0.0
        # Bound NOFI strictly within [-1.0, 1.0]
        nofi = max(-1.0, min(1.0, nofi))
        return round(mlofi, 2), round(nofi, 4)

    def estimate_conditional_jump_volatility(
        self,
        horizon_seconds: float = 1.0,
        baseline_diffusive_vol: float = 0.15,
        jump_size_mean: float = 0.002,
        jump_size_std: float = 0.005,
        trading_seconds_per_year: float = 252.0 * 375.0 * 60.0,
    ) -> float:
        """First-order conditional second-moment volatility over horizon H under Hawkes arrival.
        
        V_H ≈ sigma_t^2 * H + E[N_H | F_t] * E[J^2]
        where E[J^2] = Var(J) + E[J]^2
        
        Annualized volatility: sigma_ann = sqrt(max(0, V_H) / H * trading_seconds_per_year)
        """
        h = max(1e-6, horizon_seconds)
        intensities = self.current_intensities()
        lambda_total = sum(intensities)
        expected_jumps = lambda_total * h
        second_moment_jump = (jump_size_std ** 2) + (jump_size_mean ** 2)

        # Diffusive return variance scaled consistently by trading seconds per year
        variance_h = (baseline_diffusive_vol ** 2) * (h / trading_seconds_per_year) + (
            expected_jumps * second_moment_jump
        )
        # Annualized volatility projection invariant to horizon H
        annualized_vol = math.sqrt(max(0.0, variance_h) / h) * math.sqrt(trading_seconds_per_year)
        return round(annualized_vol, 4)

    @staticmethod
    def estimate_scenario_gamma_exposure(
        underlying_price: float,
        strikes: List[float],
        open_interests: List[float],
        gammas: List[float],
        dealer_signs: Optional[List[float]] = None,
        contract_multiplier: float = 25.0,  # e.g., NIFTY lot size
    ) -> float:
        """Calculate aggregate estimated dealer gamma profile G(S, t) = sum_k s_k * OI_k * Gamma_k * Multiplier.
        
        dealer_signs: assumed net inventory sign (+1 = dealer long gamma, -1 = dealer short gamma)
        """
        K = min(len(strikes), len(open_interests), len(gammas))
        if K == 0:
            return 0.0

        signs = dealer_signs or [-1.0 if strikes[k] >= underlying_price else 1.0 for k in range(K)]
        total_gamma = 0.0
        for k in range(K):
            s = signs[k]
            oi = open_interests[k]
            gamma = gammas[k]
            total_gamma += s * oi * gamma * contract_multiplier

        return round(total_gamma, 2)

    def compute_cross_excitation_asymmetry(
        self,
        source_a: int = 0,
        source_b: int = 1,
        epsilon: float = 1e-9,
    ) -> float:
        """Compute bounded asymmetric cross-excitation ratio D_cross between two processes in [-1.0, 1.0].
        
        D_cross = (kappa_{B <- A} - kappa_{A <- B}) / (kappa_{B <- A} + kappa_{A <- B} + epsilon)
        where kappa_{i <- j} = sum_m (alpha_{ijm} / beta_{ijm}).
        
        D_cross > 0: Asset A excites Asset B more strongly (Asset A leads).
        D_cross < 0: Asset B excites Asset A more strongly (Asset B leads).
        Symmetric bound: D_cross(B, A) == -D_cross(A, B) in [-1.0, 1.0].
        """
        if not (0 <= source_a < self.d and 0 <= source_b < self.d):
            raise IndexError(f"Asset indices ({source_a}, {source_b}) out of bounds for d={self.d}")

        k_ba = sum(
            self.alpha[source_b][source_a][m] / max(1e-6, self.beta[source_b][source_a][m])
            for m in range(self.M)
        )
        k_ab = sum(
            self.alpha[source_a][source_b][m] / max(1e-6, self.beta[source_a][source_b][m])
            for m in range(self.M)
        )
        denom = k_ba + k_ab + max(1e-12, epsilon)
        asym = (k_ba - k_ab) / denom
        if not math.isfinite(asym):
            asym = 0.0
        return max(-1.0, min(1.0, asym))


@dataclass
class OnlineCalibrationMetrics:
    step: int
    dt: float
    log_likelihood_increment: float
    spectral_radius: float
    is_stable: bool
    information_leadership_index: float  # ILI between type 0 and type 1


class OnlineHawkesCalibrator:
    """Online stochastic gradient ascent calibrator for multivariate Hawkes process.
    
    Implements sensitivity traces Y_{ijm} and exact score increments:
    g_mu = 1(c=i)/lambda_i - dt
    g_alpha = 1(c=i)*X^- / lambda_i - X * q(dt)
    g_beta = -alpha*Y^- / lambda + alpha * [Y*q(dt) - X*q'(dt)]
    with spectral radius projection: c = min(1.0, eta_max / rho(K)).
    """

    def __init__(
        self,
        engine: MultivariateHawkesOFIJumpEngine,
        lr_mu: float = 0.005,
        lr_alpha: float = 0.005,
        lr_beta: float = 0.001,
        momentum: float = 0.9,
        eta_max: float = 0.90,
    ) -> None:
        self.engine = engine
        self.lr_mu = lr_mu
        self.lr_alpha = lr_alpha
        self.lr_beta = lr_beta
        self.momentum = momentum
        self.eta_max = eta_max

        d, M = self.engine.d, self.engine.M
        # Unweighted state traces U[i, j, m] (dimensionless event count decay filter)
        self.U: List[List[List[float]]] = [
            [[0.0 for _ in range(M)] for _ in range(d)] for _ in range(d)
        ]
        # Sync with existing engine state if pre-populated
        if self.engine.event_count > 0:
            for i in range(d):
                for j in range(d):
                    for m in range(M):
                        a = self.engine.alpha[i][j][m]
                        self.U[i][j][m] = self.engine.X[i][j][m] / a if a > 1e-6 else 0.0

        # Sensitivity traces Y[i, j, m] = d/dbeta U[i, j, m]
        self.Y: List[List[List[float]]] = [
            [[0.0 for _ in range(M)] for _ in range(d)] for _ in range(d)
        ]

        # Velocity accumulators
        self.v_mu: List[float] = [0.0 for _ in range(d)]
        self.v_alpha: List[List[List[float]]] = [
            [[0.0 for _ in range(M)] for _ in range(d)] for _ in range(d)
        ]
        self.v_beta: List[List[List[float]]] = [
            [[0.0 for _ in range(M)] for _ in range(d)] for _ in range(d)
        ]
        self.steps: int = 0

    def step_event(self, event: HawkesEvent) -> OnlineCalibrationMetrics:
        """Process incoming tick event, update sensitivity traces, compute score, and step parameters."""
        d, M = self.engine.d, self.engine.M
        c = event.event_type
        if c < 0 or c >= d:
            raise ValueError(f"Invalid event type {c} for dimension {d}")

        if self.engine.event_count > 0:
            dt = max(0.0, event.timestamp - self.engine.last_timestamp)
        else:
            dt = 0.0

        # 1. Decay unweighted state U and update sensitivity traces Y
        U_minus: List[List[List[float]]] = [[[0.0 for _ in range(M)] for _ in range(d)] for _ in range(d)]
        Y_minus: List[List[List[float]]] = [[[0.0 for _ in range(M)] for _ in range(d)] for _ in range(d)]
        q_table: List[List[List[float]]] = [[[0.0 for _ in range(M)] for _ in range(d)] for _ in range(d)]
        q_prime_table: List[List[List[float]]] = [[[0.0 for _ in range(M)] for _ in range(d)] for _ in range(d)]

        for i in range(d):
            for j in range(d):
                for m in range(M):
                    beta_val = max(1e-4, self.engine.beta[i][j][m])
                    r_jm = math.exp(-beta_val * dt)
                    U_prev = self.U[i][j][m]
                    Y_prev = self.Y[i][j][m]

                    # Exact decay
                    U_minus[i][j][m] = r_jm * U_prev
                    Y_minus[i][j][m] = r_jm * (Y_prev + dt * U_prev)

                    # q and q' integrals
                    q_table[i][j][m] = (1.0 - r_jm) / beta_val
                    q_prime_table[i][j][m] = (beta_val * dt * r_jm - (1.0 - r_jm)) / (beta_val ** 2)

        # 2. Pre-event intensities
        lambda_minus: List[float] = []
        for i in range(d):
            val = self.engine.mu[i] + sum(
                self.engine.alpha[i][j][m] * U_minus[i][j][m] for j in range(d) for m in range(M)
            )
            lambda_minus.append(max(1e-4, val))

        # 3. Log-likelihood increment
        log_lik_event = math.log(lambda_minus[c])
        compensator = sum(self.engine.mu[i] * dt for i in range(d)) + sum(
            self.engine.alpha[i][j][m] * self.U[i][j][m] * q_table[i][j][m]
            for i in range(d) for j in range(d) for m in range(M)
        )
        delta_ll = log_lik_event - compensator

        # 4. Score gradient increments
        # Baseline gradient g_mu
        for i in range(d):
            indicator = 1.0 if c == i else 0.0
            g_mu = (indicator / lambda_minus[i]) - dt
            # Clip gradient to [-5.0, 5.0]
            g_mu = max(-5.0, min(5.0, g_mu))
            self.v_mu[i] = self.momentum * self.v_mu[i] + (1.0 - self.momentum) * g_mu
            self.engine.mu[i] = max(0.05, self.engine.mu[i] + self.lr_mu * self.v_mu[i])

        # Excitation gradient g_alpha & decay gradient g_beta
        for i in range(d):
            indicator_i = 1.0 if c == i else 0.0
            for j in range(d):
                for m in range(M):
                    u_m = U_minus[i][j][m]
                    u_prev = self.U[i][j][m]
                    q = q_table[i][j][m]
                    q_p = q_prime_table[i][j][m]
                    a_val = self.engine.alpha[i][j][m]

                    g_alpha = (indicator_i * u_m / lambda_minus[i]) - u_prev * q
                    g_alpha = max(-5.0, min(5.0, g_alpha))
                    self.v_alpha[i][j][m] = self.momentum * self.v_alpha[i][j][m] + (1.0 - self.momentum) * g_alpha
                    self.engine.alpha[i][j][m] = max(0.0, self.engine.alpha[i][j][m] + self.lr_alpha * self.v_alpha[i][j][m])

                    # Decay gradient (exact event + compensator derivative)
                    y_m = Y_minus[i][j][m]
                    y_prev = self.Y[i][j][m]
                    event_beta_term = -(a_val * y_m / lambda_minus[i]) if c == i else 0.0
                    comp_beta_term = a_val * (y_prev * q - u_prev * q_p)
                    g_beta = event_beta_term + comp_beta_term
                    g_beta = max(-2.0, min(2.0, g_beta))
                    self.v_beta[i][j][m] = self.momentum * self.v_beta[i][j][m] + (1.0 - self.momentum) * g_beta
                    self.engine.beta[i][j][m] = max(0.1, min(15.0, self.engine.beta[i][j][m] + self.lr_beta * self.v_beta[i][j][m]))

        # 5. Project spectral radius to enforce stability bound rho(K) <= eta_max
        rho, is_stable = self.engine._compute_spectral_radius()
        if rho > self.eta_max:
            scale = self.eta_max / max(1e-6, rho)
            for i in range(d):
                for j in range(d):
                    for m in range(M):
                        self.engine.alpha[i][j][m] *= scale
            rho, is_stable = self.engine._compute_spectral_radius()

        self.engine.spectral_radius = rho
        self.engine.is_stable = is_stable

        # 6. Advance state U, Y and engine.X with event arrival
        for i in range(d):
            for j in range(d):
                for m in range(M):
                    self.U[i][j][m] = U_minus[i][j][m]
                    self.Y[i][j][m] = Y_minus[i][j][m]
                    if j == c:
                        self.U[i][c][m] += 1.0
                    self.engine.X[i][j][m] = self.engine.alpha[i][j][m] * self.U[i][j][m]

        self.engine.last_timestamp = event.timestamp
        self.engine.event_count += 1
        self.steps += 1

        ili = self.compute_information_leadership(0, 1)

        return OnlineCalibrationMetrics(
            step=self.steps,
            dt=round(dt, 4),
            log_likelihood_increment=round(delta_ll, 4),
            spectral_radius=rho,
            is_stable=is_stable,
            information_leadership_index=round(ili, 4),
        )

    def compute_cross_excitation_asymmetry(
        self,
        source_a: int = 0,
        source_b: int = 1,
        epsilon: float = 1e-9,
    ) -> float:
        """Compute bounded asymmetric cross-excitation ratio D_cross in [-1.0, 1.0]."""
        return self.engine.compute_cross_excitation_asymmetry(source_a, source_b, epsilon)

    def compute_information_leadership(
        self,
        source_a: int = 0,
        source_b: int = 1,
        epsilon: float = 1e-9,
    ) -> float:
        """Compute Asymmetric Information Leadership Index (ILI) between two assets in [-1.0, 1.0]."""
        return self.engine.compute_cross_excitation_asymmetry(source_a, source_b, epsilon)


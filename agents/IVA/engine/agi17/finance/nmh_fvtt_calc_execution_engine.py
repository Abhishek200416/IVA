"""Cycle 63 NMH-FVTT-CALC research engine.

Deterministic, offline and paper-only quantitative primitives for research and
replay. This module never connects to a broker or sends an order.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import exp, gamma as gamma_fn, isfinite, sqrt
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.optimize import linprog, minimize

CYCLE_ID = "63"
ENGINE_NAME = "NMH-FVTT-CALC"
ASSETS = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
TOXICITY_RETREAT_THRESHOLD = 0.60
MAX_CONTAGION_SPECTRAL_RADIUS = 0.85
MAX_KELLY_FRACTION = 0.10
DEFAULT_TT_TOLERANCE = 1e-6


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Fail closed, regardless of arguments or configuration."""
    raise PermissionError("Cycle 63 is paper-only: live order dispatch is permanently disabled")


def _finite(name: str, value: float) -> float:
    x = float(value)
    if not isfinite(x):
        raise ValueError(f"{name} must be finite")
    return x


def _nonnegative(name: str, value: float) -> float:
    x = _finite(name, value)
    if x < 0.0:
        raise ValueError(f"{name} must be >= 0")
    return x


def power_law_kernel(lag: float | np.ndarray, alpha: float, gamma: float) -> float | np.ndarray:
    """phi(lag)=alpha*(1+lag)^(-gamma), with gamma>1 for integrable memory."""
    alpha = _nonnegative("alpha", alpha)
    gamma = _finite("gamma", gamma)
    if gamma <= 1.0:
        raise ValueError("gamma must be > 1 for an integrable power-law kernel")
    t = np.asarray(lag, dtype=float)
    if np.any(~np.isfinite(t)) or np.any(t < 0.0):
        raise ValueError("lag must contain finite, nonnegative values")
    out = alpha * np.power(1.0 + t, -gamma)
    return float(out) if out.ndim == 0 else out


def exponential_kernel(lag: float | np.ndarray, weights: Sequence[float], rates: Sequence[float]) -> float | np.ndarray:
    """Nonnegative sum-of-exponentials surrogate for long-memory excitation."""
    t = np.asarray(lag, dtype=float)
    w = np.asarray(weights, dtype=float)
    b = np.asarray(rates, dtype=float)
    if t.ndim > 0 and np.any(~np.isfinite(t)) or not np.all(np.isfinite(t)):
        raise ValueError("lag must be finite")
    if np.any(t < 0):
        raise ValueError("lag must be nonnegative")
    if w.ndim != 1 or b.ndim != 1 or len(w) == 0 or len(w) != len(b):
        raise ValueError("weights and rates must be nonempty one-dimensional arrays of equal length")
    if np.any(~np.isfinite(w)) or np.any(~np.isfinite(b)) or np.any(w < 0) or np.any(b <= 0):
        raise ValueError("weights must be finite and >=0; rates finite and >0")
    out = np.sum(w.reshape((-1,) + (1,) * t.ndim) * np.exp(-b.reshape((-1,) + (1,) * t.ndim) * t), axis=0)
    return float(out) if np.ndim(out) == 0 else out


def signed_mlofi(bid_changes: Sequence[float], ask_changes: Sequence[float],
                  level_weights: Sequence[float] = (1.0, 0.8, 0.6, 0.4, 0.2)) -> float:
    """Signed five-level MLOFI proxy: weighted (bid-side change - ask-side change).

    Inputs are signed queue-size changes, not inferred from a live broker feed.
    """
    bid = np.asarray(bid_changes, dtype=float)
    ask = np.asarray(ask_changes, dtype=float)
    weights = np.asarray(level_weights, dtype=float)
    if bid.shape != (5,) or ask.shape != (5,) or weights.shape != (5,):
        raise ValueError("bid_changes, ask_changes and level_weights must each have length 5")
    if not all(np.all(np.isfinite(x)) for x in (bid, ask, weights)) or np.any(weights < 0):
        raise ValueError("MLOFI inputs must be finite and weights nonnegative")
    scale = float(np.sum(weights))
    if scale <= 0.0:
        raise ValueError("at least one level weight must be positive")
    return float(np.dot(weights, bid - ask) / scale)


def hawkes_intensity(now: float, event_times: Sequence[float], mu0: float, *,
                     kernel: str = "power_law", alpha: float = 0.4, gamma: float = 1.4,
                     weights: Sequence[float] = (0.20, 0.08, 0.03),
                     rates: Sequence[float] = (0.15, 0.03, 0.005),
                     signed_ofi: float = 0.0, ofi_sensitivity: float = 0.0) -> float:
    """Predictable Hawkes intensity at `now`, with signed OFI modulation.

    Only events strictly before `now` contribute. The nonnegative floor avoids
    negative intensities after adverse OFI; OFI can reduce, not negate, the rate.
    """
    now, mu0 = _finite("now", now), _nonnegative("mu0", mu0)
    signed_ofi = _finite("signed_ofi", signed_ofi)
    ofi_sensitivity = _finite("ofi_sensitivity", ofi_sensitivity)
    history = np.asarray(event_times, dtype=float)
    if np.any(~np.isfinite(history)):
        raise ValueError("event_times must be finite")
    history = history[history < now]
    lags = now - history
    if kernel == "power_law":
        excitation = float(np.sum(power_law_kernel(lags, alpha, gamma)))
    elif kernel == "exponential":
        excitation = float(np.sum(exponential_kernel(lags, weights, rates)))
    else:
        raise ValueError("kernel must be 'power_law' or 'exponential'")
    return max(0.0, mu0 + excitation + ofi_sensitivity * signed_ofi)



def multivariate_hawkes_intensity(now: float, event_times_by_asset: Sequence[Sequence[float]],
        baselines: Sequence[float], excitation_matrix: Sequence[Sequence[float]], *,
        gamma: float = 1.4, ofi_scores: Sequence[float] | None = None,
        ofi_sensitivities: Sequence[float] | None = None) -> list[float]:
    """Non-Markovian cross-asset Hawkes vector with signed MLOFI modulation.

    ``excitation_matrix[i,j]`` is the power-law amplitude from events in asset j
    into intensity i. For a stationary power-law Hawkes specification, the
    branching matrix ``excitation_matrix/(gamma-1)`` should have spectral radius
    below one; the function reports intensities but does not silently rescale a
    caller's research parameters.
    """
    now, gamma = _finite("now", now), _finite("gamma", gamma)
    if gamma <= 1.0:
        raise ValueError("gamma must be >1")
    mu = np.asarray(baselines, dtype=float)
    A = np.asarray(excitation_matrix, dtype=float)
    histories = list(event_times_by_asset)
    n = len(histories)
    if mu.shape != (n,) or A.shape != (n, n) or n == 0:
        raise ValueError("histories, baselines and square excitation matrix dimensions must agree")
    if np.any(~np.isfinite(mu)) or np.any(mu < 0) or np.any(~np.isfinite(A)) or np.any(A < 0):
        raise ValueError("baselines and excitation amplitudes must be finite and nonnegative")
    ofi = np.zeros(n) if ofi_scores is None else np.asarray(ofi_scores, dtype=float)
    sens = np.zeros(n) if ofi_sensitivities is None else np.asarray(ofi_sensitivities, dtype=float)
    if ofi.shape != (n,) or sens.shape != (n,) or np.any(~np.isfinite(ofi)) or np.any(~np.isfinite(sens)):
        raise ValueError("OFI scores and sensitivities must be finite vectors matching asset count")
    memory = np.zeros(n, dtype=float)
    for j, event_times in enumerate(histories):
        times_j = np.asarray(event_times, dtype=float)
        if np.any(~np.isfinite(times_j)):
            raise ValueError("event history timestamps must be finite")
        lags = now - times_j[times_j < now]
        aggregate = float(np.sum(power_law_kernel(lags, 1.0, gamma))) if len(lags) else 0.0
        memory += A[:, j] * aggregate
    return np.maximum(0.0, mu + memory + sens * ofi).astype(float).tolist()


def hawkes_branching_diagnostics(excitation_matrix: Sequence[Sequence[float]], gamma: float) -> dict[str, Any]:
    """Compute the power-law Hawkes branching matrix spectral-radius diagnostic."""
    A = np.asarray(excitation_matrix, dtype=float)
    gamma = _finite("gamma", gamma)
    if A.ndim != 2 or A.shape[0] != A.shape[1] or A.shape[0] == 0:
        raise ValueError("excitation_matrix must be nonempty and square")
    if np.any(~np.isfinite(A)) or np.any(A < 0) or gamma <= 1.0:
        raise ValueError("amplitudes must be finite/nonnegative and gamma >1")
    branching = A / (gamma - 1.0)
    radius = float(np.max(np.abs(np.linalg.eigvals(branching))))
    return {"branching_matrix": branching.tolist(), "spectral_radius": radius,
            "subcritical": bool(radius < 1.0)}


def adverse_jump_probability(intensity: float, horizon: float) -> float:
    """P(adverse jump in horizon)=1-exp(-lambda*horizon), using a Poisson hazard."""
    lam = _nonnegative("intensity", intensity)
    tau = _nonnegative("horizon", horizon)
    return float(-np.expm1(-lam * tau))


def toxicity_action(intensity: float, horizon: float, threshold: float = TOXICITY_RETREAT_THRESHOLD) -> str:
    """RETREAT iff adverse-event probability strictly exceeds the threshold."""
    threshold = _finite("threshold", threshold)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    return "RETREAT" if adverse_jump_probability(intensity, horizon) > threshold else "CONTINUE"


def transient_power_law_impact(trade_sizes: Sequence[float], times: Sequence[float], eta: float, decay: float) -> float:
    """Quadratic transient-impact cost using a causal power-law decay matrix."""
    q = np.asarray(trade_sizes, dtype=float)
    t = np.asarray(times, dtype=float)
    eta, decay = _nonnegative("eta", eta), _finite("decay", decay)
    if decay <= 0:
        raise ValueError("decay must be >0")
    if q.ndim != 1 or t.shape != q.shape or len(q) == 0 or np.any(~np.isfinite(q)) or np.any(q < 0):
        raise ValueError("trade_sizes and times must be same-length finite 1-D arrays; sizes >=0")
    if np.any(~np.isfinite(t)) or np.any(np.diff(t) < 0):
        raise ValueError("times must be finite and nondecreasing")
    dt = np.abs(t[:, None] - t[None, :])
    kernel = np.power(1.0 + dt, -decay)
    return float(0.5 * eta * q @ kernel @ q)


def optimal_liquidation_schedule(initial_inventory: float, times: Sequence[float], *,
        volatility: float = 0.2, risk_aversion: float = 0.05, impact_eta: float = 0.01,
        impact_decay: float = 0.7, intensities: Sequence[float] | None = None,
        toxicity_penalty: float = 0.0) -> dict[str, Any]:
    """Finite-grid convex liquidation plan with exact q(T)=0.

    Optimizes nonnegative sell clips v summing to q0 under a quadratic transient
    impact + inventory risk + toxicity-weighted urgency objective. SLSQP solves
    the small convex simplex problem; output is reprojected only at roundoff scale.
    This is a grid approximation, not a claim of globally optimal continuous-time
    control under misspecified market dynamics.
    """
    q0 = _nonnegative("initial_inventory", initial_inventory)
    t = np.asarray(times, dtype=float)
    volatility = _nonnegative("volatility", volatility)
    risk_aversion = _nonnegative("risk_aversion", risk_aversion)
    impact_eta = _nonnegative("impact_eta", impact_eta)
    impact_decay = _finite("impact_decay", impact_decay)
    toxicity_penalty = _nonnegative("toxicity_penalty", toxicity_penalty)
    if impact_decay <= 0 or t.ndim != 1 or len(t) < 2 or np.any(~np.isfinite(t)) or np.any(np.diff(t) <= 0):
        raise ValueError("times must be a finite strictly increasing 1-D grid of length >=2")
    n = len(t) - 1
    lam = np.zeros(n, dtype=float) if intensities is None else np.asarray(intensities, dtype=float)
    if lam.shape != (n,) or np.any(~np.isfinite(lam)) or np.any(lam < 0):
        raise ValueError("intensities must be nonnegative and match the number of intervals")
    if q0 == 0:
        return {"times": t.tolist(), "trades": [0.0] * n, "inventory": [0.0] * len(t),
                "terminal_inventory": 0.0, "objective": 0.0, "success": True}
    dt = np.diff(t)
    # Transient impact matrix on clip times.
    lag = np.abs(t[:-1, None] - t[None, :-1])
    G = impact_eta * np.power(1.0 + lag, -impact_decay)
    def objective(v: np.ndarray) -> float:
        remaining = q0 - np.cumsum(v)
        risk = risk_aversion * volatility * volatility * float(np.sum(remaining * remaining * dt))
        impact = 0.5 * float(v @ G @ v)
        # Toxicity penalizes retaining inventory into hazard-heavy intervals,
        # therefore the optimizer tends to flatten exposure before those intervals.
        hazard = toxicity_penalty * float(np.dot(lam, remaining * remaining * dt))
        return impact + risk + hazard
    constraints = ({"type": "eq", "fun": lambda v: np.sum(v) - q0, "jac": lambda v: np.ones_like(v)},)
    result = minimize(objective, np.full(n, q0 / n), method="SLSQP", bounds=[(0.0, q0)] * n,
                      constraints=constraints, options={"ftol": 1e-12, "maxiter": 1000})
    if not result.success and abs(float(np.sum(result.x)) - q0) > 1e-7:
        raise RuntimeError(f"liquidation optimizer failed: {result.message}")
    trades = np.maximum(np.asarray(result.x, dtype=float), 0.0)
    # Correct only small simplex round-off; preserves nonnegative clip sizes.
    trades *= q0 / float(np.sum(trades))
    inventory = np.concatenate(([q0], q0 - np.cumsum(trades)))
    inventory[-1] = 0.0
    return {"times": t.tolist(), "trades": trades.tolist(), "inventory": inventory.tolist(),
            "terminal_inventory": float(inventory[-1]), "objective": float(objective(trades)),
            "success": bool(result.success)}


def volterra_kernel(t: float, s: float, H: float, *, min_gap: float = 1e-12) -> float:
    """Regularized causal fractional Volterra kernel.

    K(t,s)=(t-s)^(H-1/2)/Gamma(H+1/2) for t>s; zero for t<s. Since H<1/2,
    the diagonal is singular; its finite-grid value uses an explicit `min_gap`.
    The singularity is integrable and a discretization convention must be stated.
    """
    t, s, H, min_gap = _finite("t", t), _finite("s", s), _finite("H", H), _finite("min_gap", min_gap)
    if not 0.0 < H < 0.5:
        raise ValueError("H must lie strictly in (0, 0.5)")
    if min_gap <= 0:
        raise ValueError("min_gap must be >0")
    delta = t - s
    if delta < 0:
        return 0.0
    return float(max(delta, min_gap) ** (H - 0.5) / gamma_fn(H + 0.5))


def volterra_kernel_matrix(times: Sequence[float], H: float, *, min_gap: float = 1e-6) -> np.ndarray:
    """Lower-triangular discretization of K(t_i,t_j)."""
    t = np.asarray(times, dtype=float)
    if t.ndim != 1 or len(t) == 0 or np.any(~np.isfinite(t)) or np.any(np.diff(t) < 0):
        raise ValueError("times must be a finite nondecreasing 1-D sequence")
    return np.asarray([[volterra_kernel(float(ti), float(tj), H, min_gap=min_gap) for tj in t] for ti in t])


def tt_svd(tensor: np.ndarray, tolerance: float = DEFAULT_TT_TOLERANCE) -> dict[str, Any]:
    """Tensor-train SVD; total Frobenius truncation error is bounded by tolerance.

    Tolerance is an absolute error budget split in quadrature across TT-SVD cuts.
    Cores use shape (r[k], n[k], r[k+1]); rank-one boundary conditions hold.
    """
    A = np.asarray(tensor, dtype=float)
    tolerance = _nonnegative("tolerance", tolerance)
    if A.ndim < 2 or any(n < 1 for n in A.shape) or np.any(~np.isfinite(A)):
        raise ValueError("tensor must be finite and have at least two nonempty dimensions")
    original_norm = float(np.linalg.norm(A.ravel()))
    if original_norm == 0.0:
        cores = [np.zeros((1, n, 1), dtype=float) for n in A.shape]
        return {"cores": cores, "shape": list(A.shape), "ranks": [1] * (A.ndim + 1),
                "frobenius_error": 0.0, "relative_error": 0.0, "norm_error": 0.0,
                "tolerance": tolerance, "bound_met": True}
    cores: list[np.ndarray] = []
    ranks = [1]
    remainder = A.copy()
    r_prev = 1
    local_tol = tolerance / sqrt(max(1, A.ndim - 1))
    for k, n_k in enumerate(A.shape[:-1]):
        M = remainder.reshape(r_prev * n_k, -1)
        U, S, Vh = np.linalg.svd(M, full_matrices=False)
        # Retain the smallest rank whose discarded singular-value norm fits budget.
        tail_sq = np.cumsum((S[::-1] ** 2))[::-1]
        r = len(S)
        for candidate in range(1, len(S) + 1):
            discarded = float(tail_sq[candidate]) if candidate < len(S) else 0.0
            if sqrt(max(0.0, discarded)) <= local_tol:
                r = candidate
                break
        cores.append(U[:, :r].reshape(r_prev, n_k, r))
        remainder = (S[:r, None] * Vh[:r, :]).reshape((r,) + A.shape[k + 1:])
        r_prev = r
        ranks.append(r)
    cores.append(remainder.reshape(r_prev, A.shape[-1], 1))
    ranks.append(1)
    reconstructed = tt_reconstruct(cores)
    error = float(np.linalg.norm((A - reconstructed).ravel()))
    norm_error = abs(float(np.linalg.norm(reconstructed.ravel())) - original_norm)
    bound_met = error <= tolerance + max(1e-12, tolerance * 1e-6)
    return {"cores": cores, "shape": list(A.shape), "ranks": ranks,
            "frobenius_error": error, "relative_error": error / original_norm,
            "norm_error": norm_error, "tolerance": tolerance, "bound_met": bool(bound_met)}


def tt_reconstruct(cores: Sequence[np.ndarray]) -> np.ndarray:
    """Reconstruct a tensor from TT cores, validating bond dimensions."""
    if not cores:
        raise ValueError("at least one TT core is required")
    parsed = [np.asarray(core, dtype=float) for core in cores]
    for core in parsed:
        if core.ndim != 3 or any(n < 1 for n in core.shape) or np.any(~np.isfinite(core)):
            raise ValueError("each TT core must be a finite rank-3 nonempty array")
    if parsed[0].shape[0] != 1 or parsed[-1].shape[2] != 1:
        raise ValueError("TT boundary ranks must be one")
    result = parsed[0]
    for next_core in parsed[1:]:
        if result.shape[-1] != next_core.shape[0]:
            raise ValueError("adjacent TT bond dimensions do not match")
        result = np.tensordot(result, next_core, axes=([-1], [0]))
    return np.squeeze(result, axis=(0, -1))


def fractional_variance_covariance_tensor(asset_count: int = 4, maturity_count: int = 4,
        H: float = 0.12, seed: int = 63) -> np.ndarray:
    """Deterministic positive semi-definite sample covariance tensor for TT demos.

    It is a synthetic construction (factor Gram tensor), not an estimator from
    market data and not implied-volatility surface calibration.
    """
    if not (1 <= asset_count <= 8 and 1 <= maturity_count <= 16):
        raise ValueError("asset_count or maturity_count outside supported demo range")
    if not 0 < H < 0.5:
        raise ValueError("H must lie in (0, 0.5)")
    rng = np.random.default_rng(seed)
    base = rng.normal(size=(asset_count, maturity_count, maturity_count))
    K = volterra_kernel_matrix(np.linspace(0.0, 1.0, maturity_count), H, min_gap=1e-3)
    shaped = np.einsum("aij,jk->aik", base, K)
    return np.einsum("aij,bij->abij", shaped, shaped)


def verify_contagion_matrix(W: Sequence[Sequence[float]], max_radius: float = MAX_CONTAGION_SPECTRAL_RADIUS) -> dict[str, Any]:
    """Verify nonnegative directed spillovers and subcritical spectral radius."""
    M = np.asarray(W, dtype=float)
    max_radius = _finite("max_radius", max_radius)
    if M.ndim != 2 or M.shape[0] != M.shape[1] or M.shape[0] == 0:
        raise ValueError("W must be a nonempty square matrix")
    if np.any(~np.isfinite(M)) or np.any(M < 0):
        raise ValueError("W must contain finite nonnegative directed weights")
    if not 0.0 < max_radius < 1.0:
        raise ValueError("max_radius must lie in (0,1)")
    radius = float(np.max(np.abs(np.linalg.eigvals(M))))
    return {"spectral_radius": radius, "threshold": max_radius, "stable": bool(radius <= max_radius + 1e-12),
            "directed": bool(not np.allclose(M, M.T)), "resolvent_condition_number": float(np.linalg.cond(np.eye(M.shape[0]) - M))}


def scale_contagion_matrix(W: Sequence[Sequence[float]], max_radius: float = MAX_CONTAGION_SPECTRAL_RADIUS) -> np.ndarray:
    """Return a scaled copy with spectral radius at most the requested cap."""
    M = np.asarray(W, dtype=float)
    max_radius = _finite("max_radius", max_radius)
    if not 0.0 < max_radius < 1.0:
        raise ValueError("max_radius must lie in (0,1)")
    diagnostics = verify_contagion_matrix(M, max_radius=1.0 - 1e-12)
    radius = diagnostics["spectral_radius"]
    if radius == 0.0 or radius <= max_radius:
        return M.copy()
    return M * (max_radius / radius)


def systemic_liquidity_drain_index(W: Sequence[Sequence[float]], drain_shock: Sequence[float] | None = None) -> dict[str, Any]:
    """Systemic Liquidity Drain Index (SLDI) from nonnegative direct drain shocks.

    Amplification solves d_total=(I-W)^(-1)d. The index is normalized extra
    amplification / total amplification, in [0,1) when the matrix is subcritical
    and the shock is nonnegative. It is a defined diagnostic, not a regulator metric.
    """
    M = np.asarray(W, dtype=float)
    d = np.ones(M.shape[0], dtype=float) if M.ndim == 2 and drain_shock is None else np.asarray(drain_shock, dtype=float)
    diagnostics = verify_contagion_matrix(M, max_radius=1.0 - 1e-12)
    if not diagnostics["spectral_radius"] < 1.0:
        raise ValueError("SLDI requires rho(W)<1")
    if d.shape != (M.shape[0],) or np.any(~np.isfinite(d)) or np.any(d < 0):
        raise ValueError("drain_shock must be a nonnegative finite vector matching W")
    propagated = np.linalg.solve(np.eye(M.shape[0]) - M, d)
    denominator = float(np.sum(propagated))
    total_drain = float(np.sum(d))
    sldi = 0.0 if denominator == 0 else float(np.clip((denominator - total_drain) / denominator, 0.0, 1.0))
    return {"sldi": sldi, "direct_drain": total_drain, "propagated_drain": denominator,
            "amplification": float(denominator / total_drain) if total_drain > 0 else 1.0,
            "spectral_radius": diagnostics["spectral_radius"]}


@dataclass(frozen=True)
class MOTResult:
    lower_bound: float
    upper_bound: float
    lower_duality_gap: float
    upper_duality_gap: float
    row_martingale_residual: float
    row_mass_residual: float
    column_mass_residual: float
    lower_coupling: list[list[float]]
    upper_coupling: list[list[float]]
    success: bool


def martingale_transport_bounds(source_states: Sequence[float], source_probs: Sequence[float],
        target_states: Sequence[float], target_probs: Sequence[float], payoff: Sequence[Sequence[float]],
        tolerance: float = 1e-8) -> MOTResult:
    """Discrete one-step martingale OT primal LP and equality-marginal dual certificates.

    Constraints: row marginals, column marginals, and for each source state i,
    sum_j pi[i,j]*(y_j-x_i)=0. The supplied marginals must be in convex order or
    the LP is infeasible. The bounds apply only to this finite support/grid.
    """
    x, mu = np.asarray(source_states, float), np.asarray(source_probs, float)
    y, nu = np.asarray(target_states, float), np.asarray(target_probs, float)
    C = np.asarray(payoff, float)
    tolerance = _nonnegative("tolerance", tolerance)
    if x.ndim != 1 or y.ndim != 1 or mu.shape != x.shape or nu.shape != y.shape or C.shape != (len(x), len(y)):
        raise ValueError("states, probability vectors and payoff grid have incompatible shapes")
    if len(x) == 0 or len(y) == 0 or any(np.any(~np.isfinite(a)) for a in (x, y, mu, nu, C)):
        raise ValueError("MOT inputs must be nonempty and finite")
    if np.any(mu < 0) or np.any(nu < 0) or abs(float(mu.sum()) - 1) > tolerance or abs(float(nu.sum()) - 1) > tolerance:
        raise ValueError("marginal probabilities must be nonnegative and sum to one")
    if abs(float(np.dot(x, mu) - np.dot(y, nu))) > tolerance:
        raise ValueError("source and target means must match for a martingale coupling")
    m, n = C.shape
    # Redundancy between row mass, column mass, and per-row martingale equations is
    # harmless for HiGHS but a final row/column equation is omitted for conditioning.
    rows = []
    rhs = []
    for i in range(m):
        row = np.zeros((m, n)); row[i, :] = 1.0
        rows.append(row.ravel()); rhs.append(mu[i])
    for j in range(n - 1):
        row = np.zeros((m, n)); row[:, j] = 1.0
        rows.append(row.ravel()); rhs.append(nu[j])
    for i in range(m):
        row = np.zeros((m, n)); row[i, :] = y - x[i]
        rows.append(row.ravel()); rhs.append(0.0)
    Aeq, beq = np.asarray(rows), np.asarray(rhs)
    bounds = [(0.0, None)] * (m * n)
    lo = linprog(C.ravel(), A_eq=Aeq, b_eq=beq, bounds=bounds, method="highs")
    hi = linprog(-C.ravel(), A_eq=Aeq, b_eq=beq, bounds=bounds, method="highs")
    if not lo.success or not hi.success:
        raise ValueError(f"martingale transport LP infeasible or unsolved: lower={lo.message}; upper={hi.message}")
    plo = lo.x.reshape(m, n); phi = hi.x.reshape(m, n)
    def gap(res: Any, sign: float) -> float:
        primal = float(sign * np.dot(C.ravel(), res.x))
        dual = float(np.dot(beq, res.eqlin.marginals))
        return abs(primal - dual)
    lower = float(np.sum(plo * C)); upper = float(np.sum(phi * C))
    row_mass_resid = float(max(np.max(np.abs(plo.sum(axis=1) - mu)), np.max(np.abs(phi.sum(axis=1) - mu))))
    col_mass_resid = float(max(np.max(np.abs(plo.sum(axis=0) - nu)), np.max(np.abs(phi.sum(axis=0) - nu))))
    mart_resid = float(max(np.max(np.abs(np.sum(plo * (y[None, :] - x[:, None]), axis=1))),
                           np.max(np.abs(np.sum(phi * (y[None, :] - x[:, None]), axis=1)))) )
    lower_gap, upper_gap = gap(lo, 1.0), gap(hi, -1.0)
    success = bool(row_mass_resid <= tolerance and col_mass_resid <= tolerance and mart_resid <= tolerance
                   and lower_gap <= tolerance and upper_gap <= tolerance and lower <= upper + tolerance)
    return MOTResult(lower, upper, lower_gap, upper_gap, mart_resid, row_mass_resid, col_mass_resid,
                     plo.tolist(), phi.tolist(), success)


@dataclass(frozen=True)
class IndianFeeSchedule:
    """Cycle-63 requested statutory/transaction assumptions as decimal rates."""
    stt_sell_rate: float = 0.0015
    stamp_buy_rate: float = 0.00003
    nse_transaction_rate: float = 0.0003553
    sebi_rate: float = 0.000001
    brokerage_per_leg_inr: float = 20.0
    gst_rate: float = 0.18


def calculate_indian_fees(*, buy_turnover: float = 0.0, sell_turnover: float = 0.0,
        executed_legs: int = 0, schedule: IndianFeeSchedule = IndianFeeSchedule()) -> dict[str, float]:
    """Compute fees under the exact rates supplied by the Cycle 63 specification.

    NSE and SEBI rates apply to aggregate buy+sell turnover; GST is applied to
    brokerage+NSE+SEBI charges. STT and stamp duty are excluded from the GST base.
    This is the requested modeling schedule and does not replace live broker/tax
    statements; statutory scope/rates can differ by segment and instrument.
    """
    buy, sell = _nonnegative("buy_turnover", buy_turnover), _nonnegative("sell_turnover", sell_turnover)
    if isinstance(executed_legs, bool) or int(executed_legs) != executed_legs or executed_legs < 0:
        raise ValueError("executed_legs must be a nonnegative integer")
    turnover = buy + sell
    stt = sell * schedule.stt_sell_rate
    stamp = buy * schedule.stamp_buy_rate
    nse = turnover * schedule.nse_transaction_rate
    sebi = turnover * schedule.sebi_rate
    brokerage = int(executed_legs) * schedule.brokerage_per_leg_inr
    gst_base = brokerage + nse + sebi
    gst = gst_base * schedule.gst_rate
    total = stt + stamp + nse + sebi + brokerage + gst
    return {"stt_sell_inr": float(stt), "stamp_buy_inr": float(stamp), "nse_transaction_inr": float(nse),
            "sebi_inr": float(sebi), "brokerage_inr": float(brokerage), "gst_base_inr": float(gst_base),
            "gst_inr": float(gst), "total_fees_inr": float(total), "turnover_inr": float(turnover)}


def net_alpha_gate(expected_gross_alpha_inr: float, fees: Mapping[str, float]) -> dict[str, Any]:
    gross = _finite("expected_gross_alpha_inr", expected_gross_alpha_inr)
    total_fees = _nonnegative("total_fees_inr", fees["total_fees_inr"])
    net = gross - total_fees
    return {"gross_alpha_inr": gross, "total_fees_inr": total_fees, "net_alpha_inr": net,
            "pass": bool(net > 0.0)}


def beta_fractional_kelly(alpha_wins: float, beta_losses: float, win_loss_ratio: float,
        fractional_scale: float = 0.25, cap: float = MAX_KELLY_FRACTION) -> dict[str, float]:
    """Beta-posterior mean win probability + fractional Kelly, capped at 10% capital."""
    a, b = _finite("alpha_wins", alpha_wins), _finite("beta_losses", beta_losses)
    ratio = _nonnegative("win_loss_ratio", win_loss_ratio)
    scale = _nonnegative("fractional_scale", fractional_scale)
    cap = _finite("cap", cap)
    if a <= 0 or b <= 0:
        raise ValueError("Beta posterior parameters alpha_wins and beta_losses must be >0")
    if ratio <= 0 or not 0 <= scale <= 1 or not 0 <= cap <= MAX_KELLY_FRACTION:
        raise ValueError("ratio must be >0; fractional_scale in [0,1]; cap in [0,0.10]")
    p = a / (a + b)
    full_kelly = max(0.0, p - (1.0 - p) / ratio)
    fraction = min(cap, scale * full_kelly)
    return {"posterior_win_probability": float(p), "full_kelly_fraction": float(full_kelly),
            "fractional_kelly_fraction": float(fraction), "capital_fraction_cap": float(cap)}


@dataclass(frozen=True)
class AgentVote:
    agent: str
    approve: bool
    reason: str


def four_agent_consensus(*, operator_approved: bool, mlofi_score: float,
        macro_regime_approved: bool, volterra_fidelity_ok: bool,
        contagion_stable: bool, net_alpha_positive: bool,
        kelly_fraction: float, risk_checks_pass: bool) -> dict[str, Any]:
    """Four role-separated paper research votes; Manager Abhi has binding veto."""
    mlofi_score = _finite("mlofi_score", mlofi_score)
    kelly_fraction = _finite("kelly_fraction", kelly_fraction)
    alex_ok = abs(mlofi_score) > 0.0 and contagion_stable
    emily_ok = macro_regime_approved and volterra_fidelity_ok
    max_ok = net_alpha_positive and risk_checks_pass and 0.0 <= kelly_fraction <= MAX_KELLY_FRACTION
    votes = [AgentVote("Alex", alex_ok, "L3 MLOFI and cross-asset contagion checks"),
             AgentVote("Emily", emily_ok, "macro regime and Volterra TT fidelity checks"),
             AgentVote("Max", max_ok, "net-alpha, Indian friction and RMS checks"),
             AgentVote("Manager Abhi", bool(operator_approved), "sole operator intake, capital governance and binding veto")]
    approved = bool(operator_approved and all(v.approve for v in votes))
    return {"approved_for_paper_simulation": approved,
            "votes": [asdict(v) for v in votes], "live_dispatch_enabled": LIVE_ORDER_DISPATCH_ENABLED,
            "real_broker_fills_locked": REAL_BROKER_FILLS_LOCKED,
            "paper_ledger_epoch": PAPER_LEDGER_EPOCH, "initial_capital_inr": INITIAL_CAPITAL_INR}


def build_reference_report() -> dict[str, Any]:
    """Deterministic tiny report used by the included smoke example and regression test."""
    event_times = [0.0, 0.8, 1.2, 1.7]
    intensity = hawkes_intensity(2.0, event_times, 0.15, alpha=0.22, gamma=1.35, signed_ofi=0.4,
                                  ofi_sensitivity=0.08)
    hazard = adverse_jump_probability(intensity, 0.5)
    W = [[0.0, 0.08, 0.02, 0.01], [0.04, 0.0, 0.07, 0.02],
         [0.01, 0.05, 0.0, 0.03], [0.02, 0.02, 0.04, 0.0]]
    contagion = verify_contagion_matrix(W)
    drain = systemic_liquidity_drain_index(W, [1.0, 0.8, 0.7, 0.5])
    tensor = np.arange(1, 4 * 3 * 2 + 1, dtype=float).reshape(4, 3, 2) / 10.0
    tt = tt_svd(tensor, tolerance=1e-10)
    fees = calculate_indian_fees(buy_turnover=12500.0, sell_turnover=12500.0, executed_legs=4)
    alpha = net_alpha_gate(95.0, fees)
    kelly = beta_fractional_kelly(18.0, 12.0, 1.5, fractional_scale=0.25)
    schedule = optimal_liquidation_schedule(10.0, np.linspace(0, 1, 6), volatility=0.25,
            risk_aversion=0.1, impact_eta=0.02, intensities=[0.1, 0.2, 0.15, 0.18, 0.12], toxicity_penalty=0.1)
    votes = four_agent_consensus(operator_approved=True, mlofi_score=0.2, macro_regime_approved=True,
            volterra_fidelity_ok=tt["bound_met"], contagion_stable=contagion["stable"],
            net_alpha_positive=alpha["pass"], kelly_fraction=kelly["fractional_kelly_fraction"], risk_checks_pass=True)
    return {"cycle": 63, "engine": ENGINE_NAME, "paper_only": True,
            "hawkes_intensity": intensity, "adverse_jump_probability": hazard,
            "toxicity_action": toxicity_action(intensity, 0.5), "contagion": contagion, "sldi": drain,
            "tt": {k: v for k, v in tt.items() if k != "cores"}, "tt_ranks": [int(c.shape[2]) for c in tt["cores"]],
            "fees": fees, "alpha_gate": alpha, "kelly": kelly,
            "liquidation": {"trades": schedule["trades"], "inventory": schedule["inventory"],
                             "terminal_inventory": schedule["terminal_inventory"], "success": schedule["success"]},
            "consensus": votes}

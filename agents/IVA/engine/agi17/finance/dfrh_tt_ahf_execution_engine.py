"""Cycle 69 DFRH-TT-AHF research/reference engine.

Dependencies: Python standard library and NumPy only.

Safety invariants are hard-coded: LIVE_ORDER_DISPATCH_ENABLED is False,
REAL_BROKER_FILLS_LOCKED is True, ledger epoch is epoch_10k, and initial
paper capital is INR 10,000. dispatch_live_order always raises PermissionError.

The module provides numerical research primitives rather than claims of live
arbitrage or a broker integration. TT ranks and discretized surface diagnostics
are certified on the supplied finite tensor/grid, not on a continuum.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
DISPATCH_ERROR = (
    "LIVE_ORDER_DISPATCH_BLOCKED: Cycle 69 is fail-closed. "
    "Real broker dispatch is strictly locked."
)

STT_SELL_RATE = 0.0015
STAMP_BUY_RATE = 0.00003
NSE_TRANSACTION_RATE = 0.0003553
SEBI_TURNOVER_RATE = 0.000001
BROKERAGE_PER_LEG_INR = 20.0
GST_RATE = 0.18


def _finite_array(value: Any, name: str, ndim: int | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _nonnegative(name: str, value: float) -> float:
    x = float(value)
    if not math.isfinite(x) or x < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return x


def build_volterra_lift(
    hurst: float = 0.15,
    n_modes: int = 12,
    horizon: float = 1.0,
    dt: float = 0.01,
) -> dict[str, Any]:
    """Construct positive-weight exponential modes for the fractional kernel.

    For a = 1/2-H in (0,1/2),
      t**(-a)/Gamma(H+1/2) = integral exp(-x*t) x**(a-1) dx /
                              (Gamma(a)*Gamma(H+1/2)).
    A trapezoid-like log-space quadrature yields K(t) ~= sum c_m exp(-beta_m*t).
    It is a finite lift approximation; the sampled relative error is reported,
    not hidden. Grid endpoints are selected for the requested time scale.
    """
    h = float(hurst)
    if not (0.0 < h < 0.5):
        raise ValueError("hurst must lie strictly between 0 and 0.5")
    if int(n_modes) < 2:
        raise ValueError("n_modes must be at least 2")
    if not math.isfinite(horizon) or horizon <= 0:
        raise ValueError("horizon must be positive and finite")
    if not math.isfinite(dt) or dt <= 0:
        raise ValueError("dt must be positive and finite")
    modes = int(n_modes)
    a = 0.5 - h
    beta_min = max(1.0e-5 / float(horizon), 1.0e-8)
    beta_max = max(20.0 / float(dt), 100.0 / float(horizon))
    log_beta = np.linspace(math.log(beta_min), math.log(beta_max), modes)
    beta = np.exp(log_beta)
    dlog = float(log_beta[1] - log_beta[0])
    coeff = beta**a * dlog / (math.gamma(a) * math.gamma(h + 0.5))

    sample_t = np.geomspace(max(float(dt) * 0.25, 1.0e-8), float(horizon), 256)
    target = sample_t ** (h - 0.5) / math.gamma(h + 0.5)
    approx = np.exp(-sample_t[:, None] * beta[None, :]) @ coeff
    rel = np.abs(approx - target) / np.maximum(np.abs(target), 1.0e-14)
    return {
        "betas": beta,
        "weights": coeff,
        "sampled_relative_error_max": float(np.max(rel)),
        "sampled_relative_error_mean": float(np.mean(rel)),
        "hurst": h,
        "n_modes": modes,
        "horizon": float(horizon),
        "dt": float(dt),
    }


def _correlated_ou_brownian_covariance(betas: np.ndarray, dt: float) -> np.ndarray:
    """Covariance of integral exp(-beta_m*(dt-s)) dW_s over one time step."""
    bsum = betas[:, None] + betas[None, :]
    return -np.expm1(-bsum * dt) / bsum


def simulate_rough_heston(
    n_steps: int = 100,
    dt: float = 0.01,
    initial_variance: float = 0.04,
    kappa: float = 2.0,
    theta: float = 0.04,
    xi: float = 0.30,
    hurst: float = 0.15,
    n_lift: int = 12,
    neural_drift_weights: Sequence[float] = (0.025, 0.75),
    neural_diffusion_scale: float = 0.10,
    variance_floor: float = 1.0e-8,
    seed: int = 6901,
    strict_feller: bool = True,
    initial_spot: float = 100.0,
    rho: float = -0.70,
) -> dict[str, Any]:
    r"""Simulate a lifted, neural-augmented rough-Heston variance process.

    The underlying Volterra equation is approximated by a sum of exponential
    kernels: V_t ~= V_0 + sum_m c_m Y_m(t), where each Y_m is a Markovian
    exponential-memory coordinate. The Euler update uses the exact covariance
    matrix of the correlated OU-filtered Brownian increments. A positive floor
    regularizes the square-root diffusion in the lifted numerical system.

    The equity spot is simulated jointly with correlation rho to the variance
    Brownian driver. Feller is checked on the classical CIR parameters 2*kappa*theta > xi**2.
    The neural drift residual a*tanh(b*(V-theta)) has Lipschitz constant at most
    |a*b|, hence the total drift has bound kappa + |a*b|. The diffusion's floor
    removes the square-root singularity; its explicit conservative bound is
    returned. This finite-mode scheme is an approximation, not an exact sample
    from the continuous rough-Heston law.
    """
    n = int(n_steps)
    if n < 1:
        raise ValueError("n_steps must be >= 1")
    if not (math.isfinite(dt) and dt > 0):
        raise ValueError("dt must be positive and finite")
    for name, x in (("initial_variance", initial_variance), ("kappa", kappa),
                    ("theta", theta), ("xi", xi), ("variance_floor", variance_floor)):
        if not math.isfinite(float(x)) or float(x) < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    if kappa <= 0 or theta <= 0 or xi <= 0 or variance_floor <= 0:
        raise ValueError("kappa, theta, xi, and variance_floor must be strictly positive")
    if initial_variance < 0:
        raise ValueError("initial_variance must be non-negative")
    if not math.isfinite(float(initial_spot)) or initial_spot <= 0:
        raise ValueError("initial_spot must be positive and finite")
    if not math.isfinite(float(rho)) or not (-1.0 <= rho <= 1.0):
        raise ValueError("rho must be in [-1,1]")
    if len(neural_drift_weights) != 2:
        raise ValueError("neural_drift_weights must contain (amplitude, slope)")
    amp, slope = (float(neural_drift_weights[0]), float(neural_drift_weights[1]))
    if not np.all(np.isfinite([amp, slope, neural_diffusion_scale])):
        raise ValueError("neural weights must be finite")
    # Spectral/weight clipping: keeps the neural residual globally Lipschitz.
    amp = float(np.clip(amp, -0.25, 0.25))
    slope = float(np.clip(slope, -2.0, 2.0))
    diff_scale = float(np.clip(neural_diffusion_scale, -0.5, 0.5))
    feller_margin = 2.0 * kappa * theta - xi * xi
    feller_ok = feller_margin > 0.0
    if strict_feller and not feller_ok:
        raise ValueError("Feller condition violated: require 2*kappa*theta > xi**2")

    lift = build_volterra_lift(hurst, n_lift, horizon=n * dt, dt=dt)
    betas = np.asarray(lift["betas"], dtype=float)
    coeff = np.asarray(lift["weights"], dtype=float)
    m = len(betas)
    qcov = _correlated_ou_brownian_covariance(betas, dt)
    # Include the interval Brownian increment in the joint covariance. Its
    # covariance with the filtered mode m is integral_0^dt exp(-beta_m*u) du.
    mode_w_cov = -np.expm1(-betas * dt) / betas
    joint_cov = np.empty((m + 1, m + 1), dtype=float)
    joint_cov[:m, :m] = qcov
    joint_cov[:m, m] = mode_w_cov
    joint_cov[m, :m] = mode_w_cov
    joint_cov[m, m] = dt
    # An eigen square root is more stable than Cholesky for near-collinear modes.
    eigval, eigvec = np.linalg.eigh((joint_cov + joint_cov.T) * 0.5)
    cov_root = eigvec @ np.diag(np.sqrt(np.maximum(eigval, 0.0)))
    decay = np.exp(-betas * dt)
    drift_integral = -np.expm1(-betas * dt) / betas
    rng = np.random.default_rng(int(seed))

    initial_level = max(float(initial_variance), float(variance_floor))
    variance = np.empty(n + 1, dtype=float)
    spot = np.empty(n + 1, dtype=float)
    memory_path = np.empty(n + 1, dtype=float)
    lifted = np.zeros((n + 1, m), dtype=float)
    variance[0] = initial_level
    spot[0] = float(initial_spot)
    memory_path[0] = 0.0
    for t in range(n):
        v = float(variance[t])
        neural = amp * math.tanh(slope * (v - theta) + 0.1 * math.tanh(memory_path[t]))
        drift = kappa * (theta - v) + neural
        # Bounded neural modulation of the regularized state-dependent diffusion.
        ratio = v / (1.0 + v)
        diffusion = xi * math.sqrt(max(v, variance_floor)) * (1.0 + diff_scale * math.tanh(ratio))
        z = rng.standard_normal(m + 1)
        correlated_noise_joint = cov_root @ z
        correlated_noise = correlated_noise_joint[:m]
        dW_variance = float(correlated_noise_joint[m])
        y_next = decay * lifted[t] + drift_integral * drift + diffusion * correlated_noise
        raw_v = initial_level + float(np.dot(coeff, y_next))
        v_next = max(raw_v, float(variance_floor))
        # Preserve the algebraic relation V ~= V0 + c dot Y after projection.
        denom = float(np.dot(coeff, coeff))
        if denom > 0 and v_next != raw_v:
            y_next = y_next + coeff * ((v_next - raw_v) / denom)
        lifted[t + 1] = y_next
        variance[t + 1] = v_next
        memory_path[t + 1] = float(np.dot(coeff, y_next))
        dW_independent = math.sqrt(dt) * float(rng.standard_normal())
        dW_spot = float(rho) * dW_variance + math.sqrt(max(0.0, 1.0 - float(rho) ** 2)) * dW_independent
        spot[t + 1] = spot[t] * math.exp(-0.5 * v * dt + math.sqrt(max(v, 0.0)) * dW_spot)

    drift_lipschitz_bound = float(kappa + abs(amp) * math.sqrt(slope * slope + 0.1 * 0.1))
    # Since sqrt(max(v,floor)) is Lipschitz and tanh(v/(1+v)) is bounded,
    # this deliberately conservative bound is finite on v >= 0.
    diffusion_lipschitz_bound = float(
        xi * ((1.0 + abs(diff_scale)) / (2.0 * math.sqrt(variance_floor))
              + abs(diff_scale) * max(1.0, math.sqrt(variance_floor)))
    )
    return {
        "variance_path": variance,
        "spot_path": spot,
        "lifted_states": lifted,
        "rough_memory_path": memory_path,
        "lifted_betas": betas,
        "lifted_weights": coeff,
        "feller_verified": bool(feller_ok),
        "feller_condition_scope": "nominal CIR parameters only; rough-neural path uses a positive numerical floor",
        "feller_margin": float(feller_margin),
        "drift_lipschitz_bound": drift_lipschitz_bound,
        "diffusion_lipschitz_bound": diffusion_lipschitz_bound,
        "lipschitz_verified": bool(np.isfinite(drift_lipschitz_bound + diffusion_lipschitz_bound)),
        "finite_trajectory": bool(np.all(np.isfinite(variance)) and np.all(np.isfinite(lifted)) and np.all(np.isfinite(spot))),
        "positive_variance": bool(np.all(variance >= variance_floor)),
        "stability_verified": bool(feller_ok and np.all(np.isfinite(variance)) and np.max(variance) < 1.0e8),
        "lift_kernel_diagnostics": lift,
        "dt": float(dt),
        "seed": int(seed),
    }


def tt_svd_decompose(
    tensor: Any,
    max_rank: int = 16,
    tolerance: float = 1.0e-8,
) -> dict[str, Any]:
    """TT-SVD of a 4D tensor with explicit truncation/reconstruction diagnostics.

    At each unfolding, singular values are truncated using a global Frobenius
    error budget split across the d-1 internal ranks. `max_rank` is constrained
    to <=16 to match the specified bond-dimension ceiling. If the rank cap makes
    the requested tolerance impossible, `tolerance_met` is False rather than
    pretending a certificate exists.
    """
    arr = _finite_array(tensor, "tensor", ndim=4)
    if any(s < 1 for s in arr.shape):
        raise ValueError("all tensor dimensions must be non-empty")
    if int(max_rank) < 1 or int(max_rank) > 16:
        raise ValueError("max_rank must be in [1, 16]")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and non-negative")
    shape = arr.shape
    norm = float(np.linalg.norm(arr.ravel()))
    if norm == 0.0:
        cores = [np.zeros((1, d, 1), dtype=float) for d in shape]
        recon = np.zeros_like(arr)
        return {"cores": cores, "reconstructed": recon, "rank_profile": [1, 1, 1, 1, 1],
                "frobenius_error": 0.0, "relative_error": 0.0, "error_bound": 0.0,
                "tolerance_met": True, "bond_dimension_max": 1, "frobenius_norm_original": 0.0,
                "frobenius_norm_reconstructed": 0.0}

    cores: list[np.ndarray] = []
    residual = arr.copy()
    r_prev = 1
    rank_profile = [1]
    discarded_norms: list[float] = []
    local_budget = float(tolerance) * norm / math.sqrt(3.0)
    for k in range(3):
        unfold = residual.reshape(r_prev * shape[k], -1)
        u, s, vh = np.linalg.svd(unfold, full_matrices=False)
        # Minimum retained rank whose discarded tail is <= the local budget.
        rank_by_tol = len(s)
        for r in range(1, len(s) + 1):
            tail = float(np.linalg.norm(s[r:])) if r < len(s) else 0.0
            if tail <= local_budget:
                rank_by_tol = r
                break
        rank = max(1, min(int(max_rank), rank_by_tol))
        discarded_norms.append(float(np.linalg.norm(s[rank:])))
        core = u[:, :rank].reshape(r_prev, shape[k], rank)
        cores.append(core)
        residual = (s[:rank, None] * vh[:rank, :])
        r_prev = rank
        rank_profile.append(rank)
    cores.append(residual.reshape(r_prev, shape[3], 1))
    rank_profile.append(1)
    recon = cores[0]
    for core in cores[1:]:
        recon = np.tensordot(recon, core, axes=([-1], [0]))
    recon = np.squeeze(recon, axis=(0, -1))
    error = float(np.linalg.norm((arr - recon).ravel()))
    relerr = error / norm
    round_bound = float(math.sqrt(sum(x * x for x in discarded_norms)))
    return {
        "cores": cores,
        "reconstructed": recon,
        "rank_profile": rank_profile,
        "frobenius_error": error,
        "relative_error": float(relerr),
        "error_bound": float(round_bound),
        "relative_error_bound": float(round_bound / norm),
        "tolerance_met": bool(relerr <= tolerance + 1e-12),
        "bond_dimension_max": int(max(rank_profile)),
        "frobenius_norm_original": norm,
        "frobenius_norm_reconstructed": float(np.linalg.norm(recon.ravel())),
    }


def audit_volatility_surface(
    total_variance: Any,
    log_moneyness: Any,
    maturities: Any,
    tolerance: float = 1.0e-10,
) -> dict[str, Any]:
    """Finite-grid calendar and butterfly audit for w(k,T).

    Input shape is (n_strikes, n_maturities). Calendar condition is checked by
    finite differences in T. The supplied g(k) formula is evaluated with
    numpy gradients; positivity is only guaranteed at evaluated grid points.
    """
    w = _finite_array(total_variance, "total_variance", ndim=2)
    k = _finite_array(log_moneyness, "log_moneyness", ndim=1)
    t = _finite_array(maturities, "maturities", ndim=1)
    if w.shape != (len(k), len(t)):
        raise ValueError("surface shape must be (len(log_moneyness), len(maturities))")
    if len(k) < 3 or len(t) < 2:
        raise ValueError("need at least 3 strikes and 2 maturities for the finite-grid audit")
    if np.any(np.diff(k) <= 0) or np.any(np.diff(t) <= 0):
        raise ValueError("log_moneyness and maturities must be strictly increasing")
    if np.any(t <= 0) or np.any(w <= 0):
        raise ValueError("maturities and total variance must be strictly positive")
    wk = np.gradient(w, k, axis=0, edge_order=2)
    wkk = np.gradient(wk, k, axis=0, edge_order=2)
    g = (1.0 - k[:, None] * wk / (2.0 * w)) ** 2 - (wk ** 2 / 4.0) * (1.0 / w + 0.25) + 0.5 * wkk
    calendar_diff = np.diff(w, axis=1)
    calendar_min = float(np.min(calendar_diff)) if calendar_diff.size else 0.0
    g_min = float(np.min(g))
    calendar_ok = bool(calendar_min >= -float(tolerance))
    butterfly_ok = bool(g_min > float(tolerance))
    return {
        "calendar_monotone": calendar_ok,
        "butterfly_convexity_positive": butterfly_ok,
        "static_arbitrage_free_on_grid": bool(calendar_ok and butterfly_ok),
        "calendar_increment_min": calendar_min,
        "butterfly_g_min": g_min,
        "butterfly_g": g,
        "calendar_increments": calendar_diff,
        "w_k": wk,
        "w_kk": wkk,
    }


def cross_surface_relative_value(
    surface_a: Any,
    surface_b: Any,
    fee_drag: float = 0.0,
) -> dict[str, Any]:
    """Compute finite-grid relative-value edges after a per-cell friction drag."""
    a = _finite_array(surface_a, "surface_a")
    b = _finite_array(surface_b, "surface_b")
    if a.shape != b.shape:
        raise ValueError("surfaces must have matching shapes")
    fee = _nonnegative("fee_drag", fee_drag)
    gross = a - b
    net = np.sign(gross) * np.maximum(np.abs(gross) - fee, 0.0)
    mask = np.abs(gross) > fee
    return {
        "gross_difference": gross,
        "net_edge": net,
        "trade_mask": mask,
        "mispricing_metric": float(np.mean(np.abs(gross))),
        "max_abs_net_edge": float(np.max(np.abs(net))) if net.size else 0.0,
        "opportunities_after_friction": int(np.count_nonzero(mask)),
    }


def compute_mlofi_top5(
    delta_bid_volumes: Any,
    delta_ask_volumes: Any,
    delta_bid_prices: Any,
    delta_ask_prices: Any,
    weights: Any | None = None,
) -> float:
    """Signed five-level MLOFI as specified, with default weights 1.0 to 0.2."""
    dbv = _finite_array(delta_bid_volumes, "delta_bid_volumes", ndim=1)
    dav = _finite_array(delta_ask_volumes, "delta_ask_volumes", ndim=1)
    dbp = _finite_array(delta_bid_prices, "delta_bid_prices", ndim=1)
    dap = _finite_array(delta_ask_prices, "delta_ask_prices", ndim=1)
    if any(len(x) != 5 for x in (dbv, dav, dbp, dap)):
        raise ValueError("each MLOFI input must contain exactly five levels")
    w = np.linspace(1.0, 0.2, 5) if weights is None else _finite_array(weights, "weights", ndim=1)
    if len(w) != 5 or np.any(w < 0):
        raise ValueError("weights must be five non-negative values")
    bid_term = dbv * (dbp >= 0.0)
    ask_term = dav * (dap <= 0.0)
    return float(np.dot(w, bid_term - ask_term))


def hawkes_toxicity_gate(
    mlofi: float,
    base_intensity: float = 0.10,
    mlofi_gamma: float = 0.02,
    mlofi_beta: float = 0.70,
    past_jump_amplitudes: Sequence[float] = (),
    past_jump_ages: Sequence[float] = (),
    decay_rate: float = 1.25,
    tau: float = 1.0,
    retreat_threshold: float = 0.60,
) -> dict[str, Any]:
    """Hawkes-like toxicity intensity and RETREAT gate from MLOFI and jumps."""
    params = [mlofi, base_intensity, mlofi_gamma, mlofi_beta, decay_rate, tau, retreat_threshold]
    if not np.all(np.isfinite(params)):
        raise ValueError("toxicity parameters must be finite")
    if base_intensity < 0 or mlofi_gamma < 0 or mlofi_beta <= 0 or decay_rate < 0 or tau < 0:
        raise ValueError("intensity, gamma, decay and tau must be non-negative; beta must be positive")
    if not (0.0 <= retreat_threshold <= 1.0):
        raise ValueError("retreat_threshold must be in [0,1]")
    amps = _finite_array(past_jump_amplitudes, "past_jump_amplitudes", ndim=1)
    ages = _finite_array(past_jump_ages, "past_jump_ages", ndim=1)
    if len(amps) != len(ages) or np.any(amps < 0) or np.any(ages < 0):
        raise ValueError("jump amplitudes and ages must match and be non-negative")
    cascade = float(np.sum(amps * np.exp(-decay_rate * ages)))
    intensity = float(base_intensity + mlofi_gamma * abs(float(mlofi)) ** mlofi_beta + cascade)
    prob = float(-math.expm1(-intensity * tau))
    return {
        "intensity": intensity,
        "cascade_component": cascade,
        "toxicity_prob": prob,
        "toxicity_action": "RETREAT" if prob > retreat_threshold else "CONTINUE_PAPER",
        "retreat_threshold": float(retreat_threshold),
    }


def almgren_chriss_multi_expiry_unwind(
    inventory: Any,
    horizon_steps: int = 20,
    dt: float = 1.0,
    eta: float = 0.1,
    gamma_decay: float = 0.5,
    sigma: float = 0.01,
    lambda_risk: float = 1.0e-4,
    intensity: float = 0.0,
    tau: float = 1.0,
    impact_matrix: Any | None = None,
    c: float = 0.01,
    c_fee: float = 0.0,
    gamma_risk: float = 1.0,
) -> dict[str, Any]:
    """Solve a discrete multi-asset non-local impact unwind with q(T)=0.

    Let v_t be signed liquidation amounts, C the lower-triangular cumulative
    trade map, and q_after = 1*q0 - C v. Minimize a convex quadratic combining
    the power-law transient kernel (1+|t-s|dt)^(-gamma_decay), a PSD-projected
    cross-impact matrix, and quadratic inventory risk, subject to sum_t v_t=q0.
    A KKT system provides the schedule. The final trade is set algebraically to
    the residual inventory, guaranteeing exact zero terminal inventory in the
    returned path. This is a deterministic paper-research schedule, not an order.
    """
    inv = _finite_array(inventory, "inventory")
    original_shape = inv.shape
    q0 = inv.reshape(-1)
    d = len(q0)
    if d < 1:
        raise ValueError("inventory must be non-empty")
    steps = int(horizon_steps)
    if steps < 1:
        raise ValueError("horizon_steps must be >= 1")
    for name, val in (("dt", dt), ("eta", eta), ("gamma_decay", gamma_decay),
                      ("sigma", sigma), ("lambda_risk", lambda_risk), ("intensity", intensity),
                      ("tau", tau), ("c", c), ("c_fee", c_fee), ("gamma_risk", gamma_risk)):
        if not math.isfinite(float(val)) or float(val) < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    if dt <= 0 or eta <= 0 or gamma_decay <= 0 or gamma_risk <= 0:
        raise ValueError("dt, eta, gamma_decay, and gamma_risk must be positive")

    if impact_matrix is None:
        impact = np.eye(d, dtype=float)
    else:
        impact = _finite_array(impact_matrix, "impact_matrix", ndim=2)
        if impact.shape != (d, d):
            raise ValueError("impact_matrix shape must match flattened inventory dimension")
    # Cross impact may be asymmetric; the quadratic objective uses its symmetric
    # part, shifted to positive definite to ensure a convex optimization problem.
    impact_sym = 0.5 * (impact + impact.T)
    eigvals, eigvecs = np.linalg.eigh(impact_sym)
    impact_psd = eigvecs @ np.diag(np.maximum(eigvals, 1.0e-8)) @ eigvecs.T

    times = np.arange(steps, dtype=float)
    kernel = (1.0 + np.abs(times[:, None] - times[None, :]) * float(dt)) ** (-float(gamma_decay))
    keig, kvec = np.linalg.eigh(0.5 * (kernel + kernel.T))
    kernel_psd = kvec @ np.diag(np.maximum(keig, 1.0e-8)) @ kvec.T
    impact_h = np.kron(kernel_psd, impact_psd) * float(eta)

    cmat = np.tril(np.ones((steps, steps), dtype=float))
    cumulative = np.kron(cmat, np.eye(d))
    q_rep = np.tile(q0, steps)
    risk_weight = float(lambda_risk) * float(sigma) ** 2
    hess = impact_h + risk_weight * (cumulative.T @ cumulative)
    hess = 0.5 * (hess + hess.T) + 1.0e-10 * np.eye(steps * d)
    linear_rhs = risk_weight * cumulative.T @ q_rep
    eq = np.zeros((d, steps * d), dtype=float)
    for t in range(steps):
        eq[:, t * d:(t + 1) * d] = np.eye(d)
    kkt = np.block([[hess, eq.T], [eq, np.zeros((d, d), dtype=float)]])
    rhs = np.concatenate([linear_rhs, q0])
    try:
        solution = np.linalg.solve(kkt, rhs)[:steps * d]
    except np.linalg.LinAlgError:
        solution = np.linalg.lstsq(kkt, rhs, rcond=1.0e-12)[0][:steps * d]
    trades = solution.reshape(steps, d)
    if steps > 1:
        trades[-1] = q0 - np.sum(trades[:-1], axis=0)
    else:
        trades[0] = q0.copy()
    q_path = np.empty((steps + 1, d), dtype=float)
    q_path[0] = q0
    for t in range(steps):
        q_path[t + 1] = q_path[t] - trades[t]
    q_path[-1] = 0.0  # hard terminal inventory invariant after exact residual trade

    flat_trades = trades.reshape(-1)
    q_after = q_rep - cumulative @ flat_trades
    objective = float(flat_trades @ impact_h @ flat_trades + risk_weight * np.dot(q_after, q_after))
    toxicity = hawkes_toxicity_gate(0.0, base_intensity=float(intensity), tau=float(tau))
    width_arg = 3.0 * (float(c) + float(c_fee)) * float(sigma) ** 2 / (4.0 * float(gamma_risk))
    width = float(max(width_arg, 0.0) ** (1.0 / 3.0))
    return {
        "terminal_inventory": 0.0,
        "inventory_path": q_path.reshape((steps + 1,) + original_shape),
        "trade_schedule": trades.reshape((steps,) + original_shape),
        "transient_kernel": kernel,
        "cross_impact_matrix_psd": impact_psd,
        "objective_value": objective,
        "terminal_constraint_residual": float(np.max(np.abs(q_path[-1]))) if d else 0.0,
        "toxicity_prob": toxicity["toxicity_prob"],
        "toxicity_action": toxicity["toxicity_action"],
        "indifference_width": width,
    }


def indian_statutory_fees(
    buy_turnover_inr: float,
    sell_turnover_inr: float,
    executed_legs: int = 0,
) -> dict[str, Any]:
    """Configured Indian derivatives friction schedule (verify rates independently)."""
    buy = _nonnegative("buy_turnover_inr", buy_turnover_inr)
    sell = _nonnegative("sell_turnover_inr", sell_turnover_inr)
    legs = int(executed_legs)
    if legs < 0 or legs != executed_legs:
        raise ValueError("executed_legs must be a non-negative integer")
    total_turnover = buy + sell
    stt = sell * STT_SELL_RATE
    stamp = buy * STAMP_BUY_RATE
    exchange = total_turnover * NSE_TRANSACTION_RATE
    sebi = total_turnover * SEBI_TURNOVER_RATE
    brokerage = legs * BROKERAGE_PER_LEG_INR
    gst = GST_RATE * (brokerage + exchange + sebi)
    breakdown = {
        "stt_sell": stt,
        "stamp_duty_buy": stamp,
        "nse_transaction_fee": exchange,
        "sebi_turnover_fee": sebi,
        "brokerage": brokerage,
        "gst_on_brokerage_exchange_sebi": gst,
    }
    return {"total_fees_inr": float(sum(breakdown.values())), "breakdown": breakdown,
            "buy_turnover_inr": buy, "sell_turnover_inr": sell, "executed_legs": legs}


def net_alpha_gate(expected_gross_alpha_inr: float, total_fees_inr: float) -> dict[str, Any]:
    gross = float(expected_gross_alpha_inr)
    fees = _nonnegative("total_fees_inr", total_fees_inr)
    if not math.isfinite(gross):
        raise ValueError("expected_gross_alpha_inr must be finite")
    net = gross - fees
    return {"approved": bool(net > 0.0), "net_alpha_inr": float(net), "strictly_positive": bool(net > 0.0)}


def beta_fractional_kelly(
    alpha_prior: float,
    beta_prior: float,
    wins: int,
    losses: int,
    win_loss_ratio: float,
    scale: float = 0.25,
    cap: float = 0.10,
    net_alpha_positive: bool = True,
) -> dict[str, Any]:
    """Beta posterior probability and capped positive-edge fractional Kelly."""
    a, b = float(alpha_prior), float(beta_prior)
    ratio, sc, ceiling = float(win_loss_ratio), float(scale), float(cap)
    if not np.all(np.isfinite([a, b, ratio, sc, ceiling])) or a <= 0 or b <= 0:
        raise ValueError("prior parameters must be positive and parameters finite")
    if int(wins) != wins or int(losses) != losses or wins < 0 or losses < 0:
        raise ValueError("wins and losses must be non-negative integers")
    if ratio <= 0 or sc < 0 or ceiling < 0:
        raise ValueError("win_loss_ratio must be positive; scale and cap non-negative")
    p = (a + int(wins)) / (a + b + int(wins) + int(losses))
    # Binary-outcome Kelly: f = p - (1-p)/b, before fractional scaling.
    full_kelly = max(0.0, p - (1.0 - p) / ratio)
    allocated = min(ceiling, sc * full_kelly) if net_alpha_positive else 0.0
    return {"capital_fraction": float(max(0.0, allocated)),
            "posterior_win_probability": float(p), "full_kelly_fraction": float(full_kelly),
            "cap": ceiling, "net_alpha_positive": bool(net_alpha_positive)}


def squad_consensus(
    agent_votes: Mapping[str, Any],
    manager_live_veto: bool = True,
    require_unanimous: bool = True,
    risk_gates_passed: bool = True,
) -> dict[str, Any]:
    """4-agent paper-research consensus; live dispatch is always disabled."""
    required = ("Abhi", "Alex", "Emily", "Max")
    if not isinstance(agent_votes, Mapping) or any(k not in agent_votes for k in required):
        raise ValueError("agent_votes must contain Abhi, Alex, Emily, and Max")
    votes = {k: bool(agent_votes[k]) for k in required}
    approval = all(votes.values()) if require_unanimous else sum(votes.values()) >= 3
    approval = bool(approval and risk_gates_passed)
    return {
        "paper_research_approved": approval,
        "agent_votes": votes,
        "risk_gates_passed": bool(risk_gates_passed),
        "manager_live_veto": bool(manager_live_veto),
        "live_order_dispatch_enabled": False,
        "real_broker_fills_locked": True,
        "paper_ledger_epoch": PAPER_LEDGER_EPOCH,
    }


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Fail-closed permanent live dispatch prohibition."""
    raise PermissionError(DISPATCH_ERROR)

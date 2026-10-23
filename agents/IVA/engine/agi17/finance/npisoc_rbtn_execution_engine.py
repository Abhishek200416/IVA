"""Cycle 71 NPISOC-RBTN offline quantitative research engine.

Dependencies: Python standard library and NumPy only. No broker/API integration.

Mathematical conventions and guarantees
---------------------------------------
1) Neural path-integral control: for simulated nonnegative costs C_n, the
   implementation estimates V=-(1/lambda) log mean(exp(-lambda*C_n)). It
   subtracts min(C) before exponentiation, clips only below double-precision
   underflow relevance, and uses normalized weights. Its MLP layers are scaled
   so the product of spectral-norm bounds (with tanh hidden activations) is at
   most the requested Lipschitz limit. The forward/backward solver estimates
   the BSDE cost-to-go and a Brownian covariance proxy on a finite time grid.
   X_T=0 is a hard *discrete projection* on the final step, not a claim that an
   unconstrained diffusion reaches exactly zero with positive probability.
2) Rough-Bergomi: the singular Riemann-Liouville kernel is replaced by a finite
   log-quadrature sum of exponential modes. The simulated variance is positive
   by exponential construction; finite-factor/time-step output is approximate.
3) Tensor-train: sequential SVD truncation yields a discarded-singular-value
   Frobenius error bound and a separate actual reconstruction error. The cap
   chi<=16 is enforced; if it prevents tolerance, `tolerance_met` is false.
4) Static-arbitrage checks use finite differences on the provided grid. Passing
   them certifies only those sampled slices, not a continuous surface.
5) Unwind: a discrete convex quadratic program is solved for intermediate
   inventory states with q_0 specified and q_N constrained exactly to zero.
6) Fees are the rates explicitly specified for this research cycle; this is
   not current-law validation, tax advice, or evidence of positive expectancy.
7) All functions are offline references. `dispatch_live_order` always raises
   the specified PermissionError; no code path can enable broker dispatch.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np

CYCLE_ID = "NPISOC-RBTN"
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
AGENT_NAMES = ("Abhi", "Alex", "Emily", "Max")

# Rates are the rates specified for this research package; they are configurable
# assumptions and are not a legal/tax opinion or confirmation of current rates.
STT_SELL_RATE = 0.0015
STAMP_BUY_RATE = 0.00003
NSE_TRANSACTION_RATE = 0.0003553
SEBI_TURNOVER_RATE = 0.000001
BROKERAGE_PER_LEG_INR = 20.0
GST_RATE = 0.18


def _finite_array(value: Any, name: str, ndim: Optional[int] = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _positive_int(value: int, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or int(value) != value or int(value) < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _logmeanexp(log_values: np.ndarray) -> float:
    """Stable log(mean(exp(log_values))) using max subtraction."""
    a = _finite_array(log_values, "log_values").ravel()
    if a.size == 0:
        raise ValueError("log_values cannot be empty")
    m = float(np.max(a))
    return m + math.log(float(np.mean(np.exp(a - m))))


def _path_integral_value_and_weights(costs: Any, temperature: float) -> Tuple[float, np.ndarray]:
    """Stable log-partition value and normalized importance weights for C >= 0.

    Shifting by min(C) makes every exponential <= 1. Large products
    temperature*(C-min(C)) are clipped only below the exp underflow range; this
    avoids overflow/NaN while preserving double-precision partition accuracy.
    """
    c = _finite_array(costs, "costs").ravel()
    if c.size == 0 or np.any(c < 0) or not math.isfinite(float(temperature)) or temperature <= 0:
        raise ValueError("costs must be nonnegative and temperature positive")
    c_min = float(np.min(c))
    delta = c - c_min
    with np.errstate(over="ignore", invalid="raise"):
        scaled = np.asarray(temperature, dtype=float) * delta
    scaled = np.minimum(scaled, 745.0)
    log_relative_weights = -scaled
    log_partition_relative = _logmeanexp(log_relative_weights)
    value = c_min - log_partition_relative / float(temperature)
    weights = np.exp(log_relative_weights - float(np.max(log_relative_weights)))
    total = float(np.sum(weights))
    if not math.isfinite(value) or not math.isfinite(total) or total <= 0:
        raise FloatingPointError("path-integral partition normalization failed")
    return float(value), weights / total


def path_integral_stochastic_control(
    initial_state: float = 1.0,
    n_samples: int = 512,
    horizon_steps: int = 40,
    dt: float = 0.025,
    risk_temperature: float = 1.0,
    drift_rate: float = 0.2,
    diffusion: float = 0.25,
    control_penalty: float = 0.5,
    state_penalty: float = 0.1,
    terminal_penalty: float = 100.0,
    control_noise: float = 0.25,
    seed: int = 71,
) -> Dict[str, Any]:
    """Monte Carlo path-integral control for a scalar controlled diffusion.

    Uses stable log-mean-exp for V=-(1/lambda) log E[exp(-lambda C)].
    Candidate controls are Gaussian perturbations around a feedback baseline.
    The terminal boundary is imposed by an explicit constrained projection on
    the last step; this is a discrete hard constraint, not an unconstrained SDE
    path that magically hits zero with probability one.
    """
    n_samples = _positive_int(n_samples, "n_samples")
    horizon_steps = _positive_int(horizon_steps, "horizon_steps")
    vals = (initial_state, dt, risk_temperature, drift_rate, diffusion,
            control_penalty, state_penalty, terminal_penalty, control_noise)
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("control parameters must be finite")
    if dt <= 0 or risk_temperature <= 0 or diffusion < 0 or control_penalty <= 0:
        raise ValueError("dt/risk_temperature/control_penalty must be positive; diffusion nonnegative")
    if state_penalty < 0 or terminal_penalty < 0 or control_noise < 0:
        raise ValueError("cost weights and control_noise must be nonnegative")

    rng = np.random.default_rng(seed)
    dt_sqrt = math.sqrt(dt)
    time_grid = np.arange(horizon_steps + 1, dtype=float) * dt
    # Linear feedback baseline would mean-revert state before the terminal
    # projection. Perturbations create a path-integral search over controls.
    baseline = np.full(horizon_steps, -float(initial_state) / (horizon_steps * dt), dtype=float)
    perturb = rng.normal(0.0, control_noise, size=(n_samples, horizon_steps))
    controls = baseline[None, :] + perturb
    trajectories = np.zeros((n_samples, horizon_steps + 1), dtype=float)
    trajectories[:, 0] = float(initial_state)
    costs = np.zeros(n_samples, dtype=float)
    brownian = rng.normal(size=(n_samples, horizon_steps))
    for t in range(horizon_steps):
        x = trajectories[:, t]
        u = controls[:, t]
        drift = -float(drift_rate) * x
        # Avoid injective overflow from malformed user-supplied values: parameters
        # and state are finite checked, and this model is linear.
        x_next = x + (drift + u) * dt + float(diffusion) * dt_sqrt * brownian[:, t]
        running = (float(state_penalty) * x * x + float(control_penalty) * u * u) * dt
        costs += running
        if t == horizon_steps - 1:
            # Hard, deterministic terminal projection for the discrete problem.
            x_next = np.zeros_like(x_next)
            costs += float(terminal_penalty) * x_next * x_next
        trajectories[:, t + 1] = x_next
    if not np.all(np.isfinite(trajectories)) or not np.all(np.isfinite(costs)):
        raise FloatingPointError("non-finite path-integral rollout")
    value, weights = _path_integral_value_and_weights(costs, float(risk_temperature))
    weight_sum = float(weights.sum())
    if not math.isfinite(weight_sum) or weight_sum <= 0:
        raise FloatingPointError("path-integral weights underflowed to zero")
    # Weighted perturbation estimate is the sample-based control improvement.
    control_sequence = np.sum(weights[:, None] * controls, axis=0)
    ess = float(1.0 / np.sum(weights * weights))
    return {
        "value_estimate": float(value),
        "control_sequence": control_sequence,
        "trajectories": trajectories,
        "sample_costs": costs,
        "time_grid": time_grid,
        "effective_sample_size": ess,
        "terminal_inventory": 0.0,
        "terminal_residual": 0.0,
        "finite_verified": bool(np.all(np.isfinite(trajectories)) and np.all(np.isfinite(costs)) and math.isfinite(value)),
    }


def exponential_lift_kernel(
    times: Sequence[float], hurst: float = 0.12, n_factors: int = 12,
    beta_min: float = 0.02, beta_max: float = 250.0,
) -> Dict[str, np.ndarray]:
    """Log-quadrature approximation to K(t)=t^(H-1/2)/Gamma(H+1/2).

    Uses the Laplace identity t^-a = 1/Gamma(a) integral beta^(a-1)e^-beta*t d beta,
    with a=1/2-H and trapezoidal quadrature in log(beta). At t=0 the kernel is
    singular; callers should evaluate strictly positive lags.
    """
    t = _finite_array(times, "times").ravel()
    if not (0.0 < float(hurst) < 0.5):
        raise ValueError("hurst must lie in (0, 0.5)")
    n_factors = _positive_int(n_factors, "n_factors", 2)
    if np.any(t <= 0) or beta_min <= 0 or beta_max <= beta_min:
        raise ValueError("times and beta bounds must be positive; beta_max > beta_min")
    logs = np.linspace(math.log(beta_min), math.log(beta_max), n_factors)
    betas = np.exp(logs)
    dlog = float(logs[1] - logs[0])
    endpoint = np.ones(n_factors); endpoint[[0, -1]] = 0.5
    a = 0.5 - float(hurst)
    weights = endpoint * dlog * betas**a / (math.gamma(a) * math.gamma(1.0 - a))
    approx = np.exp(-np.outer(t, betas)) @ weights
    exact = t ** (float(hurst) - 0.5) / math.gamma(float(hurst) + 0.5)
    abs_error = np.abs(approx - exact)
    return {"betas": betas, "weights": weights, "approximation": approx,
            "exact": exact, "absolute_error": abs_error}


def simulate_rough_bergomi(
    n_steps: int = 48, n_paths: int = 128, dt: float = 1.0 / 252.0,
    hurst: float = 0.12, eta: float = 1.5, rho: float = -0.7,
    xi0: float = 0.04, n_factors: int = 12, seed: int = 71,
) -> Dict[str, Any]:
    """Simulate a discretized rough-Bergomi variance/spot proxy via exponential lift.

    The fractional Gaussian driver is approximated by a log-quadrature sum of
    Ornstein-Uhlenbeck factors. Variance is strictly positive by exponential
    construction. This is a finite-factor, finite-step research approximation.
    """
    n_steps = _positive_int(n_steps, "n_steps")
    n_paths = _positive_int(n_paths, "n_paths")
    n_factors = _positive_int(n_factors, "n_factors", 2)
    if not (0 < hurst < 0.5) or dt <= 0 or eta < 0 or xi0 <= 0 or not (-1 <= rho <= 1):
        raise ValueError("invalid rough-Bergomi parameters")
    rng = np.random.default_rng(seed)
    dW = math.sqrt(dt) * rng.normal(size=(n_paths, n_steps))
    dW_ind = math.sqrt(dt) * rng.normal(size=(n_paths, n_steps))
    logs = np.linspace(math.log(0.02), math.log(250.0), n_factors)
    betas = np.exp(logs)
    dlog = logs[1] - logs[0]
    endpoint = np.ones(n_factors); endpoint[[0, -1]] = 0.5
    a = 0.5 - hurst
    weights = endpoint * dlog * betas**a / (math.gamma(a) * math.gamma(1.0 - a))
    weights *= math.sqrt(2.0 * hurst)
    # Lift states: Y_m(t+dt)=e^-beta*dt Y_m(t)+dW_t. Their weighted sum is
    # a regularized convolution approximation to the Riemann-Liouville driver.
    lift = np.zeros((n_paths, n_steps + 1, n_factors), dtype=float)
    decay = np.exp(-betas * dt)
    for t in range(n_steps):
        lift[:, t + 1, :] = lift[:, t, :] * decay[None, :] + dW[:, t, None]
    fractional = np.einsum("ptm,m->pt", lift, weights)
    time = np.arange(n_steps + 1, dtype=float) * dt
    variance = float(xi0) * np.exp(float(eta) * fractional - 0.5 * float(eta) ** 2 * np.maximum(time, 0.0)[None, :] ** (2.0 * float(hurst)))
    corr_driver = float(rho) * dW + math.sqrt(max(0.0, 1.0 - float(rho) ** 2)) * dW_ind
    spot = np.ones((n_paths, n_steps + 1), dtype=float)
    for t in range(n_steps):
        vol = np.sqrt(np.maximum(variance[:, t], 1e-12))
        spot[:, t + 1] = spot[:, t] * np.exp(-0.5 * variance[:, t] * dt + vol * corr_driver[:, t])
    if not np.all(np.isfinite(variance)) or not np.all(np.isfinite(spot)):
        raise FloatingPointError("rough-Bergomi simulation produced non-finite values")
    return {"time": time, "variance_paths": variance, "spot_paths": spot,
            "lift_states": lift, "hurst": float(hurst), "factor_betas": betas,
            "factor_weights": weights, "positive_variance_verified": bool(np.all(variance > 0)),
            "finite_verified": True}


def tt_svd(tensor: Any, max_bond_dim: int = 16, tol: float = 1e-8) -> Dict[str, Any]:
    """Tensor-train SVD with actual discarded-tail error certificate.

    Sequential truncation tails are orthogonal in TT-SVD, so sqrt(sum tail^2)
    is a conservative/global Frobenius error certificate. If rank cap blocks tol,
    the result reports that fact instead of claiming tolerance was met.
    """
    arr = _finite_array(tensor, "tensor")
    if arr.ndim < 2 or any(d < 1 for d in arr.shape):
        raise ValueError("tensor must have at least 2 non-empty dimensions")
    max_bond_dim = _positive_int(max_bond_dim, "max_bond_dim")
    if max_bond_dim > 16:
        raise ValueError("max_bond_dim must be <= 16")
    if not (math.isfinite(tol) and tol >= 0):
        raise ValueError("tol must be finite and nonnegative")
    d = arr.ndim
    local_tol = float(tol) / math.sqrt(max(1, d - 1))
    cores = []
    tails = []
    ranks = [1]
    current = arr.copy()
    r_prev = 1
    for mode in range(d - 1):
        current = current.reshape(r_prev * arr.shape[mode], -1)
        u, s, vh = np.linalg.svd(current, full_matrices=False)
        # Find the smallest rank whose discarded spectral tail is within local
        # budget, then enforce the hard bond-dimension cap.
        rank_for_tol = len(s)
        for r in range(1, len(s) + 1):
            if float(np.linalg.norm(s[r:])) <= local_tol:
                rank_for_tol = r
                break
        rank = max(1, min(rank_for_tol, max_bond_dim, len(s)))
        tails.append(float(np.linalg.norm(s[rank:])))
        cores.append(u[:, :rank].reshape(r_prev, arr.shape[mode], rank))
        current = s[:rank, None] * vh[:rank, :]
        r_prev = rank
        ranks.append(rank)
    cores.append(current.reshape(r_prev, arr.shape[-1], 1))
    ranks.append(1)
    bound = float(math.sqrt(sum(v * v for v in tails)))
    reconstruction = reconstruct_tt(cores)
    actual = float(np.linalg.norm(arr - reconstruction))
    return {"cores": cores, "ranks": ranks, "bond_dimensions": ranks[1:-1],
            "max_bond_dimension": max(ranks[1:-1], default=1),
            "truncation_error_bound": bound, "reconstruction_error": actual,
            "tolerance_met": bool(bound <= float(tol) + 1e-12),
            "original_shape": tuple(arr.shape), "original_frobenius_norm": float(np.linalg.norm(arr)),
            "reconstructed_frobenius_norm": float(np.linalg.norm(reconstruction))}


def reconstruct_tt(cores: Sequence[np.ndarray]) -> np.ndarray:
    if not cores:
        raise ValueError("cores cannot be empty")
    result = _finite_array(cores[0], "core[0]", ndim=3)
    if result.shape[0] != 1:
        raise ValueError("first TT core left rank must be 1")
    for i, raw in enumerate(cores[1:], 1):
        core = _finite_array(raw, f"core[{i}]", ndim=3)
        if result.shape[-1] != core.shape[0]:
            raise ValueError("adjacent TT ranks do not match")
        result = np.tensordot(result, core, axes=([-1], [0]))
    if result.shape[-1] != 1:
        raise ValueError("last TT core right rank must be 1")
    return np.asarray(result[0, ..., 0], dtype=float)


def volatility_surface_audit(
    strikes: Sequence[float], maturities: Sequence[float], total_variance: Any,
    tol: float = 1e-10,
) -> Dict[str, Any]:
    """Finite-grid calendar monotonicity and Gatheral butterfly g(k) audit.

    total_variance has shape (n_maturities, n_strikes). Strict butterfly checks
    only use interior strike grid points where centered finite differences exist.
    """
    k = _finite_array(strikes, "strikes").ravel()
    t = _finite_array(maturities, "maturities").ravel()
    w = _finite_array(total_variance, "total_variance", ndim=2)
    if len(k) < 3 or len(t) < 2 or np.any(np.diff(k) <= 0) or np.any(np.diff(t) <= 0):
        raise ValueError("need >=3 increasing strikes and >=2 increasing maturities")
    if w.shape != (len(t), len(k)) or np.any(w <= 0):
        raise ValueError("total_variance shape mismatch or nonpositive values")
    calendar_diff = np.diff(w, axis=0) / np.diff(t)[:, None]
    calendar_ok = bool(np.all(calendar_diff >= -tol))
    g_all = []
    for row in w:
        dk = np.gradient(row, k, edge_order=2)
        d2k = np.gradient(dk, k, edge_order=2)
        wi = row[1:-1]
        ki = k[1:-1]
        dki = dk[1:-1]
        d2ki = d2k[1:-1]
        g = (1.0 - ki * dki / (2.0 * wi)) ** 2 - (dki ** 2 / 4.0) * (1.0 / wi + 0.25) + 0.5 * d2ki
        g_all.append(g)
    g_arr = np.asarray(g_all, dtype=float)
    butterfly_ok = bool(np.all(g_arr > tol))
    return {"calendar_ok": calendar_ok, "butterfly_ok": butterfly_ok,
            "static_arbitrage_free_on_grid": bool(calendar_ok and butterfly_ok),
            "minimum_calendar_slope": float(np.min(calendar_diff)),
            "minimum_butterfly_g": float(np.min(g_arr)),
            "calendar_slope_grid": calendar_diff, "butterfly_g_grid": g_arr}


def cross_surface_relative_value(surface_a: Any, surface_b: Any, fee_drag: float = 0.0) -> Dict[str, float | bool]:
    a = _finite_array(surface_a, "surface_a")
    b = _finite_array(surface_b, "surface_b")
    if a.shape != b.shape or a.size == 0 or fee_drag < 0 or not math.isfinite(fee_drag):
        raise ValueError("surfaces must share a non-empty shape and fee_drag be nonnegative")
    raw = float(np.mean(a - b))
    net = raw - float(fee_drag)
    return {"raw_relative_value": raw, "fee_drag": float(fee_drag), "net_relative_value": net,
            "net_alpha_positive": bool(net > 0.0)}


def compute_mlofi(
    bid_volume_changes: Any, ask_volume_changes: Any,
    bid_price_changes: Any, ask_price_changes: Any,
    weights: Optional[Sequence[float]] = None,
) -> np.ndarray | float:
    """Top-five signed depth-weighted MLOFI, accepts arrays ending in dimension 5."""
    bv = _finite_array(bid_volume_changes, "bid_volume_changes")
    av = _finite_array(ask_volume_changes, "ask_volume_changes")
    bp = _finite_array(bid_price_changes, "bid_price_changes")
    ap = _finite_array(ask_price_changes, "ask_price_changes")
    if not (bv.shape == av.shape == bp.shape == ap.shape) or bv.ndim < 1 or bv.shape[-1] != 5:
        raise ValueError("all MLOFI inputs must have matching shapes ending in 5")
    w = np.linspace(1.0, 0.2, 5) if weights is None else _finite_array(weights, "weights").ravel()
    if w.shape != (5,) or np.any(w < 0):
        raise ValueError("weights must be five nonnegative values")
    per_level = bv * (bp >= 0.0) - av * (ap <= 0.0)
    result = np.sum(per_level * w, axis=-1)
    return float(result) if np.ndim(result) == 0 else result


def hawkes_toxicity_gate(
    mlofi: float, event_ages: Optional[Sequence[float]] = None,
    jump_sizes: Optional[Sequence[float]] = None, mu0: float = 0.1,
    gamma_mlofi: float = 0.1, beta: float = 1.0, kappa: float = 1.0,
    tau: float = 1.0, probability_threshold: float = 0.60,
) -> Dict[str, float | str | bool]:
    vals = [mlofi, mu0, gamma_mlofi, beta, kappa, tau, probability_threshold]
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("Hawkes parameters must be finite")
    if mu0 < 0 or gamma_mlofi < 0 or beta <= 0 or kappa < 0 or tau < 0 or not (0 <= probability_threshold <= 1):
        raise ValueError("invalid Hawkes or gate parameter")
    ages = np.asarray([] if event_ages is None else event_ages, dtype=float).ravel()
    sizes = np.asarray([] if jump_sizes is None else jump_sizes, dtype=float).ravel()
    if ages.shape != sizes.shape or not np.all(np.isfinite(ages)) or not np.all(np.isfinite(sizes)):
        raise ValueError("event_ages and jump_sizes must be matching finite arrays")
    if np.any(ages < 0) or np.any(sizes < 0):
        raise ValueError("event ages and jump sizes must be nonnegative")
    intensity = float(mu0 + gamma_mlofi * abs(float(mlofi)) ** float(beta) + np.sum(sizes * np.exp(-float(kappa) * ages)))
    # expm1 preserves accuracy for small hazards.
    p_adv = float(-math.expm1(-intensity * float(tau)))
    action = "RETREAT" if p_adv > float(probability_threshold) else "CONTINUE_PAPER"
    return {"intensity": intensity, "toxicity_prob": p_adv, "toxicity_action": action,
            "retreat_triggered": bool(action == "RETREAT")}


def _psd_matrix(matrix: Any, dimension: int, name: str) -> np.ndarray:
    m = _finite_array(matrix, name, ndim=2)
    if m.shape != (dimension, dimension):
        raise ValueError(f"{name} must have shape ({dimension},{dimension})")
    m = 0.5 * (m + m.T)
    eig, vec = np.linalg.eigh(m)
    if np.min(eig) < -1e-9:
        raise ValueError(f"{name} must be positive semidefinite")
    eig = np.maximum(eig, 1e-8)
    return (vec * eig) @ vec.T


def almgren_chriss_multi_expiry_unwind(
    inventory: Sequence[float] | float, horizon_steps: int = 12,
    eta: float = 0.1, gamma_decay: float = 0.5, dt: float = 1.0,
    sigma: float = 0.01, lambda_risk: float = 1e-4,
    intensity: float = 0.0, tau: float = 1.0,
    impact_matrix: Optional[Any] = None, c: float = 0.01,
    c_fee: float = 0.0, gamma_risk: float = 1.0,
) -> Dict[str, Any]:
    """Quadratic non-local AC unwind solved as a discrete convex QP.

    The free variables are intermediate inventory states q_1..q_(N-1), while
    q_0 is given and q_N is constrained to zero. The objective includes a
    positive-definite quadratic trading term with a power-law temporal kernel,
    cross-asset impact matrix, and quadratic inventory risk.
    """
    q0 = _finite_array(inventory, "inventory").reshape(-1)
    if q0.size == 0:
        raise ValueError("inventory cannot be empty")
    n = _positive_int(horizon_steps, "horizon_steps", 2)
    params = (eta, gamma_decay, dt, sigma, lambda_risk, intensity, tau, c, c_fee, gamma_risk)
    if not all(math.isfinite(float(x)) for x in params):
        raise ValueError("unwind parameters must be finite")
    if eta <= 0 or gamma_decay <= 0 or dt <= 0 or sigma < 0 or lambda_risk < 0 or intensity < 0 or tau < 0 or c < 0 or c_fee < 0 or gamma_risk <= 0:
        raise ValueError("invalid unwind parameters")
    d = q0.size
    cm = np.eye(d) if impact_matrix is None else _psd_matrix(impact_matrix, d, "impact_matrix")
    # Non-local power-law temporal coupling. Add eta*I for strict convexity.
    time = np.arange(n, dtype=float) * dt
    kernel = (1.0 + np.abs(time[:, None] - time[None, :])) ** (-float(gamma_decay))
    qv = np.kron(kernel, cm) + float(eta) * np.eye(n * d)
    # Map intermediate q_1..q_(n-1) into trades v_t=q_t-q_(t+1).
    bt = np.zeros((n, n - 1), dtype=float)
    bt[0, 0] = -1.0
    for t in range(1, n - 1):
        bt[t, t - 1] = 1.0
        bt[t, t] = -1.0
    bt[n - 1, n - 2] = 1.0
    bmat = np.kron(bt, np.eye(d))
    fixed = np.zeros((n, d), dtype=float)
    fixed[0] = q0
    a = fixed.reshape(-1)
    risk_diag = float(lambda_risk) * float(sigma) ** 2 * float(dt) * np.eye((n - 1) * d)
    hessian = bmat.T @ qv @ bmat + risk_diag + 1e-10 * np.eye((n - 1) * d)
    rhs = -(bmat.T @ qv @ a)
    x = np.linalg.solve(hessian, rhs).reshape(n - 1, d)
    inventory_path = np.vstack([q0, x, np.zeros((1, d))])
    trades = inventory_path[:-1] - inventory_path[1:]
    impact_cost = float(trades.reshape(-1) @ qv @ trades.reshape(-1))
    risk_cost = float(lambda_risk * sigma**2 * dt * np.sum(inventory_path[1:-1] ** 2))
    p_adv = float(-math.expm1(-float(intensity) * float(tau)))
    delta = float((3.0 * (float(c) + float(c_fee)) * float(sigma) ** 2 / (4.0 * float(gamma_risk))) ** (1.0 / 3.0)) if (c + c_fee) > 0 and sigma > 0 else 0.0
    return {"terminal_inventory": np.zeros(d, dtype=float) if d > 1 else 0.0,
            "inventory_path": inventory_path[:, 0] if d == 1 else inventory_path,
            "trade_schedule": trades[:, 0] if d == 1 else trades,
            "toxicity_prob": p_adv, "toxicity_action": "RETREAT" if p_adv > 0.60 else "CONTINUE_PAPER",
            "indifference_width": delta, "objective_cost": impact_cost + risk_cost,
            "impact_cost": impact_cost, "risk_cost": risk_cost,
            "terminal_residual": float(np.max(np.abs(inventory_path[-1]))),
            "kernel": kernel, "impact_matrix": cm, "convexity_regularization": 1e-10}


def indian_statutory_fees(buy_turnover_inr: float, sell_turnover_inr: float, executed_legs: int = 0) -> Dict[str, Any]:
    vals = (buy_turnover_inr, sell_turnover_inr)
    if not all(math.isfinite(float(v)) and float(v) >= 0 for v in vals):
        raise ValueError("turnover must be finite and nonnegative")
    legs = _positive_int(executed_legs, "executed_legs", 0)
    buy = float(buy_turnover_inr); sell = float(sell_turnover_inr); turnover = buy + sell
    stt = sell * STT_SELL_RATE
    stamp = buy * STAMP_BUY_RATE
    exchange = turnover * NSE_TRANSACTION_RATE
    sebi = turnover * SEBI_TURNOVER_RATE
    brokerage = legs * BROKERAGE_PER_LEG_INR
    gst = GST_RATE * (brokerage + exchange + sebi)
    breakdown = {"stt_sell": stt, "stamp_duty_buy": stamp, "nse_transaction_fee": exchange,
                 "sebi_turnover_fee": sebi, "brokerage": brokerage, "gst": gst}
    return {"total_fees_inr": float(sum(breakdown.values())), "breakdown": breakdown,
            "buy_turnover_inr": buy, "sell_turnover_inr": sell, "executed_legs": legs}


def net_alpha_gate(expected_gross_alpha_inr: float, total_fees_inr: float) -> Dict[str, float | bool]:
    if not all(math.isfinite(float(x)) for x in (expected_gross_alpha_inr, total_fees_inr)) or total_fees_inr < 0:
        raise ValueError("alpha and nonnegative fees must be finite")
    net = float(expected_gross_alpha_inr) - float(total_fees_inr)
    return {"approved": bool(net > 0.0), "net_alpha_inr": net}


def beta_fractional_kelly(
    alpha_prior: float, beta_prior: float, wins: int, losses: int,
    win_loss_ratio: float, scale: float = 0.25, cap: float = 0.10,
    net_alpha_positive: bool = True,
) -> Dict[str, float | bool]:
    vals = (alpha_prior, beta_prior, win_loss_ratio, scale, cap)
    if not all(math.isfinite(float(x)) for x in vals) or alpha_prior <= 0 or beta_prior <= 0 or win_loss_ratio <= 0 or scale < 0 or cap < 0:
        raise ValueError("invalid Beta/Kelly parameters")
    wins = _positive_int(wins, "wins", 0); losses = _positive_int(losses, "losses", 0)
    p = (float(alpha_prior) + wins) / (float(alpha_prior) + float(beta_prior) + wins + losses)
    raw = p - (1.0 - p) / float(win_loss_ratio)
    fraction = min(float(cap), max(0.0, float(scale) * raw)) if net_alpha_positive else 0.0
    return {"capital_fraction": fraction, "posterior_win_probability": p,
            "raw_kelly_fraction": raw, "net_alpha_positive": bool(net_alpha_positive),
            "cap": float(cap)}


def squad_consensus(
    agent_votes: Mapping[str, bool], manager_live_veto: bool = True,
    require_unanimous: bool = True, risk_gates_passed: bool = True,
) -> Dict[str, Any]:
    if not isinstance(agent_votes, Mapping) or any(k not in agent_votes for k in AGENT_NAMES):
        raise ValueError("agent_votes must contain Abhi, Alex, Emily, Max")
    if any(not isinstance(agent_votes[k], (bool, np.bool_)) for k in AGENT_NAMES):
        raise ValueError("all agent votes must be booleans")
    yes_count = sum(bool(agent_votes[k]) for k in AGENT_NAMES)
    research_ok = bool((yes_count == len(AGENT_NAMES) if require_unanimous else yes_count >= 3)
                       and risk_gates_passed)
    # Manager veto concerns live activity only; this cycle never enables live dispatch.
    return {"paper_research_approved": research_ok,
            "live_order_dispatch_enabled": False,
            "manager_live_veto": bool(manager_live_veto),
            "votes_for": int(yes_count), "votes_required": 4 if require_unanimous else 3,
            "risk_gates_passed": bool(risk_gates_passed)}


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Permanently disabled broker dispatch; always fails closed."""
    raise PermissionError(
        "LIVE_ORDER_DISPATCH_BLOCKED: Cycle 71 is fail-closed. Real broker dispatch is strictly locked."
    )


def _mlp_eval(
    inputs: Any, weights: Sequence[Any], biases: Sequence[Any],
    lipschitz_limit: float = 1.5,
) -> Tuple[np.ndarray, float, list[np.ndarray]]:
    """Evaluate a tanh MLP after layer scaling so product spectral bound <= L."""
    x = _finite_array(inputs, "inputs")
    if x.ndim == 1:
        x = x[None, :]
    if x.ndim != 2 or not weights or len(weights) != len(biases):
        raise ValueError("MLP needs 2D inputs and equal non-empty weights/biases lists")
    if not (math.isfinite(float(lipschitz_limit)) and lipschitz_limit > 0):
        raise ValueError("lipschitz_limit must be finite and positive")
    mats = [_finite_array(w, f"weights[{i}]", ndim=2).copy() for i, w in enumerate(weights)]
    vecs = [_finite_array(b, f"biases[{i}]").reshape(-1) for i, b in enumerate(biases)]
    if mats[0].shape[1] != x.shape[1] or any(mats[i].shape[0] != vecs[i].size for i in range(len(mats))):
        raise ValueError("MLP layer dimensions do not match")
    if any(mats[i + 1].shape[1] != mats[i].shape[0] for i in range(len(mats) - 1)):
        raise ValueError("adjacent MLP layer dimensions do not match")
    per_layer = float(lipschitz_limit) ** (1.0 / len(mats))
    norms = []
    for i, mat in enumerate(mats):
        norm = float(np.linalg.norm(mat, ord=2))
        if norm > per_layer and norm > 0:
            mat *= per_layer / norm
            norm = per_layer
        norms.append(norm)
    upper = float(np.prod(norms))
    y = x
    for i, (mat, bias) in enumerate(zip(mats, vecs)):
        y = y @ mat.T + bias[None, :]
        if i < len(mats) - 1:
            y = np.tanh(y)
    if not np.all(np.isfinite(y)):
        raise FloatingPointError("MLP forward pass produced non-finite values")
    return y, upper, mats


def mlp_forward(
    inputs: Any, weights: Sequence[Any], biases: Sequence[Any],
    lipschitz_limit: float = 1.5,
) -> Dict[str, Any]:
    """Public spectral-normalized MLP inference helper for neural SDE fields."""
    output, bound, normalized_weights = _mlp_eval(inputs, weights, biases, lipschitz_limit)
    return {"output": output, "lipschitz_upper_bound": bound,
            "lipschitz_verified": bool(bound <= float(lipschitz_limit) + 1e-12),
            "normalized_weights": normalized_weights}


def solve_neural_fbsde(
    initial_state: float = 1.0,
    drift_weights: Optional[Sequence[Any]] = None,
    drift_biases: Optional[Sequence[Any]] = None,
    control_weights: Optional[Sequence[Any]] = None,
    control_biases: Optional[Sequence[Any]] = None,
    diffusion_weights: Optional[Sequence[Any]] = None,
    diffusion_biases: Optional[Sequence[Any]] = None,
    n_paths: int = 128,
    n_steps: int = 32,
    dt: float = 0.025,
    diffusion: float = 0.2,
    risk_temperature: float = 1.0,
    lipschitz_limit: float = 1.5,
    seed: int = 71,
) -> Dict[str, Any]:
    """Forward-backward neural SDE solver with hard discrete terminal boundary.

    Networks take [state, normalized_time] and output scalar drift/control or
    a scalar diffusion logit. Defaults are small deterministic tanh networks.
    The backward component is a Monte Carlo pathwise cost-to-go plus a
    regression-style Brownian covariance estimate for the BSDE martingale term.
    It is a transparent numerical solver, not a trained neural network optimizer.
    """
    n_paths = _positive_int(n_paths, "n_paths")
    n_steps = _positive_int(n_steps, "n_steps")
    if dt <= 0 or risk_temperature <= 0 or diffusion < 0 or not all(math.isfinite(float(v)) for v in (initial_state, dt, risk_temperature, diffusion)):
        raise ValueError("invalid FBSDE simulation parameters")
    default_drift = [np.array([[0.0, -0.2]])]
    default_drift_b = [np.array([0.0])]
    default_control = [np.array([[-1.0, 0.0]])]
    default_control_b = [np.array([0.0])]
    dw = default_drift if drift_weights is None else drift_weights
    db = default_drift_b if drift_biases is None else drift_biases
    cw = default_control if control_weights is None else control_weights
    cb = default_control_b if control_biases is None else control_biases
    if len(dw) != len(db) or len(cw) != len(cb):
        raise ValueError("drift/control network weights and biases lengths must match")
    rng = np.random.default_rng(seed)
    x_path = np.zeros((n_paths, n_steps + 1), dtype=float)
    x_path[:, 0] = float(initial_state)
    dW = math.sqrt(dt) * rng.normal(size=(n_paths, n_steps))
    drift_path = np.zeros((n_paths, n_steps), dtype=float)
    control_path = np.zeros_like(drift_path)
    diffusion_path = np.zeros_like(drift_path)
    running = np.zeros_like(drift_path)
    lipschitz_values = []
    for t in range(n_steps):
        tn = float(t) / max(1, n_steps - 1)
        features = np.column_stack([x_path[:, t], np.full(n_paths, tn)])
        bval, bbound, _ = _mlp_eval(features, dw, db, lipschitz_limit)
        uval, ubound, _ = _mlp_eval(features, cw, cb, lipschitz_limit)
        b = bval[:, 0]; u = uval[:, 0]
        if diffusion_weights is None:
            sig = np.full(n_paths, float(diffusion))
        else:
            if diffusion_biases is None:
                raise ValueError("diffusion_biases required with diffusion_weights")
            dval, dbound, _ = _mlp_eval(features, diffusion_weights, diffusion_biases, lipschitz_limit)
            # Softplus is stable and ensures state-dependent strictly positive sigma.
            raw = dval[:, 0]
            sig = np.maximum(np.log1p(np.exp(-np.abs(raw))) + np.maximum(raw, 0.0), 1e-6)
            lipschitz_values.append(dbound)
        drift_path[:, t] = b; control_path[:, t] = u; diffusion_path[:, t] = sig
        candidate = x_path[:, t] + (b + u) * dt + sig * dW[:, t]
        running[:, t] = (x_path[:, t] ** 2 + 0.25 * u ** 2) * dt
        if t == n_steps - 1:
            candidate = np.zeros_like(candidate)  # enforce X_T=0 exactly
        x_path[:, t + 1] = candidate
        lipschitz_values.extend([bbound, ubound])
    y_paths = np.zeros((n_paths, n_steps + 1), dtype=float)
    for t in range(n_steps - 1, -1, -1):
        y_paths[:, t] = running[:, t] + y_paths[:, t + 1]
    z_path = np.zeros(n_steps, dtype=float)
    for t in range(n_steps):
        z_path[t] = float(np.mean(y_paths[:, t + 1] * dW[:, t]) / dt)
    costs = y_paths[:, 0]
    value, _ = _path_integral_value_and_weights(costs, float(risk_temperature))
    if not all(np.all(np.isfinite(a)) for a in (x_path, drift_path, control_path, diffusion_path, y_paths, z_path)) or not math.isfinite(value):
        raise FloatingPointError("non-finite forward-backward neural SDE output")
    max_bound = max(lipschitz_values, default=0.0)
    return {"trajectory": x_path, "drift_path": drift_path, "control_path": control_path,
            "diffusion_path": diffusion_path, "backward_value_paths": y_paths,
            "backward_value_mean": np.mean(y_paths, axis=0), "bsde_z_estimate": z_path,
            "path_integral_value": value, "sample_costs": costs,
            "terminal_inventory": 0.0, "terminal_residual": float(np.max(np.abs(x_path[:, -1]))),
            "lipschitz_upper_bound_max": max_bound,
            "lipschitz_verified": bool(max_bound <= float(lipschitz_limit) + 1e-12),
            "finite_verified": True, "seed": int(seed)}

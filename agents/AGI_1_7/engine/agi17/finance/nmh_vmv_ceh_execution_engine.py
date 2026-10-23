"""Cycle 68 NMH-VMV-CEH: offline quantitative research/reference engine.

Uses Python's standard library and NumPy only. This module never sends broker orders.
The stochastic outputs are model simulations, not forecasts or profitability guarantees.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence
import numpy as np

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
AGENT_NAMES = ("Abhi", "Alex", "Emily", "Max")


def _finite_array(value: Any, name: str, ndim: int | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _positive(value: float, name: str, allow_zero: bool = False) -> float:
    value = float(value)
    if not math.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        op = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {op}")
    return value


def volterra_memory_kernel(t: float, s: float, hurst: float = 0.15) -> float:
    """K(t,s)=(t-s)^(H-1/2)/Gamma(H+1/2), defined for t>s."""
    if not (0.0 < float(hurst) < 0.5):
        raise ValueError("hurst must lie strictly inside (0, 0.5)")
    if not (math.isfinite(t) and math.isfinite(s) and t > s):
        raise ValueError("kernel requires finite t > s")
    return (t - s) ** (hurst - 0.5) / math.gamma(hurst + 0.5)


def volterra_increment_weights(n_steps: int, dt: float, hurst: float = 0.15) -> np.ndarray:
    """Exact interval integrals of the weakly singular Volterra kernel.

    Weight[k] integrates K(u,0) over [k*dt,(k+1)*dt] after reversing lag.
    The integrated weights are finite even though K(t,t) is singular.
    """
    if int(n_steps) < 1:
        raise ValueError("n_steps must be >= 1")
    _positive(dt, "dt")
    if not (0.0 < float(hurst) < 0.5):
        raise ValueError("hurst must lie strictly inside (0, 0.5)")
    p = float(hurst) + 0.5
    return np.asarray([(((k + 1) * dt) ** p - (k * dt) ** p) / math.gamma(p + 1.0)
                       for k in range(int(n_steps))], dtype=float)


def _signals_for_particles(signals: Any, n_steps: int, n_particles: int) -> np.ndarray:
    if signals is None:
        return np.zeros((n_steps, n_particles), dtype=float)
    arr = _finite_array(signals, "mlofi_signals")
    if arr.ndim == 0:
        return np.full((n_steps, n_particles), float(arr))
    if arr.ndim == 1:
        if arr.shape[0] == n_steps:
            return np.repeat(arr[:, None], n_particles, axis=1)
        if arr.shape[0] == n_particles:
            return np.repeat(arr[None, :], n_steps, axis=0)
    if arr.shape == (n_steps, n_particles):
        return arr.copy()
    raise ValueError("mlofi_signals must be scalar, (n_steps,), (n_particles,), or (n_steps,n_particles)")


def simulate_nmh_vmv_system(
    n_particles: int = 100,
    n_steps: int = 50,
    dt: float = 0.01,
    kappa: float = 1.5,
    gamma: float = 0.8,
    x_bar: float = 0.0,
    beta: float = 0.2,
    mlofi_signals: Any = None,
    sigma_base: float = 0.15,
    hurst: float = 0.15,
    lambda_0: float = 0.1,
    gamma_mlofi: float = 0.05,
    branching_matrix: Any = None,
    hawkes_decay: float = 1.2,
    jump_scale: float = 0.02,
    seed: int = 6801,
) -> dict[str, Any]:
    """Euler simulation of a finite-particle McKean-Vlasov/Hawkes-Volterra model.

    The input Gamma is the integrated Hawkes offspring matrix; its spectral radius
    must be < .88. Diffusion variance is bounded below by 1e-6. Hawkes excitation
    uses beta_H * Gamma * event_count with exponential decay so the kernel integral
    of each entry equals Gamma_ij.
    """
    n_particles, n_steps = int(n_particles), int(n_steps)
    if n_particles < 2 or n_steps < 1:
        raise ValueError("n_particles must be >= 2 and n_steps >= 1")
    _positive(dt, "dt"); _positive(kappa, "kappa", allow_zero=True)
    _positive(gamma, "gamma", allow_zero=True); _positive(sigma_base, "sigma_base")
    _positive(lambda_0, "lambda_0", allow_zero=True); _positive(gamma_mlofi, "gamma_mlofi", allow_zero=True)
    _positive(hawkes_decay, "hawkes_decay"); _positive(jump_scale, "jump_scale", allow_zero=True)
    if not (0 < float(hurst) < 0.5):
        raise ValueError("hurst must lie strictly inside (0, 0.5)")
    if branching_matrix is None:
        # Nonnegative dense weak cross-excitation with an analytically subcritical row sum.
        branching = np.full((n_particles, n_particles), 0.10 / n_particles)
        branching[np.diag_indices(n_particles)] += 0.10
    else:
        branching = _finite_array(branching_matrix, "branching_matrix", ndim=2)
    if branching.shape != (n_particles, n_particles) or np.any(branching < 0):
        raise ValueError("branching_matrix must be nonnegative with shape (n_particles,n_particles)")
    rho = float(np.max(np.abs(np.linalg.eigvals(branching))))
    if not rho < 0.88:
        raise ValueError(f"branching matrix is not certified subcritical: spectral radius {rho:.8g} >= 0.88")
    ofi = _signals_for_particles(mlofi_signals, n_steps, n_particles)
    rng = np.random.default_rng(seed)
    path = np.zeros((n_steps + 1, n_particles), dtype=float)
    mean_path = np.zeros(n_steps + 1, dtype=float)
    var_path = np.zeros(n_steps + 1, dtype=float)
    jumps_total = 0
    hawkes_state = np.zeros(n_particles, dtype=float)
    memory_weights = volterra_increment_weights(n_steps, dt, hurst)
    min_diffusion_eigenvalue = float("inf")
    exp_decay = math.exp(-hawkes_decay * dt)
    for step in range(n_steps):
        x = path[step]
        empirical_mean = float(np.mean(x))
        drift = (-kappa * (x - float(x_bar)) + gamma * (empirical_mean - x)
                 + beta * ofi[step])
        if step:
            increments = np.diff(path[:step + 1], axis=0)[::-1]
            weights = memory_weights[:step]
            memory = np.sum((weights[:, None] * (increments ** 2)), axis=0)
        else:
            memory = np.zeros(n_particles, dtype=float)
        # State-dependent scalar Cholesky factor; Sigma=L L^T >= 1e-6.
        diffusion_diag = np.maximum(float(sigma_base) * (1.0 + 0.25 * np.tanh(np.abs(x) + memory)), 1e-3)
        min_diffusion_eigenvalue = min(min_diffusion_eigenvalue, float(np.min(diffusion_diag ** 2)))
        intensity = np.maximum(0.0, float(lambda_0) + float(gamma_mlofi) * np.abs(ofi[step]) + hawkes_state)
        events = rng.poisson(intensity * dt).astype(int)
        jumps_total += int(np.sum(events))
        jump_term = rng.normal(0.0, float(jump_scale), size=n_particles) * events
        path[step + 1] = x + drift * dt + diffusion_diag * math.sqrt(dt) * rng.standard_normal(n_particles) + jump_term
        hawkes_state = exp_decay * hawkes_state + hawkes_decay * (branching @ events.astype(float))
        mean_path[step + 1] = np.mean(path[step + 1])
        var_path[step + 1] = np.var(path[step + 1])
    finite = bool(np.all(np.isfinite(path)) and np.all(np.isfinite(mean_path)) and np.all(np.isfinite(var_path)))
    stable = bool(rho < 0.88 and finite and min_diffusion_eigenvalue >= 1e-6 - 1e-12)
    return {
        "particle_trajectories": path,
        "mean_field_path": mean_path,
        "variance_field_path": var_path,
        "jumps_total": int(jumps_total),
        "stability_verified": stable,
        "branching_spectral_radius": rho,
        "min_diffusion_eigenvalue": min_diffusion_eigenvalue,
        "volterra_weights": memory_weights,
        "seed": int(seed),
    }


# Alias with a shorter discoverable name.
simulate_nmh_vmv = simulate_nmh_vmv_system


def dynamic_cross_hedge_beta(returns: Any, decay: float = 0.97, variance_floor: float = 1e-10) -> dict[str, Any]:
    """Exponentially weighted beta B_ij=Cov(S_i,S_j)/Var(S_j), rows are hedged assets."""
    r = _finite_array(returns, "returns", ndim=2)
    if r.shape[0] < 2 or r.shape[1] < 1:
        raise ValueError("returns must have at least two time samples")
    if not (0.0 < float(decay) <= 1.0):
        raise ValueError("decay must lie in (0,1]")
    _positive(variance_floor, "variance_floor")
    weights = float(decay) ** np.arange(r.shape[0] - 1, -1, -1, dtype=float)
    weights /= np.sum(weights)
    mean = np.sum(weights[:, None] * r, axis=0)
    centered = r - mean
    cov = (centered * weights[:, None]).T @ centered
    cov = 0.5 * (cov + cov.T)
    variance = np.maximum(np.diag(cov), float(variance_floor))
    beta_matrix = cov / variance[None, :]
    return {"beta_matrix": beta_matrix, "weighted_covariance": cov, "weighted_variance": variance,
            "decay": float(decay)}


def _surface_inputs(log_moneyness: Any, maturities: Any, total_variance: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    k = _finite_array(log_moneyness, "log_moneyness", ndim=1)
    t = _finite_array(maturities, "maturities", ndim=1)
    w = _finite_array(total_variance, "total_variance", ndim=2)
    if len(k) < 3 or len(t) < 2 or w.shape != (len(t), len(k)):
        raise ValueError("surface shape must be (len(maturities),len(log_moneyness)); >=3 strikes and >=2 maturities")
    if np.any(np.diff(k) <= 0) or np.any(np.diff(t) <= 0) or np.any(t <= 0) or np.any(w <= 0):
        raise ValueError("strikes/maturities must be strictly increasing, maturities and total variance positive")
    return k, t, w


def audit_cross_expiry_surface(log_moneyness: Any, maturities: Any, total_variance: Any, tolerance: float = 1e-10) -> dict[str, Any]:
    """Audit calendar monotonicity and the supplied SVI-style butterfly g(k)>0.

    This function certifies or flags the input; it does not silently repair a surface.
    Strict convexity must be demonstrated numerically on the supplied grid.
    """
    k, t, w = _surface_inputs(log_moneyness, maturities, total_variance)
    tol = _positive(tolerance, "tolerance", allow_zero=True)
    calendar_diffs = np.diff(w, axis=0) / np.diff(t)[:, None]
    wk = np.gradient(w, k, axis=1, edge_order=2)
    wkk = np.gradient(wk, k, axis=1, edge_order=2)
    g = (1.0 - k[None, :] * wk / (2.0 * w)) ** 2 - (wk ** 2 / 4.0) * (1.0 / w + 0.25) + 0.5 * wkk
    min_calendar = float(np.min(calendar_diffs))
    min_butterfly = float(np.min(g))
    calendar_ok = bool(min_calendar >= -tol)
    butterfly_ok = bool(min_butterfly > tol)
    curvature = np.diff(w, n=2, axis=0) if len(t) >= 3 else np.zeros((0, len(k)))
    dislocation = float(np.max(np.abs(curvature))) if curvature.size else 0.0
    return {"calendar_monotone": calendar_ok, "butterfly_convex": butterfly_ok,
            "static_arbitrage_free_grid": bool(calendar_ok and butterfly_ok),
            "minimum_calendar_slope": min_calendar, "minimum_butterfly_g": min_butterfly,
            "butterfly_g": g, "calendar_slopes": calendar_diffs,
            "curvature_dislocation_metric": dislocation}


def require_static_arbitrage_free_surface(log_moneyness: Any, maturities: Any, total_variance: Any,
                                          tolerance: float = 1e-10) -> dict[str, Any]:
    audit = audit_cross_expiry_surface(log_moneyness, maturities, total_variance, tolerance)
    if not audit["static_arbitrage_free_grid"]:
        raise ValueError("variance surface failed calendar monotonicity and/or butterfly convexity audit")
    return audit


def compute_top5_mlofi(delta_bid_volume: Any, delta_ask_volume: Any,
                       delta_bid_price: Any, delta_ask_price: Any,
                       weights: Any = None) -> float:
    """Compute signed five-depth-level MLOFI using price-change indicators."""
    dbv = _finite_array(delta_bid_volume, "delta_bid_volume", ndim=1)
    dav = _finite_array(delta_ask_volume, "delta_ask_volume", ndim=1)
    dbp = _finite_array(delta_bid_price, "delta_bid_price", ndim=1)
    dap = _finite_array(delta_ask_price, "delta_ask_price", ndim=1)
    if any(a.shape != (5,) for a in (dbv, dav, dbp, dap)):
        raise ValueError("each MLOFI input must contain exactly five levels")
    w = np.ones(5, dtype=float) if weights is None else _finite_array(weights, "weights", ndim=1)
    if w.shape != (5,) or np.any(w < 0) or np.sum(w) <= 0:
        raise ValueError("weights must be five nonnegative values with positive sum")
    bid = dbv * (dbp >= 0.0)
    ask = dav * (dap <= 0.0)
    return float(np.dot(w, bid - ask))


def hawkes_mlofi_toxicity(mlofi: float, event_times: Any = (), event_jumps: Any = (),
                          current_time: float = 0.0, mu0: float = 0.1,
                          gamma_mlofi: float = 0.02, beta: float = 1.0,
                          decay: float = 1.5, tau: float = 1.0,
                          lambda_threshold: float = 0.9162907318741551) -> dict[str, Any]:
    """Current nonnegative Hawkes/MLOFI intensity and adverse selection gate.

    lambda_threshold is returned as telemetry; the action is governed by P_adv > 0.60.
    """
    vals = (mlofi, current_time, mu0, gamma_mlofi, beta, decay, tau, lambda_threshold)
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("all scalar inputs must be finite")
    if mu0 < 0 or gamma_mlofi < 0 or beta <= 0 or decay <= 0 or tau < 0 or lambda_threshold < 0:
        raise ValueError("invalid intensity parameters")
    times = _finite_array(event_times, "event_times", ndim=1)
    jumps = _finite_array(event_jumps, "event_jumps", ndim=1)
    if times.shape != jumps.shape or np.any(jumps < 0) or np.any(times > current_time):
        raise ValueError("event times/jumps must match, jumps nonnegative, and events not in the future")
    excitation = float(np.sum(jumps * np.exp(-decay * (current_time - times))))
    intensity = max(0.0, float(mu0) + float(gamma_mlofi) * abs(float(mlofi)) ** float(beta) + excitation)
    p_adv = float(-math.expm1(-intensity * float(tau)))
    return {"intensity": intensity, "excitation": excitation, "toxicity_prob": p_adv,
            "toxicity_action": "RETREAT" if p_adv > 0.60 else "CONTINUE_PAPER",
            "lambda_threshold": float(lambda_threshold)}


def almgren_chriss_multi_expiry_unwind(inventory: Any, horizon_steps: int = 10, eta: float = 0.1,
                                       gamma_decay: float = 0.5, sigma: float = 0.01,
                                       lambda_risk: float = 1e-4, intensity: float = 0.0,
                                       tau: float = 1.0, cross_impact_matrix: Any = None) -> dict[str, Any]:
    """Solve a quadratic discrete AC unwind with a hard zero terminal inventory.

    The optimization uses positive-definite asset-impact matrix A, temporal kernel
    K_ts=(1+|t-s|*dt)^(-gamma_decay), state cost lambda_risk*sigma^2*dt*||q_t||^2,
    and fixed q_0, q_T=0. The terminal trade is eliminated algebraically.
    """
    q0 = _finite_array(inventory, "inventory")
    if q0.ndim == 0:
        q0 = q0.reshape(1)
    if q0.ndim != 1 or q0.size < 1:
        raise ValueError("inventory must be a scalar or 1D expiry inventory vector")
    steps = int(horizon_steps)
    if steps < 1:
        raise ValueError("horizon_steps must be >= 1")
    _positive(eta, "eta"); _positive(gamma_decay, "gamma_decay")
    _positive(sigma, "sigma", allow_zero=True); _positive(lambda_risk, "lambda_risk", allow_zero=True)
    _positive(intensity, "intensity", allow_zero=True); _positive(tau, "tau", allow_zero=True)
    m = q0.size
    if cross_impact_matrix is None:
        A = np.eye(m, dtype=float)
    else:
        A0 = _finite_array(cross_impact_matrix, "cross_impact_matrix", ndim=2)
        if A0.shape != (m, m):
            raise ValueError("cross_impact_matrix must match inventory size")
        A = 0.5 * (A0 + A0.T)
        eig = np.linalg.eigvalsh(A)
        if float(np.min(eig)) <= 0:
            raise ValueError("symmetric cross-impact matrix must be positive definite")
    dt = 1.0 / steps
    # Let u_t=q_t-q_{t+1} be signed liquidation trades, with sum_t u_t=q_0.
    # Eliminate the final trade exactly: u_{T-1}=q_0-sum_{t<T-1}u_t.
    # Optimize transient non-local impact eta*u^T (K kron A) u plus inventory risk.
    q = np.zeros((steps + 1, m), dtype=float)
    q[0] = q0
    if steps == 1:
        trades = q0.reshape(1, m).copy()
    else:
        nvar = (steps - 1) * m
        E = np.zeros((steps * m, nvar), dtype=float)
        bvec = np.zeros(steps * m, dtype=float)
        bvec[(steps - 1) * m:steps * m] = q0
        for t in range(steps - 1):
            E[t*m:(t+1)*m, t*m:(t+1)*m] = np.eye(m)
            E[(steps-1)*m:steps*m, t*m:(t+1)*m] = -np.eye(m)
        # Symmetric power-law temporal kernel and cross-asset transient impact.
        tick = np.arange(steps, dtype=float) * dt
        temporal_kernel = (1.0 + np.abs(tick[:, None] - tick[None, :])) ** (-float(gamma_decay))
        H = np.kron(temporal_kernel, A)
        min_h = float(np.min(np.linalg.eigvalsh(0.5 * (H + H.T))))
        if min_h < -1e-8:
            raise ValueError("discrete transient kernel is not positive semidefinite")
        # q_k=q0-sum_{t<k}u_t, k=0..T-1: q_flat=L z+c.
        L = np.zeros((steps * m, nvar), dtype=float)
        cvec = np.tile(q0, steps)
        for k in range(steps):
            for t in range(min(k, steps - 1)):
                L[k*m:(k+1)*m, t*m:(t+1)*m] = -np.eye(m)
        risk_weight = float(lambda_risk) * float(sigma) ** 2 * dt
        Q = float(eta) * (E.T @ H @ E) + risk_weight * (L.T @ L)
        linear = float(eta) * (E.T @ H @ bvec) + risk_weight * (L.T @ cvec)
        # A tiny scale-relative diagonal protects solves from roundoff only.
        ridge = max(1e-14, 1e-13 * float(np.trace(Q)) / max(1, nvar))
        z = np.linalg.solve(Q + ridge * np.eye(nvar), -linear).reshape(steps - 1, m)
        trades = (E @ z.reshape(-1) + bvec).reshape(steps, m)
    # Construct path using the optimized trade variables. Terminal state is hard-set
    # to zero after checking the calculated sum; this avoids roundoff inventory drift.
    for t in range(steps):
        q[t + 1] = q[t] - trades[t]
    terminal_residual = float(np.max(np.abs(q[-1])))
    if terminal_residual > 1e-8 * max(1.0, float(np.max(np.abs(q0)))):
        raise ArithmeticError("terminal inventory constraint solver residual exceeded tolerance")
    q[-1] = 0.0
    trades[-1] = q[-2]
    p_adv = float(-math.expm1(-float(intensity) * float(tau)))
    return {"inventory_path": q, "trade_schedule": trades, "terminal_inventory": float(np.max(np.abs(q[-1]))),
            "preprojection_terminal_residual": terminal_residual, "transient_kernel": temporal_kernel if steps > 1 else np.ones((1, 1)),
            "toxicity_prob": p_adv, "toxicity_action": "RETREAT" if p_adv > 0.60 else "CONTINUE_PAPER",
            "kernel_decay": float(gamma_decay), "impact_matrix": A, "time_step": dt,
            "live_dispatch_enabled": False}


def cubic_root_indifference_width(c: float, sigma: float, gamma_risk: float,
                                  statutory_fee_drag: float = 0.0) -> float:
    """Davis-Norman/Shreve cube-root width with nonnegative per-unit fee drag."""
    c_eff = _positive(c, "c") + _positive(statutory_fee_drag, "statutory_fee_drag", allow_zero=True)
    sig = _positive(sigma, "sigma", allow_zero=True)
    risk = _positive(gamma_risk, "gamma_risk")
    return float((3.0 * c_eff * sig * sig / (4.0 * risk)) ** (1.0 / 3.0))


def indian_statutory_fees(buy_turnover_inr: float, sell_turnover_inr: float, executed_legs: int = 0) -> dict[str, Any]:
    buy = _positive(buy_turnover_inr, "buy_turnover_inr", allow_zero=True)
    sell = _positive(sell_turnover_inr, "sell_turnover_inr", allow_zero=True)
    legs = int(executed_legs)
    if legs < 0:
        raise ValueError("executed_legs must be >= 0")
    brokerage = 20.0 * legs
    stt = 0.0015 * sell
    stamp = 0.00003 * buy
    exchange = 0.0003553 * (buy + sell)
    sebi = 0.000001 * (buy + sell)
    gst = 0.18 * (brokerage + exchange + sebi)
    breakdown = {"stt_sell": stt, "stamp_duty_buy": stamp, "nse_transaction_fee": exchange,
                 "sebi_turnover_fee": sebi, "brokerage": brokerage, "gst": gst}
    return {"total_fees_inr": float(sum(breakdown.values())), "breakdown": breakdown}


def net_alpha_gate(expected_gross_alpha_inr: float, total_fees_inr: float) -> dict[str, Any]:
    gross = float(expected_gross_alpha_inr); fees = float(total_fees_inr)
    if not (math.isfinite(gross) and math.isfinite(fees)) or fees < 0:
        raise ValueError("alpha/fees must be finite and fees nonnegative")
    net = gross - fees
    return {"approved": bool(net > 0.0), "net_alpha_inr": float(net)}


def beta_fractional_kelly(alpha_prior: float, beta_prior: float, wins: int, losses: int,
                          win_loss_ratio: float, scale: float = 0.25, cap: float = 0.10,
                          net_alpha_positive: bool = True) -> dict[str, Any]:
    a = _positive(alpha_prior, "alpha_prior"); b = _positive(beta_prior, "beta_prior")
    wins, losses = int(wins), int(losses)
    if wins < 0 or losses < 0:
        raise ValueError("wins and losses must be nonnegative")
    odds = _positive(win_loss_ratio, "win_loss_ratio")
    scale = _positive(scale, "scale", allow_zero=True)
    cap = _positive(cap, "cap", allow_zero=True)
    p = (a + wins) / (a + b + wins + losses)
    full_kelly = max(0.0, p - (1.0 - p) / odds)
    fraction = min(0.10, cap, scale * full_kelly) if net_alpha_positive else 0.0
    return {"capital_fraction": float(max(0.0, fraction)), "posterior_win_probability": float(p),
            "full_kelly_fraction": float(full_kelly), "cap": min(0.10, cap)}


def squad_consensus(agent_votes: Mapping[str, Any], manager_live_veto: bool = True,
                    require_unanimous: bool = True, risk_gates_passed: bool = True) -> dict[str, Any]:
    if not isinstance(agent_votes, Mapping) or any(name not in agent_votes for name in AGENT_NAMES):
        raise ValueError("agent_votes must include Abhi, Alex, Emily, and Max")
    votes = {name: bool(agent_votes[name]) for name in AGENT_NAMES}
    paper_ok = (all(votes.values()) if require_unanimous else any(votes.values())) and bool(risk_gates_passed)
    # Manager live veto is recorded for governance, but live dispatch never enables.
    return {"paper_research_approved": bool(paper_ok), "agent_votes": votes,
            "manager_live_veto": bool(manager_live_veto), "risk_gates_passed": bool(risk_gates_passed),
            "live_order_dispatch_enabled": False, "real_broker_fills_locked": True,
            "paper_ledger_epoch": PAPER_LEDGER_EPOCH, "initial_capital_inr": INITIAL_CAPITAL_INR}


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Permanent fail-closed guard: Cycle 68 never supports broker order dispatch."""
    raise PermissionError("LIVE_ORDER_DISPATCH_BLOCKED: Cycle 68 is fail-closed. Real broker dispatch is strictly locked.")

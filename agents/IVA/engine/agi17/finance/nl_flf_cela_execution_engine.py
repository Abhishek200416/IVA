"""Cycle 67 NL-FLF-CELA: offline research primitives for paper-only quant research.

Dependencies: Python standard library and NumPy. No broker, network, or order APIs.
"""
from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence, Any
import numpy as np

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
MARKET_CLOSE_IST = "15:15"
REQUIRED_AGENTS = ("Abhi", "Alex", "Emily", "Max")


def _finite_scalar(name: str, value: Any, *, minimum: float | None = None,
                   strict_minimum: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and (result <= minimum if strict_minimum else result < minimum):
        op = ">" if strict_minimum else ">="
        raise ValueError(f"{name} must be {op} {minimum}")
    return result


def _finite_array(name: str, value: Any, *, ndim: int | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def tempered_levy_characteristic_function(
    u: float | Sequence[float] | np.ndarray,
    t: float,
    alpha: float = 1.7,
    lambda_damp: float = 0.5,
    c_alpha: float = 1.0,
    gaussian_variance_rate: float = 1.0,
) -> complex | np.ndarray:
    """Characteristic function of a *symmetric*, exponentially tempered process.

    For 1 < alpha < 2, this uses the two-sided compensated exponent
      t*K*[B(lambda-iu) + B(lambda+iu)],
    B(z)=(z**alpha-lambda**alpha) plus the corresponding linear compensation,
    K=c_alpha*pi/(Gamma(alpha+1)*sin(pi*alpha/2)).
    The real part of the exponent is non-positive. This is the symmetric extension
    appropriate to nu(dx) proportional to exp(-lambda*|x|)|x|**(-1-alpha) dx.

    The supplied single-sided formula in the request has a sign inconsistency: for
    nonzero u its bracket has negative real part but the leading minus sign makes
    |Phi|>1. A characteristic function must obey |Phi(u)|<=1. This implementation
    uses the sign-corrected, two-sided symmetric form. At alpha=2 it uses the
    finite Gaussian-limit branch (variance rate supplied separately), avoiding the
    sin(pi*alpha/2)=0 singularity. This avoids claiming an ill-defined alpha=2
    evaluation of the literal expression.
    """
    tt = _finite_scalar("t", t, minimum=0.0)
    aa = _finite_scalar("alpha", alpha, minimum=1.0, strict_minimum=True)
    if aa > 2.0:
        raise ValueError("alpha must be in (1, 2]")
    damp = _finite_scalar("lambda_damp", lambda_damp, minimum=0.0, strict_minimum=True)
    ca = _finite_scalar("c_alpha", c_alpha, minimum=0.0)
    ua = _finite_array("u", u)
    if aa == 2.0:
        var_rate = _finite_scalar("gaussian_variance_rate", gaussian_variance_rate, minimum=0.0)
        out = np.exp(-0.5 * tt * var_rate * np.square(ua))
    else:
        coeff = ca * math.pi / (math.gamma(aa + 1.0) * math.sin(math.pi * aa / 2.0))
        z_minus = np.power(damp - 1j * ua, aa) - damp**aa + 1j * ua * aa * damp**(aa - 1.0)
        z_plus = np.power(damp + 1j * ua, aa) - damp**aa - 1j * ua * aa * damp**(aa - 1.0)
        out = np.exp(tt * coeff * (z_minus + z_plus))
    if np.ndim(u) == 0:
        return complex(np.asarray(out).item())
    return np.asarray(out, dtype=complex)


def sample_truncated_levy_flights(
    n: int,
    alpha: float = 1.7,
    lambda_damp: float = 0.5,
    scale: float = 1.0,
    min_jump: float = 1e-3,
    max_jump: float = 5.0,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Sample a finite-variance, symmetrized discretized tempered power-law jump law.

    Inverse-CDF sampling on a log-spaced magnitude grid approximates density
    x^(-1-alpha)*exp(-lambda_damp*x) over [min_jump, max_jump]. The cutoff and grid
    are explicit modeling choices, not an exact sample from an infinite-activity
    Levy process.
    """
    if isinstance(n, bool) or int(n) != n or n < 0:
        raise ValueError("n must be a non-negative integer")
    aa = _finite_scalar("alpha", alpha, minimum=1.0, strict_minimum=True)
    if aa > 2.0:
        raise ValueError("alpha must be in (1, 2]")
    damp = _finite_scalar("lambda_damp", lambda_damp, minimum=0.0, strict_minimum=True)
    sc = _finite_scalar("scale", scale, minimum=0.0)
    lo = _finite_scalar("min_jump", min_jump, minimum=0.0, strict_minimum=True)
    hi = _finite_scalar("max_jump", max_jump, minimum=lo, strict_minimum=True)
    gen = rng if rng is not None else np.random.default_rng(0)
    if n == 0 or sc == 0.0:
        return np.zeros(int(n), dtype=float)
    grid = np.geomspace(lo, hi, 8192)
    density = np.power(grid, -1.0-aa) * np.exp(-damp*grid)
    # Integrate in x-space (trapz replacement works across numpy versions).
    increments = 0.5 * (density[1:] + density[:-1]) * np.diff(grid)
    cdf = np.concatenate(([0.0], np.cumsum(increments)))
    cdf /= cdf[-1]
    magnitudes = np.interp(gen.random(int(n)), cdf, grid) * sc
    signs = gen.choice(np.array([-1.0, 1.0]), size=int(n))
    return magnitudes * signs


def simulate_levy_flight_path(
    n_steps: int = 100,
    dt: float = 0.01,
    alpha: float = 1.7,
    lambda_damp: float = 0.5,
    jump_intensity: float = 0.5,
    jump_scale: float = 0.02,
    drift: float = 0.0,
    seed: int = 67,
) -> dict[str, Any]:
    """Simulate compound-Poisson truncation of tempered Levy flights for paper research."""
    if isinstance(n_steps, bool) or int(n_steps) != n_steps or n_steps < 1:
        raise ValueError("n_steps must be a positive integer")
    h = _finite_scalar("dt", dt, minimum=0.0, strict_minimum=True)
    intensity = _finite_scalar("jump_intensity", jump_intensity, minimum=0.0)
    jscale = _finite_scalar("jump_scale", jump_scale, minimum=0.0)
    mu = _finite_scalar("drift", drift)
    # Validate alpha/damping through the sampler even if no jump occurs.
    rng = np.random.default_rng(seed)
    path = np.zeros(int(n_steps)+1, dtype=float)
    jumps_total = 0
    jumps_each_step = np.zeros(int(n_steps), dtype=int)
    for k in range(int(n_steps)):
        count = int(rng.poisson(intensity*h))
        jumps_each_step[k] = count
        jumps_total += count
        jump = sample_truncated_levy_flights(count, alpha, lambda_damp, jscale, rng=rng).sum()
        path[k+1] = path[k] + mu*h + jump
    return {
        "trajectory": path,
        "jumps_total": int(jumps_total),
        "jumps_each_step": jumps_each_step,
        "characteristic_function": tempered_levy_characteristic_function(
            np.array([0.0, 0.5, 1.0]), int(n_steps)*h, alpha, lambda_damp),
        "model_mode": "truncated_compound_poisson_paper_simulation",
    }


def term_structure_arbitrage_audit(
    log_moneyness: Sequence[float] | np.ndarray,
    maturities: Sequence[float] | np.ndarray,
    total_variance: Sequence[Sequence[float]] | np.ndarray,
    friction_cost: float = 0.0,
    tolerance: float = 1e-8,
) -> dict[str, Any]:
    """Audit calendar monotonicity, approximate butterfly g(k), and expiry curvature.

    total_variance has shape (n_maturities, n_strikes); k must be strictly increasing
    with at least 3 points, maturity strictly increasing, and variance strictly > 0.
    Derivatives are finite-grid estimates using numpy.gradient; strict positivity of
    the computed g values is a diagnostic on this grid, not a proof for the continuum.
    """
    k = _finite_array("log_moneyness", log_moneyness, ndim=1)
    t = _finite_array("maturities", maturities, ndim=1)
    w = _finite_array("total_variance", total_variance, ndim=2)
    if len(k) < 3 or len(t) < 2:
        raise ValueError("need at least 3 strike points and 2 maturities")
    if np.any(np.diff(k) <= 0) or np.any(np.diff(t) <= 0):
        raise ValueError("strikes and maturities must be strictly increasing")
    if w.shape != (len(t), len(k)):
        raise ValueError("total_variance must have shape (len(maturities), len(log_moneyness))")
    if np.any(w <= 0):
        raise ValueError("total_variance must be strictly positive")
    friction = _finite_scalar("friction_cost", friction_cost, minimum=0.0)
    tol = _finite_scalar("tolerance", tolerance, minimum=0.0)
    calendar_diffs = np.diff(w, axis=0)
    calendar_ok = bool(np.all(calendar_diffs >= -tol))
    dwdk = np.vstack([np.gradient(row, k, edge_order=2) for row in w])
    d2wdk2 = np.vstack([np.gradient(dwdk[i], k, edge_order=2) for i in range(len(t))])
    g = np.square(1.0 - (k[None, :] * dwdk) / (2.0*w)) - (
        np.square(dwdk)/4.0 * (1.0/w + 0.25)) + d2wdk2/2.0
    butterfly_ok = bool(np.all(g > tol))
    curvature = np.diff(w, n=2, axis=0) if len(t) >= 3 else np.zeros((0, len(k)))
    max_curvature = float(np.max(np.abs(curvature))) if curvature.size else 0.0
    net_signal = max(0.0, max_curvature-friction)
    return {
        "calendar_monotone": calendar_ok,
        "calendar_violation_count": int(np.count_nonzero(calendar_diffs < -tol)),
        "calendar_min_increment": float(np.min(calendar_diffs)),
        "butterfly_convex": butterfly_ok,
        "butterfly_g": g,
        "min_butterfly_g": float(np.min(g)),
        "cross_expiry_curvature": curvature,
        "curvature_dislocation_metric": max_curvature,
        "net_curvature_signal": net_signal,
        "friction_cost": friction,
        "diagnostic_scope": "finite_grid_numerical_audit",
    }


def compute_mlofi_5level(
    delta_bid_volume: Sequence[float],
    delta_ask_volume: Sequence[float],
    delta_bid_price: Sequence[float],
    delta_ask_price: Sequence[float],
    weights: Sequence[float] = (1.0, 0.8, 0.6, 0.4, 0.2),
) -> float:
    """Compute the signed five-level MLOFI using the requested price-direction gates."""
    dbv = _finite_array("delta_bid_volume", delta_bid_volume, ndim=1)
    dav = _finite_array("delta_ask_volume", delta_ask_volume, ndim=1)
    dbp = _finite_array("delta_bid_price", delta_bid_price, ndim=1)
    dap = _finite_array("delta_ask_price", delta_ask_price, ndim=1)
    ww = _finite_array("weights", weights, ndim=1)
    if any(len(x) != 5 for x in (dbv, dav, dbp, dap, ww)):
        raise ValueError("all MLOFI inputs must contain exactly 5 levels")
    return float(np.sum(ww * (dbv*(dbp >= 0.0) - dav*(dap <= 0.0))) )


def toxic_jump_intensity(
    mlofi: float,
    past_events: Iterable[tuple[float, float]],
    current_time: float,
    mu0: float = 0.05,
    gamma_mlofi: float = 0.01,
    beta: float = 0.7,
    kappa: float = 1.2,
    lambda_thresh: float = 1.0,
) -> dict[str, Any]:
    """Hawkes-like jump-cascade intensity and passive quote action.

    Each past event is (event_time, nonnegative_jump_mark); future events are rejected.
    """
    flow = _finite_scalar("mlofi", mlofi)
    now = _finite_scalar("current_time", current_time)
    base = _finite_scalar("mu0", mu0, minimum=0.0)
    coeff = _finite_scalar("gamma_mlofi", gamma_mlofi, minimum=0.0)
    power = _finite_scalar("beta", beta, minimum=0.0, strict_minimum=True)
    decay = _finite_scalar("kappa", kappa, minimum=0.0, strict_minimum=True)
    threshold = _finite_scalar("lambda_thresh", lambda_thresh, minimum=0.0)
    cascade = 0.0
    checked_events = 0
    for event in past_events:
        if len(event) != 2:
            raise ValueError("each event must be (event_time, jump_mark)")
        event_time = _finite_scalar("event_time", event[0])
        mark = _finite_scalar("jump_mark", event[1], minimum=0.0)
        if event_time > now:
            raise ValueError("past_events cannot contain future events")
        cascade += mark*math.exp(-decay*(now-event_time))
        checked_events += 1
    intensity = base + coeff*(abs(flow)**power) + cascade
    action = "RETREAT" if intensity > threshold else "CONTINUE_PAPER"
    return {"intensity": float(intensity), "toxicity_action": action,
            "threshold": threshold, "past_events_used": checked_events}


def multi_expiry_liquidation(
    inventories: Sequence[float],
    horizon_steps: int = 10,
    eta: float = 0.1,
    gamma_decay: float = 1.2,
    sigma: float = 0.01,
    lambda_risk: float = 1e-4,
    intensity: float = 0.0,
    tau: float = 1.0,
) -> dict[str, Any]:
    """Deterministic linear unwind baseline with a non-local transient-impact diagnostic.

    Inventory is liquidated proportionally in each expiry bucket. This is a transparent
    feasible schedule, not a claim of solving the full stochastic nonlinear optimum.
    """
    q0 = _finite_array("inventories", inventories, ndim=1)
    if len(q0) < 1:
        raise ValueError("inventories cannot be empty")
    if isinstance(horizon_steps, bool) or int(horizon_steps) != horizon_steps or horizon_steps < 1:
        raise ValueError("horizon_steps must be a positive integer")
    eta_v = _finite_scalar("eta", eta, minimum=0.0)
    decay = _finite_scalar("gamma_decay", gamma_decay, minimum=0.0, strict_minimum=True)
    sig = _finite_scalar("sigma", sigma, minimum=0.0)
    risk = _finite_scalar("lambda_risk", lambda_risk, minimum=0.0)
    inten = _finite_scalar("intensity", intensity, minimum=0.0)
    tau_v = _finite_scalar("tau", tau, minimum=0.0)
    steps = int(horizon_steps)
    fractions = np.linspace(1.0, 0.0, steps+1)
    qpath = fractions[:, None]*q0[None, :]
    # Positive trade_schedule means signed units removed from inventory at each step.
    trades = qpath[:-1] - qpath[1:]
    kernel = np.array([(1.0+lag)**(-decay) for lag in range(steps)], dtype=float)
    impact = np.zeros_like(trades)
    for t_idx in range(steps):
        for s_idx in range(t_idx+1):
            # Impact is signed in each asset and decays non-locally in time.
            impact[t_idx] += eta_v*kernel[t_idx-s_idx]*np.sign(trades[s_idx])*np.power(np.abs(trades[s_idx]), 1.0)
    toxicity_prob = float(1.0-math.exp(-inten*tau_v))
    toxicity_action = "RETREAT" if toxicity_prob > 0.60 else "CONTINUE_PAPER"
    risk_energy = float(risk*sig**2*np.sum(np.square(qpath[:-1])))
    impact_energy = float(eta_v*np.sum(np.square(trades)))
    return {
        "terminal_inventory": 0.0,
        "inventory_path": qpath,
        "trade_schedule": trades,
        "transient_impact": impact,
        "toxicity_prob": toxicity_prob,
        "toxicity_action": toxicity_action,
        "objective_estimate": risk_energy+impact_energy,
        "market_close_ist": MARKET_CLOSE_IST,
        "schedule_mode": "deterministic_feasible_linear_unwind",
    }


def friction_aware_indifference_width(
    c: float,
    sigma: float,
    gamma_risk: float,
    fee_drag: float = 0.0,
) -> dict[str, float]:
    """Cubic-root indifference width plus fee drag expressed in matching price units."""
    cc = _finite_scalar("c", c, minimum=0.0, strict_minimum=True)
    sig = _finite_scalar("sigma", sigma, minimum=0.0)
    gr = _finite_scalar("gamma_risk", gamma_risk, minimum=0.0, strict_minimum=True)
    fee = _finite_scalar("fee_drag", fee_drag, minimum=0.0)
    base = (3.0*cc*sig*sig/(4.0*gr))**(1.0/3.0)
    return {"base_width": float(base), "fee_drag": fee, "indifference_width": float(base+fee)}


def indian_statutory_fees(
    buy_turnover_inr: float,
    sell_turnover_inr: float,
    executed_legs: int = 0,
) -> dict[str, Any]:
    """Compute the user-specified fee schedule; rates are explicit configurable premises."""
    buy = _finite_scalar("buy_turnover_inr", buy_turnover_inr, minimum=0.0)
    sell = _finite_scalar("sell_turnover_inr", sell_turnover_inr, minimum=0.0)
    if isinstance(executed_legs, bool) or int(executed_legs) != executed_legs or executed_legs < 0:
        raise ValueError("executed_legs must be a non-negative integer")
    stt = sell*0.0015
    stamp = buy*0.00003
    exchange = (buy+sell)*0.0003553
    sebi = (buy+sell)*0.000001
    brokerage = int(executed_legs)*20.0
    gst = 0.18*(brokerage+exchange+sebi)
    breakdown = {"stt_sell": stt, "stamp_duty_buy": stamp,
                 "nse_transaction_fee": exchange, "sebi_turnover_fee": sebi,
                 "brokerage": brokerage, "gst": gst}
    return {"total_fees_inr": float(sum(breakdown.values())), "breakdown": breakdown,
            "rates_are_user_supplied_assumptions": True}


def net_alpha_gate(expected_gross_alpha_inr: float, total_fees_inr: float) -> dict[str, Any]:
    gross = _finite_scalar("expected_gross_alpha_inr", expected_gross_alpha_inr)
    fees = _finite_scalar("total_fees_inr", total_fees_inr, minimum=0.0)
    net = gross-fees
    return {"approved": bool(net > 0.0), "net_alpha_inr": float(net)}


def beta_fractional_kelly(
    alpha_prior: float,
    beta_prior: float,
    wins: int,
    losses: int,
    win_loss_ratio: float,
    scale: float = 0.25,
    cap: float = 0.10,
    net_alpha_positive: bool = True,
) -> dict[str, float]:
    a = _finite_scalar("alpha_prior", alpha_prior, minimum=0.0, strict_minimum=True)
    b = _finite_scalar("beta_prior", beta_prior, minimum=0.0, strict_minimum=True)
    if isinstance(wins, bool) or int(wins) != wins or wins < 0:
        raise ValueError("wins must be a non-negative integer")
    if isinstance(losses, bool) or int(losses) != losses or losses < 0:
        raise ValueError("losses must be a non-negative integer")
    ratio = _finite_scalar("win_loss_ratio", win_loss_ratio, minimum=0.0, strict_minimum=True)
    multiplier = _finite_scalar("scale", scale, minimum=0.0)
    ceiling = _finite_scalar("cap", cap, minimum=0.0)
    if ceiling > 0.10 + 1e-15:
        raise ValueError("cap cannot exceed the mandated 10% capital fraction")
    posterior_p = (a+int(wins))/(a+b+int(wins)+int(losses))
    full_kelly = max(0.0, posterior_p-(1.0-posterior_p)/ratio)
    fraction = min(ceiling, multiplier*full_kelly) if net_alpha_positive else 0.0
    return {"capital_fraction": float(fraction),
            "posterior_win_probability": float(posterior_p),
            "full_kelly_fraction": float(full_kelly),
            "cap": float(ceiling)}


def squad_consensus(
    agent_votes: Mapping[str, Any],
    manager_live_veto: bool = True,
    require_unanimous: bool = True,
    risk_gates_passed: bool = True,
) -> dict[str, Any]:
    """Research consensus only; live dispatch remains disabled under all vote patterns."""
    if not isinstance(agent_votes, Mapping):
        raise ValueError("agent_votes must be a mapping")
    missing = [name for name in REQUIRED_AGENTS if name not in agent_votes]
    if missing:
        raise ValueError(f"missing required agent votes: {', '.join(missing)}")
    votes = {}
    for name in REQUIRED_AGENTS:
        raw = agent_votes[name]
        if isinstance(raw, Mapping):
            if "approve" not in raw:
                raise ValueError(f"vote for {name} mapping must include 'approve'")
            raw = raw["approve"]
        if not isinstance(raw, (bool, np.bool_)):
            raise ValueError(f"vote for {name} must be boolean or {{'approve': bool}}")
        votes[name] = bool(raw)
    if not isinstance(manager_live_veto, (bool, np.bool_)):
        raise ValueError("manager_live_veto must be boolean")
    if not isinstance(require_unanimous, (bool, np.bool_)) or not isinstance(risk_gates_passed, (bool, np.bool_)):
        raise ValueError("require_unanimous and risk_gates_passed must be boolean")
    approvals = sum(votes.values())
    votes_ok = approvals == len(REQUIRED_AGENTS) if require_unanimous else approvals >= 3
    research_approved = bool(votes_ok and risk_gates_passed)
    return {
        "paper_research_approved": research_approved,
        "live_order_dispatch_enabled": False,
        "manager_live_veto_active": bool(manager_live_veto),
        "votes": votes,
        "approvals": int(approvals),
        "risk_gates_passed": bool(risk_gates_passed),
    }


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Permanent fail-closed guard. Every invocation is blocked unconditionally."""
    raise PermissionError(
        "LIVE_ORDER_DISPATCH_BLOCKED: Cycle 67 is fail-closed. Real broker dispatch is strictly locked."
    )


__all__ = [
    "LIVE_ORDER_DISPATCH_ENABLED", "REAL_BROKER_FILLS_LOCKED", "PAPER_LEDGER_EPOCH",
    "INITIAL_CAPITAL_INR", "tempered_levy_characteristic_function",
    "sample_truncated_levy_flights", "simulate_levy_flight_path",
    "term_structure_arbitrage_audit", "compute_mlofi_5level", "toxic_jump_intensity",
    "multi_expiry_liquidation", "friction_aware_indifference_width",
    "indian_statutory_fees", "net_alpha_gate", "beta_fractional_kelly",
    "squad_consensus", "dispatch_live_order"
]

"""Cycle 66: Continuous-Time Fractional McKean-Vlasov Jump-Diffusion research engine.

Dependencies: Python standard library and NumPy only. This module is paper/research-only;
it intentionally contains no broker connector or live order dispatch implementation.
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
CYCLE = 66


# ---------- Shared validation helpers ----------
def _finite_float(name: str, value: Any, *, minimum: float | None = None,
                  strict_minimum: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and (result <= minimum if strict_minimum else result < minimum):
        op = ">" if strict_minimum else ">="
        raise ValueError(f"{name} must be {op} {minimum}")
    return result


def _positive_int(name: str, value: Any, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer >= {minimum}")
    result = int(value)
    if result < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return result


def _as_finite_array(name: str, value: Any, *, ndim: int | None = None) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a numeric array") from exc
    if ndim is not None and array.ndim != ndim:
        raise ValueError(f"{name} must be {ndim}-dimensional")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def _volterra_bin_weights(n_steps: int, dt: float, hurst: float) -> np.ndarray:
    """Integrated fractional kernel weights with a finite-bin singularity treatment.

    For lag bin [k*dt, (k+1)*dt], integrate u^(H-1/2)/Gamma(H+1/2), then
    normalize the nonempty vector to unit Euclidean norm for stable modulation.
    """
    exponent = hurst + 0.5
    edges = np.arange(n_steps + 1, dtype=float) * dt
    weights = np.diff(edges ** exponent) / math.gamma(exponent + 1.0)
    norm = float(np.linalg.norm(weights))
    if norm > 0.0:
        weights = weights / norm
    return weights


def _normalize_mlofi(mlofi_signals: Any, n_steps: int, n_particles: int) -> np.ndarray:
    if mlofi_signals is None:
        return np.zeros((n_steps, n_particles), dtype=float)
    signals = _as_finite_array("mlofi_signals", mlofi_signals)
    if signals.ndim == 0:
        return np.full((n_steps, n_particles), float(signals), dtype=float)
    if signals.ndim == 1:
        if signals.shape[0] != n_steps:
            raise ValueError("1D mlofi_signals must have length n_steps")
        return np.repeat(signals[:, None], n_particles, axis=1)
    if signals.ndim == 2:
        if signals.shape[0] != n_steps or signals.shape[1] not in (1, n_particles):
            raise ValueError("2D mlofi_signals must have shape (n_steps, 1) or (n_steps, n_particles)")
        return np.broadcast_to(signals, (n_steps, n_particles)).copy()
    raise ValueError("mlofi_signals must be scalar, 1D, or 2D")


# ---------- CT-FMV-JD particle simulator ----------
def simulate_mckean_vlasov_system(
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
    lambda_jump: float = 0.1,
    jump_scale: float = 0.02,
    seed: int | None = None,
) -> dict[str, Any]:
    """Euler-Maruyama particle approximation of the fractional MV jump-diffusion.

    The MLOFI-dependent intensity is lambda_i=max(0, lambda_jump + alpha*MLOFI_i),
    with alpha=lambda_jump because the public specification has no separate alpha
    parameter. State-dependent scalar Cholesky factors are floored at 1e-3, so their
    scalar covariance eigenvalues are >= 1e-6.
    """
    n_particles = _positive_int("n_particles", n_particles)
    n_steps = _positive_int("n_steps", n_steps)
    dt = _finite_float("dt", dt, minimum=0.0, strict_minimum=True)
    kappa = _finite_float("kappa", kappa, minimum=0.0, strict_minimum=True)
    gamma = _finite_float("gamma", gamma, minimum=0.0)
    x_bar = _finite_float("x_bar", x_bar)
    beta = _finite_float("beta", beta)
    sigma_base = _finite_float("sigma_base", sigma_base, minimum=0.0)
    hurst = _finite_float("hurst", hurst, minimum=0.0, strict_minimum=True)
    if hurst >= 0.5:
        raise ValueError("hurst must lie in (0, 0.5)")
    lambda_jump = _finite_float("lambda_jump", lambda_jump, minimum=0.0)
    jump_scale = _finite_float("jump_scale", jump_scale, minimum=0.0)
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, (int, np.integer))):
        raise ValueError("seed must be an integer or None")

    rng = np.random.default_rng(seed)
    mlofi = _normalize_mlofi(mlofi_signals, n_steps, n_particles)
    weights = _volterra_bin_weights(n_steps, dt, hurst)
    trajectory = np.empty((n_steps + 1, n_particles), dtype=float)
    drift_path = np.empty((n_steps, n_particles), dtype=float)
    diffusion_path = np.empty((n_steps, n_particles), dtype=float)
    trajectory[0] = rng.normal(loc=x_bar, scale=0.1, size=n_particles)
    rough_innovations = rng.standard_normal((n_steps, n_particles))
    jumps_total = 0
    cholesky_floor = 1e-3

    for t in range(n_steps):
        state = trajectory[t]
        empirical_mean = float(np.mean(state))
        # Mean-field sum_j (X_j-X_i)/N = empirical_mean - X_i.
        drift = -kappa * (state - x_bar) + gamma * (empirical_mean - state) + beta * mlofi[t]
        if t == 0:
            rough_state = np.zeros(n_particles, dtype=float)
        else:
            current_weights = weights[:t][::-1]
            rough_state = current_weights @ rough_innovations[:t, :]
        sigma_state = np.maximum(sigma_base * np.exp(np.clip(0.2 * rough_state, -5.0, 5.0)), cholesky_floor)
        diffusion_path[t] = sigma_state
        drift_path[t] = drift

        # Independent scalar Wiener innovations per particle.
        brownian_increment = sigma_state * math.sqrt(dt) * rng.standard_normal(n_particles)
        # alpha is identified with lambda_jump under the specified signature.
        jump_intensity = np.maximum(0.0, lambda_jump + lambda_jump * mlofi[t])
        if not np.all(np.isfinite(jump_intensity)):
            raise ValueError("MLOFI generated a non-finite jump intensity")
        jump_counts = rng.poisson(jump_intensity * dt)
        jump_sign_random = rng.choice(np.array([-1.0, 1.0]), size=n_particles)
        jump_sign = np.where(mlofi[t] > 0.0, 1.0,
                             np.where(mlofi[t] < 0.0, -1.0, jump_sign_random))
        jump_increment = jump_scale * jump_counts * jump_sign
        jumps_total += int(np.sum(jump_counts))
        trajectory[t + 1] = state + drift * dt + brownian_increment + jump_increment

    mean_field_path = np.mean(trajectory, axis=1)
    variance_field_path = np.var(trajectory, axis=1)
    deterministic_euler_stable = dt * max(kappa, kappa + gamma) < 2.0
    finite_paths = bool(np.all(np.isfinite(trajectory)) and np.all(np.isfinite(drift_path))
                        and np.all(np.isfinite(diffusion_path)))
    covariance_floor_ok = bool(np.all(diffusion_path ** 2 >= 1e-6 - 1e-15))
    return {
        "particle_trajectories": trajectory,
        "mean_field_path": mean_field_path,
        "variance_field_path": variance_field_path,
        "jumps_total": jumps_total,
        "stability_verified": bool(deterministic_euler_stable and finite_paths and covariance_floor_ok),
        "drift_path": drift_path,
        "diffusion_path": diffusion_path,
        "volterra_weights": weights,
        "cholesky_min_eigenvalue_floor": 1e-6,
        "configured_hurst": hurst,
        "seed": seed,
    }


# ---------- Multi-asset non-local power-law cross-impact ----------
def cross_asset_nonlocal_impact(
    ofi_trajectories: Any,
    impact_matrix: Any,
    dt: float = 0.01,
    gamma_decay: float = 1.2,
) -> dict[str, Any]:
    """Causal quadrature of G_ij(tau)=Lambda_ij*(1+tau)^(-gamma_decay)."""
    ofi = _as_finite_array("ofi_trajectories", ofi_trajectories)
    if ofi.ndim == 1:
        ofi = ofi[:, None]
    if ofi.ndim != 2 or ofi.shape[0] < 1 or ofi.shape[1] < 1:
        raise ValueError("ofi_trajectories must have shape (time>=1, assets>=1)")
    lam = _as_finite_array("impact_matrix", impact_matrix, ndim=2)
    n_times, n_assets = ofi.shape
    if lam.shape != (n_assets, n_assets):
        raise ValueError("impact_matrix must be square with dimension equal to OFI asset count")
    if np.any(lam < 0.0):
        raise ValueError("impact_matrix entries must be nonnegative")
    dt = _finite_float("dt", dt, minimum=0.0, strict_minimum=True)
    gamma_decay = _finite_float("gamma_decay", gamma_decay, minimum=1.0, strict_minimum=True)

    cumulative = np.zeros((n_times, n_assets), dtype=float)
    for t in range(n_times):
        lags = (t - np.arange(t + 1, dtype=float)) * dt
        kernel = (1.0 + lags) ** (-gamma_decay)
        weighted_ofi = ofi[:t + 1, :] * kernel[:, None]
        cumulative[t] = dt * np.sum(weighted_ofi @ lam.T, axis=0)

    denom = lam + lam.T
    asymmetry = np.divide(lam - lam.T, denom, out=np.zeros_like(lam), where=denom > 0.0)
    np.fill_diagonal(asymmetry, 0.0)
    energy = float(np.sum(cumulative * cumulative) * dt)
    return {
        "cumulative_impact": cumulative,
        "cross_asymmetry_matrix": asymmetry,
        "total_energy": energy,
    }


# ---------- Discrete convex Almgren-Chriss unwind ----------
def almgren_chriss_unwind(
    inventory: float,
    horizon_steps: int = 10,
    eta: float = 0.1,
    gamma_decay: float = 0.5,
    sigma: float = 0.01,
    lambda_risk: float = 1e-4,
    intensity: float = 0.0,
    tau: float = 1.0,
) -> dict[str, Any]:
    """Solve a finite-horizon convex quadratic unwind with q[0]=inventory, q[T]=0.

    Minimize sum_k eta_k*(q_k-q_{k+1})^2 + risk*q_k^2 over internal q values,
    with eta_k=eta*exp(-gamma_decay*k/max(T-1,1)); this is an explicit discrete
    Almgren-Chriss-style objective, not a calibrated execution-cost prediction.
    """
    inventory = _finite_float("inventory", inventory)
    horizon_steps = _positive_int("horizon_steps", horizon_steps)
    eta = _finite_float("eta", eta, minimum=0.0, strict_minimum=True)
    gamma_decay = _finite_float("gamma_decay", gamma_decay, minimum=0.0)
    sigma = _finite_float("sigma", sigma, minimum=0.0)
    lambda_risk = _finite_float("lambda_risk", lambda_risk, minimum=0.0)
    intensity = _finite_float("intensity", intensity, minimum=0.0)
    tau = _finite_float("tau", tau, minimum=0.0)

    n = horizon_steps
    q = np.zeros(n + 1, dtype=float)
    q[0] = inventory
    eta_k = eta * np.exp(-gamma_decay * np.arange(n, dtype=float) / max(n - 1, 1))
    risk = lambda_risk * sigma * sigma
    # Objective with fixed q0 and qn. The normal-equation matrix is SPD since eta_k>0.
    if n > 1:
        matrix = np.zeros((n - 1, n - 1), dtype=float)
        rhs = np.zeros(n - 1, dtype=float)
        for idx in range(n - 1):
            k = idx + 1  # internal inventory q_k
            left_eta = eta_k[k - 1]
            right_eta = eta_k[k]
            matrix[idx, idx] = left_eta + right_eta + risk
            if idx > 0:
                matrix[idx, idx - 1] = -left_eta
            if idx < n - 2:
                matrix[idx, idx + 1] = -right_eta
            if k == 1:
                rhs[idx] += left_eta * inventory
        q[1:n] = np.linalg.solve(matrix, rhs)
    q[-1] = 0.0  # hard equality invariant, not a numerical tolerance check
    trade_schedule = q[:-1] - q[1:]
    toxicity_prob = float(-math.expm1(-intensity * tau))
    return {
        "terminal_inventory": 0.0,
        "inventory_path": q,
        "trade_schedule": trade_schedule,
        "toxicity_prob": toxicity_prob,
        "toxicity_action": "RETREAT" if toxicity_prob > 0.60 else "CONTINUE_PAPER",
        "objective_discrete": float(np.sum(eta_k * trade_schedule ** 2)
                                     + risk * np.sum(q[:-1] ** 2)),
    }


# ---------- Offline snapshot position/cash stress ----------
def stress_test_positions(
    positions: Sequence[Mapping[str, Any]],
    available_funds_inr: float,
    price_shocks: Mapping[str, Any] | None = None,
    liquidity_haircut: float = 0.20,
) -> dict[str, Any]:
    """Stress operator-supplied positions, never fetches a broker account.

    Position keys: quantity (signed), underlying (or symbol), underlying_price, delta,
    optional gamma, multiplier (or lot_size), mark_price (or price), and is_illiquid.
    Shock map values can be a scalar return or a nonempty sequence of return scenarios.
    With price_shocks=None, each named underlying receives both -3% and +3% cases and
    the worst aggregate scenario is selected. Illiquid-leg haircut is deducted once.
    """
    if isinstance(positions, (str, bytes)) or not isinstance(positions, Sequence):
        raise ValueError("positions must be a sequence of mapping snapshots")
    funds = _finite_float("available_funds_inr", available_funds_inr, minimum=0.0)
    haircut = _finite_float("liquidity_haircut", liquidity_haircut, minimum=0.0)
    if haircut > 1.0:
        raise ValueError("liquidity_haircut must be <= 1")
    clean: list[dict[str, Any]] = []
    symbols: list[str] = []
    haircut_loss = 0.0
    gross_exposure = 0.0
    for idx, item in enumerate(positions):
        if not isinstance(item, Mapping):
            raise ValueError(f"positions[{idx}] must be a mapping")
        qty = _finite_float(f"positions[{idx}].quantity", item.get("quantity", 0.0))
        symbol = str(item.get("underlying", item.get("symbol", "UNKNOWN"))).strip() or "UNKNOWN"
        mark = _finite_float(f"positions[{idx}].mark_price", item.get("mark_price", item.get("price", 0.0)), minimum=0.0)
        underlying_price = _finite_float(f"positions[{idx}].underlying_price", item.get("underlying_price", mark), minimum=0.0)
        delta = _finite_float(f"positions[{idx}].delta", item.get("delta", 1.0))
        gamma = _finite_float(f"positions[{idx}].gamma", item.get("gamma", 0.0))
        multiplier = _finite_float(f"positions[{idx}].multiplier", item.get("multiplier", item.get("lot_size", 1.0)), minimum=0.0)
        illiquid_value = item.get("is_illiquid", item.get("illiquid", False))
        if not isinstance(illiquid_value, (bool, np.bool_)):
            raise ValueError(f"positions[{idx}].is_illiquid must be boolean")
        clean.append({"quantity": qty, "symbol": symbol, "mark": mark,
                      "underlying_price": underlying_price, "delta": delta,
                      "gamma": gamma, "multiplier": multiplier,
                      "is_illiquid": bool(illiquid_value)})
        symbols.append(symbol)
        gross_exposure += abs(qty * multiplier * underlying_price * delta)
        if illiquid_value:
            haircut_loss += abs(qty * multiplier * mark) * haircut

    unique_symbols = sorted(set(symbols))
    if len(unique_symbols) > 12:
        raise ValueError("at most 12 distinct underlying symbols are supported for exhaustive +/- scenarios")
    shock_options: dict[str, tuple[float, ...]] = {}
    if price_shocks is None:
        shock_options = {sym: (-0.03, 0.03) for sym in unique_symbols}
    else:
        if not isinstance(price_shocks, Mapping):
            raise ValueError("price_shocks must be a mapping from underlying symbol to return scenario(s)")
        for sym in unique_symbols:
            raw = price_shocks.get(sym, (-0.03, 0.03))
            if isinstance(raw, (str, bytes)):
                raise ValueError(f"price_shocks[{sym}] must be numeric or a numeric sequence")
            if isinstance(raw, Sequence) or isinstance(raw, np.ndarray):
                vals = tuple(_finite_float(f"price_shocks[{sym}] item", v) for v in raw)
                if not vals:
                    raise ValueError(f"price_shocks[{sym}] cannot be empty")
            else:
                vals = (_finite_float(f"price_shocks[{sym}]", raw),)
            shock_options[sym] = vals

    if unique_symbols:
        scenario_rows = itertools.product(*(shock_options[sym] for sym in unique_symbols))
        worst_pnl = math.inf
        worst_scenario: dict[str, float] = {}
        scenarios_evaluated = 0
        symbol_index = {s: i for i, s in enumerate(unique_symbols)}
        for row in scenario_rows:
            scenario = dict(zip(unique_symbols, row))
            pnl = 0.0
            for pos in clean:
                shock = scenario[pos["symbol"]]
                d_s = pos["underlying_price"] * shock
                pnl += pos["quantity"] * pos["multiplier"] * (
                    pos["delta"] * d_s + 0.5 * pos["gamma"] * d_s * d_s
                )
            scenarios_evaluated += 1
            if pnl < worst_pnl:
                worst_pnl = pnl
                worst_scenario = scenario
    else:
        worst_pnl = 0.0
        worst_scenario = {}
        scenarios_evaluated = 1

    stress_pnl = float(worst_pnl - haircut_loss)
    stressed_funds = float(funds + stress_pnl)
    return {
        "stress_pnl_inr": stress_pnl,
        "stressed_funds_inr": stressed_funds,
        "gross_exposure_inr": float(gross_exposure),
        "source_mode": "operator_supplied_offline_snapshot",
        "margin_call_triggered": bool(stressed_funds < 0.0),
        "liquidity_haircut_loss_inr": float(haircut_loss),
        "worst_shock_scenario": worst_scenario,
        "scenarios_evaluated": scenarios_evaluated,
    }


# ---------- Configured Indian fee schedule, alpha gate, Bayesian Kelly ----------
def indian_statutory_fees(
    buy_turnover_inr: float,
    sell_turnover_inr: float,
    executed_legs: int = 0,
) -> dict[str, Any]:
    """Fee model using Cycle 66 operator-specified rates, not a legal-rate assertion."""
    buy = _finite_float("buy_turnover_inr", buy_turnover_inr, minimum=0.0)
    sell = _finite_float("sell_turnover_inr", sell_turnover_inr, minimum=0.0)
    if isinstance(executed_legs, bool) or not isinstance(executed_legs, (int, np.integer)) or int(executed_legs) < 0:
        raise ValueError("executed_legs must be a nonnegative integer")
    legs = int(executed_legs)
    stt = sell * 0.0015
    stamp = buy * 0.00003
    exchange = (buy + sell) * 0.0003553
    sebi = (buy + sell) * 0.000001
    brokerage = 20.0 * legs
    gst = 0.18 * (brokerage + exchange + sebi)
    breakdown = {
        "stt_sell_premium_inr": stt,
        "stamp_duty_buy_inr": stamp,
        "nse_transaction_fee_inr": exchange,
        "sebi_fee_inr": sebi,
        "brokerage_inr": brokerage,
        "gst_inr": gst,
    }
    total = float(sum(breakdown.values()))
    return {"total_fees_inr": total, "breakdown": breakdown,
            "rates": {"stt_sell": 0.0015, "stamp_buy": 0.00003,
                      "nse_transaction": 0.0003553, "sebi": 0.000001,
                      "brokerage_per_leg_inr": 20.0, "gst": 0.18}}


def net_alpha_gate(expected_gross_alpha_inr: float, total_fees_inr: float) -> dict[str, Any]:
    gross = _finite_float("expected_gross_alpha_inr", expected_gross_alpha_inr)
    fees = _finite_float("total_fees_inr", total_fees_inr, minimum=0.0)
    net = gross - fees
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
) -> dict[str, Any]:
    """Beta-Bernoulli posterior win rate and conservatively capped fractional Kelly."""
    a = _finite_float("alpha_prior", alpha_prior, minimum=0.0, strict_minimum=True)
    b = _finite_float("beta_prior", beta_prior, minimum=0.0, strict_minimum=True)
    if isinstance(wins, bool) or not isinstance(wins, (int, np.integer)) or int(wins) < 0:
        raise ValueError("wins must be a nonnegative integer")
    if isinstance(losses, bool) or not isinstance(losses, (int, np.integer)) or int(losses) < 0:
        raise ValueError("losses must be a nonnegative integer")
    ratio = _finite_float("win_loss_ratio", win_loss_ratio, minimum=0.0, strict_minimum=True)
    scale = _finite_float("scale", scale, minimum=0.0)
    cap = _finite_float("cap", cap, minimum=0.0)
    if cap > 1.0:
        raise ValueError("cap must be <= 1.0")
    if not isinstance(net_alpha_positive, (bool, np.bool_)):
        raise ValueError("net_alpha_positive must be boolean")
    posterior = (a + int(wins)) / (a + b + int(wins) + int(losses))
    raw_kelly = posterior - (1.0 - posterior) / ratio
    effective_cap = min(cap, 0.10)
    fraction = min(effective_cap, max(0.0, scale * raw_kelly)) if net_alpha_positive else 0.0
    return {"capital_fraction": float(fraction),
            "posterior_win_probability": float(posterior),
            "raw_kelly_fraction": float(raw_kelly),
            "effective_cap": float(effective_cap)}


# ---------- Four-agent consensus and hard paper-only guard ----------
def squad_consensus(
    agent_votes: Mapping[str, bool],
    manager_live_veto: bool = True,
    require_unanimous: bool = True,
    risk_gates_passed: bool = True,
) -> dict[str, Any]:
    required = ("Abhi", "Alex", "Emily", "Max")
    if not isinstance(agent_votes, Mapping):
        raise ValueError("agent_votes must be a mapping")
    missing = [name for name in required if name not in agent_votes]
    if missing:
        raise ValueError(f"missing required agent vote(s): {', '.join(missing)}")
    votes: dict[str, bool] = {}
    for name in required:
        if not isinstance(agent_votes[name], (bool, np.bool_)):
            raise ValueError(f"agent vote for {name} must be boolean")
        votes[name] = bool(agent_votes[name])
    for name, val in (("manager_live_veto", manager_live_veto),
                      ("require_unanimous", require_unanimous),
                      ("risk_gates_passed", risk_gates_passed)):
        if not isinstance(val, (bool, np.bool_)):
            raise ValueError(f"{name} must be boolean")
    yes_count = sum(votes.values())
    votes_pass = all(votes.values()) if require_unanimous else (votes["Abhi"] and yes_count >= 3)
    research_approved = bool(votes_pass and risk_gates_passed)
    return {
        "paper_research_approved": research_approved,
        "live_order_dispatch_enabled": False,
        "real_broker_fills_locked": True,
        "paper_ledger_epoch": PAPER_LEDGER_EPOCH,
        "manager_live_veto_active": bool(manager_live_veto),
        "risk_gates_passed": bool(risk_gates_passed),
        "votes": votes,
        "affirmative_votes": int(yes_count),
    }


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Permanent fail-closed guard. This intentionally has no live pathway."""
    raise PermissionError("Cycle 66 is paper-only: live order dispatch is permanently disabled")

"""Cycle 65 DNSDE-MLT reference execution engine.

Dependencies: Python standard library and NumPy. Paper research only; no broker IO.
"""
from __future__ import annotations

import itertools
import math
from typing import Any, Mapping, Sequence

import numpy as np

CYCLE_ID = "65"
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
MIN_COVARIANCE_EIGENVALUE = 1.0e-6
MAX_KELLY_CAPITAL_FRACTION = 0.10
REQUIRED_AGENTS = ("Abhi", "Alex", "Emily", "Max")
INDEX_NAMES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")


def _finite_array(value: Any, name: str, *, ndim: int | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must be {ndim}-dimensional")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite numbers")
    return arr


def _nonnegative(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


def _positive(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def _network_spec(spec: Any, name: str) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Normalize weights into sequential dense layers and optional biases."""
    if isinstance(spec, Mapping):
        raw_weights = spec.get("weights")
        raw_biases = spec.get("biases")
        if raw_weights is None:
            raise ValueError(f"{name} mapping must include 'weights'")
    else:
        raw_weights = spec
        raw_biases = None
    if isinstance(raw_weights, np.ndarray):
        raw_layers = [raw_weights]
    elif isinstance(raw_weights, (tuple, list)):
        raw_layers = list(raw_weights)
    else:
        raise ValueError(f"{name} must be a 2-D matrix or sequence of 2-D matrices")
    if not raw_layers:
        raise ValueError(f"{name} must contain at least one layer")
    layers = [_finite_array(w, f"{name} layer {i}", ndim=2).copy() for i, w in enumerate(raw_layers)]
    for i in range(1, len(layers)):
        if layers[i].shape[1] != layers[i - 1].shape[0]:
            raise ValueError(f"{name} layer dimensions do not compose")
    if raw_biases is None:
        biases = [np.zeros(w.shape[0], dtype=float) for w in layers]
    else:
        if len(raw_biases) != len(layers):
            raise ValueError(f"{name} biases must match layer count")
        biases = [_finite_array(b, f"{name} bias {i}", ndim=1).copy() for i, b in enumerate(raw_biases)]
        for i, (b, w) in enumerate(zip(biases, layers)):
            if b.shape[0] != w.shape[0]:
                raise ValueError(f"{name} bias {i} has wrong length")
    return layers, biases


def _spectrally_clip(layers: list[np.ndarray], lipschitz_limit: float) -> tuple[list[np.ndarray], float]:
    """Clip each matrix's spectral norm to L**(1/n); tanh layers are 1-Lipschitz."""
    n = len(layers)
    per_layer_limit = lipschitz_limit ** (1.0 / n)
    clipped: list[np.ndarray] = []
    product_bound = 1.0
    for layer in layers:
        norm = float(np.linalg.norm(layer, ord=2)) if layer.size else 0.0
        if norm > per_layer_limit and norm > 0.0:
            layer = layer * (per_layer_limit / norm)
            norm = per_layer_limit
        clipped.append(layer)
        product_bound *= norm
    return clipped, product_bound


def _forward_network(x: np.ndarray, layers: Sequence[np.ndarray], biases: Sequence[np.ndarray]) -> np.ndarray:
    h = np.asarray(x, dtype=float)
    for w, b in zip(layers, biases):
        h = np.tanh(w @ h + b)
    return h


def _signal_at(signals: Any, step: int, n_steps: int) -> np.ndarray:
    arr = _finite_array(signals, "mlofi_signals")
    if arr.ndim == 0:
        return np.asarray([float(arr)])
    if arr.ndim == 1:
        # A vector of length n_steps is a scalar time series; otherwise it is a fixed feature vector.
        if arr.shape[0] == n_steps:
            return np.asarray([float(arr[step])])
        return arr.copy()
    if arr.ndim == 2:
        if arr.shape[0] < n_steps:
            raise ValueError("mlofi_signals 2-D input must have at least n_steps rows")
        return arr[step].reshape(-1).copy()
    raise ValueError("mlofi_signals must be scalar, 1-D or 2-D")


def _softplus(x: np.ndarray) -> np.ndarray:
    # Numerically stable softplus.
    return np.maximum(x, 0.0) + np.log1p(np.exp(-np.abs(x)))


def simulate_dnsde(
    initial_state: Any,
    drift_weights: Any,
    diffusion_weights: Any,
    mlofi_signals: Any,
    n_steps: int = 50,
    dt: float = 0.01,
    lambda_jump: Any = 0.1,
    jump_scale: float = 0.02,
    lipschitz_limit: float = 1.5,
) -> dict[str, Any]:
    """Simulate an Euler--Maruyama latent path with marked Poisson jumps.

    ``drift_weights`` is a dense layer matrix or list of matrices. The first layer
    consumes [state, normalized_time, MLOFI features]; the output width equals
    state dimension. ``diffusion_weights`` consumes [state, normalized_time] and
    outputs either d diagonal logits or d(d+1)/2 lower-triangular logits. Network
    activations are tanh; weights are clipped to satisfy the requested global bound.

    ``lambda_jump`` may be a nonnegative scalar or a precomputed nonnegative intensity
    path of length ``n_steps`` (e.g. from an external Hawkes filter). A local NumPy
    generator with seed 0 makes the specified signature reproducible. The covariance is regularized as L L^T + 1e-6 I before its Cholesky factor is
    used, yielding a minimum eigenvalue at least 1e-6 (up to floating-point error).
    """
    x0 = _finite_array(initial_state, "initial_state", ndim=1)
    dim = x0.size
    if dim == 0:
        raise ValueError("initial_state must be non-empty")
    if not isinstance(n_steps, (int, np.integer)) or isinstance(n_steps, bool) or n_steps < 1:
        raise ValueError("n_steps must be a positive integer")
    dt = _positive(dt, "dt")
    if np.isscalar(lambda_jump):
        intensity_path = np.full(int(n_steps), _nonnegative(float(lambda_jump), "lambda_jump"), dtype=float)
    else:
        intensity_path = _finite_array(lambda_jump, "lambda_jump", ndim=1)
        if intensity_path.shape != (int(n_steps),) or np.any(intensity_path < 0.0):
            raise ValueError("lambda_jump path must have shape (n_steps,) and nonnegative intensities")
    if not np.all(np.isfinite(intensity_path * dt)):
        raise ValueError("lambda_jump * dt must remain finite")
    jump_scale = _nonnegative(jump_scale, "jump_scale")
    lipschitz_limit = _positive(lipschitz_limit, "lipschitz_limit")

    drift_layers, drift_biases = _network_spec(drift_weights, "drift_weights")
    diff_layers, diff_biases = _network_spec(diffusion_weights, "diffusion_weights")
    drift_layers, lipschitz_bound = _spectrally_clip(drift_layers, lipschitz_limit)
    if drift_layers[-1].shape[0] != dim:
        raise ValueError("last drift layer output width must equal state dimension")
    if diff_layers[-1].shape[0] not in (dim, dim * (dim + 1) // 2):
        raise ValueError("last diffusion layer width must be dim or dim*(dim+1)//2")

    # Validate signal dimensionality before entering the loop.
    sig0 = _signal_at(mlofi_signals, 0, int(n_steps))
    if drift_layers[0].shape[1] != dim + 1 + sig0.size:
        raise ValueError("first drift layer input width must be dim + 1 + MLOFI feature count")
    if diff_layers[0].shape[1] != dim + 1:
        raise ValueError("first diffusion layer input width must be dim + 1")

    trajectory = np.empty((int(n_steps) + 1, dim), dtype=float)
    drift_path = np.empty((int(n_steps), dim), dtype=float)
    diffusion_path = np.empty((int(n_steps), dim, dim), dtype=float)
    trajectory[0] = x0
    rng = np.random.default_rng(0)
    jumps_total = 0
    tri_i, tri_j = np.tril_indices(dim)
    time_scale = max(1, int(n_steps) - 1)

    for k in range(int(n_steps)):
        x = trajectory[k]
        t_norm = np.asarray([k / time_scale], dtype=float)
        signal = _signal_at(mlofi_signals, k, int(n_steps))
        drift_input = np.concatenate((x, t_norm, signal))
        drift = _forward_network(drift_input, drift_layers, drift_biases)
        diff_input = np.concatenate((x, t_norm))
        raw = _forward_network(diff_input, diff_layers, diff_biases)
        if raw.size == dim:
            lower = np.diag(_softplus(raw))
        else:
            lower = np.zeros((dim, dim), dtype=float)
            lower[tri_i, tri_j] = raw
            diag_idx = np.diag_indices(dim)
            lower[diag_idx] = _softplus(lower[diag_idx])
        covariance = lower @ lower.T + MIN_COVARIANCE_EIGENVALUE * np.eye(dim)
        try:
            diffusion = np.linalg.cholesky(covariance)
        except np.linalg.LinAlgError as exc:  # defensive guard against corrupted numerics
            raise FloatingPointError("regularized diffusion covariance was not positive definite") from exc
        if not np.all(np.isfinite(drift)) or not np.all(np.isfinite(diffusion)):
            raise FloatingPointError("DNSDE produced non-finite drift or diffusion")
        count = int(rng.poisson(float(intensity_path[k]) * dt))
        jumps_total += count
        # Sum independent jump marks; compound-Poisson variance scales with count,
        # not count squared.
        jump_mark = jump_scale * rng.normal(size=(count, dim)).sum(axis=0) if count else np.zeros(dim)
        drift_path[k] = drift
        diffusion_path[k] = diffusion
        trajectory[k + 1] = x + drift * dt + diffusion @ (math.sqrt(dt) * rng.normal(size=dim)) + jump_mark

    return {
        "trajectory": trajectory,
        "drift_path": drift_path,
        "diffusion_path": diffusion_path,
        "jumps_occurred": jumps_total,
        "lipschitz_verified": bool(lipschitz_bound <= lipschitz_limit + 1.0e-12),
        "lipschitz_bound": float(lipschitz_bound),
        "covariance_min_eigenvalue_floor": MIN_COVARIANCE_EIGENVALUE,
    }


def _logsumexp(a: np.ndarray, axis: int) -> np.ndarray:
    a_max = np.max(a, axis=axis, keepdims=True)
    # If all inputs are -inf, preserve -inf; the transport inputs here have finite costs.
    out = a_max + np.log(np.sum(np.exp(a - a_max), axis=axis, keepdims=True))
    return np.squeeze(out, axis=axis)


def optimal_liquidity_transport(
    source_depths: Any,
    target_profile: Any,
    cost_matrix: Any = None,
    epsilon: float = 0.05,
    max_iter: int = 200,
    tol: float = 1.0e-6,
) -> dict[str, Any]:
    """Entropy-regularized discrete W2-like transport using log-domain Sinkhorn.

    Source and target vectors are nonnegative masses and are normalized to sum 1.
    The default cost is squared distance between uniformly spaced normalized level
    coordinates; callers can pass a full cost matrix incorporating prices/penalties.
    ``transport_cost`` reports the unregularized linear cost <C, pi>, not the entropy term.
    Convergence is explicitly reported: a caller that supplies too few iterations or
    an extreme cost/epsilon ratio must not treat a non-converged plan as certified.
    """
    src = _finite_array(source_depths, "source_depths", ndim=1)
    tgt = _finite_array(target_profile, "target_profile", ndim=1)
    if src.size == 0 or tgt.size == 0:
        raise ValueError("source_depths and target_profile must be non-empty")
    if np.any(src < 0.0) or np.any(tgt < 0.0):
        raise ValueError("depth masses must be nonnegative")
    if float(src.sum()) <= 0.0 or float(tgt.sum()) <= 0.0:
        raise ValueError("each depth distribution must have positive total mass")
    epsilon = _positive(epsilon, "epsilon")
    tol = _positive(tol, "tol")
    if not isinstance(max_iter, (int, np.integer)) or isinstance(max_iter, bool) or max_iter < 1:
        raise ValueError("max_iter must be a positive integer")
    a = src / src.sum()
    b = tgt / tgt.sum()
    n, m = a.size, b.size
    if cost_matrix is None:
        x = np.linspace(0.0, 1.0, n) if n > 1 else np.asarray([0.0])
        y = np.linspace(0.0, 1.0, m) if m > 1 else np.asarray([0.0])
        c = (x[:, None] - y[None, :]) ** 2
    else:
        c = _finite_array(cost_matrix, "cost_matrix", ndim=2)
        if c.shape != (n, m):
            raise ValueError("cost_matrix shape must be (len(source_depths), len(target_profile))")
        if np.any(c < 0.0):
            raise ValueError("cost_matrix entries must be nonnegative")
    log_a = np.log(a, where=a > 0.0, out=np.full_like(a, -np.inf))
    log_b = np.log(b, where=b > 0.0, out=np.full_like(b, -np.inf))
    u = np.zeros(n, dtype=float)
    v = np.zeros(m, dtype=float)
    plan = np.zeros((n, m), dtype=float)
    err_source = math.inf
    err_target = math.inf
    converged = False

    for iteration in range(1, int(max_iter) + 1):
        u = epsilon * (log_a - _logsumexp((v[None, :] - c) / epsilon, axis=1))
        v = epsilon * (log_b - _logsumexp((u[:, None] - c) / epsilon, axis=0))
        log_plan = (u[:, None] + v[None, :] - c) / epsilon
        plan = np.exp(np.clip(log_plan, -745.0, 700.0))
        row = plan.sum(axis=1)
        col = plan.sum(axis=0)
        err_source = float(np.sum(np.abs(row - a)))
        err_target = float(np.sum(np.abs(col - b)))
        if max(err_source, err_target) <= tol:
            converged = True
            break

    return {
        "transport_plan": plan,
        "transport_cost": float(np.sum(c * plan)),
        "marginal_error_source": err_source,
        "marginal_error_target": err_target,
        "convergence": bool(converged),
        "iterations": iteration,
        "source_marginal": a.copy(),
        "target_marginal": b.copy(),
    }


def almgren_chriss_unwind(
    inventory: float,
    horizon_steps: int = 10,
    eta: float = 0.1,
    gamma_decay: float = 0.5,
    sigma: float = 0.01,
    lambda_risk: float = 1.0e-4,
    intensity: float = 0.0,
    tau: float = 1.0,
) -> dict[str, Any]:
    """Solve a discrete convex quadratic unwind with exact terminal inventory zero.

    For q_0=inventory and q_H=0, minimize
      sum_k eta_k (q_{k+1}-q_k)^2 + lambda_risk*sigma^2*q_{k+1}^2,
    where eta_k=eta*exp(-gamma_decay*k/(H-1)). The linear permanent-impact term
    in the usual fixed-total Almgren--Chriss model is constant across schedules and
    therefore does not alter this optimizer. A tridiagonal positive-definite system
    solves the interior q values, and q_H is assigned exactly 0.0.
    """
    inventory = float(inventory)
    if not math.isfinite(inventory):
        raise ValueError("inventory must be finite")
    if not isinstance(horizon_steps, (int, np.integer)) or isinstance(horizon_steps, bool) or horizon_steps < 1:
        raise ValueError("horizon_steps must be a positive integer")
    eta = _positive(eta, "eta")
    gamma_decay = _nonnegative(gamma_decay, "gamma_decay")
    sigma = _nonnegative(sigma, "sigma")
    lambda_risk = _nonnegative(lambda_risk, "lambda_risk")
    intensity = _nonnegative(intensity, "intensity")
    tau = _nonnegative(tau, "tau")
    h = int(horizon_steps)
    q = np.empty(h + 1, dtype=float)
    q[0] = inventory
    q[-1] = 0.0
    risk_weight = lambda_risk * sigma * sigma
    weights = eta * np.exp(-gamma_decay * np.arange(h, dtype=float) / max(1, h - 1))
    if h == 1:
        q[1] = 0.0
    else:
        # Unknowns are q[1] ... q[h-1]. Hessian is tridiagonal and strictly PD.
        n = h - 1
        mat = np.zeros((n, n), dtype=float)
        rhs = np.zeros(n, dtype=float)
        for j in range(n):
            k = j + 1  # state q[k]
            left_w = weights[k - 1]
            right_w = weights[k] if k < h else 0.0
            mat[j, j] = left_w + right_w + risk_weight
            if j > 0:
                mat[j, j - 1] = -left_w
            if j < n - 1:
                mat[j, j + 1] = -right_w
            if k == 1:
                rhs[j] = left_w * inventory
        try:
            q[1:h] = np.linalg.solve(mat, rhs)
        except np.linalg.LinAlgError as exc:
            raise FloatingPointError("unwind optimization system was singular") from exc
        q[-1] = 0.0
    trades = q[:-1] - q[1:]
    toxicity_prob = float(-math.expm1(-intensity * tau))
    toxicity_prob = min(1.0, max(0.0, toxicity_prob))
    return {
        "terminal_inventory": 0.0,
        "inventory_path": q.tolist(),
        "trade_schedule": trades.tolist(),
        "toxicity_prob": toxicity_prob,
        "toxicity_action": "RETREAT" if toxicity_prob > 0.60 else "CONTINUE_PAPER",
        "objective_value": float(np.sum(weights * (trades ** 2)) + risk_weight * np.sum(q[1:] ** 2)),
    }


def _normalise_index(value: Any) -> str | None:
    token = str(value).upper().replace(" ", "").replace("-", "").replace("_", "")
    aliases = {
        "NIFTY": "NIFTY", "NIFTY50": "NIFTY", "NIFTY50INDEX": "NIFTY",
        "BANKNIFTY": "BANKNIFTY", "BANKNIFTYINDEX": "BANKNIFTY",
        "FINNIFTY": "FINNIFTY", "MIDCPNIFTY": "MIDCPNIFTY",
    }
    for key, canonical in aliases.items():
        if token == key or token.startswith(key):
            return canonical
    return None


def _position_sign(record: Mapping[str, Any], quantity: float) -> float:
    side = str(record.get("side", record.get("transaction_type", ""))).strip().upper()
    if side in ("BUY", "B", "LONG"):
        return abs(quantity)
    if side in ("SELL", "S", "SHORT"):
        return -abs(quantity)
    return quantity


def stress_test_positions(
    positions: Any,
    available_funds_inr: float,
    price_shocks: Mapping[str, float] | None = None,
    liquidity_haircut: float = 0.20,
) -> dict[str, Any]:
    """Stress an operator-supplied offline snapshot; never logs into a broker.

    Each position mapping may provide: ``symbol``/``underlying``, ``quantity`` (or
    ``net_quantity``), ``side``, ``price`` and ``multiplier``; optionally ``delta``
    and ``underlying_price`` for delta-based P&L, ``market_value_inr`` as a notional
    fallback, ``instrument_type='option'``, ``illiquid=True`` and
    ``margin_required_inr``. Without Greeks, percentage shocks are a linear notional
    proxy, not a full option valuation. With no explicit shocks, all +/-3% combinations
    across indices represented in the snapshot are considered and the worst P&L used.
    """
    available = float(available_funds_inr)
    if not math.isfinite(available):
        raise ValueError("available_funds_inr must be finite")
    liquidity_haircut = _nonnegative(liquidity_haircut, "liquidity_haircut")
    if liquidity_haircut > 1.0:
        raise ValueError("liquidity_haircut cannot exceed 1")
    if isinstance(positions, Mapping):
        raw = positions.get("positions", positions.get("data"))
        if raw is None:
            raise ValueError("position mapping must contain 'positions' or 'data'")
        positions = raw
    if not isinstance(positions, (tuple, list)):
        raise ValueError("positions must be a sequence of mappings or a snapshot mapping")

    rows: list[dict[str, Any]] = []
    gross = 0.0
    margin_required = 0.0
    haircut_cost = 0.0
    held_indices: list[str] = []
    for idx, record in enumerate(positions):
        if not isinstance(record, Mapping):
            raise ValueError(f"position {idx} must be a mapping")
        underlying = _normalise_index(record.get("underlying", record.get("symbol", "")))
        if underlying is None:
            # For typical contract labels, look for an index name embedded in symbol.
            symbol = str(record.get("symbol", "")).upper().replace(" ", "")
            for candidate in INDEX_NAMES:
                if candidate in symbol:
                    underlying = candidate
                    break
        if underlying is not None and underlying not in held_indices:
            held_indices.append(underlying)
        quantity = float(record.get("quantity", record.get("net_quantity", 0.0)))
        if not math.isfinite(quantity):
            raise ValueError(f"position {idx} quantity must be finite")
        signed_qty = _position_sign(record, quantity)
        price = float(record.get("price", record.get("market_price", record.get("average_price", 0.0))))
        multiplier = float(record.get("multiplier", record.get("lot_size", 1.0)))
        market_value = float(record.get("market_value_inr", record.get("market_value", abs(signed_qty * price * multiplier))))
        underlying_price = float(record.get("underlying_price", 0.0))
        delta = record.get("delta")
        margin = float(record.get("margin_required_inr", 0.0))
        for val, label in ((price, "price"), (multiplier, "multiplier"), (market_value, "market_value"), (underlying_price, "underlying_price"), (margin, "margin_required_inr")):
            if not math.isfinite(val) or (label in ("multiplier", "market_value", "margin_required_inr") and val < 0.0):
                raise ValueError(f"position {idx} has invalid {label}")
        if delta is not None:
            delta = float(delta)
            if not math.isfinite(delta):
                raise ValueError(f"position {idx} delta must be finite")
        instrument_type = str(record.get("instrument_type", record.get("product_type", ""))).lower()
        is_option = "option" in instrument_type or bool(record.get("is_option", False))
        illiquid = bool(record.get("illiquid", not bool(record.get("liquid", True))))
        if is_option and illiquid:
            haircut_cost += abs(market_value) * liquidity_haircut
        gross += abs(market_value)
        margin_required += margin
        rows.append({
            "underlying": underlying or "OTHER", "signed_qty": signed_qty,
            "multiplier": multiplier, "market_value": abs(market_value),
            "underlying_price": underlying_price, "delta": delta, "margin": margin,
        })

    explicit = price_shocks is not None
    if explicit:
        if not isinstance(price_shocks, Mapping):
            raise ValueError("price_shocks must be a mapping from index to fractional shock")
        normalized_shocks: dict[str, float] = {}
        for key, value in price_shocks.items():
            index = _normalise_index(key)
            if index is None:
                raise ValueError(f"unsupported index in price_shocks: {key}")
            shock = float(value)
            if not math.isfinite(shock) or abs(shock) > 1.0:
                raise ValueError("price shocks must be finite fractional changes with absolute value <= 1")
            normalized_shocks[index] = shock
        scenarios = [normalized_shocks]
    elif held_indices:
        scenarios = [dict(zip(held_indices, combo)) for combo in itertools.product((-0.03, 0.03), repeat=len(held_indices))]
    else:
        scenarios = [{}]

    scenario_pnls: list[tuple[float, dict[str, float]]] = []
    for shocks in scenarios:
        pnl = 0.0
        for row in rows:
            shock = float(shocks.get(row["underlying"], 0.0))
            delta = row["delta"]
            if delta is not None and row["underlying_price"] > 0.0:
                pnl += row["signed_qty"] * row["multiplier"] * delta * row["underlying_price"] * shock
            else:
                # Transparent linear proxy for supplied notional if Greeks are absent.
                signed_exposure = math.copysign(row["market_value"], row["signed_qty"]) if row["signed_qty"] != 0.0 else 0.0
                pnl += signed_exposure * shock
        pnl -= haircut_cost
        scenario_pnls.append((pnl, dict(shocks)))
    stress_pnl, worst_shocks = min(scenario_pnls, key=lambda item: item[0])
    stressed_funds = available + stress_pnl
    return {
        "stress_pnl_inr": float(stress_pnl),
        "stressed_funds_inr": float(stressed_funds),
        "gross_exposure_inr": float(gross),
        "source_mode": "operator_supplied_offline_snapshot",
        "margin_call_triggered": bool(stressed_funds < margin_required),
        "worst_case_price_shocks": worst_shocks,
        "liquidity_haircut_cost_inr": float(haircut_cost),
        "margin_required_inr": float(margin_required),
        "scenario_count": len(scenarios),
    }


def indian_statutory_fees(
    buy_turnover_inr: float,
    sell_turnover_inr: float,
    executed_legs: int = 0,
) -> dict[str, Any]:
    """Calculate the Cycle 65 configured fee schedule, in INR.

    Rates are explicit configurable assumptions from the specification, not a claim
    that this frozen schedule supersedes a broker contract note or future regulations.
    Each component and final total are rounded to paise for a deterministic ledger.
    """
    buy = _nonnegative(buy_turnover_inr, "buy_turnover_inr")
    sell = _nonnegative(sell_turnover_inr, "sell_turnover_inr")
    if not isinstance(executed_legs, (int, np.integer)) or isinstance(executed_legs, bool) or executed_legs < 0:
        raise ValueError("executed_legs must be a nonnegative integer")
    stt = round(sell * 0.0015, 2)
    stamp = round(buy * 0.00003, 2)
    exchange = round((buy + sell) * 0.0003553, 2)
    sebi = round((buy + sell) * 0.000001, 2)
    brokerage = round(20.0 * int(executed_legs), 2)
    gst = round(0.18 * (brokerage + exchange + sebi), 2)
    breakdown = {
        "stt_sell_premium_inr": stt,
        "stamp_duty_buy_inr": stamp,
        "nse_transaction_fee_inr": exchange,
        "sebi_fee_inr": sebi,
        "brokerage_inr": brokerage,
        "gst_inr": gst,
    }
    total = round(sum(breakdown.values()), 2)
    return {"total_fees_inr": total, "breakdown": breakdown}


def net_alpha_gate(expected_gross_alpha_inr: float, total_fees_inr: float) -> dict[str, Any]:
    gross_alpha = float(expected_gross_alpha_inr)
    fees = _nonnegative(total_fees_inr, "total_fees_inr")
    if not math.isfinite(gross_alpha):
        raise ValueError("expected_gross_alpha_inr must be finite")
    net = gross_alpha - fees
    return {"approved": bool(net > 0.0), "net_alpha_inr": float(net)}


def beta_fractional_kelly(
    alpha_prior: float,
    beta_prior: float,
    wins: float,
    losses: float,
    win_loss_ratio: float,
    scale: float = 0.25,
    cap: float = 0.10,
    net_alpha_positive: bool = True,
) -> dict[str, Any]:
    """Posterior-Beta fractional Kelly fraction, clamped to [0, 10%]."""
    a = _positive(alpha_prior, "alpha_prior")
    b = _positive(beta_prior, "beta_prior")
    w = _nonnegative(wins, "wins")
    l = _nonnegative(losses, "losses")
    ratio = _positive(win_loss_ratio, "win_loss_ratio")
    scale = _nonnegative(scale, "scale")
    requested_cap = _nonnegative(cap, "cap")
    effective_cap = min(requested_cap, MAX_KELLY_CAPITAL_FRACTION)
    posterior_p = (a + w) / (a + b + w + l)
    full_kelly = max(0.0, posterior_p - (1.0 - posterior_p) / ratio)
    fraction = min(effective_cap, scale * full_kelly) if net_alpha_positive else 0.0
    return {
        "capital_fraction": float(min(MAX_KELLY_CAPITAL_FRACTION, max(0.0, fraction))),
        "posterior_win_probability": float(posterior_p),
        "full_kelly_fraction": float(full_kelly),
        "effective_cap": float(effective_cap),
    }


def squad_consensus(
    agent_votes: Mapping[str, Any],
    manager_live_veto: bool = True,
    require_unanimous: bool = True,
    risk_gates_passed: bool = True,
) -> dict[str, Any]:
    """Evaluate paper-research consensus; live dispatch can never be enabled here."""
    if not isinstance(agent_votes, Mapping):
        raise ValueError("agent_votes must be a mapping")
    missing = [name for name in REQUIRED_AGENTS if name not in agent_votes]
    if missing:
        raise ValueError(f"agent_votes missing required agents: {', '.join(missing)}")
    for name in REQUIRED_AGENTS:
        if not isinstance(agent_votes[name], (bool, np.bool_)):
            raise ValueError(f"agent vote for {name} must be boolean")
    votes = {name: bool(agent_votes[name]) for name in REQUIRED_AGENTS}
    all_yes = all(votes.values())
    majority = sum(votes.values()) >= 3
    abhi_approved = votes["Abhi"]  # capital/operator governance cannot be bypassed
    vote_gate = all_yes if require_unanimous else majority
    approved = bool(abhi_approved and vote_gate and risk_gates_passed)
    return {
        "paper_research_approved": approved,
        "live_order_dispatch_enabled": False,
        "manager_live_veto_active": bool(manager_live_veto),
        "risk_gates_passed": bool(risk_gates_passed),
        "agent_votes": votes,
        "unanimous": all_yes,
        "approval_reason": "approved for paper research" if approved else "paper research blocked by consensus/operator/risk gate",
    }


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Permanent fail-closed guard: Cycle 65 cannot send live broker orders."""
    raise PermissionError("Cycle 65 is paper-only: live order dispatch is permanently disabled")

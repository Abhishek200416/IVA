"""Cycle 64 HD-HV-GAT-TR research/reference engine.

Offline quantitative primitives only. No broker/network APIs are present.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
import math
import numpy as np
from scipy.optimize import linprog

CYCLE = 64
CYCLE_NAME = "HD-HV-GAT-TR"
INDEX_NODES = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
MAX_KELLY_FRACTION = 0.10
MAX_ATTENTION_SPECTRAL_RADIUS = 0.85
MAX_TOXICITY_PROBABILITY = 0.60

# Values requested for this cycle; confirm current applicability with a qualified
# tax/legal source before using for any real-world accounting.
FEE_SCHEDULE = {
    "stt_sell": 0.0015,
    "stamp_buy": 0.00003,
    "nse_transaction": 0.0003553,
    "sebi": 0.000001,
    "brokerage_per_leg_inr": 20.0,
    "gst": 0.18,
}


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Permanent fail-closed boundary: this package cannot dispatch live orders."""
    raise PermissionError("Cycle 64 is paper-only: live order dispatch is permanently disabled")


def _finite_array(value: Any, name: str, ndim: int | None = None) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must be {ndim}-dimensional")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def spectral_radius(matrix: Any) -> float:
    """Return max absolute eigenvalue for a finite square matrix."""
    a = _finite_array(matrix, "matrix", 2)
    if a.shape[0] != a.shape[1]:
        raise ValueError("matrix must be square")
    if a.size == 0:
        return 0.0
    vals = np.linalg.eigvals(a)
    return float(np.max(np.abs(vals)))


def _spectrally_scale_nonnegative(matrix: np.ndarray, bound: float) -> np.ndarray:
    if not (0.0 < bound < 1.0):
        raise ValueError("bound must be in (0, 1)")
    out = np.maximum(np.asarray(matrix, dtype=float), 0.0).copy()
    np.fill_diagonal(out, 0.0)
    rho = spectral_radius(out)
    if rho > bound and rho > 0.0:
        out *= bound / rho
    # Move a hair inside the boundary to absorb eigensolver rounding.
    rho2 = spectral_radius(out)
    if rho2 > bound:
        out *= (bound * (1.0 - 1e-12)) / rho2
    return out


def build_graph_attention(logits: Any, volterra_state: Any, adjacency: Any | None = None,
                          max_radius: float = MAX_ATTENTION_SPECTRAL_RADIUS) -> np.ndarray:
    """Build directed, volatility-conditioned, nonnegative attention weights.

    Volterra state shifts receiving-node logits. The resulting matrix is then
    scaled to satisfy the explicit subcritical spectral-radius constraint.
    """
    z = _finite_array(logits, "logits", 2)
    v = _finite_array(volterra_state, "volterra_state").reshape(-1)
    if z.shape[0] != z.shape[1] or z.shape[0] != len(v):
        raise ValueError("logits must be square and match the volatility-state length")
    n = len(v)
    if adjacency is None:
        adj = np.ones((n, n), dtype=bool)
        np.fill_diagonal(adj, False)
    else:
        adj_raw = _finite_array(adjacency, "adjacency", 2)
        if adj_raw.shape != z.shape or np.any(adj_raw < 0):
            raise ValueError("adjacency must be nonnegative and match logits shape")
        adj = adj_raw > 0
    np.fill_diagonal(adj, False)
    shifted = z + v[None, :]
    shifted = shifted - np.max(np.where(adj, shifted, -np.inf), axis=1, keepdims=True)
    weights = np.zeros_like(z)
    for i in range(n):
        mask = adj[i]
        if not np.any(mask):
            continue
        row = np.exp(np.clip(shifted[i, mask], -700.0, 0.0))
        row_sum = float(row.sum())
        if row_sum > 0:
            weights[i, mask] = row / row_sum
    return _spectrally_scale_nonnegative(weights, max_radius)


def rough_volterra_kernel(t: float, s: float, hurst: float) -> float:
    """K(t,s)=(t-s)^(H-1/2)/Gamma(H+1/2), for t>s and 0<H<0.5."""
    if not (0.0 < float(hurst) < 0.5):
        raise ValueError("hurst must be in (0, 0.5)")
    if not (math.isfinite(t) and math.isfinite(s)) or t <= s:
        raise ValueError("kernel requires finite t > s")
    d = t - s
    return float(d ** (hurst - 0.5) / math.gamma(hurst + 0.5))


def fractional_volterra_state(events: Sequence[float], times: Sequence[float], hurst: float,
                              amplitudes: Sequence[float] | None = None) -> np.ndarray:
    """Discretized causal Volterra state with events located at supplied times.

    Events are nonnegative impulse magnitudes. Only prior/equal event times are
    included; a small positive time gap avoids evaluating the singular diagonal.
    """
    ts = _finite_array(times, "times", 1)
    ev = _finite_array(events, "events", 1)
    if len(ts) != len(ev) or np.any(np.diff(ts) < 0) or np.any(ev < 0):
        raise ValueError("times/events must have equal lengths, sorted times and nonnegative events")
    amps = np.ones_like(ev) if amplitudes is None else _finite_array(amplitudes, "amplitudes", 1)
    if len(amps) != len(ev) or np.any(amps < 0):
        raise ValueError("amplitudes must be nonnegative and match events")
    out = np.zeros_like(ts)
    for i, t in enumerate(ts):
        for j in range(i):
            if ev[j] > 0:
                out[i] += ev[j] * amps[j] * rough_volterra_kernel(float(t), float(ts[j]), hurst)
    return out


def hawkes_network_intensity(base_intensity: Any, attention: Any, alpha: Any, beta: Any,
                             event_counts: Any, signed_mlofi: Any, gamma_ofi: float = 0.05,
                             max_radius: float = MAX_ATTENTION_SPECTRAL_RADIUS) -> np.ndarray:
    """Compute a discrete stable approximation to the four-node Hawkes intensity."""
    mu = _finite_array(base_intensity, "base_intensity", 1)
    a = _finite_array(attention, "attention", 2)
    al = _finite_array(alpha, "alpha", 2)
    be = _finite_array(beta, "beta", 2)
    ev = _finite_array(event_counts, "event_counts", 1)
    ofi = _finite_array(signed_mlofi, "signed_mlofi", 1)
    n = len(mu)
    if any(x.shape != (n, n) for x in (a, al, be)) or len(ev) != n or len(ofi) != n:
        raise ValueError("incompatible four-node dimensions")
    if np.any(mu <= 0) or np.any(al < 0) or np.any(be <= 0) or np.any(ev < 0):
        raise ValueError("base intensity/beta must be positive; alpha/events nonnegative")
    if not math.isfinite(gamma_ofi):
        raise ValueError("gamma_ofi must be finite")
    branching = a * al / be
    branching = _spectrally_scale_nonnegative(branching, max_radius)
    # Signed OFI may lower intensity, but intensity remains strictly nonnegative.
    return np.maximum(mu + branching @ ev + gamma_ofi * ofi, 1e-12)


@dataclass(frozen=True)
class TensorRingDecomposition:
    """Tensor-ring cores with scalar (rank-1) closure; equivalent to TT-SVD."""
    cores: tuple[np.ndarray, ...]
    original_shape: tuple[int, ...]
    relative_error: float
    original_frobenius_norm: float
    tolerance: float

    @property
    def ranks(self) -> tuple[int, ...]:
        if not self.cores:
            return ()
        return (1,) + tuple(int(c.shape[2]) for c in self.cores[:-1]) + (1,)


def _reconstruct_cores(cores: Sequence[np.ndarray]) -> np.ndarray:
    if not cores:
        raise ValueError("at least one core is required")
    acc = np.asarray(cores[0], dtype=float)
    if acc.shape[0] != 1:
        raise ValueError("first tensor-ring boundary rank must be 1")
    acc = acc[0, :, :]
    for core in cores[1:]:
        g = np.asarray(core, dtype=float)
        acc = np.tensordot(acc, g, axes=([-1], [0]))
    if acc.shape[-1] != 1:
        raise ValueError("last tensor-ring boundary rank must be 1")
    return np.squeeze(acc, axis=-1)


def tensor_ring_svd(tensor: Any, tolerance: float = 1e-6,
                    max_rank: int | None = None) -> TensorRingDecomposition:
    """Deterministic SVD rounding with an explicit reconstruction error certificate.

    For robust portability, the cyclic boundary bond is fixed to rank one, so
    the contraction is a closed-ring trace with a scalar boundary. The internal
    bonds use sequential SVD and form an open-boundary special case of a TR.
    If rank caps prevent the requested tolerance, the routine raises rather than
    silently claiming a guarantee.
    """
    x = _finite_array(tensor, "tensor")
    if x.ndim < 2 or any(d < 1 for d in x.shape):
        raise ValueError("tensor must have at least two nonempty dimensions")
    if not (math.isfinite(tolerance) and 0 < tolerance < 1):
        raise ValueError("tolerance must be in (0,1)")
    if max_rank is not None and max_rank < 1:
        raise ValueError("max_rank must be >= 1")
    shape = tuple(int(d) for d in x.shape)
    norm = float(np.linalg.norm(x.ravel()))
    if norm == 0.0:
        cores = [np.zeros((1, d, 1), dtype=float) for d in shape]
        return TensorRingDecomposition(tuple(cores), shape, 0.0, 0.0, tolerance)
    cores: list[np.ndarray] = []
    residual = x.copy()
    left_rank = 1
    local_budget = tolerance * norm / math.sqrt(max(1, x.ndim - 1))
    for mode, n in enumerate(shape[:-1]):
        mat = residual.reshape(left_rank * n, -1)
        u, s, vh = np.linalg.svd(mat, full_matrices=False)
        r = len(s)
        # Choose the smallest rank whose discarded singular-value norm fits budget.
        for candidate in range(1, len(s) + 1):
            tail = float(np.linalg.norm(s[candidate:]))
            if tail <= local_budget:
                r = candidate
                break
        if max_rank is not None:
            r = min(r, max_rank)
        core = u[:, :r].reshape(left_rank, n, r)
        cores.append(core)
        residual = (s[:r, None] * vh[:r, :]).reshape((r,) + shape[mode + 1:])
        left_rank = r
    cores.append(residual.reshape(left_rank, shape[-1], 1))
    rebuilt = _reconstruct_cores(cores)
    err = float(np.linalg.norm((x - rebuilt).ravel()) / norm)
    # Explicit measured certificate is authoritative; fail closed on a miss.
    if err > tolerance * (1.0 + 1e-10):
        raise ValueError(f"rank/tolerance combination cannot certify reconstruction: {err} > {tolerance}")
    return TensorRingDecomposition(tuple(cores), shape, err, norm, tolerance)


def reconstruct_tensor_ring(decomposition: TensorRingDecomposition) -> np.ndarray:
    rebuilt = _reconstruct_cores(decomposition.cores)
    if rebuilt.shape != decomposition.original_shape:
        raise ValueError("reconstructed tensor shape mismatch")
    return rebuilt


def tensor_ring_trace_value(cores: Sequence[np.ndarray], indices: Sequence[int]) -> float:
    """Evaluate a ring entry by multiplying mode slices and taking the trace."""
    if len(cores) != len(indices) or not cores:
        raise ValueError("one index is required for each core")
    product = None
    for core, index in zip(cores, indices):
        g = np.asarray(core, dtype=float)
        if g.ndim != 3 or not (0 <= int(index) < g.shape[1]):
            raise ValueError("invalid tensor-ring core or mode index")
        matrix = g[:, int(index), :]
        if product is None:
            product = matrix
        else:
            if product.shape[1] != matrix.shape[0]:
                raise ValueError("incompatible tensor-ring bond dimensions")
            product = product @ matrix
    if product.shape[0] != product.shape[1]:
        raise ValueError("ring closure requires square boundary product")
    return float(np.trace(product))


def surface_dislocation(calendar_variance: Any, nifty_smile: Any, banknifty_smile: Any,
                        smile_tolerance: float = 0.03) -> dict[str, Any]:
    """Measure calendar monotonicity violations and cross-index smile dislocation."""
    cv = _finite_array(calendar_variance, "calendar_variance", 2)
    ns = _finite_array(nifty_smile, "nifty_smile", 1)
    bs = _finite_array(banknifty_smile, "banknifty_smile", 1)
    if ns.shape != bs.shape or smile_tolerance < 0:
        raise ValueError("smiles must have equal shapes and tolerance must be nonnegative")
    increments = np.diff(cv, axis=1)
    calendar_violation = float(max(0.0, -float(np.min(increments)))) if increments.size else 0.0
    diffs = np.abs(ns - bs)
    smile_metric = float(np.max(diffs)) if diffs.size else 0.0
    return {
        "calendar_monotonic": calendar_violation <= 1e-12,
        "max_calendar_variance_drop": calendar_violation,
        "cross_index_smile_dislocation": smile_metric,
        "smile_dislocated": smile_metric > smile_tolerance,
        "smile_tolerance": float(smile_tolerance),
    }


def toxicity_probability(intensity: float, tau: float) -> float:
    if not (math.isfinite(intensity) and intensity >= 0 and math.isfinite(tau) and tau >= 0):
        raise ValueError("intensity and tau must be finite and nonnegative")
    return float(-math.expm1(-intensity * tau))


def almgren_chriss_unwind(inventory: float, horizon_steps: int = 10, eta: float = 0.1,
                          risk_aversion: float = 1e-3, volatility: float = 0.02,
                          intensity: float = 0.0, tau: float = 1.0,
                          impact_power: float = 1.0) -> dict[str, Any]:
    """Hyperbolic AC trajectory, exact terminal zero, power-law temporary impact.

    Inventory is an abstract signed unit count. This produces a paper schedule;
    it does not issue orders or assume fills.
    """
    vals = (inventory, eta, risk_aversion, volatility, intensity, tau, impact_power)
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("all parameters must be finite")
    if horizon_steps < 1 or eta <= 0 or risk_aversion < 0 or volatility < 0 or impact_power <= 0:
        raise ValueError("invalid liquidation parameters")
    lam = math.sqrt(max(0.0, risk_aversion * volatility * volatility / eta))
    grid = np.linspace(0.0, 1.0, horizon_steps + 1)
    if abs(lam) < 1e-14:
        q = float(inventory) * (1.0 - grid)
    else:
        den = math.sinh(lam)
        q = float(inventory) * np.sinh(lam * (1.0 - grid)) / den
    q[-1] = 0.0  # hard terminal constraint, not a floating-point approximation
    trades = q[:-1] - q[1:]
    rates = trades * horizon_steps
    impact_cost = float(eta * np.sum(np.abs(rates) ** (impact_power + 1.0) / (impact_power + 1.0)) / horizon_steps)
    padv = toxicity_probability(float(intensity), float(tau))
    action = "RETREAT" if padv > MAX_TOXICITY_PROBABILITY else "CONTINUE_PAPER"
    return {
        "inventory_path": [float(x) for x in q],
        "trade_schedule": [float(x) for x in trades],
        "terminal_inventory": float(q[-1]),
        "initial_inventory": float(inventory),
        "temporary_impact_cost": impact_cost,
        "toxicity_probability": padv,
        "toxicity_action": action,
        "horizon_steps": int(horizon_steps),
    }


def stress_test_positions(positions: Sequence[Mapping[str, Any]], available_funds_inr: float,
                          price_shocks: Mapping[str, float] | None = None,
                          liquidity_haircut: float = 0.30) -> dict[str, Any]:
    """Offline position stress test using operator-supplied snapshots only."""
    if not math.isfinite(available_funds_inr) or available_funds_inr < 0:
        raise ValueError("available funds must be finite and nonnegative")
    if not (math.isfinite(liquidity_haircut) and 0 <= liquidity_haircut <= 1):
        raise ValueError("liquidity_haircut must be in [0,1]")
    shocks = price_shocks or {}
    rows = []
    total_exposure = 0.0
    total_stress_pnl = 0.0
    for p in positions:
        symbol = str(p.get("symbol", ""))
        qty = float(p.get("quantity", 0.0))
        price = float(p.get("mark_price", 0.0))
        liq = float(p.get("liquidity_scale", 1.0))
        if not symbol or not all(math.isfinite(v) for v in (qty, price, liq)) or price < 0 or liq < 0:
            raise ValueError("each position requires symbol, finite quantity, nonnegative price/liquidity_scale")
        shock = float(shocks.get(symbol, -0.05))
        if not math.isfinite(shock) or shock < -1.0:
            raise ValueError("price shocks must be finite and >= -100%")
        exposure = abs(qty * price)
        pnl = qty * price * shock
        stressed_exit_capacity = exposure * liq * (1.0 - liquidity_haircut)
        rows.append({"symbol": symbol, "exposure_inr": exposure, "shock": shock,
                     "stress_pnl_inr": pnl, "stressed_exit_capacity_inr": stressed_exit_capacity})
        total_exposure += exposure
        total_stress_pnl += pnl
    stressed_funds = available_funds_inr + total_stress_pnl
    return {
        "positions": rows,
        "gross_exposure_inr": float(total_exposure),
        "stress_pnl_inr": float(total_stress_pnl),
        "available_funds_inr": float(available_funds_inr),
        "stressed_funds_inr": float(stressed_funds),
        "liquidity_haircut": float(liquidity_haircut),
        "liquidity_drain_index": float(liquidity_haircut if total_exposure == 0 else
                                        min(1.0, 1.0 - sum(r["stressed_exit_capacity_inr"] for r in rows) / total_exposure)),
        "source_mode": "operator_supplied_offline_snapshot",
    }


def indian_statutory_fees(buy_turnover_inr: float, sell_turnover_inr: float,
                          executed_legs: int = 2,
                          schedule: Mapping[str, float] | None = None) -> dict[str, float]:
    """Calculate costs under the explicitly configured Cycle 64 rate schedule."""
    rates = dict(FEE_SCHEDULE)
    if schedule:
        rates.update({k: float(v) for k, v in schedule.items()})
    buy, sell = float(buy_turnover_inr), float(sell_turnover_inr)
    if not all(math.isfinite(v) and v >= 0 for v in (buy, sell)) or executed_legs < 0:
        raise ValueError("turnover must be finite/nonnegative and executed_legs nonnegative")
    for key in rates:
        if not math.isfinite(float(rates[key])) or rates[key] < 0:
            raise ValueError(f"invalid fee rate: {key}")
    total_turnover = buy + sell
    stt = sell * rates["stt_sell"]
    stamp = buy * rates["stamp_buy"]
    exchange = total_turnover * rates["nse_transaction"]
    sebi = total_turnover * rates["sebi"]
    brokerage = int(executed_legs) * rates["brokerage_per_leg_inr"]
    gst = rates["gst"] * (brokerage + exchange)
    total = stt + stamp + exchange + sebi + brokerage + gst
    return {"stt_sell_inr": stt, "stamp_buy_inr": stamp, "nse_transaction_inr": exchange,
            "sebi_inr": sebi, "brokerage_inr": brokerage, "gst_inr": gst,
            "total_fees_inr": total, "buy_turnover_inr": buy, "sell_turnover_inr": sell,
            "configured_schedule_only": 1.0}


def net_alpha_gate(expected_gross_alpha_inr: float, total_fees_inr: float) -> dict[str, Any]:
    if not all(math.isfinite(float(x)) for x in (expected_gross_alpha_inr, total_fees_inr)) or total_fees_inr < 0:
        raise ValueError("gross alpha and fees must be finite; fees must be nonnegative")
    net = float(expected_gross_alpha_inr) - float(total_fees_inr)
    return {"gross_alpha_inr": float(expected_gross_alpha_inr), "fees_inr": float(total_fees_inr),
            "net_alpha_inr": net, "approved": bool(net > 0.0)}


def beta_fractional_kelly(alpha_prior: float, beta_prior: float, wins: int, losses: int,
                          payoff_odds: float, fractional_scale: float = 0.25,
                          capital_fraction_cap: float = MAX_KELLY_FRACTION,
                          net_alpha_positive: bool = True) -> dict[str, float | bool]:
    """Posterior-mean binary Kelly with explicit fractional and absolute caps."""
    nums = (alpha_prior, beta_prior, payoff_odds, fractional_scale, capital_fraction_cap)
    if not all(math.isfinite(float(x)) for x in nums) or alpha_prior <= 0 or beta_prior <= 0:
        raise ValueError("positive finite beta priors and finite sizing parameters required")
    if wins < 0 or losses < 0 or payoff_odds <= 0 or fractional_scale < 0 or not (0 <= capital_fraction_cap <= 0.10):
        raise ValueError("invalid beta-Kelly arguments or cap exceeds the 10% governance ceiling")
    post_a, post_b = alpha_prior + wins, beta_prior + losses
    p = post_a / (post_a + post_b)
    raw_kelly = max(0.0, (payoff_odds * p - (1.0 - p)) / payoff_odds)
    uncapped = fractional_scale * raw_kelly if net_alpha_positive else 0.0
    fraction = min(float(capital_fraction_cap), uncapped)
    return {"posterior_alpha": post_a, "posterior_beta": post_b, "posterior_win_probability": p,
            "raw_kelly_fraction": raw_kelly, "fractional_kelly_before_cap": uncapped,
            "capital_fraction": fraction, "capital_fraction_cap": float(capital_fraction_cap),
            "net_alpha_gate_passed": bool(net_alpha_positive),
            "allocation_inr_at_epoch_10k": fraction * INITIAL_CAPITAL_INR}


def squad_consensus(agent_votes: Mapping[str, bool], manager_live_veto: bool = True,
                    risk_gates_passed: bool = False) -> dict[str, Any]:
    """Paper-only consensus. A manager veto is binding and cannot enable live routing."""
    required = ("Abhi", "Alex", "Emily", "Max")
    missing = [a for a in required if a not in agent_votes]
    unanimous = not missing and all(bool(agent_votes[a]) for a in required)
    approved = unanimous and bool(risk_gates_passed)
    return {"agents": {a: bool(agent_votes.get(a, False)) for a in required},
            "missing_agents": missing, "unanimous": unanimous,
            "paper_research_approved": approved,
            "manager_live_veto": bool(manager_live_veto),
            "live_order_dispatch_enabled": False,
            "real_broker_fills_locked": True,
            "ledger_epoch": PAPER_LEDGER_EPOCH}


def martingale_transport_bounds(x: Any, p: Any, y: Any, q: Any,
                                payoff: Any) -> dict[str, Any]:
    """Discrete martingale transport expectation bounds using primal LPs.

    x,p and y,q are source/target supports and masses. Equalities enforce both
    marginals and rowwise conditional martingale constraints. Returned duality
    gaps are computed from HiGHS equality marginals for each LP.
    """
    xs = _finite_array(x, "x", 1)
    ps = _finite_array(p, "p", 1)
    ys = _finite_array(y, "y", 1)
    qs = _finite_array(q, "q", 1)
    h = _finite_array(payoff, "payoff", 2)
    n, m = len(xs), len(ys)
    if len(ps) != n or len(qs) != m or h.shape != (n, m):
        raise ValueError("support, marginal and payoff dimensions do not match")
    if np.any(ps < 0) or np.any(qs < 0) or abs(float(ps.sum()) - 1) > 1e-10 or abs(float(qs.sum()) - 1) > 1e-10:
        raise ValueError("marginal probabilities must be nonnegative and sum to one")
    if abs(float(np.dot(xs, ps) - np.dot(ys, qs))) > 1e-8:
        raise ValueError("martingale marginals must have equal means")
    # Constraint order: source marginals, target marginals, rowwise martingale.
    rows, rhs = [], []
    for i in range(n):
        row = np.zeros((n, m)); row[i, :] = 1
        rows.append(row.ravel()); rhs.append(ps[i])
    for j in range(m):
        row = np.zeros((n, m)); row[:, j] = 1
        rows.append(row.ravel()); rhs.append(qs[j])
    for i in range(n):
        row = np.zeros((n, m)); row[i, :] = ys - xs[i]
        rows.append(row.ravel()); rhs.append(0.0)
    aeq = np.asarray(rows, dtype=float)
    beq = np.asarray(rhs, dtype=float)
    outputs = []
    for sign in (1.0, -1.0):
        result = linprog(sign * h.ravel(), A_eq=aeq, b_eq=beq,
                         bounds=(0, None), method="highs")
        if not result.success:
            raise ValueError(f"martingale transport LP failed: {result.message}")
        residual = float(np.max(np.abs(aeq @ result.x - beq)))
        dual = float(np.dot(beq, result.eqlin.marginals))
        gap = float(abs(result.fun - dual))
        value = float(sign * result.fun)
        outputs.append({"value": value, "coupling": result.x.reshape(n, m).tolist(),
                        "constraint_residual": residual, "duality_gap": gap})
    lower, upper = outputs[0], outputs[1]
    if lower["value"] > upper["value"] + 1e-8:
        raise ArithmeticError("LP bounds inverted beyond tolerance")
    return {"lower_bound": lower["value"], "upper_bound": upper["value"],
            "lower_coupling": lower["coupling"], "upper_coupling": upper["coupling"],
            "max_martingale_constraint_residual": max(lower["constraint_residual"], upper["constraint_residual"]),
            "max_duality_gap": max(lower["duality_gap"], upper["duality_gap"]),
            "residual_tolerance": 1e-8, "duality_gap_tolerance": 1e-8,
            "solver": "scipy.optimize.linprog(method='highs')"}


def default_squad() -> dict[str, str]:
    return {"Abhi": "operator intake, capital governance, binding veto",
            "Alex": "L3 microstructure and MLOFI",
            "Emily": "macro regime and Volterra tensor ring",
            "Max": "risk management and Indian friction"}

__all__ = [
    "CYCLE", "CYCLE_NAME", "INDEX_NODES", "LIVE_ORDER_DISPATCH_ENABLED",
    "REAL_BROKER_FILLS_LOCKED", "PAPER_LEDGER_EPOCH", "INITIAL_CAPITAL_INR",
    "MAX_KELLY_FRACTION", "FEE_SCHEDULE", "dispatch_live_order", "spectral_radius",
    "build_graph_attention", "rough_volterra_kernel", "fractional_volterra_state",
    "hawkes_network_intensity", "TensorRingDecomposition", "tensor_ring_svd",
    "reconstruct_tensor_ring", "tensor_ring_trace_value", "surface_dislocation",
    "toxicity_probability", "almgren_chriss_unwind", "stress_test_positions",
    "indian_statutory_fees", "net_alpha_gate", "beta_fractional_kelly",
    "squad_consensus", "martingale_transport_bounds", "default_squad"
]

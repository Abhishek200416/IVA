"""Cycle 60 QTN-MOT: tensor-train compression, martingale transport and Hawkes-game research.

Offline research/paper-simulation package. No broker integration or live order path is present.
Python 3.11-compatible; requires NumPy and SciPy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple
import math

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import linprog

ASSETS: Tuple[str, ...] = ("NIFTY50", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10000.0
MAX_KELLY_FRACTION = 0.10
MAX_MPS_BOND_DIM = 16
MAX_MPS_RELATIVE_ERROR = 1e-4


def _finite_array(value: ArrayLike, name: str, ndim: Optional[int] = None) -> NDArray[np.float64]:
    arr = np.asarray(value, dtype=float)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must be {ndim}-dimensional")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _positive(value: float, name: str, allow_zero: bool = False) -> float:
    out = float(value)
    if not math.isfinite(out) or (out < 0.0 if allow_zero else out <= 0.0):
        relation = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {relation}")
    return out


def spectral_radius(matrix: ArrayLike) -> float:
    """Return max absolute eigenvalue of a finite square matrix."""
    a = _finite_array(matrix, "matrix", 2)
    if a.shape[0] != a.shape[1] or a.shape[0] == 0:
        raise ValueError("matrix must be non-empty and square")
    vals = np.linalg.eigvals(a)
    return float(np.max(np.abs(vals)))


# ---------------------------------------------------------------------------
# Matrix Product State / Tensor Train SVD
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TensorTrainResult:
    cores: Tuple[NDArray[np.float64], ...]  # each (r_left, n_k, r_right)
    shape: Tuple[int, ...]
    relative_error: float
    max_bond_dim: int
    requested_tolerance: float

    def reconstruct(self) -> NDArray[np.float64]:
        if not self.cores:
            raise ValueError("tensor train contains no cores")
        result = self.cores[0][0, :, :]
        for core in self.cores[1:]:
            # result indices ..., r; core indices r, n, r'
            result = np.tensordot(result, core, axes=([-1], [0]))
        return np.asarray(result[..., 0], dtype=float)


def tensor_train_decompose(
    tensor: ArrayLike,
    max_bond_dim: int = 16,
    tolerance: float = 1e-4,
    strict: bool = True,
) -> TensorTrainResult:
    """Sequential-SVD tensor train approximation with measured Frobenius error.

    The requested bond cap and error tolerance are checked against the Cycle 60
    limits. If the cap prevents the requested error, strict=True raises rather
    than making an unsupported precision claim.
    """
    x = _finite_array(tensor, "tensor")
    if x.ndim < 1 or any(int(n) <= 0 for n in x.shape):
        raise ValueError("tensor must have at least one non-empty dimension")
    if not isinstance(max_bond_dim, (int, np.integer)) or max_bond_dim < 1 or max_bond_dim > MAX_MPS_BOND_DIM:
        raise ValueError(f"max_bond_dim must be an integer in [1, {MAX_MPS_BOND_DIM}]")
    tol = _positive(tolerance, "tolerance")
    if tol > MAX_MPS_RELATIVE_ERROR:
        raise ValueError(f"tolerance must be <= {MAX_MPS_RELATIVE_ERROR}")
    shape = tuple(int(n) for n in x.shape)
    norm = float(np.linalg.norm(x.ravel()))
    if norm == 0.0:
        cores = (np.zeros((1, shape[0], 1), dtype=float),) if x.ndim == 1 else None
        if cores is None:
            # Zero tensor has an exact rank-one train of matching shape.
            built = []
            for n in shape:
                built.append(np.zeros((1, n, 1), dtype=float))
            cores = tuple(built)
        return TensorTrainResult(tuple(cores), shape, 0.0, 1, tol)
    if x.ndim == 1:
        core = x.reshape(1, shape[0], 1).copy()
        return TensorTrainResult((core,), shape, 0.0, 1, tol)

    cores = []
    remainder = x.copy()
    r_left = 1
    # Allocate a global error budget across SVD truncations. The true final
    # reconstruction error is always measured separately below.
    local_tol = tol / math.sqrt(max(1, x.ndim - 1))
    for axis in range(x.ndim - 1):
        n = shape[axis]
        matrix = remainder.reshape(r_left * n, -1)
        u, s, vh = np.linalg.svd(matrix, full_matrices=False)
        cap = min(int(max_bond_dim), len(s))
        total_energy = float(np.dot(s, s))
        tail_energy = np.cumsum((s[::-1] ** 2))[::-1]
        # Choose the smallest admissible retained rank with residual below the
        # allocated SVD budget; always retain at least one singular component.
        rank_by_tol = len(s)
        for rank in range(1, cap + 1):
            discarded = float(np.sum(s[rank:] ** 2))
            if discarded <= (local_tol ** 2) * total_energy:
                rank_by_tol = rank
                break
        rank = min(cap, rank_by_tol)
        core = u[:, :rank].reshape(r_left, n, rank)
        cores.append(core)
        remainder = (s[:rank, None] * vh[:rank, :]).reshape((rank,) + shape[axis + 1 :])
        r_left = rank
    cores.append(remainder.reshape(r_left, shape[-1], 1))
    provisional = TensorTrainResult(tuple(cores), shape, 0.0, max(c.shape[2] for c in cores[:-1]) if len(cores) > 1 else 1, tol)
    rebuilt = provisional.reconstruct()
    error = float(np.linalg.norm((x - rebuilt).ravel()) / norm)
    max_rank = max((max(c.shape[0], c.shape[2]) for c in cores), default=1)
    result = TensorTrainResult(tuple(cores), shape, error, max_rank, tol)
    if strict and (error > tol or error >= MAX_MPS_RELATIVE_ERROR):
        raise ValueError(
            f"requested relative error {tol:g} cannot be met with bond cap {max_bond_dim}; measured {error:g}"
        )
    return result


def tensor_train_contract(cores: Sequence[ArrayLike], indices: Sequence[int]) -> float:
    """Contract a tensor train at discrete multi-index `indices`."""
    if len(cores) == 0 or len(cores) != len(indices):
        raise ValueError("cores and indices must have equal non-zero length")
    state = np.ones((1,), dtype=float)
    for core_raw, idx_raw in zip(cores, indices):
        core = _finite_array(core_raw, "core", 3)
        idx = int(idx_raw)
        if idx < 0 or idx >= core.shape[1]:
            raise IndexError("tensor index out of range")
        if state.shape[0] != core.shape[0]:
            raise ValueError("incompatible tensor train bond dimensions")
        state = state @ core[:, idx, :]
    if state.size != 1:
        raise ValueError("tensor train is not closed at final bond")
    return float(state[0])


def tensor_greeks(
    tensor: ArrayLike, index: Sequence[int], axis: int, spacing: float = 1.0
) -> Dict[str, float]:
    """Finite-difference first and second derivatives along one tensor axis.

    Uses central differences in the interior and second-order one-sided first
    derivatives/nearest valid second differences near boundaries.
    """
    x = _finite_array(tensor, "tensor")
    if x.ndim < 1 or len(index) != x.ndim:
        raise ValueError("index dimensionality must match tensor")
    if not isinstance(axis, (int, np.integer)) or not (0 <= axis < x.ndim):
        raise ValueError("axis out of range")
    h = _positive(spacing, "spacing")
    idx = [int(i) for i in index]
    for a, i in enumerate(idx):
        if i < 0 or i >= x.shape[a]:
            raise IndexError("tensor index out of range")
    n = x.shape[axis]
    if n < 3:
        raise ValueError("at least three points are required for second derivatives")
    i = idx[axis]
    lo, hi = idx.copy(), idx.copy()
    if 0 < i < n - 1:
        lo[axis], hi[axis] = i - 1, i + 1
        f0, fm, fp = float(x[tuple(idx)]), float(x[tuple(lo)]), float(x[tuple(hi)])
        first = (fp - fm) / (2.0 * h)
        second = (fp - 2.0 * f0 + fm) / (h * h)
    elif i == 0:
        i1, i2 = idx.copy(), idx.copy()
        i1[axis], i2[axis] = 1, 2
        f0, f1, f2 = float(x[tuple(idx)]), float(x[tuple(i1)]), float(x[tuple(i2)])
        first = (-3 * f0 + 4 * f1 - f2) / (2 * h)
        second = (f2 - 2 * f1 + f0) / (h * h)
    else:
        i1, i2 = idx.copy(), idx.copy()
        i1[axis], i2[axis] = n - 2, n - 3
        f0, f1, f2 = float(x[tuple(idx)]), float(x[tuple(i1)]), float(x[tuple(i2)])
        first = (3 * f0 - 4 * f1 + f2) / (2 * h)
        second = (f0 - 2 * f1 + f2) / (h * h)
    return {"first": float(first), "second": float(second)}


def tensor_train_greeks(
    cores: Sequence[ArrayLike], index: Sequence[int], axis: int, spacing: float = 1.0
) -> Dict[str, float]:
    """Evaluate local first/second differences by MPS contraction only.

    No dense tensor reconstruction is needed. Differences are central in the
    interior and second-order one-sided at the first/last grid point.
    """
    if len(cores) == 0 or len(cores) != len(index):
        raise ValueError("cores and index must have equal non-zero length")
    h = _positive(spacing, "spacing")
    dims = []
    for c in cores:
        arr = _finite_array(c, "core", 3)
        dims.append(arr.shape[1])
    if not isinstance(axis, (int, np.integer)) or not 0 <= axis < len(dims):
        raise ValueError("axis out of range")
    idx = [int(v) for v in index]
    if any(v < 0 or v >= dims[i] for i, v in enumerate(idx)):
        raise IndexError("tensor index out of range")
    n = dims[axis]
    if n < 3:
        raise ValueError("at least three points are required for second derivatives")
    i = idx[axis]
    f0 = tensor_train_contract(cores, idx)
    if 0 < i < n - 1:
        low, high = idx.copy(), idx.copy()
        low[axis], high[axis] = i - 1, i + 1
        fm, fp = tensor_train_contract(cores, low), tensor_train_contract(cores, high)
        first, second = (fp - fm) / (2 * h), (fp - 2 * f0 + fm) / (h * h)
    elif i == 0:
        one, two = idx.copy(), idx.copy(); one[axis], two[axis] = 1, 2
        f1, f2 = tensor_train_contract(cores, one), tensor_train_contract(cores, two)
        first, second = (-3 * f0 + 4 * f1 - f2) / (2 * h), (f2 - 2 * f1 + f0) / (h * h)
    else:
        one, two = idx.copy(), idx.copy(); one[axis], two[axis] = n - 2, n - 3
        f1, f2 = tensor_train_contract(cores, one), tensor_train_contract(cores, two)
        first, second = (3 * f0 - 4 * f1 + f2) / (2 * h), (f0 - 2 * f1 + f2) / (h * h)
    return {"first": float(first), "second": float(second)}


# ---------------------------------------------------------------------------
# Discrete martingale optimal transport (MOT)
# ---------------------------------------------------------------------------
def validate_martingale_plan(
    plan: ArrayLike,
    x: ArrayLike,
    mu: ArrayLike,
    y: ArrayLike,
    nu: ArrayLike,
    tolerance: float = 1e-8,
) -> Dict[str, float]:
    """Audit non-negativity, marginal constraints, and row-wise martingale constraints."""
    p = _finite_array(plan, "plan", 2)
    xs, ys = _finite_array(x, "x", 1), _finite_array(y, "y", 1)
    m, n = _finite_array(mu, "mu", 1), _finite_array(nu, "nu", 1)
    tol = _positive(tolerance, "tolerance")
    if xs.size == 0 or ys.size == 0:
        raise ValueError("supports must be non-empty")
    if p.shape != (xs.size, ys.size) or m.size != xs.size or n.size != ys.size:
        raise ValueError("plan/support/marginal dimensions do not match")
    if np.min(p) < -tol or np.min(m) < -tol or np.min(n) < -tol:
        raise ValueError("plan and marginals must be non-negative")
    if abs(float(m.sum()) - 1.0) > tol or abs(float(n.sum()) - 1.0) > tol:
        raise ValueError("marginals must each sum to one")
    row_res = float(np.max(np.abs(p.sum(axis=1) - m)))
    col_res = float(np.max(np.abs(p.sum(axis=0) - n)))
    mart = p @ ys - xs * m
    mart_res = float(np.max(np.abs(mart))) if mart.size else 0.0
    return {"row_residual": row_res, "column_residual": col_res,
            "martingale_residual": mart_res, "minimum_plan_mass": float(np.min(p))}


@dataclass(frozen=True)
class MOTBounds:
    lower_price: float
    upper_price: float
    lower_plan: NDArray[np.float64]
    upper_plan: NDArray[np.float64]
    lower_residuals: Mapping[str, float]
    upper_residuals: Mapping[str, float]
    lower_dual_bound: float
    upper_dual_bound: float
    lower_dual_variables: NDArray[np.float64]
    upper_dual_variables: NDArray[np.float64]
    lower_dual_constraint_violation: float
    upper_dual_constraint_violation: float


def solve_martingale_transport_bounds(
    x: ArrayLike,
    mu: ArrayLike,
    y: ArrayLike,
    nu: ArrayLike,
    payoff: ArrayLike,
    tolerance: float = 1e-8,
) -> MOTBounds:
    """Solve lower/upper payoff expectation over discrete martingale couplings.

    The transport plan pi[i,j] must satisfy row sums mu[i], column sums nu[j],
    pi >= 0, and sum_j y[j] pi[i,j] = x[i] mu[i]. Marginal supports are assumed
    already calibrated. Infeasible constraints raise ValueError.
    """
    xs, ys = _finite_array(x, "x", 1), _finite_array(y, "y", 1)
    m, n = _finite_array(mu, "mu", 1), _finite_array(nu, "nu", 1)
    v = _finite_array(payoff, "payoff", 2)
    tol = _positive(tolerance, "tolerance")
    if xs.size == 0 or ys.size == 0 or m.size != xs.size or n.size != ys.size:
        raise ValueError("support and marginal dimensions do not match")
    if v.shape != (xs.size, ys.size):
        raise ValueError("payoff must have shape (len(x), len(y))")
    if np.min(m) < 0 or np.min(n) < 0 or abs(m.sum() - 1) > tol or abs(n.sum() - 1) > tol:
        raise ValueError("marginals must be nonnegative and sum to one")
    if abs(float(xs @ m) - float(ys @ n)) > tol:
        raise ValueError("source and target marginal means must agree for a martingale coupling")
    nx, ny = xs.size, ys.size
    rows = []
    rhs = []
    # Row constraints
    for i in range(nx):
        row = np.zeros((nx, ny)); row[i, :] = 1.0
        rows.append(row.ravel()); rhs.append(m[i])
    # Column constraints
    for j in range(ny):
        row = np.zeros((nx, ny)); row[:, j] = 1.0
        rows.append(row.ravel()); rhs.append(n[j])
    # Martingale constraints by source state
    for i in range(nx):
        row = np.zeros((nx, ny)); row[i, :] = ys
        rows.append(row.ravel()); rhs.append(xs[i] * m[i])
    a_eq, b_eq = np.vstack(rows), np.asarray(rhs, dtype=float)
    bounds = [(0.0, None)] * (nx * ny)
    lower_res = linprog(v.ravel(), A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    upper_res = linprog(-v.ravel(), A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not lower_res.success or not upper_res.success:
        reason = lower_res.message if not lower_res.success else upper_res.message
        raise ValueError(f"discrete martingale transport problem infeasible: {reason}")
    p_lo = lower_res.x.reshape(nx, ny)
    p_hi = upper_res.x.reshape(nx, ny)
    lo_audit = validate_martingale_plan(p_lo, xs, m, ys, n, max(tol, 1e-8))
    hi_audit = validate_martingale_plan(p_hi, xs, m, ys, n, max(tol, 1e-8))
    # The LP duals are static super/sub-hedging certificates. For the lower
    # primal, max b·y subject to A^T y <= payoff; for the upper primal,
    # min b·y subject to A^T y >= payoff. Marginal and martingale constraints
    # are equalities, so all dual potentials are free (unbounded-sign) variables.
    dual_bounds = [(None, None)] * b_eq.size
    lower_dual = linprog(-b_eq, A_ub=a_eq.T, b_ub=v.ravel(), bounds=dual_bounds, method="highs")
    upper_dual = linprog(b_eq, A_ub=-a_eq.T, b_ub=-v.ravel(), bounds=dual_bounds, method="highs")
    if not lower_dual.success or not upper_dual.success:
        reason = lower_dual.message if not lower_dual.success else upper_dual.message
        raise ValueError(f"martingale transport dual problem failed: {reason}")
    ylo, yhi = lower_dual.x, upper_dual.x
    lower_violation = float(max(0.0, np.max(a_eq.T @ ylo - v.ravel())))
    upper_violation = float(max(0.0, np.max(v.ravel() - a_eq.T @ yhi)))
    lower_dual_value = float(-lower_dual.fun)
    upper_dual_value = float(upper_dual.fun)
    return MOTBounds(
        float(np.sum(p_lo * v)), float(np.sum(p_hi * v)), p_lo, p_hi,
        lo_audit, hi_audit, lower_dual_value, upper_dual_value,
        ylo.copy(), yhi.copy(), lower_violation, upper_violation,
    )


# ---------------------------------------------------------------------------
# MLOFI, queue priority and Hawkes game
# ---------------------------------------------------------------------------
def multi_level_ofi(
    delta_bid_volume: ArrayLike,
    delta_ask_volume: ArrayLike,
    delta_bid_price: ArrayLike,
    delta_ask_price: ArrayLike,
    weights: Optional[ArrayLike] = None,
) -> float:
    """Top-five MLOFI with default [5,4,3,2,1] depth weights."""
    vb = _finite_array(delta_bid_volume, "delta_bid_volume", 1)
    va = _finite_array(delta_ask_volume, "delta_ask_volume", 1)
    pb = _finite_array(delta_bid_price, "delta_bid_price", 1)
    pa = _finite_array(delta_ask_price, "delta_ask_price", 1)
    if any(a.size != 5 for a in (vb, va, pb, pa)):
        raise ValueError("MLOFI inputs must each contain exactly five levels")
    w = np.asarray([5, 4, 3, 2, 1], dtype=float) if weights is None else _finite_array(weights, "weights", 1)
    if w.size != 5 or np.any(w < 0):
        raise ValueError("weights must be five nonnegative values")
    bid = vb * (pb >= 0.0)
    ask = va * (pa <= 0.0)
    return float(w @ (bid - ask))


class L3QueuePriorityTracker:
    """Minimal deterministic queue-ahead/depletion tracker for five levels."""
    def __init__(self, queue_ahead: ArrayLike):
        q = _finite_array(queue_ahead, "queue_ahead", 1)
        if q.size != 5 or np.any(q < 0):
            raise ValueError("queue_ahead must be five nonnegative quantities")
        self.queue_ahead = q.copy()
        self.depleted = np.zeros(5, dtype=float)

    def update(self, level: int, traded_ahead: float = 0.0, cancelled_ahead: float = 0.0, replenished_ahead: float = 0.0) -> float:
        if not isinstance(level, (int, np.integer)) or not 0 <= level < 5:
            raise ValueError("level must be in [0,4]")
        trade = _positive(traded_ahead, "traded_ahead", allow_zero=True)
        cancel = _positive(cancelled_ahead, "cancelled_ahead", allow_zero=True)
        replen = _positive(replenished_ahead, "replenished_ahead", allow_zero=True)
        raw = self.queue_ahead[level] - trade - cancel + replen
        self.depleted[level] += min(self.queue_ahead[level], trade + cancel)
        self.queue_ahead[level] = max(0.0, raw)
        return float(self.queue_ahead[level])

    def priority_score(self, level: int) -> float:
        if not isinstance(level, (int, np.integer)) or not 0 <= level < 5:
            raise ValueError("level must be in [0,4]")
        return float(1.0 / (1.0 + self.queue_ahead[level]))


class MultiAgentHawkesGame:
    """Mutually exciting Hawkes process with stable branching matrix.

    alpha[i,j] is the jump in intensity contribution i caused by an event of j;
    beta[i,j] is its exponential decay rate. The model refuses supercritical
    parameterizations with rho(alpha / beta) > max_branching_ratio.
    """
    def __init__(
        self,
        baseline: ArrayLike,
        alpha: ArrayLike,
        beta: ArrayLike,
        gamma_mlofi: float = 0.0,
        max_branching_ratio: float = 0.88,
    ):
        self.baseline = _finite_array(baseline, "baseline", 1)
        self.alpha = _finite_array(alpha, "alpha", 2)
        self.beta = _finite_array(beta, "beta", 2)
        n = self.baseline.size
        if n == 0 or self.alpha.shape != (n, n) or self.beta.shape != (n, n):
            raise ValueError("baseline, alpha, beta dimensions must be N, N×N, N×N")
        if np.any(self.baseline < 0) or np.any(self.alpha < 0) or np.any(self.beta <= 0):
            raise ValueError("baseline/alpha must be nonnegative and beta strictly positive")
        self.gamma_mlofi = _positive(gamma_mlofi, "gamma_mlofi", allow_zero=True)
        self.max_branching_ratio = _positive(max_branching_ratio, "max_branching_ratio")
        if self.max_branching_ratio > 0.88:
            raise ValueError("max_branching_ratio cannot exceed 0.88")
        self.branching_matrix = self.alpha / self.beta
        self.branching_radius = spectral_radius(self.branching_matrix)
        if self.branching_radius > self.max_branching_ratio + 1e-12:
            raise ValueError(f"Hawkes process is not subcritical: rho={self.branching_radius:.6g} > {self.max_branching_ratio}")
        self.excitation = np.zeros((n, n), dtype=float)
        self.n_events = np.zeros(n, dtype=np.int64)
        self.last_intensity = self.baseline.copy()

    @property
    def n_agents(self) -> int:
        return int(self.baseline.size)

    def intensity(self, mlofi: ArrayLike | float = 0.0) -> NDArray[np.float64]:
        mf = np.asarray(mlofi, dtype=float)
        if mf.ndim == 0:
            mf = np.full(self.n_agents, float(mf))
        if mf.shape != (self.n_agents,) or not np.all(np.isfinite(mf)):
            raise ValueError("mlofi must be scalar or one value per agent")
        raw = self.baseline + self.excitation.sum(axis=1) + self.gamma_mlofi * mf
        self.last_intensity = np.maximum(raw, 0.0)
        return self.last_intensity.copy()

    def advance(self, dt: float, events: Optional[Mapping[int, float]] = None, mlofi: ArrayLike | float = 0.0) -> NDArray[np.float64]:
        step = _positive(dt, "dt")
        self.excitation *= np.exp(-self.beta * step)
        if events:
            for source, mark in events.items():
                if not isinstance(source, (int, np.integer)) or not 0 <= source < self.n_agents:
                    raise ValueError("event source out of range")
                mk = _positive(mark, "event mark")
                self.excitation[:, source] += self.alpha[:, source] * mk
                self.n_events[source] += 1
        return self.intensity(mlofi)

    def simulate_step(self, dt: float, rng: np.random.Generator, mlofi: ArrayLike | float = 0.0) -> Tuple[NDArray[np.int64], NDArray[np.float64]]:
        step = _positive(dt, "dt")
        lam = self.intensity(mlofi)
        counts = rng.poisson(lam * step)
        events = {i: float(counts[i]) for i in range(self.n_agents) if counts[i] > 0}
        updated = self.advance(step, events=events, mlofi=mlofi)
        return counts.astype(np.int64), updated


def optimal_toxic_spread(
    base_spread: float,
    risk_aversion: float,
    volatility: float,
    inventory: float,
    kappa: float,
    alpha: float,
    toxic_intensity: float,
    min_spread: float = 1e-8,
) -> float:
    """Risk- and toxic-flow-adjusted total spread from the supplied formula."""
    base = _positive(base_spread, "base_spread", allow_zero=True)
    gamma = _positive(risk_aversion, "risk_aversion", allow_zero=True)
    sig = _positive(volatility, "volatility", allow_zero=True)
    q = float(inventory)
    if not math.isfinite(q):
        raise ValueError("inventory must be finite")
    kap = _positive(kappa, "kappa")
    alp = _positive(alpha, "alpha")
    lam = _positive(toxic_intensity, "toxic_intensity", allow_zero=True)
    floor = _positive(min_spread, "min_spread")
    spread = base + gamma * sig * sig * q + (2.0 / kap) * math.log1p((kap / alp) * lam)
    return float(max(floor, spread))


def adverse_selection_probability(toxic_intensity: float, horizon: float) -> float:
    lam = _positive(toxic_intensity, "toxic_intensity", allow_zero=True)
    tau = _positive(horizon, "horizon", allow_zero=True)
    return float(-math.expm1(-lam * tau))


def should_retreat_quote(toxic_intensity: float, horizon: float, threshold: float = 0.60) -> bool:
    th = float(threshold)
    if not math.isfinite(th) or not 0.0 <= th <= 1.0:
        raise ValueError("threshold must be in [0,1]")
    return adverse_selection_probability(toxic_intensity, horizon) > th


def solve_spread_nash_equilibrium(
    risk_adjusted_target_spreads: ArrayLike,
    competition_weight: float = 0.2,
    minimum_spread: float = 1e-8,
    tolerance: float = 1e-10,
    max_iterations: int = 10000,
) -> NDArray[np.float64]:
    """Solve a quadratic best-response spread game for N market makers.

    Player i maximizes -0.5*(s_i-target_i)^2 - 0.5*w*(s_i-mean(s_-i))^2,
    subject to s_i >= minimum_spread. The fixed point is a Nash equilibrium
    for 0 <= w < 1; iteration is deterministic and stops at a stated tolerance.
    """
    targets = _finite_array(risk_adjusted_target_spreads, "risk_adjusted_target_spreads", 1)
    if targets.size < 2 or np.any(targets <= 0):
        raise ValueError("at least two strictly positive target spreads are required")
    w = _positive(competition_weight, "competition_weight", allow_zero=True)
    if w >= 1.0:
        raise ValueError("competition_weight must be < 1 for contraction")
    floor = _positive(minimum_spread, "minimum_spread")
    tol = _positive(tolerance, "tolerance")
    if not isinstance(max_iterations, (int, np.integer)) or max_iterations < 1:
        raise ValueError("max_iterations must be a positive integer")
    s = targets.copy()
    for _ in range(int(max_iterations)):
        nxt = np.empty_like(s)
        for i in range(s.size):
            peers = np.delete(s, i)
            nxt[i] = max(floor, (targets[i] + w * float(peers.mean())) / (1.0 + w))
        if float(np.max(np.abs(nxt - s))) <= tol:
            return nxt
        s = nxt
    raise RuntimeError("spread equilibrium did not converge within max_iterations")


# ---------------------------------------------------------------------------
# Fees, net alpha, Kelly and inventory bands
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FeeBreakdown:
    buy_turnover: float
    sell_turnover: float
    stt: float
    stamp_duty: float
    exchange_fee: float
    sebi_fee: float
    brokerage: float
    gst: float
    total: float


def indian_statutory_fees(buy_turnover: float, sell_turnover: float, executed_legs: int = 1) -> FeeBreakdown:
    buy = _positive(buy_turnover, "buy_turnover", allow_zero=True)
    sell = _positive(sell_turnover, "sell_turnover", allow_zero=True)
    if not isinstance(executed_legs, (int, np.integer)) or executed_legs < 0:
        raise ValueError("executed_legs must be a nonnegative integer")
    turnover = buy + sell
    stt = 0.0015 * sell
    stamp = 0.00003 * buy
    exchange = 0.0003553 * turnover
    sebi = 0.000001 * turnover
    brokerage = 20.0 * int(executed_legs)
    gst = 0.18 * (exchange + brokerage)
    total = stt + stamp + exchange + sebi + brokerage + gst
    return FeeBreakdown(buy, sell, stt, stamp, exchange, sebi, brokerage, gst, float(total))


def net_alpha_gate(expected_gross_alpha: float, total_fees: float) -> Dict[str, float | bool]:
    gross = float(expected_gross_alpha); fees = float(total_fees)
    if not math.isfinite(gross) or not math.isfinite(fees) or fees < 0:
        raise ValueError("gross alpha must be finite; fees must be finite and nonnegative")
    net = gross - fees
    return {"gross_alpha": gross, "fees": fees, "net_alpha": net, "approved": bool(net > 0.0)}


def beta_posterior_fractional_kelly(
    wins: float,
    losses: float,
    payoff_ratio: float,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
    fraction: float = 0.5,
    cap: float = MAX_KELLY_FRACTION,
) -> float:
    w = _positive(wins, "wins", allow_zero=True)
    l = _positive(losses, "losses", allow_zero=True)
    b = _positive(payoff_ratio, "payoff_ratio")
    a0 = _positive(prior_alpha, "prior_alpha")
    b0 = _positive(prior_beta, "prior_beta")
    frac = _positive(fraction, "fraction", allow_zero=True)
    ceiling = _positive(cap, "cap", allow_zero=True)
    if ceiling > MAX_KELLY_FRACTION:
        raise ValueError("cap cannot exceed 10%")
    p = (a0 + w) / (a0 + b0 + w + l)
    raw_kelly = (p * (b + 1.0) - 1.0) / b
    return float(np.clip(raw_kelly * frac, 0.0, ceiling))


@dataclass(frozen=True)
class InventoryBand:
    lower: float
    upper: float
    width: float
    target: float


def inventory_indifference_band(
    target_inventory: float,
    transaction_cost: float,
    volatility: float,
    risk_aversion: float,
    buy_spread_penalty: float = 0.0,
    sell_spread_penalty: float = 0.0,
    fee_drag: float = 0.0,
) -> InventoryBand:
    q = float(target_inventory)
    if not math.isfinite(q):
        raise ValueError("target_inventory must be finite")
    c = _positive(transaction_cost, "transaction_cost")
    sig = _positive(volatility, "volatility", allow_zero=True)
    gamma = _positive(risk_aversion, "risk_aversion")
    bp = _positive(buy_spread_penalty, "buy_spread_penalty", allow_zero=True)
    sp = _positive(sell_spread_penalty, "sell_spread_penalty", allow_zero=True)
    fd = _positive(fee_drag, "fee_drag", allow_zero=True)
    delta = ((3.0 * c * sig * sig) / (4.0 * gamma)) ** (1.0 / 3.0)
    lower = q - (delta + bp + fd)
    upper = q + (delta + sp + fd)
    return InventoryBand(float(lower), float(upper), float(delta), q)


def inventory_trade_action(inventory: float, band: InventoryBand) -> str:
    q = float(inventory)
    if not math.isfinite(q):
        raise ValueError("inventory must be finite")
    if band.lower > band.upper:
        raise ValueError("invalid inventory band")
    if q < band.lower:
        return "BUY_TO_REBALANCE"
    if q > band.upper:
        return "SELL_TO_REBALANCE"
    return "NO_TRADE"


# ---------------------------------------------------------------------------
# 16-state actor-critic and consensus
# ---------------------------------------------------------------------------
class ContinuousActorCritic:
    """Small NumPy two-hidden-layer actor and critic baseline for research."""
    def __init__(self, state_dim: int = 16, action_dim: int = 3, hidden_dim: int = 24, seed: int = 60):
        if state_dim != 16 or action_dim != 3:
            raise ValueError("Cycle 60 policy contract is state_dim=16, action_dim=3")
        if not isinstance(hidden_dim, (int, np.integer)) or hidden_dim < 2:
            raise ValueError("hidden_dim must be integer >= 2")
        self.state_dim, self.action_dim, self.hidden_dim = state_dim, action_dim, int(hidden_dim)
        rng = np.random.default_rng(seed)
        def init(a: int, b: int) -> NDArray[np.float64]:
            return rng.normal(0.0, math.sqrt(2.0 / (a + b)), size=(a, b))
        self.a1, self.a2, self.a3 = init(state_dim, hidden_dim), init(hidden_dim, hidden_dim), init(hidden_dim, action_dim)
        self.c1, self.c2, self.c3 = init(state_dim, hidden_dim), init(hidden_dim, hidden_dim), init(hidden_dim, 1)
        self.last_state: Optional[NDArray[np.float64]] = None
        self.last_action: Optional[NDArray[np.float64]] = None
        self.last_value: float = 0.0

    def _state(self, state: ArrayLike) -> NDArray[np.float64]:
        s = _finite_array(state, "state", 1)
        if s.shape != (16,):
            raise ValueError("state must be exactly 16-dimensional")
        return np.clip(s, -1e6, 1e6)

    def act(self, state: ArrayLike, exploration_scale: float = 0.0, rng: Optional[np.random.Generator] = None) -> NDArray[np.float64]:
        s = self._state(state)
        h1 = np.tanh(s @ self.a1)
        h2 = np.tanh(h1 @ self.a2)
        z = h2 @ self.a3
        scale = _positive(exploration_scale, "exploration_scale", allow_zero=True)
        if scale > 0:
            gen = rng if rng is not None else np.random.default_rng(0)
            z = z + gen.normal(0.0, scale, size=self.action_dim)
        action = np.tanh(z)
        self.last_state, self.last_action = s.copy(), action.copy()
        return action

    def value(self, state: ArrayLike) -> float:
        s = self._state(state)
        h1 = np.tanh(s @ self.c1)
        h2 = np.tanh(h1 @ self.c2)
        self.last_value = float((h2 @ self.c3)[0])
        return self.last_value

    def update_critic(self, state: ArrayLike, target_value: float, learning_rate: float = 1e-3) -> float:
        s = self._state(state); target = float(target_value); lr = _positive(learning_rate, "learning_rate")
        h1 = np.tanh(s @ self.c1); h2 = np.tanh(h1 @ self.c2)
        old_c3 = self.c3.copy()
        pred = float((h2 @ self.c3)[0]); err = pred - target
        grad3 = h2[:, None] * err
        grad2 = np.outer(h1, (old_c3[:, 0] * err) * (1.0 - h2 * h2))
        grad1 = np.outer(s, (self.c2 @ ((old_c3[:, 0] * err) * (1.0 - h2 * h2))) * (1.0 - h1 * h1))
        self.c3 -= lr * grad3; self.c2 -= lr * grad2; self.c1 -= lr * grad1
        return float(0.5 * err * err)

    def update_actor(self, state: ArrayLike, advantage: float, learning_rate: float = 1e-3) -> None:
        s = self._state(state); adv = float(advantage); lr = _positive(learning_rate, "learning_rate")
        if not math.isfinite(adv):
            raise ValueError("advantage must be finite")
        h1 = np.tanh(s @ self.a1); h2 = np.tanh(h1 @ self.a2)
        z = h2 @ self.a3; action = np.tanh(z)
        # Deterministic policy-gradient surrogate: maximize advantage-weighted
        # action magnitude, with tanh derivative preserving bounded outputs.
        grad_z = -adv * action * (1.0 - action * action)
        grad3 = np.outer(h2, grad_z)
        grad_h2 = self.a3 @ grad_z
        grad2 = np.outer(h1, grad_h2 * (1.0 - h2 * h2))
        grad_h1 = self.a2 @ (grad_h2 * (1.0 - h2 * h2))
        grad1 = np.outer(s, grad_h1 * (1.0 - h1 * h1))
        self.a3 -= lr * grad3; self.a2 -= lr * grad2; self.a1 -= lr * grad1


def friction_aware_advantage(gross_advantage: float, statutory_fees: float, risk_lambda: float, inventory: float, inventory_variance: float) -> float:
    vals = [float(gross_advantage), float(statutory_fees), float(risk_lambda), float(inventory), float(inventory_variance)]
    if not all(math.isfinite(x) for x in vals) or vals[1] < 0 or vals[2] < 0 or vals[4] < 0:
        raise ValueError("invalid friction-aware advantage input")
    return float(vals[0] - vals[1] - vals[2] * vals[3] ** 2 * vals[4])


AGENT_ROLES: Mapping[str, str] = {
    "Abhi": "Operator liaison, sovereign arbitration, capital approval, binding live veto",
    "Alex": "Microstructure, MLOFI, Hawkes and queue risk",
    "Emily": "Rough volatility, macro jump and news IV",
    "Max": "Risk management, statutory friction and Kelly sizing",
}


def squad_consensus(
    net_alpha: float,
    alpha_gate_passed: bool,
    queue_risk_passed: bool,
    volatility_risk_passed: bool,
    capital_approved: bool,
    manager_abhi_veto: bool = True,
) -> Dict[str, Any]:
    """Return an auditable paper/research decision; live dispatch is never approved."""
    vals = (net_alpha,)
    if not all(math.isfinite(float(v)) for v in vals):
        raise ValueError("net_alpha must be finite")
    checks = {
        "Abhi_capital_approval": bool(capital_approved) and not bool(manager_abhi_veto),
        "Alex_queue_risk": bool(queue_risk_passed),
        "Emily_volatility_risk": bool(volatility_risk_passed),
        "Max_net_alpha": bool(alpha_gate_passed) and float(net_alpha) > 0.0,
    }
    return {
        "approved_for_paper_research": bool(all(checks.values())),
        "live_dispatch_approved": False,
        "manager_veto_active": bool(manager_abhi_veto),
        "checks": checks,
        "agents": dict(AGENT_ROLES),
        "ledger_epoch": PAPER_LEDGER_EPOCH,
        "initial_capital_inr": INITIAL_CAPITAL_INR,
    }


def dispatch_live_order(*args: Any, **kwargs: Any) -> None:
    """Permanently disabled live-order entry point."""
    raise PermissionError("Cycle 60 is paper-only: live order dispatch is permanently disabled")


__all__ = [
    "ASSETS", "LIVE_ORDER_DISPATCH_ENABLED", "REAL_BROKER_FILLS_LOCKED", "PAPER_LEDGER_EPOCH", "INITIAL_CAPITAL_INR",
    "MAX_KELLY_FRACTION", "MAX_MPS_BOND_DIM", "MAX_MPS_RELATIVE_ERROR", "spectral_radius",
    "TensorTrainResult", "tensor_train_decompose", "tensor_train_contract", "tensor_greeks", "tensor_train_greeks",
    "MOTBounds", "validate_martingale_plan", "solve_martingale_transport_bounds",
    "multi_level_ofi", "L3QueuePriorityTracker", "MultiAgentHawkesGame", "optimal_toxic_spread",
    "adverse_selection_probability", "should_retreat_quote", "solve_spread_nash_equilibrium",
    "FeeBreakdown", "indian_statutory_fees", "net_alpha_gate", "beta_posterior_fractional_kelly",
    "InventoryBand", "inventory_indifference_band", "inventory_trade_action", "ContinuousActorCritic",
    "friction_aware_advantage", "AGENT_ROLES", "squad_consensus", "dispatch_live_order",
]

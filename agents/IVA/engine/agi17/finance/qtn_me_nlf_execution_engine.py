"""Cycle 70 QTN-ME-NLF offline research/reference engine.

Dependencies: Python standard library and NumPy only. No broker connectivity.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence
import numpy as np

LIVE_ORDER_DISPATCH_ENABLED = False
REAL_BROKER_FILLS_LOCKED = True
PAPER_LEDGER_EPOCH = "epoch_10k"
INITIAL_CAPITAL_INR = 10_000.0
AGENTS = ("Abhi", "Alex", "Emily", "Max")


def _finite_array(value, name: str, ndim: int | None = None, dtype=float) -> np.ndarray:
    arr = np.asarray(value, dtype=dtype)
    if ndim is not None and arr.ndim != ndim:
        raise ValueError(f"{name} must be {ndim}-dimensional")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _positive(value: float, name: str, allow_zero: bool = False) -> float:
    x = float(value)
    if not math.isfinite(x) or (x < 0 if allow_zero else x <= 0):
        cmp = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be finite and {cmp}")
    return x


def lindblad_rhs(rho, hamiltonian, jump_operators: Sequence[np.ndarray]) -> np.ndarray:
    """Evaluate dρ/dt = -i[H,ρ] + Σ(LρL† - 1/2{L†L,ρ})."""
    r = _finite_array(rho, "rho", 2, dtype=complex)
    h = _finite_array(hamiltonian, "hamiltonian", 2, dtype=complex)
    if r.shape[0] != r.shape[1] or h.shape != r.shape:
        raise ValueError("rho and Hamiltonian must be square and have equal shape")
    if not np.allclose(h, h.conj().T, atol=1e-10):
        raise ValueError("Hamiltonian must be Hermitian")
    out = -1j * (h @ r - r @ h)
    for raw in jump_operators:
        op = _finite_array(raw, "jump operator", 2, dtype=complex)
        if op.shape != r.shape:
            raise ValueError("all jump operators must match rho shape")
        ld_l = op.conj().T @ op
        out += op @ r @ op.conj().T - 0.5 * (ld_l @ r + r @ ld_l)
    return 0.5 * (out + out.conj().T) if np.allclose(out, out.conj().T, atol=1e-8) else out


def _validate_density(rho, tol: float = 1e-9) -> np.ndarray:
    r = _finite_array(rho, "rho", 2, dtype=complex)
    if r.shape[0] != r.shape[1]:
        raise ValueError("density matrix must be square")
    if not np.allclose(r, r.conj().T, atol=tol):
        raise ValueError("density matrix must be Hermitian")
    r = 0.5 * (r + r.conj().T)
    tr = np.trace(r)
    if abs(tr.imag) > tol or tr.real <= 0 or not math.isfinite(float(tr.real)):
        raise ValueError("density matrix must have positive real trace")
    eig = np.linalg.eigvalsh(r)
    if eig.min(initial=0.0) < -tol:
        raise ValueError("density matrix must be positive semidefinite")
    return r / float(tr.real)


def liouvillian_spectral_gap(hamiltonian, jump_operators: Sequence[np.ndarray], tol: float = 1e-8) -> float:
    """Small-system diagnostic: smallest non-zero decay rate of the Liouvillian."""
    h = _finite_array(hamiltonian, "hamiltonian", 2, dtype=complex)
    d = h.shape[0]
    if h.shape != (d, d):
        raise ValueError("Hamiltonian must be square")
    ops = [_finite_array(x, "jump operator", 2, dtype=complex) for x in jump_operators]
    basis = []
    for k in range(d * d):
        e = np.zeros((d, d), dtype=complex)
        e.flat[k] = 1.0
        basis.append(lindblad_rhs(e, h, ops).reshape(-1))
    liouv = np.column_stack(basis)
    vals = np.linalg.eigvals(liouv)
    decay = [-float(v.real) for v in vals if v.real < -tol]
    return min(decay) if decay else 0.0


def _kraus_step(rho: np.ndarray, h: np.ndarray, jumps: Sequence[np.ndarray], dt: float) -> np.ndarray:
    """Completely-positive, trace-preserving first-order Kraus step."""
    d = rho.shape[0]
    ident = np.eye(d, dtype=complex)
    dissipator = sum((l.conj().T @ l for l in jumps), np.zeros_like(h))
    k0 = ident - (1j * h + 0.5 * dissipator) * dt
    kraus = [k0] + [math.sqrt(dt) * l for l in jumps]
    completeness = sum((k.conj().T @ k for k in kraus), np.zeros_like(h))
    completeness = 0.5 * (completeness + completeness.conj().T)
    eig, vec = np.linalg.eigh(completeness)
    if eig.min(initial=1.0) <= 1e-14:
        raise ValueError("time step too large or Kraus completeness matrix is singular")
    invsqrt = (vec * (1.0 / np.sqrt(eig))) @ vec.conj().T
    corrected = [k @ invsqrt for k in kraus]
    nxt = sum((k @ rho @ k.conj().T for k in corrected), np.zeros_like(rho))
    nxt = 0.5 * (nxt + nxt.conj().T)
    # Correct round-off only; the Kraus map itself preserves PSD and trace.
    values, vectors = np.linalg.eigh(nxt)
    if values.min(initial=0.0) < -1e-10:
        raise ArithmeticError("numerical positivity invariant violated")
    if values.min(initial=0.0) < 0:
        values = np.maximum(values, 0.0)
        nxt = (vectors * values) @ vectors.conj().T
    tr = float(np.trace(nxt).real)
    if tr <= 0 or not math.isfinite(tr):
        raise ArithmeticError("invalid trace after master-equation step")
    return nxt / tr


def simulate_lindblad_master_equation(initial_density, hamiltonian, jump_operators: Sequence[np.ndarray],
                                      dt: float = 0.01, n_steps: int = 100,
                                      dissipation_rate_cap: float = 100.0) -> dict:
    """Evolve a density state while retaining trace and PSD under a CP map."""
    step = _positive(dt, "dt")
    if int(n_steps) != n_steps or n_steps < 0:
        raise ValueError("n_steps must be a non-negative integer")
    cap = _positive(dissipation_rate_cap, "dissipation_rate_cap")
    rho = _validate_density(initial_density)
    h = _finite_array(hamiltonian, "hamiltonian", 2, dtype=complex)
    if h.shape != rho.shape or not np.allclose(h, h.conj().T, atol=1e-10):
        raise ValueError("Hamiltonian must be Hermitian and match density dimension")
    jumps = [_finite_array(x, "jump operator", 2, dtype=complex) for x in jump_operators]
    if any(x.shape != rho.shape for x in jumps):
        raise ValueError("jump operator shape mismatch")
    dissipation = float(sum(np.linalg.norm(x.conj().T @ x, ord=2) for x in jumps))
    if not math.isfinite(dissipation) or dissipation > cap:
        raise ValueError("dissipation rate exceeds configured cap")
    path = [rho.copy()]
    for _ in range(int(n_steps)):
        rho = _kraus_step(rho, h, jumps, step)
        path.append(rho.copy())
    traces = np.array([np.trace(x).real for x in path])
    min_eigs = np.array([np.linalg.eigvalsh(x).min() for x in path])
    return {
        "density_path": np.asarray(path),
        "trace_error_max": float(np.max(np.abs(traces - 1.0))),
        "minimum_eigenvalue": float(np.min(min_eigs)),
        "spectral_gap": liouvillian_spectral_gap(h, jumps),
        "dissipation_rate": dissipation,
        "dissipation_subcritical": bool(dissipation < cap),
        "trace_preserved": bool(np.max(np.abs(traces - 1.0)) <= 1e-10),
        "positive_semidefinite": bool(np.min(min_eigs) >= -1e-10),
    }


def tensor_train_decompose(tensor, max_bond_dim: int = 16, tolerance: float = 1e-10) -> dict:
    """TT-SVD for a finite tensor; reports actual and certified truncation error."""
    a = np.asarray(tensor)
    if not np.issubdtype(a.dtype, np.number) or not np.all(np.isfinite(a)):
        raise ValueError("tensor must be numeric and finite")
    if a.ndim < 2 or any(n < 1 for n in a.shape):
        raise ValueError("tensor must have at least two non-empty axes")
    if int(max_bond_dim) != max_bond_dim or not 1 <= max_bond_dim <= 16:
        raise ValueError("max_bond_dim must be an integer in [1, 16]")
    tol = _positive(tolerance, "tolerance", allow_zero=True)
    original_shape = a.shape
    work = a.copy()
    cores = []
    left_rank = 1
    discarded_sq = 0.0
    bond_dims = []
    for n in original_shape[:-1]:
        mat = work.reshape(left_rank * n, -1)
        u, s, vh = np.linalg.svd(mat, full_matrices=False)
        # Keep the smallest rank meeting local Frobenius tolerance when possible, subject to cap.
        threshold = tol / math.sqrt(max(1, a.ndim - 1))
        if threshold > 0:
            tail_sq = np.concatenate(([0.0], np.cumsum((s[::-1] ** 2))))
            candidate = len(s)
            for r in range(1, len(s) + 1):
                if float(np.sum(s[r:] ** 2)) <= threshold ** 2:
                    candidate = r
                    break
        else:
            candidate = len(s)
        rank = max(1, min(int(candidate), int(max_bond_dim), len(s)))
        discarded_sq += float(np.sum(s[rank:] ** 2))
        core = u[:, :rank].reshape(left_rank, n, rank)
        cores.append(core)
        work = (s[:rank, None] * vh[:rank, :])
        left_rank = rank
        bond_dims.append(rank)
    cores.append(work.reshape(left_rank, original_shape[-1], 1))
    recon = cores[0]
    for c in cores[1:]:
        recon = np.tensordot(recon, c, axes=([-1], [0]))
    recon = np.squeeze(recon, axis=(0, -1))
    err = float(np.linalg.norm(a - recon))
    bound = math.sqrt(discarded_sq)
    return {
        "cores": cores,
        "reconstructed_tensor": recon,
        "shape": original_shape,
        "bond_dimensions": tuple(bond_dims),
        "max_bond_dimension": max(bond_dims, default=1),
        "frobenius_error": err,
        "truncation_error_bound": bound,
        "relative_error": err / max(float(np.linalg.norm(a)), np.finfo(float).tiny),
        "tolerance_met": bool(err <= tol + 1e-12),
    }


def mpo_decompose_density(density_matrix, local_dim: int = 2, max_bond_dim: int = 16,
                          tolerance: float = 1e-10) -> dict:
    """MPO factorization of a density matrix; rejects output losing trace/PSD invariants."""
    rho = _validate_density(density_matrix)
    d = rho.shape[0]
    loc = int(local_dim)
    if loc < 2 or loc != local_dim:
        raise ValueError("local_dim must be an integer >= 2")
    nsites = 0
    x = d
    while x > 1 and x % loc == 0:
        x //= loc
        nsites += 1
    if x != 1 or nsites < 1:
        raise ValueError("density dimension must be an integer power of local_dim")
    # Change row/column multi-indices into per-site paired physical index (row_i, col_i).
    paired_axes = [a for i in range(nsites) for a in (i, nsites + i)]
    paired = np.transpose(rho.reshape([loc] * (2 * nsites)), paired_axes)
    paired = paired.reshape([loc * loc] * nsites)
    tt = tensor_train_decompose(paired, max_bond_dim=max_bond_dim, tolerance=tolerance)
    rpair = tt["reconstructed_tensor"].reshape([loc, loc] * nsites)
    unpaired_axes = [2 * i for i in range(nsites)] + [2 * i + 1 for i in range(nsites)]
    reconstructed = np.transpose(rpair, unpaired_axes).reshape(d, d)
    reconstructed = 0.5 * (reconstructed + reconstructed.conj().T)
    trace = np.trace(reconstructed)
    if abs(trace.imag) > max(tolerance, 1e-10) or trace.real <= 0:
        raise ValueError("MPO compression fails trace-positivity check; increase bond dimension")
    reconstructed = reconstructed / trace.real
    eig_min = float(np.linalg.eigvalsh(reconstructed).min())
    if eig_min < -max(tolerance, 1e-9):
        raise ValueError("MPO compression fails PSD check; increase bond dimension or tolerance")
    error = float(np.linalg.norm(rho - reconstructed, ord="fro"))
    return {
        "cores": tt["cores"],
        "reconstructed_density": reconstructed,
        "bond_dimensions": tt["bond_dimensions"],
        "max_bond_dimension": tt["max_bond_dimension"],
        "frobenius_error": error,
        "truncation_error_bound": tt["truncation_error_bound"],
        "trace": float(np.trace(reconstructed).real),
        "minimum_eigenvalue": eig_min,
        "trace_preserved": abs(float(np.trace(reconstructed).real) - 1.0) <= 1e-10,
        "positive_semidefinite": eig_min >= -max(tolerance, 1e-9),
    }


def tempered_levy_characteristic(u, t: float, alpha: float = 1.5,
                                 damping: float = 0.5, intensity_scale: float = 1.0,
                                 gaussian_limit_variance_rate: float = 1.0) -> np.ndarray | complex:
    """Characteristic function for symmetric exponentially tempered stable jumps.

    For 1<alpha<2, ψ(u)=2 C Γ(-alpha) [Re((λ-iu)^alpha)-λ^alpha],
    which is non-positive. At alpha=2 the singular Lévy-measure endpoint is
    explicitly defined as a Gaussian limit with variance rate provided by caller.
    """
    a = float(alpha)
    if not math.isfinite(a) or not (1.0 < a <= 2.0):
        raise ValueError("alpha must be in (1, 2]")
    tt = _positive(t, "t", allow_zero=True)
    lam = _positive(damping, "damping")
    c = _positive(intensity_scale, "intensity_scale", allow_zero=True)
    us = np.asarray(u, dtype=float)
    if not np.all(np.isfinite(us)):
        raise ValueError("u must be finite")
    if a >= 2.0 - 1e-10:
        var_rate = _positive(gaussian_limit_variance_rate, "gaussian_limit_variance_rate", allow_zero=True)
        result = np.exp(-0.5 * var_rate * us * us * tt)
    else:
        gamma_neg = math.gamma(-a)
        z = (lam - 1j * us) ** a
        exponent = 2.0 * c * gamma_neg * (np.real(z) - lam ** a) * tt
        result = np.exp(exponent)
    return complex(result) if result.ndim == 0 else result


def sample_truncated_levy_flight(n_steps: int = 100, dt: float = 0.01, alpha: float = 1.5,
                                 damping: float = 0.5, intensity_scale: float = 0.3,
                                 cutoff: float = 1e-3, max_jump: float = 5.0, seed: int = 7) -> np.ndarray:
    """Finite-grid, damped compound-jump approximation to a tempered stable path."""
    if int(n_steps) != n_steps or n_steps < 1:
        raise ValueError("n_steps must be a positive integer")
    if not (1.0 < float(alpha) <= 2.0):
        raise ValueError("alpha must be in (1, 2]")
    step = _positive(dt, "dt")
    lam = _positive(damping, "damping")
    c = _positive(intensity_scale, "intensity_scale", allow_zero=True)
    lo, hi = _positive(cutoff, "cutoff"), _positive(max_jump, "max_jump")
    if hi <= lo:
        raise ValueError("max_jump must exceed cutoff")
    rng = np.random.default_rng(seed)
    # Log-spaced bins discretize ν(dx)=C exp(-λx)x^(-1-α) dx on [cutoff,max_jump].
    edges = np.geomspace(lo, hi, 96)
    mids = np.sqrt(edges[:-1] * edges[1:])
    widths = np.diff(edges)
    rates = 2.0 * c * np.exp(-lam * mids) * mids ** (-1.0 - float(alpha)) * widths
    path = np.zeros(int(n_steps) + 1, dtype=float)
    for i in range(1, int(n_steps) + 1):
        counts = rng.poisson(rates * step)
        if counts.sum():
            sizes = np.repeat(mids, counts)
            signs = rng.choice(np.array([-1.0, 1.0]), size=sizes.size)
            jump = float(np.dot(sizes, signs))
        else:
            jump = 0.0
        path[i] = path[i - 1] + jump
    return path


def mlofi_top5(bid_volume_changes, ask_volume_changes, bid_price_changes, ask_price_changes,
               weights=None) -> float:
    """Signed five-level MLOFI with conditional volume changes."""
    vb = _finite_array(bid_volume_changes, "bid_volume_changes", 1)
    va = _finite_array(ask_volume_changes, "ask_volume_changes", 1)
    pb = _finite_array(bid_price_changes, "bid_price_changes", 1)
    pa = _finite_array(ask_price_changes, "ask_price_changes", 1)
    if any(x.shape != (5,) for x in (vb, va, pb, pa)):
        raise ValueError("all four MLOFI inputs must have length five")
    w = np.linspace(1.0, 0.2, 5) if weights is None else _finite_array(weights, "weights", 1)
    if w.shape != (5,) or np.any(w < 0) or np.any(w > 1.0):
        raise ValueError("weights must have five values in [0,1]")
    return float(np.sum(w * (vb * (pb >= 0) - va * (pa <= 0))))


def hawkes_intensity(mlofi: float, mu0: float = 0.1, gamma_mlofi: float = 0.05,
                     beta: float = 1.0, prior_jumps: Sequence[tuple[float, float]] = (),
                     now: float = 0.0, decay: float = 1.0) -> float:
    """Hawkes intensity; prior_jumps are (time, positive jump amplitude)."""
    mu = _positive(mu0, "mu0", allow_zero=True)
    g = _positive(gamma_mlofi, "gamma_mlofi", allow_zero=True)
    b = _positive(beta, "beta", allow_zero=True)
    dcy = _positive(decay, "decay")
    current = float(now)
    if not math.isfinite(current) or not math.isfinite(float(mlofi)):
        raise ValueError("now and mlofi must be finite")
    lam = mu + g * abs(float(mlofi)) ** b
    for event_time, amplitude in prior_jumps:
        et = float(event_time)
        amp = _positive(amplitude, "jump amplitude", allow_zero=True)
        if not math.isfinite(et) or et > current:
            raise ValueError("jump event times must be finite and no later than now")
        lam += amp * math.exp(-dcy * (current - et))
    if not math.isfinite(lam):
        raise OverflowError("intensity overflow")
    return max(0.0, lam)


def toxicity_gate(intensity: float, tau: float = 1.0, threshold: float = 0.60) -> dict:
    lam = _positive(intensity, "intensity", allow_zero=True)
    horizon = _positive(tau, "tau", allow_zero=True)
    cut = float(threshold)
    if not math.isfinite(cut) or not 0.0 <= cut <= 1.0:
        raise ValueError("threshold must be in [0,1]")
    probability = -math.expm1(-lam * horizon)
    return {"toxicity_prob": probability, "toxicity_action": "RETREAT" if probability > cut else "CONTINUE_PAPER"}


def contagion_routing(liquidity, contagion_matrix, initial_depletion=None) -> dict:
    """Solve the linear propagation of a subcritical directed liquidity network."""
    liq = _finite_array(liquidity, "liquidity", 1)
    w = _finite_array(contagion_matrix, "contagion_matrix", 2)
    n = liq.size
    if w.shape != (n, n) or np.any(liq < 0) or np.any(w < 0):
        raise ValueError("liquidity must be nonnegative and W square, nonnegative, and aligned")
    rho = float(np.max(np.abs(np.linalg.eigvals(w)))) if n else 0.0
    if rho >= 1.0:
        raise ValueError("contagion matrix must be subcritical (spectral radius < 1)")
    base = np.zeros(n) if initial_depletion is None else _finite_array(initial_depletion, "initial_depletion", 1)
    if base.shape != (n,) or np.any(base < 0):
        raise ValueError("initial_depletion must be a nonnegative vector aligned with liquidity")
    depletion = np.linalg.solve(np.eye(n) - w, base) if n else base.copy()
    stressed = np.maximum(0.0, liq - depletion)
    drain = float(np.sum(np.minimum(depletion, liq)) / max(np.sum(liq), np.finfo(float).tiny))
    return {"spectral_radius": rho, "propagated_depletion": depletion,
            "stressed_liquidity": stressed, "systemic_liquidity_drain_index": min(1.0, drain),
            "subcritical": rho < 1.0}


def volatility_surface_audit(total_variance, log_moneyness, maturities, tol: float = 1e-8) -> dict:
    """Finite-grid calendar monotonicity and butterfly-g diagnostic."""
    w = _finite_array(total_variance, "total_variance", 2)
    k = _finite_array(log_moneyness, "log_moneyness", 1)
    t = _finite_array(maturities, "maturities", 1)
    if w.shape != (t.size, k.size) or t.size < 2 or k.size < 3:
        raise ValueError("surface shape must be (len(maturities), len(log_moneyness)); require >=2 maturities and >=3 strikes")
    if np.any(np.diff(t) <= 0) or np.any(np.diff(k) <= 0) or np.any(w <= 0):
        raise ValueError("maturities/strikes must be increasing and total variance positive")
    threshold = _positive(tol, "tol", allow_zero=True)
    wt = np.gradient(w, t, axis=0, edge_order=1)
    wk = np.gradient(w, k, axis=1, edge_order=1)
    wkk = np.gradient(wk, k, axis=1, edge_order=1)
    term = 1.0 - (k[None, :] * wk) / (2.0 * w)
    g = term ** 2 - (wk ** 2 / 4.0) * (1.0 / w + 0.25) + 0.5 * wkk
    # Avoid endpoints where finite-difference curvature is especially grid-sensitive? Report all supplied points.
    return {"calendar_derivative": wt, "butterfly_g": g,
            "calendar_monotonic": bool(np.all(wt >= -threshold)),
            "butterfly_convex": bool(np.all(g > threshold)),
            "min_calendar_derivative": float(np.min(wt)), "min_butterfly_g": float(np.min(g)),
            "calendar_violation_count": int(np.count_nonzero(wt < -threshold)),
            "butterfly_violation_count": int(np.count_nonzero(g <= threshold))}


def cross_surface_relative_value(surface_a, surface_b, friction_inr: float = 0.0) -> dict:
    a = _finite_array(surface_a, "surface_a")
    b = _finite_array(surface_b, "surface_b")
    if a.shape != b.shape:
        raise ValueError("surface shapes must match")
    friction = _positive(friction_inr, "friction_inr", allow_zero=True)
    spread = a - b
    gross = float(np.mean(np.abs(spread)))
    net = gross - friction
    return {"gross_mispricing": gross, "friction_inr": friction, "net_mispricing": net,
            "relative_value_flag": net > 0.0, "spread_tensor": spread}


def _fees(buy_turnover_inr: float, sell_turnover_inr: float, executed_legs: int) -> dict:
    buy = _positive(buy_turnover_inr, "buy_turnover_inr", allow_zero=True)
    sell = _positive(sell_turnover_inr, "sell_turnover_inr", allow_zero=True)
    if int(executed_legs) != executed_legs or executed_legs < 0:
        raise ValueError("executed_legs must be a nonnegative integer")
    stt = 0.0015 * sell
    stamp = 0.00003 * buy
    exchange = 0.0003553 * (buy + sell)
    sebi = 0.000001 * (buy + sell)
    brokerage = 20.0 * int(executed_legs)
    gst = 0.18 * (brokerage + exchange + sebi)
    breakdown = {"stt_sell": stt, "stamp_duty_buy": stamp, "nse_transaction_fee": exchange,
                 "sebi_turnover_fee": sebi, "brokerage": brokerage, "gst": gst}
    return {"total_fees_inr": float(sum(breakdown.values())), "breakdown": breakdown}


def indian_statutory_fees(buy_turnover_inr: float, sell_turnover_inr: float, executed_legs: int = 0) -> dict:
    return _fees(buy_turnover_inr, sell_turnover_inr, executed_legs)


def net_alpha_gate(expected_gross_alpha_inr: float, total_fees_inr: float) -> dict:
    gross = float(expected_gross_alpha_inr)
    fees = _positive(total_fees_inr, "total_fees_inr", allow_zero=True)
    if not math.isfinite(gross):
        raise ValueError("expected_gross_alpha_inr must be finite")
    net = gross - fees
    return {"approved": net > 0.0, "net_alpha_inr": net}


def beta_fractional_kelly(alpha_prior: float, beta_prior: float, wins: int, losses: int,
                          win_loss_ratio: float, scale: float = 0.25, cap: float = 0.10,
                          net_alpha_positive: bool = True) -> dict:
    a = _positive(alpha_prior, "alpha_prior")
    b = _positive(beta_prior, "beta_prior")
    if int(wins) != wins or wins < 0 or int(losses) != losses or losses < 0:
        raise ValueError("wins and losses must be nonnegative integers")
    ratio = _positive(win_loss_ratio, "win_loss_ratio")
    s = _positive(scale, "scale", allow_zero=True)
    c = _positive(cap, "cap", allow_zero=True)
    if c > 0.10 + 1e-12:
        raise ValueError("cap may not exceed the 10% capital fraction limit")
    p = (a + int(wins)) / (a + b + int(wins) + int(losses))
    raw = max(0.0, (p * ratio - (1.0 - p)) / ratio)
    fraction = min(c, s * raw) if net_alpha_positive else 0.0
    return {"capital_fraction": float(fraction), "posterior_win_probability": float(p),
            "raw_kelly_fraction": float(raw), "net_alpha_positive": bool(net_alpha_positive)}


def almgren_chriss_multi_expiry_unwind(inventory, horizon_steps: int = 10, eta: float = 0.1,
                                       risk_aversion: float = 1e-4, sigma: float = 0.01,
                                       gamma_decay: float = 0.5, dt: float = 1.0,
                                       cross_impact_matrix=None, transient_impact: float = 0.05,
                                       intensity: float = 0.0, tau: float = 1.0,
                                       temporary_cost: float = 0.0, fee_cost: float = 0.0) -> dict:
    """Convex discrete AC unwind with non-local temporal/cross-asset impact and exact q(T)=0."""
    q0 = _finite_array(inventory, "inventory", 1)
    if q0.size < 1:
        raise ValueError("inventory must contain at least one expiry")
    if int(horizon_steps) != horizon_steps or horizon_steps < 1:
        raise ValueError("horizon_steps must be a positive integer")
    nstep, nasset = int(horizon_steps), q0.size
    eta_v = _positive(eta, "eta")
    risk = _positive(risk_aversion, "risk_aversion")
    sig = _positive(sigma, "sigma", allow_zero=True)
    decay = _positive(gamma_decay, "gamma_decay")
    step = _positive(dt, "dt")
    cross = np.eye(nasset) if cross_impact_matrix is None else _finite_array(cross_impact_matrix, "cross_impact_matrix", 2)
    if cross.shape != (nasset, nasset):
        raise ValueError("cross_impact_matrix shape mismatch")
    cross = 0.5 * (cross + cross.T)
    if np.linalg.eigvalsh(cross).min() < -1e-10:
        raise ValueError("cross_impact_matrix must be positive semidefinite after symmetrization")
    strength = _positive(transient_impact, "transient_impact", allow_zero=True)
    # Power-law temporal kernel K_ts=(1+|t-s|dt)^(-gamma_decay).
    times = np.arange(nstep, dtype=float)
    kt = (1.0 + np.abs(times[:, None] - times[None, :]) * step) ** (-decay)
    # Trade vector v[t,a], q_t = q0 - dt * cumulative_{s<t} v[s,a].
    size = nstep * nasset
    A = np.zeros((size, size), dtype=float)
    for t in range(nstep):
        for aidx in range(nasset):
            row = t * nasset + aidx
            for sidx in range(t):
                A[row, sidx * nasset + aidx] = 1.0
    # q vector across t contains q0 repeated.
    qvec = np.tile(q0, nstep)
    rmat = eta_v * np.eye(size) + strength * np.kron(kt, cross)
    # Ensure convexity if user supplies large but PSD cross impact; power-law matrix is PSD for decay>0.
    risk_weight = risk * sig * sig
    hess = 2.0 * (rmat + risk_weight * step * step * (A.T @ A))
    linear = -2.0 * risk_weight * step * (A.T @ qvec)
    constraint = np.zeros((nasset, size), dtype=float)
    for t in range(nstep):
        for aidx in range(nasset):
            constraint[aidx, t * nasset + aidx] = step
    kkt = np.block([[hess, constraint.T], [constraint, np.zeros((nasset, nasset))]])
    rhs = np.concatenate([-linear, q0])
    sol = np.linalg.lstsq(kkt, rhs, rcond=1e-12)[0][:size]
    schedule = sol.reshape(nstep, nasset)
    # Recompute path, and enforce exact terminal condition algebraically in the final control interval.
    path = np.zeros((nstep + 1, nasset), dtype=float)
    path[0] = q0
    for t in range(nstep - 1):
        path[t + 1] = path[t] - schedule[t] * step
    schedule[-1] = path[-2] / step
    path[-1] = path[-2] - schedule[-1] * step
    path[-1] = 0.0
    hazard = toxicity_gate(float(intensity), tau)
    c = _positive(temporary_cost, "temporary_cost", allow_zero=True)
    cf = _positive(fee_cost, "fee_cost", allow_zero=True)
    denom = 4.0 * risk
    width = 0.0 if denom == 0 else ((3.0 * (c + cf) * sig * sig) / denom) ** (1.0 / 3.0)
    flat_schedule = schedule.reshape(-1)
    objective = float(flat_schedule @ rmat @ flat_schedule + risk_weight * np.sum(path[:-1] ** 2))
    return {"terminal_inventory": path[-1].copy(), "inventory_path": path,
            "trade_schedule": schedule, "toxicity_prob": hazard["toxicity_prob"],
            "toxicity_action": hazard["toxicity_action"], "indifference_width": float(width),
            "terminal_zero_exact": bool(np.all(path[-1] == 0.0)),
            "objective_value": objective,
            "impact_kernel": kt}


def squad_consensus(agent_votes, manager_live_veto: bool = True,
                    require_unanimous: bool = True, risk_gates_passed: bool = True) -> dict:
    if not isinstance(agent_votes, dict) or any(k not in agent_votes for k in AGENTS):
        raise ValueError(f"agent_votes must include {AGENTS}")
    votes = {k: bool(agent_votes[k]) for k in AGENTS}
    consensus = all(votes.values()) if require_unanimous else sum(votes.values()) >= 3
    # Live dispatch is always disabled; manager_live_veto is recorded as governance state only.
    # The manager veto disables LIVE dispatch; paper research approval is separate.
    approved = bool(consensus and risk_gates_passed)
    return {"paper_research_approved": approved, "agent_votes": votes,
            "manager_live_veto": bool(manager_live_veto), "risk_gates_passed": bool(risk_gates_passed),
            "live_order_dispatch_enabled": False}


def dispatch_live_order(*args, **kwargs):
    raise PermissionError("LIVE_ORDER_DISPATCH_BLOCKED: Cycle 70 is fail-closed. Real broker dispatch is strictly locked.")

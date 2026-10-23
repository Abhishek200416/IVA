"""SABR & SVI Arbitrage-Free Implied Volatility Surface Calibrator.

Wave 35 Deliverable (TASK-BN-45):
Synthesized for Indian Index Options (Bank Nifty & Nifty 50):
1. Hagan et al. (2002) SABR Closed-Form Formula:
   - Evaluates implied Black volatility sigma_B(F, K, T) as a function of forward price F,
     strike K, and time-to-expiry T:
     * Parameters: alpha (initial volatility), beta (CEV elasticity, beta=1.0 for lognormal),
       rho (spot-vol correlation in (-1, 1)), nu (vol-of-vol > 0).
   - Exact ATM limit (F = K) and general formula for OTM wings with asymptotic expansion.
2. Gatheral (2004) Raw Stochastic Volatility Inspired (SVI) Model:
   - Total implied variance w(k) = sigma^2(k) * T parameterized across log-moneyness k = ln(K / F):
     w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma_svi^2))
   - Parameters: a, b >= 0, |rho| < 1, m, sigma_svi > 0.
3. No-Arbitrage Verification Engine:
   - Positivity constraint: w(k) >= 0 everywhere (a + b * sigma_svi * sqrt(1 - rho^2) >= 0).
   - Lee Wing Slope constraint: b * (1 + |rho|) < 2 (prevents Roger & Tehranchi moment explosions).
   - Butterfly arbitrage test (Durrleman condition):
     Risk-neutral probability density g(k) >= 0:
     g(k) = (1 - k * w'(k) / (2 * w(k)))^2 - (w'(k)^2 / 4) * (1 / w(k) + 0.25) + 0.5 * w''(k) >= 0.
   - Calendar spread monotonicity: w(k, T_2) >= w(k, T_1) for T_2 > T_1.

Zero external dependencies outside standard library math, dataclasses, and typing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Fail-Closed Institutional Safety Invariant:
# Live order dispatch is permanently locked to False across all analytical engines.
LIVE_ORDER_DISPATCH_ENABLED: bool = False

try:
    from .authoritative_cost_calculator import (
        AuthoritativeCostCalculator,
        BrokerageModel,
        InstrumentCategory,
        OrderSide,
        RegulatoryRegime,
    )
except ImportError:
    from authoritative_cost_calculator import (  # type: ignore
        AuthoritativeCostCalculator,
        BrokerageModel,
        InstrumentCategory,
        OrderSide,
        RegulatoryRegime,
    )


class VolatilityModelType(str, Enum):
    SABR = "SABR"
    SVI = "SVI"


@dataclass(frozen=True)
class SABRParameters:
    """Parameters for Hagan et al. (2002) SABR Model."""
    alpha: float      # Initial volatility (alpha > 0)
    beta: float       # CEV elasticity (0 <= beta <= 1.0)
    rho: float        # Spot-vol correlation (-1.0 < rho < 1.0)
    nu: float         # Volatility of volatility (nu >= 0)

    def validate(self) -> None:
        if self.alpha <= 0.0:
            raise ValueError(f"SABR alpha must be strictly positive, got {self.alpha}")
        if not (0.0 <= self.beta <= 1.0):
            raise ValueError(f"SABR beta must be in [0.0, 1.0], got {self.beta}")
        if not (-1.0 < self.rho < 1.0):
            raise ValueError(f"SABR rho must be in (-1.0, 1.0), got {self.rho}")
        if self.nu < 0.0:
            raise ValueError(f"SABR nu must be non-negative, got {self.nu}")


@dataclass(frozen=True)
class SVIParameters:
    """Parameters for Gatheral (2004) Raw SVI Formulation.
    
    Total implied variance w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma^2))
    
    Invariant Constraints:
    - b >= 0 (wing slope magnitude non-negative)
    - |rho| < 1.0 (correlation strictly inside open unit interval (-1, 1))
    - sigma > 0 (vertex smoothness strictly positive)
    - a + b * sigma * sqrt(1 - rho^2) >= 0 (minimum variance non-negativity across all k in R)
    """
    a: float          # Baseline variance level
    b: float          # Wing angle / slope magnitude (b >= 0)
    rho: float        # Skew parameter (-1.0 < rho < 1.0)
    m: float          # Horizontal translation (vertex location)
    sigma: float      # Vertex curvature / smoothness (sigma > 0)

    @property
    def min_variance(self) -> float:
        """Analytical minimum total variance w_min = a + b * sigma * sqrt(1 - rho^2)."""
        return self.a + self.b * self.sigma * math.sqrt(max(0.0, 1.0 - self.rho ** 2))

    def validate(self) -> None:
        if self.b < 0.0:
            raise ValueError(f"SVI b must be non-negative (b >= 0), got {self.b}")
        if not (-1.0 < self.rho < 1.0):
            raise ValueError(f"SVI rho must be strictly in (-1.0, 1.0) (|rho| < 1), got {self.rho}")
        if self.sigma <= 0.0:
            raise ValueError(f"SVI sigma must be strictly positive (sigma > 0), got {self.sigma}")
        # Minimum variance bound: a + b * sigma * sqrt(1 - rho^2) >= 0
        min_var = self.min_variance
        if min_var < -1e-9:
            raise ValueError(
                f"SVI parameters violate positive variance condition: "
                f"a + b * sigma * sqrt(1 - rho^2) = {min_var:.8f} < 0"
            )


@dataclass(frozen=True)
class SSVIParameters:
    """Parameters for Gatheral & Jacquier (2014) Surface SVI (SSVI).
    
    Total variance:
        w(k, theta) = (theta / 2) * [1 + rho * phi(theta) * k + sqrt((phi(theta)*k + rho)^2 + (1 - rho^2))]
    where phi(theta) = eta / (theta^gamma * (1 + theta)^(1 - gamma)).
    """
    theta: float        # ATM total variance (theta > 0)
    rho: float          # Correlation parameter (-1.0 < rho < 1.0)
    eta: float          # Wing curvature parameter (eta > 0)
    gamma: float = 0.5  # Power law exponent (0.0 < gamma <= 1.0)

    def validate(self) -> None:
        if self.theta <= 0.0:
            raise ValueError(f"SSVI theta must be strictly positive, got {self.theta}")
        if not (-1.0 < self.rho < 1.0):
            raise ValueError(f"SSVI rho must be in (-1.0, 1.0), got {self.rho}")
        if self.eta <= 0.0:
            raise ValueError(f"SSVI eta must be strictly positive, got {self.eta}")
        if not (0.0 < self.gamma <= 1.0):
            raise ValueError(f"SSVI gamma must be in (0.0, 1.0], got {self.gamma}")


@dataclass(frozen=True)
class ModelUncertaintySkewResult:
    """Model-uncertainty-aware skew z-score evaluation result.
    
    z_t = (IV_market - IV_model) / sqrt(s_quote^2 + s_model^2 + s_parameter^2)
    """
    z_score: float
    iv_market: float
    iv_model: float
    iv_diff: float
    s_quote: float
    s_model: float
    s_parameter: float
    total_uncertainty: float
    is_statistically_significant: bool  # |z_t| >= threshold (default 2.0)
    regime: str                         # "OVERPRICED", "UNDERPRICED", "FAIR_VALUE"
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "z_score": self.z_score,
            "iv_market": self.iv_market,
            "iv_model": self.iv_model,
            "iv_diff": self.iv_diff,
            "s_quote": self.s_quote,
            "s_model": self.s_model,
            "s_parameter": self.s_parameter,
            "total_uncertainty": self.total_uncertainty,
            "is_statistically_significant": self.is_statistically_significant,
            "regime": self.regime,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class FrictionAwareKellyResult:
    """Friction-aware Bayesian Kelly allocation under downside semi-variance with Indian statutory deductions."""
    gross_edge_pts: float
    gross_return_pct: float
    statutory_friction_inr: float
    friction_pct: float
    net_return_pct: float
    downside_semi_variance: float
    full_kelly_fraction: float
    fractional_kelly_fraction: float
    effective_allocation_fraction: float
    allocated_capital_inr: float
    quantized_lots: int
    quantized_contracts: int
    margin_utilized_inr: float
    cash_buffer_remaining_inr: float
    is_actionable: bool
    fail_closed_reason: Optional[str]
    live_order_dispatch_enabled: bool  # Strictly False invariant

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gross_edge_pts": self.gross_edge_pts,
            "gross_return_pct": self.gross_return_pct,
            "statutory_friction_inr": self.statutory_friction_inr,
            "friction_pct": self.friction_pct,
            "net_return_pct": self.net_return_pct,
            "downside_semi_variance": self.downside_semi_variance,
            "full_kelly_fraction": self.full_kelly_fraction,
            "fractional_kelly_fraction": self.fractional_kelly_fraction,
            "effective_allocation_fraction": self.effective_allocation_fraction,
            "allocated_capital_inr": self.allocated_capital_inr,
            "quantized_lots": self.quantized_lots,
            "quantized_contracts": self.quantized_contracts,
            "margin_utilized_inr": self.margin_utilized_inr,
            "cash_buffer_remaining_inr": self.cash_buffer_remaining_inr,
            "is_actionable": self.is_actionable,
            "fail_closed_reason": self.fail_closed_reason,
            "live_order_dispatch_enabled": self.live_order_dispatch_enabled,
        }


@dataclass(frozen=True)
class ArbitrageAuditResult:
    """No-arbitrage invariant verification result across a strike grid."""
    has_calendar_arbitrage: bool
    has_butterfly_arbitrage: bool
    has_negative_variance: bool
    min_density_value: float
    max_wing_slope: float
    is_arbitrage_free: bool
    violations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_calendar_arbitrage": self.has_calendar_arbitrage,
            "has_butterfly_arbitrage": self.has_butterfly_arbitrage,
            "has_negative_variance": self.has_negative_variance,
            "min_density": round(self.min_density_value, 6),
            "max_wing_slope": round(self.max_wing_slope, 4),
            "is_arbitrage_free": self.is_arbitrage_free,
            "violations": self.violations,
        }


class SabrSviCalibrator:
    """Institutional SABR & SVI Calibration and Arbitrage Validation Engine."""

    @staticmethod
    def calculate_sabr_volatility(
        forward: float,
        strike: float,
        expiry_years: float,
        params: SABRParameters,
    ) -> float:
        """Hagan et al. (2002) analytical SABR implied Black volatility."""
        params.validate()
        if forward <= 0.0 or strike <= 0.0 or expiry_years <= 0.0:
            raise ValueError("Forward, strike, and expiry must be strictly positive.")

        f = forward
        k = strike
        t = expiry_years
        alpha = params.alpha
        beta = params.beta
        rho = params.rho
        nu = params.nu

        one_minus_beta = 1.0 - beta

        # ATM special limit (F == K)
        if abs(f - k) < 1e-8:
            fk_beta = f ** one_minus_beta
            term1 = alpha / fk_beta
            term2 = (
                (one_minus_beta ** 2 / 24.0) * (alpha ** 2 / (f ** (2.0 * one_minus_beta)))
                + (0.25 * rho * beta * nu * alpha / fk_beta)
                + ((2.0 - 3.0 * rho ** 2) / 24.0) * (nu ** 2)
            )
            return term1 * (1.0 + term2 * t)

        # General OTM formula
        log_fk = math.log(f / k)
        fk_prod = f * k
        fk_mid = fk_prod ** (one_minus_beta / 2.0)

        # z and chi(z)
        z = (nu / alpha) * fk_mid * log_fk
        # Clamp radicand
        radicand = max(1e-12, 1.0 - 2.0 * rho * z + z * z)
        sqrt_term = math.sqrt(radicand)
        chi_arg = (sqrt_term + z - rho) / (1.0 - rho)
        if chi_arg <= 1e-12:
            chi_arg = 1e-12
        chi = math.log(chi_arg)

        # Numerator & Denominators
        z_over_chi = 1.0 if abs(z) < 1e-6 else z / chi

        denom1 = fk_mid * (
            1.0
            + (one_minus_beta ** 2 / 24.0) * (log_fk ** 2)
            + (one_minus_beta ** 4 / 1920.0) * (log_fk ** 4)
        )
        if denom1 <= 1e-12:
            denom1 = 1e-12

        term_growth = (
            (one_minus_beta ** 2 / 24.0) * (alpha ** 2 / (fk_prod ** one_minus_beta))
            + (0.25 * rho * beta * nu * alpha / fk_mid)
            + ((2.0 - 3.0 * rho ** 2) / 24.0) * (nu ** 2)
        )

        vol = (alpha / denom1) * z_over_chi * (1.0 + term_growth * t)
        return max(0.001, vol)

    @staticmethod
    def calculate_svi_total_variance(
        log_moneyness: float,
        params: SVIParameters,
    ) -> float:
        """Gatheral (2004) Raw SVI total variance: w(k) = a + b * (rho*(k-m) + sqrt((k-m)^2 + sigma^2))."""
        params.validate()
        k = log_moneyness
        diff = k - params.m
        disc = math.sqrt(diff * diff + params.sigma * params.sigma)
        w = params.a + params.b * (params.rho * diff + disc)
        return max(0.0, w)

    @classmethod
    def calculate_svi_implied_volatility(
        cls,
        forward: float,
        strike: float,
        expiry_years: float,
        params: SVIParameters,
    ) -> float:
        """Derive implied Black volatility sigma = sqrt(w(k) / T) from SVI total variance."""
        if forward <= 0.0 or strike <= 0.0 or expiry_years <= 0.0:
            raise ValueError("Forward, strike, and expiry must be strictly positive.")
        k = math.log(strike / forward)
        w = cls.calculate_svi_total_variance(k, params)
        return math.sqrt(max(1e-12, w / expiry_years))

    @classmethod
    def check_svi_butterfly_arbitrage(
        cls,
        params: SVIParameters,
        k_grid: Sequence[float],
    ) -> Tuple[bool, float, List[str]]:
        """Verify absence of butterfly arbitrage using Durrleman risk-neutral density condition g(k) >= 0.

        g(k) = (1 - k*w'/(2w))^2 - (w'^2 / 4)*(1/w + 0.25) + 0.5 * w'' >= 0
        """
        params.validate()
        violations: List[str] = []
        min_density = float("inf")
        has_arbitrage = False

        eps = 1e-4
        for k in k_grid:
            w = cls.calculate_svi_total_variance(k, params)
            if w <= 1e-8:
                has_arbitrage = True
                violations.append(f"Zero or negative variance at k={k:.4f}")
                min_density = min(min_density, 0.0)
                continue

            # Numerical centered 1st and 2nd derivatives of w(k)
            w_plus = cls.calculate_svi_total_variance(k + eps, params)
            w_minus = cls.calculate_svi_total_variance(k - eps, params)
            w_prime = (w_plus - w_minus) / (2.0 * eps)
            w_prime2 = (w_plus - 2.0 * w + w_minus) / (eps * eps)

            term1 = (1.0 - (k * w_prime) / (2.0 * w)) ** 2
            term2 = (w_prime ** 2 / 4.0) * (1.0 / w + 0.25)
            term3 = 0.5 * w_prime2

            density = term1 - term2 + term3
            min_density = min(min_density, density)

            if density < -1e-6:
                has_arbitrage = True
                violations.append(f"Negative risk-neutral density g({k:.3f}) = {density:.6f}")

        return has_arbitrage, min_density, violations

    @classmethod
    def audit_surface_arbitrage(
        cls,
        svi_near: SVIParameters,
        svi_far: SVIParameters,
        t_near: float,
        t_far: float,
        k_grid: Sequence[float],
    ) -> ArbitrageAuditResult:
        """Audit calendar spread monotonicity and butterfly arbitrage across near and far expiries."""
        if t_far <= t_near:
            raise ValueError(f"Far expiry t_far={t_far} must exceed near expiry t_near={t_near}")

        violations: List[str] = []
        has_calendar = False

        # 1. Calendar spread check: w(k, t_far) >= w(k, t_near)
        for k in k_grid:
            w_near = cls.calculate_svi_total_variance(k, svi_near)
            w_far = cls.calculate_svi_total_variance(k, svi_far)
            if w_far < w_near - 1e-6:
                has_calendar = True
                violations.append(f"Calendar arbitrage at k={k:.3f}: w_far={w_far:.5f} < w_near={w_near:.5f}")

        # 2. Butterfly checks on both slices
        bf_near, min_dens_near, v_near = cls.check_svi_butterfly_arbitrage(svi_near, k_grid)
        bf_far, min_dens_far, v_far = cls.check_svi_butterfly_arbitrage(svi_far, k_grid)
        has_butterfly = bf_near or bf_far
        violations.extend(v_near)
        violations.extend(v_far)

        min_dens = min(min_dens_near, min_dens_far)

        # 3. Wing slope limits: b * (1 + |rho|) < 2.0
        slope_near = svi_near.b * (1.0 + abs(svi_near.rho))
        slope_far = svi_far.b * (1.0 + abs(svi_far.rho))
        max_slope = max(slope_near, slope_far)

        if max_slope >= 2.0:
            violations.append(f"Wing slope exceeds theoretical bound of 2.0: max_slope={max_slope:.4f}")

        # 4. Strict non-negative variance check: a + b * sigma * sqrt(1 - rho^2) >= 0
        min_var_near = svi_near.min_variance
        min_var_far = svi_far.min_variance
        has_negative_var = (min_var_near < -1e-9) or (min_var_far < -1e-9)
        if has_negative_var:
            violations.append(
                f"Negative variance condition violated: near_min_var={min_var_near:.6f}, far_min_var={min_var_far:.6f}"
            )

        is_free = (not has_calendar) and (not has_butterfly) and (not has_negative_var) and (max_slope < 2.0)

        return ArbitrageAuditResult(
            has_calendar_arbitrage=has_calendar,
            has_butterfly_arbitrage=has_butterfly,
            has_negative_variance=has_negative_var,
            min_density_value=min_dens,
            max_wing_slope=max_slope,
            is_arbitrage_free=is_free,
            violations=violations,
        )

    @classmethod
    def fit_sabr_atm(
        cls,
        forward: float,
        atm_vol: float,
        expiry_years: float,
        beta: float = 1.0,
        rho: float = -0.30,
        nu: float = 0.40,
    ) -> SABRParameters:
        """Calibrate initial SABR alpha to match observed ATM implied volatility."""
        if forward <= 0.0 or atm_vol <= 0.0 or expiry_years <= 0.0:
            raise ValueError("Forward, atm_vol, and expiry must be positive.")

        # Invert ATM approximation: alpha ~ atm_vol * F^(1 - beta)
        f = forward
        t = expiry_years
        one_minus_beta = 1.0 - beta
        fk_beta = f ** one_minus_beta

        alpha_guess = atm_vol * fk_beta

        # Refine with 4-step Newton-Raphson on alpha
        for _ in range(5):
            p = SABRParameters(alpha=alpha_guess, beta=beta, rho=rho, nu=nu)
            model_vol = cls.calculate_sabr_volatility(f, f, t, p)
            diff = model_vol - atm_vol
            if abs(diff) < 1e-6:
                break
            # Numerical derivative dVol / dAlpha
            p_eps = SABRParameters(alpha=alpha_guess + 1e-5, beta=beta, rho=rho, nu=nu)
            vol_eps = cls.calculate_sabr_volatility(f, f, t, p_eps)
            dvol = (vol_eps - model_vol) / 1e-5
            if abs(dvol) < 1e-8:
                break
            alpha_guess = max(0.001, alpha_guess - diff / dvol)

        return SABRParameters(alpha=alpha_guess, beta=beta, rho=rho, nu=nu)

    @classmethod
    def compute_max_admissible_eta(cls, rho: float, delta_arb: float = 0.05) -> float:
        """Compute maximum admissible eta guaranteeing zero butterfly arbitrage across all strikes.
        
        Sufficient condition from Gatheral & Jacquier (2014):
            eta <= (1 - delta_arb) * min(4 / (1 + |rho|), 2 / sqrt(1 + |rho|))
        """
        abs_rho = min(0.999, abs(rho))
        bound_lee = 4.0 / (1.0 + abs_rho)
        bound_bf = 2.0 / math.sqrt(1.0 + abs_rho)
        return (1.0 - delta_arb) * min(bound_lee, bound_bf)

    @classmethod
    def ssvi_to_raw_svi(
        cls,
        ssvi: SSVIParameters,
        enforce_butterfly_free: bool = True,
        delta_arb: float = 0.05,
    ) -> SVIParameters:
        """Exact closed-form mapping from SSVI to Gatheral Raw-SVI parameters (a, b, rho, m, sigma).
        
        Closed-Form Equations:
            phi = eta / (theta^gamma * (1 + theta)^(1 - gamma))
            a = (theta / 2) * (1 - rho^2)
            b = (theta * phi) / 2
            rho_raw = rho
            m = -rho / phi
            sigma = sqrt(1 - rho^2) / phi
            
        Proof of guaranteed non-negative variance:
            min_var = a + b * sigma * sqrt(1 - rho^2)
                    = (theta/2)(1 - rho^2) + ((theta*phi)/2) * (sqrt(1-rho^2)/phi) * sqrt(1-rho^2)
                    = (theta/2)(1 - rho^2) + (theta/2)(1 - rho^2)
                    = theta * (1 - rho^2) > 0 identically (since theta > 0 and |rho| < 1).
        """
        ssvi.validate()
        eta = ssvi.eta
        if enforce_butterfly_free:
            max_eta = cls.compute_max_admissible_eta(ssvi.rho, delta_arb=delta_arb)
            eta = min(eta, max_eta)

        theta = ssvi.theta
        rho = ssvi.rho
        gamma = ssvi.gamma

        phi = eta / ((theta ** gamma) * ((1.0 + theta) ** (1.0 - gamma)))
        phi = max(1e-6, phi)

        a = (theta / 2.0) * (1.0 - rho ** 2)
        b = (theta * phi) / 2.0
        m = -rho / phi
        sigma = math.sqrt(max(1e-12, 1.0 - rho ** 2)) / phi

        raw = SVIParameters(a=a, b=b, rho=rho, m=m, sigma=sigma)
        raw.validate()
        return raw

    @staticmethod
    def calculate_model_uncertainty_skew_z_score(
        iv_market: float,
        iv_model: float,
        s_quote: float,
        s_model: float,
        s_parameter: float,
        significance_threshold: float = 2.0,
    ) -> ModelUncertaintySkewResult:
        """Evaluates model-uncertainty-aware skew z-score:
        
        z_t = (IV_market - IV_model) / sqrt(s_quote^2 + s_model^2 + s_parameter^2)
        
        Accounts for 3 orthogonal uncertainty components:
        1. s_quote: microstructure quote noise (bid-ask spread / tick uncertainty).
        2. s_model: model structural specification residual RMSE across smile.
        3. s_parameter: parameter estimation error / covariance uncertainty.
        """
        if s_quote < 0.0 or s_model < 0.0 or s_parameter < 0.0:
            raise ValueError(
                f"Uncertainty components must be non-negative: "
                f"s_quote={s_quote}, s_model={s_model}, s_parameter={s_parameter}"
            )

        var_total = s_quote ** 2 + s_model ** 2 + s_parameter ** 2
        if var_total <= 1e-14:
            raise ValueError(
                "Total uncertainty sqrt(s_quote^2 + s_model^2 + s_parameter^2) must be strictly positive."
            )

        s_total = math.sqrt(var_total)
        iv_diff = iv_market - iv_model
        z_t = iv_diff / s_total

        if z_t >= significance_threshold:
            regime = "OVERPRICED"
            sig = True
        elif z_t <= -significance_threshold:
            regime = "UNDERPRICED"
            sig = True
        else:
            regime = "FAIR_VALUE"
            sig = False

        rationale = (
            f"z_t = {z_t:.3f} (|z| {' >= ' if sig else ' < '} {significance_threshold:.1f}). "
            f"IV_diff = {iv_diff * 100:+.2f}% vs composite uncertainty = {s_total * 100:.2f}% "
            f"(quote_noise={s_quote * 100:.2f}%, model_rmse={s_model * 100:.2f}%, "
            f"param_se={s_parameter * 100:.2f}%). Regime: {regime}"
        )

        return ModelUncertaintySkewResult(
            z_score=round(z_t, 4),
            iv_market=round(iv_market, 6),
            iv_model=round(iv_model, 6),
            iv_diff=round(iv_diff, 6),
            s_quote=round(s_quote, 6),
            s_model=round(s_model, 6),
            s_parameter=round(s_parameter, 6),
            total_uncertainty=round(s_total, 6),
            is_statistically_significant=sig,
            regime=regime,
            rationale=rationale,
        )

    @staticmethod
    def calculate_downside_semi_variance(
        returns: Sequence[float],
        target_return: float = 0.0,
    ) -> float:
        """Calculates empirical downside semi-variance: sigma_-^2 = (1/N) * sum(min(0, R_i - target)^2)."""
        if not returns:
            return 1e-4
        squared_downside = [min(0.0, r - target_return) ** 2 for r in returns]
        semi_var = sum(squared_downside) / len(returns)
        return max(1e-6, semi_var)

    @classmethod
    def calculate_friction_aware_kelly_allocation(
        cls,
        *,
        equity_inr: float,
        margin_per_lot_inr: float,
        lot_size_contracts: int,
        entry_premium: float,
        expected_exit_premium: float,
        downside_returns: Optional[Sequence[float]] = None,
        downside_semi_variance: Optional[float] = None,
        risk_free_rate: float = 0.0,
        kappa: float = 0.25,
        max_allocation_fraction: float = 0.40,
        regime: Optional[RegulatoryRegime] = None,
        brokerage_model: BrokerageModel = BrokerageModel.PAYTM_FLAT_20,
        live_order_dispatch_enabled: bool = False,
    ) -> FrictionAwareKellyResult:
        """Computes friction-aware Bayesian-Kelly allocation f* under downside semi-variance with exact Indian statutory deductions.
        
        Exact Statutory Deductions enforced via AuthoritativeCostCalculator:
        - STT: 0.15% on option sale premium turnover (Finance Act 2026/Post-April 2026)
        - NSE Transaction Fee: ₹3,553/cr (NSE Circular 73061)
        - GST: 18.0% on Taxable Services (Brokerage + Exchange + IPFT + SEBI)
        - Stamp Duty: 0.003% on option buy turnover (Indian Stamp Act)
        - SEBI Turnover Fee: ₹10 per crore (0.0001%)
        - Brokerage: Paytm standard flat ₹20/executed leg
        
        Downside Semi-Variance Kelly Formulation:
            f_full = (mu_gross - friction_pct - r_f) / sigma_-^2
            f* = kappa * max(0, f_full)
            Lots = floor(Equity * f* / Margin_lot)
        """
        # Institutional Invariant Check: Live dispatch must remain strictly False
        if live_order_dispatch_enabled or LIVE_ORDER_DISPATCH_ENABLED:
            return FrictionAwareKellyResult(
                gross_edge_pts=0.0,
                gross_return_pct=0.0,
                statutory_friction_inr=0.0,
                friction_pct=0.0,
                net_return_pct=0.0,
                downside_semi_variance=1e-4,
                full_kelly_fraction=0.0,
                fractional_kelly_fraction=0.0,
                effective_allocation_fraction=0.0,
                allocated_capital_inr=0.0,
                quantized_lots=0,
                quantized_contracts=0,
                margin_utilized_inr=0.0,
                cash_buffer_remaining_inr=equity_inr,
                is_actionable=False,
                fail_closed_reason="LIVE_ORDER_DISPATCH_ENABLED safety invariant violated. Live execution blocked.",
                live_order_dispatch_enabled=False,
            )

        if equity_inr <= 0.0 or margin_per_lot_inr <= 0.0 or lot_size_contracts <= 0:
            return FrictionAwareKellyResult(
                gross_edge_pts=0.0,
                gross_return_pct=0.0,
                statutory_friction_inr=0.0,
                friction_pct=0.0,
                net_return_pct=0.0,
                downside_semi_variance=1e-4,
                full_kelly_fraction=0.0,
                fractional_kelly_fraction=0.0,
                effective_allocation_fraction=0.0,
                allocated_capital_inr=0.0,
                quantized_lots=0,
                quantized_contracts=0,
                margin_utilized_inr=0.0,
                cash_buffer_remaining_inr=max(0.0, equity_inr),
                is_actionable=False,
                fail_closed_reason="Invalid equity, margin, or lot size inputs.",
                live_order_dispatch_enabled=False,
            )

        target_regime = regime or RegulatoryRegime.POST_APRIL_2026

        # Calculate exact statutory friction for 1 roundtrip lot (BUY entry, SELL exit)
        entry_cost = AuthoritativeCostCalculator.calculate_order_friction(
            side=OrderSide.BUY,
            quantity=lot_size_contracts,
            price=Decimal(str(round(entry_premium, 2))),
            instrument_category=InstrumentCategory.OPTIONS,
            brokerage_model=brokerage_model,
            force_regime=target_regime,
        )
        exit_cost = AuthoritativeCostCalculator.calculate_order_friction(
            side=OrderSide.SELL,
            quantity=lot_size_contracts,
            price=Decimal(str(round(expected_exit_premium, 2))),
            instrument_category=InstrumentCategory.OPTIONS,
            brokerage_model=brokerage_model,
            force_regime=target_regime,
        )
        friction_per_lot = float(entry_cost.total_friction + exit_cost.total_friction)

        gross_edge_pts = expected_exit_premium - entry_premium
        gross_edge_inr = gross_edge_pts * lot_size_contracts
        gross_return_pct = gross_edge_inr / margin_per_lot_inr
        friction_pct = friction_per_lot / margin_per_lot_inr
        net_return_pct = gross_return_pct - friction_pct - risk_free_rate

        # Evaluate downside semi-variance
        if downside_semi_variance is not None:
            semi_var = max(1e-6, float(downside_semi_variance))
        elif downside_returns is not None:
            semi_var = cls.calculate_downside_semi_variance(downside_returns, target_return=risk_free_rate)
        else:
            semi_var = 0.0025  # Standard default ~5% downside volatility

        # Fail-closed if net expected return is negative or zero after Indian statutory taxes
        if net_return_pct <= 0.0:
            return FrictionAwareKellyResult(
                gross_edge_pts=round(gross_edge_pts, 2),
                gross_return_pct=round(gross_return_pct, 6),
                statutory_friction_inr=round(friction_per_lot, 2),
                friction_pct=round(friction_pct, 6),
                net_return_pct=round(net_return_pct, 6),
                downside_semi_variance=round(semi_var, 6),
                full_kelly_fraction=0.0,
                fractional_kelly_fraction=0.0,
                effective_allocation_fraction=0.0,
                allocated_capital_inr=0.0,
                quantized_lots=0,
                quantized_contracts=0,
                margin_utilized_inr=0.0,
                cash_buffer_remaining_inr=equity_inr,
                is_actionable=False,
                fail_closed_reason=(
                    f"Negative or zero net edge after Indian statutory friction deductions: "
                    f"gross={gross_edge_inr:.2f} INR, friction={friction_per_lot:.2f} INR."
                ),
                live_order_dispatch_enabled=False,
            )

        # Kelly fraction under downside semi-variance
        f_full = net_return_pct / semi_var
        k_scaling = max(0.05, min(1.0, float(kappa)))
        f_frac = f_full * k_scaling
        effective_fraction = min(max_allocation_fraction, max(0.0, f_frac))

        allocated_capital = round(equity_inr * effective_fraction, 2)
        lots = int(math.floor(allocated_capital / margin_per_lot_inr))
        contracts = lots * lot_size_contracts
        margin_used = round(lots * margin_per_lot_inr, 2)
        cash_buffer = round(equity_inr - margin_used, 2)
        total_friction_position = round(lots * friction_per_lot, 2)

        is_actionable = lots > 0

        return FrictionAwareKellyResult(
            gross_edge_pts=round(gross_edge_pts, 2),
            gross_return_pct=round(gross_return_pct, 6),
            statutory_friction_inr=total_friction_position,
            friction_pct=round(friction_pct, 6),
            net_return_pct=round(net_return_pct, 6),
            downside_semi_variance=round(semi_var, 6),
            full_kelly_fraction=round(f_full, 4),
            fractional_kelly_fraction=round(f_frac, 4),
            effective_allocation_fraction=round(effective_fraction, 4),
            allocated_capital_inr=allocated_capital,
            quantized_lots=lots,
            quantized_contracts=contracts,
            margin_utilized_inr=margin_used,
            cash_buffer_remaining_inr=cash_buffer,
            is_actionable=is_actionable,
            fail_closed_reason=None if is_actionable else "Allocated capital insufficient for single lot.",
            live_order_dispatch_enabled=False,
        )


__all__ = [
    "LIVE_ORDER_DISPATCH_ENABLED",
    "VolatilityModelType",
    "SABRParameters",
    "SVIParameters",
    "SSVIParameters",
    "ArbitrageAuditResult",
    "ModelUncertaintySkewResult",
    "FrictionAwareKellyResult",
    "SabrSviCalibrator",
]

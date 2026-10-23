"""AGI 1.7 Options Analytics & Greeks Engine.

Standard Black-Scholes formula implementation for European index options,
computing theoretical fair value, Delta, Gamma, Vega, and Theta,
and solving for Implied Volatility (IV) with bounded numerical search.
"""

from __future__ import annotations

import math
from typing import Dict, Optional


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


class OptionsMath:
    """Analytical European option valuation and Greeks calculation."""

    @staticmethod
    def black_scholes_price(
        *,
        spot: float,
        strike: float,
        time_to_expiry_years: float,
        risk_free_rate: float = 0.065,  # 6.5% typical RBI T-bill rate
        volatility: float = 0.15,
        is_call: bool = True,
    ) -> float:
        if time_to_expiry_years <= 0:
            return max(0.0, (spot - strike) if is_call else (strike - spot))
        if volatility <= 0 or spot <= 0 or strike <= 0:
            return max(0.0, (spot - strike) if is_call else (strike - spot))

        d1 = (
            math.log(spot / strike)
            + (risk_free_rate + 0.5 * volatility * volatility) * time_to_expiry_years
        ) / (volatility * math.sqrt(time_to_expiry_years))
        d2 = d1 - volatility * math.sqrt(time_to_expiry_years)

        df = math.exp(-risk_free_rate * time_to_expiry_years)
        if is_call:
            return spot * _norm_cdf(d1) - strike * df * _norm_cdf(d2)
        else:
            return strike * df * _norm_cdf(-d2) - spot * _norm_cdf(-d1)

    @staticmethod
    def calculate_greeks(
        *,
        spot: float,
        strike: float,
        time_to_expiry_years: float,
        risk_free_rate: float = 0.065,
        volatility: float = 0.15,
        is_call: bool = True,
    ) -> Dict[str, float]:
        if time_to_expiry_years <= 0 or volatility <= 0 or spot <= 0 or strike <= 0:
            intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
            delta = 1.0 if (is_call and spot > strike) else (-1.0 if (not is_call and spot < strike) else 0.0)
            return {
                "price": intrinsic,
                "delta": delta,
                "gamma": 0.0,
                "vega": 0.0,
                "theta": 0.0,
            }

        t_sqrt = math.sqrt(time_to_expiry_years)
        d1 = (
            math.log(spot / strike)
            + (risk_free_rate + 0.5 * volatility * volatility) * time_to_expiry_years
        ) / (volatility * t_sqrt)
        d2 = d1 - volatility * t_sqrt

        df = math.exp(-risk_free_rate * time_to_expiry_years)
        pdf_d1 = _norm_pdf(d1)

        price = (
            spot * _norm_cdf(d1) - strike * df * _norm_cdf(d2)
            if is_call
            else strike * df * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        )
        delta = _norm_cdf(d1) if is_call else (_norm_cdf(d1) - 1.0)
        gamma = pdf_d1 / (spot * volatility * t_sqrt)
        vega = spot * pdf_d1 * t_sqrt / 100.0  # scaled per 1% change in vol

        theta_term1 = -(spot * pdf_d1 * volatility) / (2.0 * t_sqrt)
        if is_call:
            theta_term2 = -risk_free_rate * strike * df * _norm_cdf(d2)
            theta = (theta_term1 + theta_term2) / 365.0  # per calendar day
        else:
            theta_term2 = risk_free_rate * strike * df * _norm_cdf(-d2)
            theta = (theta_term1 + theta_term2) / 365.0

        return {
            "price": round(price, 4),
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "vega": round(vega, 4),
            "theta": round(theta, 4),
        }

    @classmethod
    def calculate_implied_volatility(
        cls,
        *,
        market_price: float,
        spot: float,
        strike: float,
        time_to_expiry_years: float,
        risk_free_rate: float = 0.065,
        is_call: bool = True,
        max_iterations: int = 50,
        precision: float = 1e-4,
    ) -> Optional[float]:
        """Solves for IV using bounded binary search with fallback."""
        if market_price <= 0 or spot <= 0 or strike <= 0 or time_to_expiry_years <= 0:
            return None

        intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
        if market_price < intrinsic:
            return None

        low_vol = 0.01
        high_vol = 3.00

        for _ in range(max_iterations):
            mid_vol = 0.5 * (low_vol + high_vol)
            theo = cls.black_scholes_price(
                spot=spot,
                strike=strike,
                time_to_expiry_years=time_to_expiry_years,
                risk_free_rate=risk_free_rate,
                volatility=mid_vol,
                is_call=is_call,
            )
            diff = theo - market_price
            if abs(diff) < precision:
                return round(mid_vol, 4)
            if diff > 0:
                high_vol = mid_vol
            else:
                low_vol = mid_vol

        return round(0.5 * (low_vol + high_vol), 4)

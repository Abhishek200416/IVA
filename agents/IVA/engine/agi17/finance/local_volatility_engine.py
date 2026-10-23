"""AGI 1.7 Dupire (1994) Arbitrage-Free Local Volatility Surface Engine.

Implements the continuous Dupire local volatility equation:
    sigma_loc^2(K, T) = [ dC/dT + r * K * (dC/dK) ] / [ 0.5 * K^2 * (d^2C/dK^2) ]

Key Features:
1. Exact Dupire Local Volatility formulation for European options under interest rate r.
2. Arbitrage-free boundary validation:
   - Calendar spread non-negativity: dC/dT >= 0 (no calendar arbitrage).
   - Butterfly spread non-negativity: d^2C/dK^2 >= 0 (strictly positive risk-neutral density).
   - Strike monotonicity: -e^(-rT) <= dC/dK <= 0.
3. Robust numerical safety & clipping:
   - Enforces min_local_vol (5%) and max_local_vol (150%) safeguards against numerical singulars.
4. 2D Surface grid construction across strikes and maturities.
5. Euler-Maruyama discrete time-stepping for stochastic simulation under local volatility.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class LocalVolPoint:
    """Represents local volatility evaluation at a specific (Strike, Tenor) coordinate."""
    spot: float
    strike: float
    time_to_expiry_years: float
    implied_vol: float
    local_vol: float
    dC_dT: float
    dC_dK: float
    d2C_dK2: float
    is_calendar_arbitrage: bool
    is_butterfly_arbitrage: bool


@dataclass
class LocalVolSurfaceGrid:
    """Discrete 2D mesh grid of local volatilities across strike and maturity dimensions."""
    strikes: List[float]
    maturities_years: List[float]
    matrix: List[List[float]]
    atm_local_vols: List[float] = field(default_factory=list)


class DupireLocalVolatilityEngine:
    """Dupire (1994) Arbitrage-Free Local Volatility Surface Engine for Bank Nifty."""

    def __init__(
        self,
        risk_free_rate: float = 0.065,
        min_local_vol: float = 0.05,
        max_local_vol: float = 1.50,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.min_local_vol = min_local_vol
        self.max_local_vol = max_local_vol

    @staticmethod
    def _bs_call_price(spot: float, strike: float, t: float, r: float, iv: float) -> float:
        """Standard Black-Scholes European call pricing with error function CDF."""
        if t <= 1e-6:
            return max(0.0, spot - strike)
        if iv <= 1e-6:
            return max(0.0, spot - strike * math.exp(-r * t))

        sqrt_t = math.sqrt(t)
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * sqrt_t)
        d2 = d1 - iv * sqrt_t
        cdf_d1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
        cdf_d2 = 0.5 * (1.0 + math.erf(d2 / math.sqrt(2.0)))
        return spot * cdf_d1 - strike * math.exp(-r * t) * cdf_d2

    def calculate_local_volatility(
        self,
        spot: float,
        strike: float,
        time_to_expiry_years: float,
        base_iv: Optional[float] = None,
        iv_model: Optional[Callable[[float, float], float]] = None,
        dk: float = 25.0,
        dt: float = 0.0005,
    ) -> LocalVolPoint:
        """Calculates instantaneous Dupire local volatility at (strike, time_to_expiry_years)."""
        r = self.risk_free_rate
        t = max(1e-4, time_to_expiry_years)

        def get_iv(k_val: float, t_val: float) -> float:
            if iv_model is not None:
                return max(1e-4, iv_model(k_val, t_val))
            if base_iv is not None:
                return max(1e-4, base_iv)
            return 0.16

        current_iv = get_iv(strike, t)

        # 1. Time derivative dC/dT
        dt_step = min(dt, t * 0.1)
        t_plus = t + dt_step
        t_minus = max(1e-6, t - dt_step)
        c_t_plus = self._bs_call_price(spot, strike, t_plus, r, get_iv(strike, t_plus))
        c_t_minus = self._bs_call_price(spot, strike, t_minus, r, get_iv(strike, t_minus))
        dC_dT = (c_t_plus - c_t_minus) / (t_plus - t_minus)

        # 2. Strike derivatives dC/dK and d^2C/dK^2
        dk_step = max(1.0, min(dk, strike * 0.002))
        k_plus = strike + dk_step
        k_minus = strike - dk_step
        c_k_plus = self._bs_call_price(spot, k_plus, t, r, get_iv(k_plus, t))
        c_k_minus = self._bs_call_price(spot, k_minus, t, r, get_iv(k_minus, t))
        c_mid = self._bs_call_price(spot, strike, t, r, current_iv)

        dC_dK = (c_k_plus - c_k_minus) / (2.0 * dk_step)
        d2C_dK2 = (c_k_plus - 2.0 * c_mid + c_k_minus) / (dk_step * dk_step)

        # 3. Arbitrage boundary diagnostics
        is_calendar_arbitrage = dC_dT < -1e-6
        is_butterfly_arbitrage = (d2C_dK2 <= 1e-8) or (dC_dK < -1.05) or (dC_dK > 0.05)

        # 4. Dupire formulation
        numerator = dC_dT + r * strike * dC_dK
        denominator = 0.5 * (strike ** 2) * d2C_dK2

        if is_calendar_arbitrage or is_butterfly_arbitrage or denominator <= 1e-8 or numerator <= 0:
            local_vol = self.min_local_vol
        else:
            var = numerator / denominator
            local_vol = math.sqrt(max(self.min_local_vol ** 2, min(self.max_local_vol ** 2, var)))

        return LocalVolPoint(
            spot=spot,
            strike=strike,
            time_to_expiry_years=t,
            implied_vol=current_iv,
            local_vol=local_vol,
            dC_dT=dC_dT,
            dC_dK=dC_dK,
            d2C_dK2=d2C_dK2,
            is_calendar_arbitrage=is_calendar_arbitrage,
            is_butterfly_arbitrage=is_butterfly_arbitrage,
        )

    def generate_surface_grid(
        self,
        spot: float,
        strikes: List[float],
        maturities_years: List[float],
        base_iv: Optional[float] = None,
        iv_model: Optional[Callable[[float, float], float]] = None,
    ) -> LocalVolSurfaceGrid:
        """Constructs a 2D mesh grid of local volatility points across strikes and tenors."""
        matrix: List[List[float]] = []
        atm_local_vols: List[float] = []

        for t in maturities_years:
            row: List[float] = []
            for k in strikes:
                pt = self.calculate_local_volatility(
                    spot=spot,
                    strike=k,
                    time_to_expiry_years=t,
                    base_iv=base_iv,
                    iv_model=iv_model,
                )
                row.append(pt.local_vol)
            matrix.append(row)

            # ATM local volatility evaluation
            atm_pt = self.calculate_local_volatility(
                spot=spot,
                strike=spot,
                time_to_expiry_years=t,
                base_iv=base_iv,
                iv_model=iv_model,
            )
            atm_local_vols.append(atm_pt.local_vol)

        return LocalVolSurfaceGrid(
            strikes=list(strikes),
            maturities_years=list(maturities_years),
            matrix=matrix,
            atm_local_vols=atm_local_vols,
        )

    def simulate_local_vol_step(
        self,
        current_spot: float,
        current_t: float,
        dt: float,
        z: float,
        local_vol: Optional[float] = None,
        iv_model: Optional[Callable[[float, float], float]] = None,
    ) -> float:
        """Simulates a discrete Euler-Maruyama step under local volatility:
        S_{t+dt} = S_t * exp( (r - 0.5 * sigma_loc^2) * dt + sigma_loc * sqrt(dt) * Z )
        """
        r = self.risk_free_rate
        if local_vol is not None:
            vol = max(self.min_local_vol, min(self.max_local_vol, local_vol))
        else:
            pt = self.calculate_local_volatility(
                spot=current_spot,
                strike=current_spot,
                time_to_expiry_years=max(1e-4, current_t),
                iv_model=iv_model,
            )
            vol = pt.local_vol

        sqrt_dt = math.sqrt(max(1e-8, dt))
        drift = (r - 0.5 * (vol ** 2)) * dt
        diffusion = vol * sqrt_dt * z
        return current_spot * math.exp(drift + diffusion)

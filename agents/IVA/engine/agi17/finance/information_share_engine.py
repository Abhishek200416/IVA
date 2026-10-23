"""High-Frequency Information Share & Price Discovery Engine.

Wave 33 Deliverable (TASK-BN-43):
Synthesized in consultation with external frontier models and ChatGPT (aptaz / Go):
1. Econometric Foundation:
   - Price Discovery in cointegrated high-frequency asset pairs:
     Bank Nifty Current-Month Futures vs Synthetic Forward (ATM Option Chain).
   - Cointegrating Vector: z_{t-1} = P_{1, t-1} - beta * P_{2, t-1} - c
2. Vector Error Correction Model (VECM):
   - Delta P_{1, t} = alpha_1 * z_{t-1} + gamma_1 * Delta P_{1, t-1} + eps_{1, t}
   - Delta P_{2, t} = alpha_2 * z_{t-1} + gamma_2 * Delta P_{2, t-1} + eps_{2, t}
   - alpha_1, alpha_2 denote error-correction adjustment speeds toward long-run equilibrium.
3. Gonzalo-Granger (1995) Component Share (GG):
   - Decomposes permanent common factor f_t = gamma_1 * P_{1, t} + gamma_2 * P_{2, t}
   - Orthogonality: alpha_perp^T * alpha = 0 => GG_1 = |alpha_2| / (|alpha_1| + |alpha_2|)
   - The market that adjusts LESS to pricing errors contributes MORE to permanent price discovery.
4. Hasbrouck (1995) Information Share (IS):
   - Cholesky factorization of residual covariance Omega = M * M^T
   - Bounds IS_i^{[min, max]} computed across variable permutations to bound contemporaneous
     correlation ambiguity:
     IS_1^{(1)} = ([psi * M^{(1)}]_1)^2 / (psi * Omega * psi^T)
     IS_2^{(2)} = ([psi * M^{(2)}]_1)^2 / (psi * Omega * psi^T)
5. Microstructure Execution Routing:
   - Identifies leading vs lagging venue during Opening Range Breakouts (ORB) and macro shocks.
   - Pacing logic: Aggressive liquidity extraction on the leading venue, passive maker quoting
     on the lagging venue to capture lagged mispricing spreads.

Zero external dependencies outside standard library math, dataclasses, and typing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple


class PriceDiscoveryRegime(str, Enum):
    """Regime classification for price discovery between two cointegrated venues."""
    LEADER_MARKET_1 = "LEADER_MARKET_1"          # Market 1 predominantly impounds information first
    LEADER_MARKET_2 = "LEADER_MARKET_2"          # Market 2 predominantly impounds information first
    SYNCHRONOUS_DISCOVERY = "SYNCHRONOUS_DISCOVERY" # Information share is balanced/mutual
    CONTEMPORANEOUS_UNCERTAINTY = "CONTEMPORANEOUS_UNCERTAINTY" # High residual correlation widens bounds


class ExecutionRoutingAdvice(str, Enum):
    """Institutional execution recommendation based on price discovery leadership."""
    AGGRESSIVE_1_PASSIVE_2 = "AGGRESSIVE_1_PASSIVE_2"  # Cross-market arbitrage: snipe M1, post limit on M2
    AGGRESSIVE_2_PASSIVE_1 = "AGGRESSIVE_2_PASSIVE_1"  # Reverse: snipe M2, post limit on M1
    SYMMETRIC_CROSS_HEDGE = "SYMMETRIC_CROSS_HEDGE"    # Simultaneous balanced execution
    REDUCE_EXPOSURE_HIGH_CORR = "REDUCE_EXPOSURE_HIGH_CORR" # Pacing delay under high correlation ambiguity


@dataclass(frozen=True)
class PricePairTick:
    """A synchronized tick observation across two cointegrated price series."""
    timestamp: float
    price_1: float
    price_2: float
    volume_1: float = 0.0
    volume_2: float = 0.0


@dataclass(frozen=True)
class HasbrouckBounds:
    """Hasbrouck Information Share lower, upper, and midpoint estimates."""
    is_min: float
    is_max: float
    is_mid: float
    spread: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "is_min": round(self.is_min, 4),
            "is_max": round(self.is_max, 4),
            "is_mid": round(self.is_mid, 4),
            "spread": round(self.spread, 4),
        }


@dataclass(frozen=True)
class PriceDiscoveryMetrics:
    """Comprehensive high-frequency price discovery report."""
    market_1_hasbrouck: HasbrouckBounds
    market_2_hasbrouck: HasbrouckBounds
    market_1_gg_share: float
    market_2_gg_share: float
    error_correction_alpha_1: float
    error_correction_alpha_2: float
    residual_correlation: float
    residual_volatility_1: float
    residual_volatility_2: float
    cointegration_residual_mean: float
    cointegration_residual_std: float
    regime: PriceDiscoveryRegime
    recommended_routing: ExecutionRoutingAdvice

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_1_hasbrouck": self.market_1_hasbrouck.to_dict(),
            "market_2_hasbrouck": self.market_2_hasbrouck.to_dict(),
            "market_1_gg_share": round(self.market_1_gg_share, 4),
            "market_2_gg_share": round(self.market_2_gg_share, 4),
            "alpha_1": round(self.error_correction_alpha_1, 6),
            "alpha_2": round(self.error_correction_alpha_2, 6),
            "residual_correlation": round(self.residual_correlation, 4),
            "residual_vol_1": round(self.residual_volatility_1, 4),
            "residual_vol_2": round(self.residual_volatility_2, 4),
            "cointeg_std": round(self.cointegration_residual_std, 4),
            "regime": self.regime.value,
            "routing": self.recommended_routing.value,
        }


class HighFrequencyInformationShareEngine:
    """Vector Error Correction & Information Share Engine for High-Frequency Pairs.

    Implements Hasbrouck (1995) variance decomposition and Gonzalo-Granger (1995)
    common factor analysis for Bank Nifty futures vs synthetic forward or cross-asset pairs.
    """

    def __init__(
        self,
        min_ticks: int = 15,
        lead_threshold: float = 0.60,
        uncertainty_threshold: float = 0.35,
        cointegrating_beta: float = 1.0,
    ) -> None:
        if min_ticks < 5:
            raise ValueError("min_ticks must be at least 5 for degrees of freedom.")
        if not (0.50 <= lead_threshold <= 0.95):
            raise ValueError("lead_threshold must be in [0.50, 0.95].")
        if uncertainty_threshold <= 0.0:
            raise ValueError("uncertainty_threshold must be strictly positive.")

        self.min_ticks = min_ticks
        self.lead_threshold = lead_threshold
        self.uncertainty_threshold = uncertainty_threshold
        self.cointegrating_beta = cointegrating_beta

    @staticmethod
    def extract_synthetic_forward(
        underlying_price: float,
        call_price: float,
        put_price: float,
        strike: float,
    ) -> float:
        """Derive Bank Nifty synthetic forward price from Put-Call Parity.

        F_syn = K + C(K) - P(K)
        """
        if call_price < 0 or put_price < 0 or strike <= 0:
            raise ValueError("Option prices and strike must be non-negative.")
        return strike + (call_price - put_price)

    def fit_from_arrays(
        self,
        prices_1: Sequence[float],
        prices_2: Sequence[float],
        timestamps: Optional[Sequence[float]] = None,
    ) -> PriceDiscoveryMetrics:
        """Compute price discovery metrics directly from two synchronous price series."""
        if len(prices_1) != len(prices_2):
            raise ValueError(f"Price series length mismatch: {len(prices_1)} vs {len(prices_2)}")

        n = len(prices_1)
        if n < self.min_ticks:
            raise ValueError(f"Sample size {n} below required minimum {self.min_ticks}")

        if timestamps is None:
            ts = [float(i) for i in range(n)]
        else:
            if len(timestamps) != n:
                raise ValueError("Timestamps length mismatch with prices.")
            ts = list(timestamps)

        ticks = [
            PricePairTick(timestamp=ts[i], price_1=prices_1[i], price_2=prices_2[i])
            for i in range(n)
        ]
        return self.fit(ticks)

    def fit(self, ticks: Sequence[PricePairTick]) -> PriceDiscoveryMetrics:
        """Fit VECM, compute Hasbrouck bounds, GG shares, and classify leadership."""
        n = len(ticks)
        if n < self.min_ticks:
            raise ValueError(f"Insufficient ticks: {n} < {self.min_ticks}")

        # 1. Cointegration residual series: z_t = P_{1,t} - beta * P_{2,t}
        z_series: List[float] = [
            ticks[i].price_1 - self.cointegrating_beta * ticks[i].price_2
            for i in range(n)
        ]
        mean_z = sum(z_series) / n
        var_z = sum((z - mean_z) ** 2 for z in z_series) / max(1, n - 1)
        std_z = math.sqrt(max(1e-12, var_z))

        # Demeaned lagged cointegrating errors: z_{t-1}
        # Price changes: Delta P_{1, t} and Delta P_{2, t}
        dp1: List[float] = []
        dp2: List[float] = []
        z_lag: List[float] = []

        for t in range(1, n):
            dp1.append(ticks[t].price_1 - ticks[t - 1].price_1)
            dp2.append(ticks[t].price_2 - ticks[t - 1].price_2)
            z_lag.append(z_series[t - 1] - mean_z)

        m = len(dp1)  # m = n - 1
        denom_z = sum(z * z for z in z_lag)
        if denom_z < 1e-12:
            denom_z = 1e-12

        mean_dp1 = sum(dp1) / m
        mean_dp2 = sum(dp2) / m

        # OLS estimation of error-correction speeds:
        # Delta P_{1, t} = c_1 + alpha_1 * z_{t-1} + eps_{1, t}
        # Delta P_{2, t} = c_2 + alpha_2 * z_{t-1} + eps_{2, t}
        alpha_1 = sum(z_lag[t] * (dp1[t] - mean_dp1) for t in range(m)) / denom_z
        alpha_2 = sum(z_lag[t] * (dp2[t] - mean_dp2) for t in range(m)) / denom_z

        # Residual innovations
        eps1: List[float] = [
            dp1[t] - (mean_dp1 + alpha_1 * z_lag[t])
            for t in range(m)
        ]
        eps2: List[float] = [
            dp2[t] - (mean_dp2 + alpha_2 * z_lag[t])
            for t in range(m)
        ]

        # Residual variance-covariance matrix Omega
        var_eps1 = sum(e * e for e in eps1) / max(1, m - 1)
        var_eps2 = sum(e * e for e in eps2) / max(1, m - 1)
        cov_eps12 = sum(eps1[t] * eps2[t] for t in range(m)) / max(1, m - 1)

        sig1 = math.sqrt(max(1e-12, var_eps1))
        sig2 = math.sqrt(max(1e-12, var_eps2))

        # Clamp correlation to [-0.99999, 0.99999]
        denom_corr = sig1 * sig2
        raw_corr = cov_eps12 / denom_corr if denom_corr > 1e-12 else 0.0
        rho = max(-0.99999, min(0.99999, raw_corr))

        # 2. Gonzalo-Granger (1995) Component Share
        # The market with SMALLER absolute error correction speed has HIGHER component share
        abs_a1 = abs(alpha_1)
        abs_a2 = abs(alpha_2)
        total_abs_a = abs_a1 + abs_a2

        if total_abs_a < 1e-10:
            gg_1 = 0.50
            gg_2 = 0.50
        else:
            gg_1 = abs_a2 / total_abs_a
            gg_2 = abs_a1 / total_abs_a

        # 3. Hasbrouck (1995) Information Share
        # Long-run impact vector psi = (gg_1, gg_2)
        psi_1 = gg_1
        psi_2 = gg_2

        # Total variance V = psi * Omega * psi^T
        total_var = (
            psi_1 ** 2 * var_eps1
            + 2.0 * psi_1 * psi_2 * cov_eps12
            + psi_2 ** 2 * var_eps2
        )
        if total_var < 1e-12:
            total_var = 1e-12

        # Cholesky Factorization 1: Ordering (Market 1 first, Market 2 second)
        # M^{(1)} = [[sig1, 0], [cov / sig1, sqrt(sig2^2 - (cov/sig1)^2)]]
        cov_over_sig1 = cov_eps12 / sig1
        cond_sig2_sq = max(1e-12, var_eps2 - cov_over_sig1 ** 2)
        cond_sig2 = math.sqrt(cond_sig2_sq)

        # Vector product psi * M^{(1)}
        pm1_col1 = psi_1 * sig1 + psi_2 * cov_over_sig1
        pm1_col2 = psi_2 * cond_sig2

        is1_ordering1 = (pm1_col1 ** 2) / total_var
        is1_ordering1 = max(0.0, min(1.0, is1_ordering1))

        # Cholesky Factorization 2: Ordering (Market 2 first, Market 1 second)
        # M^{(2)} = [[sig2, 0], [cov / sig2, sqrt(sig1^2 - (cov/sig2)^2)]]
        cov_over_sig2 = cov_eps12 / sig2
        cond_sig1_sq = max(1e-12, var_eps1 - cov_over_sig2 ** 2)
        cond_sig1 = math.sqrt(cond_sig1_sq)

        pm2_col1 = psi_2 * sig2 + psi_1 * cov_over_sig2
        pm2_col2 = psi_1 * cond_sig1

        is2_ordering2 = (pm2_col1 ** 2) / total_var
        is2_ordering2 = max(0.0, min(1.0, is2_ordering2))
        is1_ordering2 = max(0.0, min(1.0, 1.0 - is2_ordering2))

        # Hasbrouck Bounds for Market 1
        m1_is_min = min(is1_ordering1, is1_ordering2)
        m1_is_max = max(is1_ordering1, is1_ordering2)
        m1_is_mid = (m1_is_min + m1_is_max) / 2.0
        m1_spread = m1_is_max - m1_is_min

        # Hasbrouck Bounds for Market 2 (symmetric)
        m2_is_min = 1.0 - m1_is_max
        m2_is_max = 1.0 - m1_is_min
        m2_is_mid = (m2_is_min + m2_is_max) / 2.0
        m2_spread = m2_is_max - m2_is_min

        hb1 = HasbrouckBounds(
            is_min=m1_is_min,
            is_max=m1_is_max,
            is_mid=m1_is_mid,
            spread=m1_spread,
        )
        hb2 = HasbrouckBounds(
            is_min=m2_is_min,
            is_max=m2_is_max,
            is_mid=m2_is_mid,
            spread=m2_spread,
        )

        # 4. Regime & Routing Decision
        if m1_spread >= self.uncertainty_threshold:
            regime = PriceDiscoveryRegime.CONTEMPORANEOUS_UNCERTAINTY
            routing = ExecutionRoutingAdvice.REDUCE_EXPOSURE_HIGH_CORR
        elif m1_is_mid >= self.lead_threshold and gg_1 >= self.lead_threshold:
            regime = PriceDiscoveryRegime.LEADER_MARKET_1
            routing = ExecutionRoutingAdvice.AGGRESSIVE_1_PASSIVE_2
        elif m2_is_mid >= self.lead_threshold and gg_2 >= self.lead_threshold:
            regime = PriceDiscoveryRegime.LEADER_MARKET_2
            routing = ExecutionRoutingAdvice.AGGRESSIVE_2_PASSIVE_1
        else:
            regime = PriceDiscoveryRegime.SYNCHRONOUS_DISCOVERY
            routing = ExecutionRoutingAdvice.SYMMETRIC_CROSS_HEDGE

        return PriceDiscoveryMetrics(
            market_1_hasbrouck=hb1,
            market_2_hasbrouck=hb2,
            market_1_gg_share=gg_1,
            market_2_gg_share=gg_2,
            error_correction_alpha_1=alpha_1,
            error_correction_alpha_2=alpha_2,
            residual_correlation=rho,
            residual_volatility_1=sig1,
            residual_volatility_2=sig2,
            cointegration_residual_mean=mean_z,
            cointegration_residual_std=std_z,
            regime=regime,
            recommended_routing=routing,
        )

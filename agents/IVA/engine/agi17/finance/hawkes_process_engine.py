"""Mutually Exciting Bivariate Hawkes Process & Order Clustering Engine.

Implements Alan Hawkes's (1971) self-exciting and mutually exciting point process,
recursive O(1) state propagation, spectral radius branching matrix stability checking,
endogeneity ratio estimation, and microstructure order clustering spread widener.

References:
- Hawkes, A. G. (1971). Spectra of some self-exciting and mutually exciting point processes.
  Biometrika, 58(1), 83-90.
- Bacry, E., Delattre, S., Hoffmann, M., & Muzy, J. F. (2013). Some properties of the
  mutually exciting Hawkes processes with applications to financial data.
  Stochastic Processes and their Applications, 123(7), 2475-2499.
- Hardiman, S. J., Bercot, N., & Bouchaud, J. P. (2013). Reflexivity and critical
  phenomena in financial markets. Physical Review E, 88(2), 022808.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class HawkesClusterRegime(Enum):
    """Classification of order flow reflexivity and clustering intensity."""
    EXOGENOUS_CALM = "EXOGENOUS_CALM"          # Baseline Poisson flow, low endogeneity
    MOMENTUM_CLUSTERING = "MOMENTUM_CLUSTERING"  # Directional burst (dominant buy or sell)
    CROSS_EXCITED_CHOP = "CROSS_EXCITED_CHOP"    # Heavy ping-pong trading, high volume
    EXPLOSIVE_CASCADE = "EXPLOSIVE_CASCADE"      # Near-critical endogeneity, liquidity shock


@dataclass(frozen=True)
class HawkesParameters:
    """Parameters for bivariate Hawkes process: (1=BUY, 2=SELL)."""
    mu_buy: float = 0.5          # Base arrival rate for buys (events / sec)
    mu_sell: float = 0.5         # Base arrival rate for sells (events / sec)
    alpha_bb: float = 0.3        # Buy self-excitation magnitude
    alpha_bs: float = 0.1        # Buy-from-sell cross-excitation magnitude
    alpha_sb: float = 0.1        # Sell-from-buy cross-excitation magnitude
    alpha_ss: float = 0.3        # Sell self-excitation magnitude
    beta_decay: float = 1.0      # Exponential decay rate (1 / sec)


@dataclass(frozen=True)
class HawkesIntensitySnapshot:
    """Current streaming intensities and microstructure risk metrics."""
    timestamp: float
    lambda_buy: float
    lambda_sell: float
    lambda_total: float
    intensity_imbalance: float    # (lambda_buy - lambda_sell) / lambda_total in [-1, 1]
    endogeneity_ratio: float      # (lambda_total - baseline) / lambda_total in [0, 1]
    branching_spectral_radius: float
    is_stable: bool
    regime: HawkesClusterRegime
    suggested_spread_widening_mult: float


class BivariateHawkesEngine:
    """Real-time streaming bivariate Hawkes process for order flow analysis."""

    def __init__(
        self,
        params: Optional[HawkesParameters] = None,
        max_endogeneity_threshold: float = 0.75,
    ) -> None:
        self.params = params or HawkesParameters()
        self.max_endogeneity_threshold = max_endogeneity_threshold

        # Validate branching ratio matrix spectral radius
        self.spectral_radius, self.is_stable = self._compute_spectral_radius(self.params)

        # Recursive exponential decay state accumulators R_{ij}
        self._last_event_time: float = 0.0
        self._r_bb: float = 0.0
        self._r_bs: float = 0.0
        self._r_sb: float = 0.0
        self._r_ss: float = 0.0

        # Event counts
        self.total_buy_events: int = 0
        self.total_sell_events: int = 0

    @staticmethod
    def _compute_spectral_radius(p: HawkesParameters) -> Tuple[float, bool]:
        """Compute maximum eigenvalue (spectral radius) of branching ratio matrix Gamma.
        
        Gamma = [[alpha_bb/beta, alpha_bs/beta],
                 [alpha_sb/beta, alpha_ss/beta]]
        """
        beta = max(1e-6, p.beta_decay)
        g11 = p.alpha_bb / beta
        g12 = p.alpha_bs / beta
        g21 = p.alpha_sb / beta
        g22 = p.alpha_ss / beta

        trace = g11 + g22
        det = (g11 * g22) - (g12 * g21)
        discriminant = max(0.0, (trace ** 2) - (4.0 * det))
        
        eigen_1 = (trace + math.sqrt(discriminant)) / 2.0
        eigen_2 = (trace - math.sqrt(discriminant)) / 2.0
        spectral_radius = max(abs(eigen_1), abs(eigen_2))
        
        is_stable = (spectral_radius < 1.0)
        return spectral_radius, is_stable

    def _decay_state(self, current_time: float) -> None:
        """Decay recursive accumulators from last event time to current time."""
        if current_time <= self._last_event_time or self._last_event_time == 0.0:
            return

        dt = current_time - self._last_event_time
        decay = math.exp(-self.params.beta_decay * dt)

        self._r_bb *= decay
        self._r_bs *= decay
        self._r_sb *= decay
        self._r_ss *= decay
        self._last_event_time = current_time

    def record_event(self, timestamp: float, event_type: str) -> HawkesIntensitySnapshot:
        """Record trade arrival event: 'BUY' (type 1) or 'SELL' (type 2)."""
        is_buy = event_type.upper().startswith("B")
        
        # Step 1: Decay prior state to this event arrival time
        self._decay_state(timestamp)

        # Step 2: Increment respective impulse
        if is_buy:
            self._r_bb += 1.0
            self._r_sb += 1.0
            self.total_buy_events += 1
        else:
            self._r_bs += 1.0
            self._r_ss += 1.0
            self.total_sell_events += 1

        self._last_event_time = timestamp
        return self.get_intensity(timestamp)

    def get_intensity(self, current_time: float) -> HawkesIntensitySnapshot:
        """Query instantaneous intensities and clustering metrics at current_time."""
        self._decay_state(current_time)

        p = self.params
        lam_buy = p.mu_buy + (p.alpha_bb * self._r_bb) + (p.alpha_bs * self._r_bs)
        lam_sell = p.mu_sell + (p.alpha_sb * self._r_sb) + (p.alpha_ss * self._r_ss)
        lam_total = max(1e-9, lam_buy + lam_sell)

        imbalance = (lam_buy - lam_sell) / lam_total
        base_total = p.mu_buy + p.mu_sell
        
        # Endogeneity ratio: fraction of activity caused by feedback loops
        endogeneity = max(0.0, min(1.0, (lam_total - base_total) / lam_total))

        # Classify regime
        if endogeneity >= self.max_endogeneity_threshold or not self.is_stable:
            regime = HawkesClusterRegime.EXPLOSIVE_CASCADE
            spread_mult = 2.5
        elif abs(imbalance) >= 0.50 and endogeneity > 0.40:
            regime = HawkesClusterRegime.MOMENTUM_CLUSTERING
            spread_mult = 1.6
        elif endogeneity > 0.40:
            regime = HawkesClusterRegime.CROSS_EXCITED_CHOP
            spread_mult = 1.3
        else:
            regime = HawkesClusterRegime.EXOGENOUS_CALM
            spread_mult = 1.0

        return HawkesIntensitySnapshot(
            timestamp=current_time,
            lambda_buy=round(lam_buy, 4),
            lambda_sell=round(lam_sell, 4),
            lambda_total=round(lam_total, 4),
            intensity_imbalance=round(imbalance, 4),
            endogeneity_ratio=round(endogeneity, 4),
            branching_spectral_radius=round(self.spectral_radius, 4),
            is_stable=self.is_stable,
            regime=regime,
            suggested_spread_widening_mult=spread_mult,
        )

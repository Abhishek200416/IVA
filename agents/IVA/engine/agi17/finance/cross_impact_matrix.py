"""Multi-Asset Cross-Impact & Hayashi-Yoshida (2005) Lead-Lag Microstructure Matrix.

Implements structural cross-market price impact and asynchronous lead-lag dynamics
between NIFTY 50 and BANK NIFTY options and futures:
1. Cross-Market Price Impact Matrix (Huberman-Stanzl 2004, Bouchaud et al. 2018):
   - Price change vector: Delta P = Lambda * Q
     [Delta P_1]   [lambda_11  lambda_12] [Q_1]
     [Delta P_2] = [lambda_21  lambda_22] [Q_2]
   - No-Arbitrage / Manipulation-Free Constraints:
     * Positive Definiteness: Symmetric part S = 0.5 * (Lambda + Lambda^T) is positive definite
       (S_11 > 0, S_22 > 0, det(S) > 0), ensuring Q^T Lambda Q > 0 for all non-zero Q.
     * Onsager Reciprocity: lambda_12 = lambda_21 ensures energy conservation / path-independent
       trading costs, mathematically ruling out round-trip money-machine arbitrage loops.
     * Cross-elasticity ratio: rho_impact = (lambda_12 + lambda_21) / (2 * sqrt(lambda_11 * lambda_22)) in (-1, 1).
2. Hayashi-Yoshida (2005) Asynchronous High-Frequency Estimator:
   - Evaluates covariance between non-synchronous, irregularly spaced trade arrival ticks
     without artificial imputation or forward-fill bias:
     Cov_HY = sum_{i, j} Delta P_1(i) * Delta P_2(j) * 1_{ [s_{i-1}, s_i] cap [t_{j-1}, t_j] neq emptyset }
   - Lead-Lag Profile: Evaluates Hayashi-Yoshida correlation across time shifts tau in [-T, +T]
     to identify informational leadership between NIFTY 50 and BANK NIFTY.
3. Cross-Asset Inventory Execution & Delta Rebalancing:
   - Optimal cross-hedging of Bank Nifty with Nifty 50 under cross-impact:
     Q_B* = beta * Q_N + ((lambda_12 - beta * lambda_22) / lambda_22) * Q_N
   - Hard enforcement of Indian statutory constraints:
     * Bank Nifty lot size = 15, Nifty 50 lot size = 25
     * Minimum tick size = 0.05 INR
     * Indian statutory transaction cost hurdle (STT, GST, SEBI turnover, stamp duty).

Zero external dependencies outside standard math and typing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class MarketIndex(str, Enum):
    NIFTY_50 = "NIFTY_50"
    BANK_NIFTY = "BANK_NIFTY"


@dataclass(frozen=True)
class AsynchronousTick:
    """An irregularly timestamped market trade tick."""
    index: MarketIndex
    start_time: float  # arrival time of previous tick
    end_time: float    # arrival time of current tick (start_time < end_time)
    price: float
    price_change: float
    volume: float


@dataclass(frozen=True)
class LeadLagPeak:
    """Result of Hayashi-Yoshida lead-lag cross-correlation scan."""
    optimal_lag_seconds: float
    max_correlation: float
    leading_asset: MarketIndex
    lagging_asset: MarketIndex
    is_statistically_significant: bool


@dataclass(frozen=True)
class CrossRebalanceResult:
    """Optimal cross-asset execution and delta rebalance order."""
    nifty_quantity: int
    nifty_lots: int
    bank_quantity: int
    bank_lots: int
    expected_nifty_impact: float
    expected_bank_impact: float
    total_permanent_cost_inr: float
    statutory_fees_inr: float
    net_economic_cost_inr: float
    is_arbitrage_free: bool
    notes: str


class CrossImpactMatrix:
    """2x2 Price Impact Matrix between NIFTY 50 and BANK NIFTY.

    Matrix structure:
        Lambda = [[lambda_11, lambda_12],
                  [lambda_21, lambda_22]]
    Where:
        1 = NIFTY 50
        2 = BANK NIFTY
    """

    def __init__(
        self,
        lambda_11: float,
        lambda_22: float,
        lambda_12: float,
        lambda_21: float,
        tolerance: float = 1e-12,
    ) -> None:
        if lambda_11 <= 0.0 or lambda_22 <= 0.0:
            raise ValueError(
                f"Self-impact coefficients must be strictly positive: "
                f"lambda_11={lambda_11}, lambda_22={lambda_22}"
            )
        self.lambda_11 = float(lambda_11)
        self.lambda_22 = float(lambda_22)
        self.lambda_12 = float(lambda_12)
        self.lambda_21 = float(lambda_21)
        self.tolerance = float(tolerance)

    @property
    def symmetric_cross(self) -> float:
        """S_12 = 0.5 * (lambda_12 + lambda_21)."""
        return 0.5 * (self.lambda_12 + self.lambda_21)

    @property
    def skewness(self) -> float:
        """Skew-symmetric component: lambda_12 - lambda_21."""
        return self.lambda_12 - self.lambda_21

    @property
    def determinant_symmetric(self) -> float:
        """det(S) = S_11 * S_22 - S_12^2."""
        s12 = self.symmetric_cross
        return (self.lambda_11 * self.lambda_22) - (s12 * s12)

    @property
    def is_positive_definite(self) -> bool:
        """True if quadratic form Q^T Lambda Q > 0 for all non-zero Q.

        Equivalent to Sylvester's criterion on symmetric part:
        S_11 > 0, S_22 > 0, det(S) > 0.
        """
        return (
            self.lambda_11 > 0.0
            and self.lambda_22 > 0.0
            and self.determinant_symmetric > self.tolerance
        )

    @property
    def is_onsager_symmetric(self) -> bool:
        """True if lambda_12 == lambda_21 within tolerance (no path dependence)."""
        return abs(self.skewness) <= max(self.tolerance, 1e-5 * min(self.lambda_11, self.lambda_22))

    @property
    def cross_elasticity(self) -> float:
        """Normalized cross-impact elasticity rho in (-1, 1)."""
        denom = math.sqrt(self.lambda_11 * self.lambda_22)
        if denom <= 0.0:
            return 0.0
        val = self.symmetric_cross / denom
        return max(-0.999999, min(0.999999, val))

    def compute_price_impact(self, q_nifty: float, q_bank: float) -> Tuple[float, float]:
        """Compute mid-price impact: Delta P = Lambda * Q."""
        delta_p_nifty = (self.lambda_11 * q_nifty) + (self.lambda_12 * q_bank)
        delta_p_bank = (self.lambda_21 * q_nifty) + (self.lambda_22 * q_bank)
        return delta_p_nifty, delta_p_bank

    def compute_round_trip_cost(self, q_nifty: float, q_bank: float) -> float:
        """Compute quadratic execution cost: 0.5 * Q^T Lambda Q INR."""
        # 0.5 * (q1 * (l11*q1 + l12*q2) + q2 * (l21*q1 + l22*q2))
        cost = 0.5 * (
            self.lambda_11 * (q_nifty ** 2)
            + (self.lambda_12 + self.lambda_21) * q_nifty * q_bank
            + self.lambda_22 * (q_bank ** 2)
        )
        return cost

    def check_round_trip_arbitrage(self, q_nifty: float, q_bank: float) -> bool:
        """Returns True if a round-trip loop produces positive profit (money machine violation).

        Under positive definiteness, round-trip cost is strictly positive (no arbitrage).
        """
        cost = self.compute_round_trip_cost(q_nifty, q_bank)
        return cost <= 0.0 and (abs(q_nifty) > 1e-4 or abs(q_bank) > 1e-4)

    def cholesky_factors(self) -> Tuple[float, float, float]:
        """Returns lower triangular Cholesky factors (L_11, L_21, L_22) of symmetric part S."""
        if not self.is_positive_definite:
            raise ValueError("Matrix is not positive definite; Cholesky decomposition does not exist.")
        l11 = math.sqrt(self.lambda_11)
        l21 = self.symmetric_cross / l11
        l22_sq = self.lambda_22 - (l21 ** 2)
        if l22_sq <= 0.0:
            raise ValueError("Cholesky factor diagonal non-positive.")
        l22 = math.sqrt(l22_sq)
        return l11, l21, l22

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lambda_11": self.lambda_11,
            "lambda_22": self.lambda_22,
            "lambda_12": self.lambda_12,
            "lambda_21": self.lambda_21,
            "symmetric_cross": self.symmetric_cross,
            "skewness": self.skewness,
            "determinant_symmetric": self.determinant_symmetric,
            "is_positive_definite": self.is_positive_definite,
            "is_onsager_symmetric": self.is_onsager_symmetric,
            "cross_elasticity": self.cross_elasticity,
        }


class HayashiYoshidaEstimator:
    """Hayashi-Yoshida (2005) High-Frequency Asynchronous Cross-Correlation Estimator."""

    @staticmethod
    def calculate_cross_covariance(
        series1: List[AsynchronousTick],
        series2: List[AsynchronousTick],
        time_lag_seconds: float = 0.0,
    ) -> float:
        """Compute Hayashi-Yoshida asynchronous covariance:

        Cov_HY = sum_{i, j} Delta P_1(i) * Delta P_2(j) * 1_{ [s_{i-1}, s_i] cap [t_{j-1}+lag, t_j+lag] neq emptyset }
        """
        if not series1 or not series2:
            return 0.0

        total_cov = 0.0
        # Iterate over all tick interval pairs
        for tick1 in series1:
            s_start = tick1.start_time
            s_end = tick1.end_time
            dp1 = tick1.price_change

            for tick2 in series2:
                # Positive lag tau > 0 means series1 leads series2 by tau (series2 follows at t + tau).
                # To align them, series2 intervals are shifted backward by time_lag_seconds:
                t_start = tick2.start_time - time_lag_seconds
                t_end = tick2.end_time - time_lag_seconds

                # Overlap condition: max(s_start, t_start) < min(s_end, t_end)
                if max(s_start, t_start) < min(s_end, t_end):
                    total_cov += dp1 * tick2.price_change

        return total_cov

    @classmethod
    def calculate_cross_correlation(
        cls,
        series1: List[AsynchronousTick],
        series2: List[AsynchronousTick],
        time_lag_seconds: float = 0.0,
    ) -> float:
        """Compute normalized Hayashi-Yoshida correlation in [-1, +1]."""
        if not series1 or not series2:
            return 0.0

        cov = cls.calculate_cross_covariance(series1, series2, time_lag_seconds)
        var1 = sum(t.price_change ** 2 for t in series1)
        var2 = sum(t.price_change ** 2 for t in series2)

        if var1 <= 1e-12 or var2 <= 1e-12:
            return 0.0

        denom = math.sqrt(var1 * var2)
        corr = cov / denom
        return max(-1.0, min(1.0, corr))

    @classmethod
    def analyze_lead_lag_profile(
        cls,
        series_nifty: List[AsynchronousTick],
        series_bank: List[AsynchronousTick],
        lag_grid_seconds: List[float],
    ) -> LeadLagPeak:
        """Scan across lag_grid_seconds to find optimal lead-lag relationship.

        Positive lag tau > 0: NIFTY leads BANK NIFTY by tau seconds.
        Negative lag tau < 0: BANK NIFTY leads NIFTY by |tau| seconds.
        """
        if not lag_grid_seconds:
            lag_grid_seconds = [0.0]

        best_lag = 0.0
        max_corr = -2.0

        for lag in lag_grid_seconds:
            corr = cls.calculate_cross_correlation(series_nifty, series_bank, time_lag_seconds=lag)
            if corr > max_corr:
                max_corr = corr
                best_lag = lag

        if best_lag > 0.0:
            leading = MarketIndex.NIFTY_50
            lagging = MarketIndex.BANK_NIFTY
        elif best_lag < 0.0:
            leading = MarketIndex.BANK_NIFTY
            lagging = MarketIndex.NIFTY_50
        else:
            leading = MarketIndex.NIFTY_50
            lagging = MarketIndex.BANK_NIFTY

        # Significance heuristic: sample size >= 10 and correlation >= 0.20
        n_obs = min(len(series_nifty), len(series_bank))
        is_significant = n_obs >= 5 and abs(max_corr) >= 0.20

        return LeadLagPeak(
            optimal_lag_seconds=best_lag,
            max_correlation=max_corr,
            leading_asset=leading,
            lagging_asset=lagging,
            is_statistically_significant=is_significant,
        )


class CrossAssetExecutionRebalancer:
    """Optimal Cross-Asset Execution & Delta Rebalancing Engine for Indian Markets."""

    BANK_NIFTY_LOT_SIZE: int = 15
    NIFTY_50_LOT_SIZE: int = 25
    MIN_TICK_SIZE: float = 0.05

    def __init__(
        self,
        impact_matrix: CrossImpactMatrix,
        beta_bank_to_nifty: float = 1.15,
        stt_rate: float = 0.000625,  # 0.0625% on option exercise or 0.0125% futures
        exchange_turnover_rate: float = 0.0005,
        sebi_turnover_rate: float = 0.000001,
        stamp_duty_rate: float = 0.00003,
        gst_rate: float = 0.18,
    ) -> None:
        self.matrix = impact_matrix
        self.beta = float(beta_bank_to_nifty)
        self.stt_rate = float(stt_rate)
        self.exchange_rate = float(exchange_turnover_rate)
        self.sebi_rate = float(sebi_turnover_rate)
        self.stamp_duty_rate = float(stamp_duty_rate)
        self.gst_rate = float(gst_rate)

    @classmethod
    def round_to_tick(cls, price: float) -> float:
        """Enforce strict NSE 0.05 INR tick grid."""
        return round(round(price / cls.MIN_TICK_SIZE) * cls.MIN_TICK_SIZE, 2)

    def calculate_statutory_fees(self, turnover_inr: float) -> float:
        """Indian statutory transaction cost calculation."""
        stt = turnover_inr * self.stt_rate
        exchange_fees = turnover_inr * self.exchange_rate
        sebi_fees = turnover_inr * self.sebi_rate
        stamp_duty = turnover_inr * self.stamp_duty_rate
        gst = exchange_fees * self.gst_rate
        return stt + exchange_fees + sebi_fees + stamp_duty + gst

    def calculate_cross_rebalance(
        self,
        target_nifty_delta: float,
        spot_nifty: float = 24500.0,
        spot_bank: float = 52000.0,
    ) -> CrossRebalanceResult:
        """Calculate optimal cross-hedged Bank Nifty order given a Nifty target delta.

        Theoretical formula:
            Q_B* = beta * Q_N + ((lambda_12 - beta * lambda_22) / lambda_22) * Q_N
        """
        # Unconstrained theoretical quantities
        q_nifty_theoretical = target_nifty_delta
        # Cross-impact adjustment term
        cross_term = (self.matrix.lambda_12 - (self.beta * self.matrix.lambda_22)) / self.matrix.lambda_22
        q_bank_theoretical = (self.beta * q_nifty_theoretical) + (cross_term * q_nifty_theoretical)

        # Enforce NSE contract lot alignment
        nifty_lots = round(q_nifty_theoretical / self.NIFTY_50_LOT_SIZE)
        nifty_quantity = nifty_lots * self.NIFTY_50_LOT_SIZE

        bank_lots = round(q_bank_theoretical / self.BANK_NIFTY_LOT_SIZE)
        bank_quantity = bank_lots * self.BANK_NIFTY_LOT_SIZE

        # Expected price impacts
        imp_nifty, imp_bank = self.matrix.compute_price_impact(nifty_quantity, bank_quantity)
        imp_nifty = self.round_to_tick(imp_nifty)
        imp_bank = self.round_to_tick(imp_bank)

        # Permanent execution impact cost
        impact_cost = self.matrix.compute_round_trip_cost(nifty_quantity, bank_quantity)

        # Statutory fees
        turnover = (abs(nifty_quantity) * spot_nifty) + (abs(bank_quantity) * spot_bank)
        statutory_fees = self.calculate_statutory_fees(turnover)

        total_net_cost = impact_cost + statutory_fees
        is_arbitrage_free = self.matrix.is_positive_definite and impact_cost >= 0.0

        notes = (
            f"Cross-rebalance Nifty Lots: {nifty_lots} ({nifty_quantity} contracts), "
            f"Bank Nifty Lots: {bank_lots} ({bank_quantity} contracts). "
            f"Cross elasticity: {self.matrix.cross_elasticity:.4f}."
        )

        return CrossRebalanceResult(
            nifty_quantity=nifty_quantity,
            nifty_lots=nifty_lots,
            bank_quantity=bank_quantity,
            bank_lots=bank_lots,
            expected_nifty_impact=imp_nifty,
            expected_bank_impact=imp_bank,
            total_permanent_cost_inr=impact_cost,
            statutory_fees_inr=statutory_fees,
            net_economic_cost_inr=total_net_cost,
            is_arbitrage_free=is_arbitrage_free,
            notes=notes,
        )

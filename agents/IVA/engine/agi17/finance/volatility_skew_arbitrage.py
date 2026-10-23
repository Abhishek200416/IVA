"""AGI 1.7 Volatility Smile Skew & Risk-Reversal Statistical Arbitrage Engine.

TASK-BN-19:
Implements quantitative volatility smile skew and risk-reversal arbitrage for BANK NIFTY options:
1. 25-Delta and 20-Delta Risk Reversal (RR) extraction:
   RR = IV_Call - IV_Put
2. 25-Delta Butterfly (BF) / Smile curvature calculation:
   BF = (IV_Call + IV_Put) / 2 - IV_ATM
3. Rolling skew z-score statistical mispricing detection against baseline (mu_skew, sigma_skew).
4. Delta-neutral synthetic structure recommendation:
   - OVERPRICED_PUT_SKEW (z >= +2.0): Short Put Skew (Sell OTM Put, Buy OTM Call, Delta Hedge Short Future/ATM)
   - UNDERPRICED_PUT_SKEW (z <= -2.0): Long Put Skew (Buy OTM Put, Sell OTM Call, Delta Hedge Long Future/ATM)
5. Indian statutory transaction cost and slippage hurdle deductions (STT, GST, SEBI, Brokerage).
6. Net Delta and Vega exposure accounting.
"""

from __future__ import annotations

import dataclasses
import enum
import math
from typing import Any, Dict, List, Optional

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import OrderSide
from .options_math import OptionsMath


class SkewRegime(enum.Enum):
    """Classification of the intraday volatility smile skew."""

    OVERPRICED_PUT_SKEW = "OVERPRICED_PUT_SKEW"      # z >= +2.0: Puts heavily rich
    MODERATELY_HIGH_SKEW = "MODERATELY_HIGH_SKEW"    # +1.0 <= z < +2.0
    FAIR_VALUE_EQUILIBRIUM = "FAIR_VALUE_EQUILIBRIUM"  # -1.0 < z < +1.0
    MODERATELY_LOW_SKEW = "MODERATELY_LOW_SKEW"      # -2.0 < z <= -1.0
    UNDERPRICED_PUT_SKEW = "UNDERPRICED_PUT_SKEW"    # z <= -2.0: Puts unusually cheap


class SkewArbitrageAction(enum.Enum):
    """Trading action recommended for volatility skew arbitrage."""

    SELL_PUT_BUY_CALL_HEDGE = "SELL_PUT_BUY_CALL_HEDGE"  # Short Put Skew (Neutralized)
    BUY_PUT_SELL_CALL_HEDGE = "BUY_PUT_SELL_CALL_HEDGE"  # Long Put Skew (Neutralized)
    NO_TRADE = "NO_TRADE"


@dataclasses.dataclass(frozen=True)
class SkewMetricsSnapshot:
    """Quantitative metrics extracted from the option smile."""

    spot_price: float
    atm_strike: float
    atm_iv: float
    call_25d_strike: float
    call_25d_iv: float
    put_25d_strike: float
    put_25d_iv: float
    risk_reversal_pts: float       # IV_Call - IV_Put (typically negative for equity index)
    put_skew_pts: float            # IV_Put - IV_Call (typically positive)
    butterfly_pts: float           # (IV_Call + IV_Put) / 2 - IV_ATM (smile curvature)
    historical_skew_mean: float
    historical_skew_std: float
    skew_z_score: float
    regime: SkewRegime


@dataclasses.dataclass(frozen=True)
class SkewArbitrageTradeProposal:
    """Trade proposal for a delta-hedged volatility skew statistical arbitrage."""

    action: SkewArbitrageAction
    regime: SkewRegime
    skew_z_score: float
    expected_edge_pts: float
    theoretical_gross_inr: float
    estimated_friction_inr: float
    net_expected_edge_inr: float
    net_delta: float
    net_vega: float
    legs: list[dict[str, Any]]
    delta_hedge_leg: dict[str, Any]
    is_actionable: bool
    rationale: str


class VolatilitySkewArbitrageEngine:
    """Detects and generates executable statistical arbitrage trades on volatility smile skew."""

    Z_SCORE_ENTRY_THRESHOLD: float = 2.0  # Statistical significance cutoff (|z| >= 2.0)
    MIN_NET_EDGE_INR: float = 400.0       # Minimum profit hurdle in INR per lot after friction (>= 26 pts)

    @classmethod
    def calculate_skew_metrics(
        cls,
        spot_price: float,
        atm_strike: float,
        atm_iv: float,
        call_25d_strike: float,
        call_25d_iv: float,
        put_25d_strike: float,
        put_25d_iv: float,
        historical_skew_mean: float = 0.035,  # 3.5% historical mean put skew (Put IV - Call IV)
        historical_skew_std: float = 0.008,   # 0.8% standard deviation
    ) -> SkewMetricsSnapshot:
        """Computes Risk Reversal, Butterfly curvature, and Skew Z-score."""
        if historical_skew_std <= 0:
            raise ValueError(f"historical_skew_std must be positive, got {historical_skew_std}")

        # Risk Reversal: Call IV - Put IV
        rr = call_25d_iv - put_25d_iv
        # Put Skew: Put IV - Call IV
        put_skew = put_25d_iv - call_25d_iv
        # Smile Curvature / Butterfly: average wings minus ATM
        butterfly = ((call_25d_iv + put_25d_iv) / 2.0) - atm_iv

        # Z-Score of the Put Skew
        z_score = round((put_skew - historical_skew_mean) / historical_skew_std, 2)

        if z_score >= cls.Z_SCORE_ENTRY_THRESHOLD:
            regime = SkewRegime.OVERPRICED_PUT_SKEW
        elif z_score >= 1.0:
            regime = SkewRegime.MODERATELY_HIGH_SKEW
        elif z_score <= -cls.Z_SCORE_ENTRY_THRESHOLD:
            regime = SkewRegime.UNDERPRICED_PUT_SKEW
        elif z_score <= -1.0:
            regime = SkewRegime.MODERATELY_LOW_SKEW
        else:
            regime = SkewRegime.FAIR_VALUE_EQUILIBRIUM

        return SkewMetricsSnapshot(
            spot_price=spot_price,
            atm_strike=atm_strike,
            atm_iv=round(atm_iv, 4),
            call_25d_strike=call_25d_strike,
            call_25d_iv=round(call_25d_iv, 4),
            put_25d_strike=put_25d_strike,
            put_25d_iv=round(put_25d_iv, 4),
            risk_reversal_pts=round(rr, 4),
            put_skew_pts=round(put_skew, 4),
            butterfly_pts=round(butterfly, 4),
            historical_skew_mean=round(historical_skew_mean, 4),
            historical_skew_std=round(historical_skew_std, 4),
            skew_z_score=z_score,
            regime=regime,
        )

    @classmethod
    def evaluate_arbitrage_opportunity(
        cls,
        metrics: SkewMetricsSnapshot,
        dte: float = 14.0,
        lots: int = 1,
        underlying_price: Optional[float] = None,
        statutory_friction_per_lot_inr: float = 120.0,
    ) -> SkewArbitrageTradeProposal:
        """Evaluates delta-hedged statistical arbitrage trade feasibility and net edge."""
        spot = underlying_price or metrics.spot_price
        t_years = max(1.0 / 365.0, dte / 365.0)
        units_per_lot = BankNiftyContractSpec.LOT_SIZE
        total_units = lots * units_per_lot

        # Vega calculation (approximate aggregate 25d vega per contract)
        # S * sqrt(T) * n(d1) * 0.01
        d1_approx = 0.675  # ~ 25-delta standard normal quantile
        nd1 = (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * d1_approx * d1_approx)
        vega_per_unit = spot * math.sqrt(t_years) * nd1 * 0.01  # Vega per 1% vol change

        if metrics.regime == SkewRegime.OVERPRICED_PUT_SKEW:
            # Overpriced Put Skew: Sell Put (high IV), Buy Call (low IV)
            # Short Put (+0.25 delta), Long Call (+0.25 delta) -> Net +0.50 delta (Synthetic Long)
            # Delta hedge: Short 0.50 delta (e.g. Sell ATM Call or Short Underlying)
            vol_edge_pts = abs(metrics.put_skew_pts - metrics.historical_skew_mean)
            # Expected gross gain as skew reverts to mean (pts * 100 * vega)
            gross_gain_pts = (vol_edge_pts * 100.0) * (vega_per_unit / spot) * spot * 0.5
            theoretical_gross_inr = round(gross_gain_pts * total_units, 2)
            friction_inr = round(statutory_friction_per_lot_inr * lots, 2)
            net_edge_inr = round(theoretical_gross_inr - friction_inr, 2)

            is_actionable = net_edge_inr >= (cls.MIN_NET_EDGE_INR * lots)

            legs = [
                {
                    "symbol": f"BANKNIFTY-{metrics.put_25d_strike}-PE",
                    "side": OrderSide.SELL,
                    "strike": metrics.put_25d_strike,
                    "iv": metrics.put_25d_iv,
                    "delta": -0.25,  # Short position contributes +0.25 delta
                    "units": total_units,
                },
                {
                    "symbol": f"BANKNIFTY-{metrics.call_25d_strike}-CE",
                    "side": OrderSide.BUY,
                    "strike": metrics.call_25d_strike,
                    "iv": metrics.call_25d_iv,
                    "delta": 0.25,   # Long position contributes +0.25 delta
                    "units": total_units,
                },
            ]

            delta_hedge = {
                "instrument": "UNDERLYING_FUTURE",
                "side": OrderSide.SELL,
                "delta": -0.50,
                "hedge_units": int(total_units * 0.50),
            }

            return SkewArbitrageTradeProposal(
                action=SkewArbitrageAction.SELL_PUT_BUY_CALL_HEDGE,
                regime=metrics.regime,
                skew_z_score=metrics.skew_z_score,
                expected_edge_pts=round(gross_gain_pts, 2),
                theoretical_gross_inr=theoretical_gross_inr,
                estimated_friction_inr=friction_inr,
                net_expected_edge_inr=net_edge_inr,
                net_delta=0.0,  # Delta-neutral
                net_vega=round(-vega_per_unit * total_units * 0.5, 2),
                legs=legs,
                delta_hedge_leg=delta_hedge,
                is_actionable=is_actionable,
                rationale=(
                    f"Overpriced Put Skew (Z = +{metrics.skew_z_score:.2f} >= 2.0). "
                    f"Sell rich 25D PE ({metrics.put_25d_iv * 100:.1f}%), Buy 25D CE ({metrics.call_25d_iv * 100:.1f}%). "
                    f"Hedge +0.50 delta via short future. Net Edge: INR {net_edge_inr:.2f}."
                ),
            )

        elif metrics.regime == SkewRegime.UNDERPRICED_PUT_SKEW:
            # Underpriced Put Skew: Buy Put (cheap IV), Sell Call (rich IV)
            # Long Put (-0.25 delta), Short Call (-0.25 delta) -> Net -0.50 delta (Synthetic Short)
            # Delta hedge: Long 0.50 delta (Buy future)
            vol_edge_pts = abs(metrics.historical_skew_mean - metrics.put_skew_pts)
            gross_gain_pts = (vol_edge_pts * 100.0) * (vega_per_unit / spot) * spot * 0.5
            theoretical_gross_inr = round(gross_gain_pts * total_units, 2)
            friction_inr = round(statutory_friction_per_lot_inr * lots, 2)
            net_edge_inr = round(theoretical_gross_inr - friction_inr, 2)

            is_actionable = net_edge_inr >= (cls.MIN_NET_EDGE_INR * lots)

            legs = [
                {
                    "symbol": f"BANKNIFTY-{metrics.put_25d_strike}-PE",
                    "side": OrderSide.BUY,
                    "strike": metrics.put_25d_strike,
                    "iv": metrics.put_25d_iv,
                    "delta": -0.25,
                    "units": total_units,
                },
                {
                    "symbol": f"BANKNIFTY-{metrics.call_25d_strike}-CE",
                    "side": OrderSide.SELL,
                    "strike": metrics.call_25d_strike,
                    "iv": metrics.call_25d_iv,
                    "delta": -0.25,  # Short call contributes -0.25 delta
                    "units": total_units,
                },
            ]

            delta_hedge = {
                "instrument": "UNDERLYING_FUTURE",
                "side": OrderSide.BUY,
                "delta": 0.50,
                "hedge_units": int(total_units * 0.50),
            }

            return SkewArbitrageTradeProposal(
                action=SkewArbitrageAction.BUY_PUT_SELL_CALL_HEDGE,
                regime=metrics.regime,
                skew_z_score=metrics.skew_z_score,
                expected_edge_pts=round(gross_gain_pts, 2),
                theoretical_gross_inr=theoretical_gross_inr,
                estimated_friction_inr=friction_inr,
                net_expected_edge_inr=net_edge_inr,
                net_delta=0.0,
                net_vega=round(vega_per_unit * total_units * 0.5, 2),
                legs=legs,
                delta_hedge_leg=delta_hedge,
                is_actionable=is_actionable,
                rationale=(
                    f"Underpriced Put Skew (Z = {metrics.skew_z_score:.2f} <= -2.0). "
                    f"Buy cheap 25D PE ({metrics.put_25d_iv * 100:.1f}%), Sell 25D CE ({metrics.call_25d_iv * 100:.1f}%). "
                    f"Hedge -0.50 delta via long future. Net Edge: INR {net_edge_inr:.2f}."
                ),
            )

        else:
            return SkewArbitrageTradeProposal(
                action=SkewArbitrageAction.NO_TRADE,
                regime=metrics.regime,
                skew_z_score=metrics.skew_z_score,
                expected_edge_pts=0.0,
                theoretical_gross_inr=0.0,
                estimated_friction_inr=0.0,
                net_expected_edge_inr=0.0,
                net_delta=0.0,
                net_vega=0.0,
                legs=[],
                delta_hedge_leg={},
                is_actionable=False,
                rationale=(
                    f"Skew in normal equilibrium band (Z = {metrics.skew_z_score:.2f}). "
                    "No statistical skew mispricing detected. Capital preserved."
                ),
            )

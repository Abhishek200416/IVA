"""AGI 1.7 Multi-Horizon Options Structure Screener & Ratio Spread Engine.

TASK-BN-28:
Provides:
1. Multi-Horizon Term Structure Analysis:
   - Annualized IV term structure slope extraction:
     Slope = (IV_far - IV_near) / (sqrt(T_far) - sqrt(T_near))
   - Classification into CONTANGO, BACKWARDATION, or FLAT regimes.
2. Calendar & Diagonal Spread Screener:
   - Evaluates near vs far horizontal expiry spreads.
   - Enforces SEBI Circular 2024/132: disallows calendar margin offsets on expiry day (T-0).
   - Aggregates multi-leg Greeks (Theta harvest vs Vega resilience).
3. 1x2 Ratio Spread Engine (Calls and Puts):
   - Buy 1 ATM/near-OTM leg, Sell 2 outer OTM legs for net credit or zero debit.
   - Models asymmetric payoff profile, maximum profit peak at short strike, and uncapped wing risk.
   - Enforces strict pre-trade Extreme Loss Margin (ELM) checks and wing disaster thresholds.
4. Quantitative Structure Scoring & Ranking:
   - Multi-metric ranking by Theta-to-Margin efficiency, Risk-Reward, and Vega exposure.
5. Strict Safe Harbor: Zero real-money API paths (strictly simulated paper trading).
"""

from __future__ import annotations

import dataclasses
import enum
import math
from typing import Any, Dict, List, Optional, Tuple

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import OrderSide
from .options_math import OptionsMath
from .sebi_regulations import SebiDerivativeRegulatoryEngine


class TermStructureRegime(enum.Enum):
    """Classification of options implied volatility term structure."""

    CONTANGO = "CONTANGO"            # IV increases with maturity (normal, far > near)
    BACKWARDATION = "BACKWARDATION"  # IV decreases with maturity (event/panic, near > far)
    FLAT = "FLAT"                    # IV approximately equal across maturities


class StructureType(enum.Enum):
    """Classification of multi-leg option structures."""

    LONG_CALENDAR_SPREAD = "LONG_CALENDAR_SPREAD"
    SHORT_CALENDAR_SPREAD = "SHORT_CALENDAR_SPREAD"
    DIAGONAL_SPREAD = "DIAGONAL_SPREAD"
    RATIO_1X2_SPREAD = "RATIO_1X2_SPREAD"


@dataclasses.dataclass(frozen=True)
class TermStructureCurve:
    """Summary of IV term structure between two distinct expiry horizons."""

    near_dte_days: int
    far_dte_days: int
    near_iv: float
    far_iv: float
    term_slope: float
    regime: TermStructureRegime


@dataclasses.dataclass(frozen=True)
class SpreadLeg:
    """Individual option leg in a multi-expiry or multi-strike structure."""

    symbol: str
    side: OrderSide
    units: int
    strike: float
    dte_days: int
    is_call: bool
    iv: float
    premium: float
    delta: float
    gamma: float
    theta: float
    vega: float


@dataclasses.dataclass(frozen=True)
class OptionsStructureProposal:
    """Complete quantitative specification and evaluation of an option structure."""

    proposal_id: str
    structure_type: StructureType
    underlying_spot: float
    legs: List[SpreadLeg]
    net_debit_or_credit_inr: float   # Positive = debit paid; negative = net credit collected
    max_profit_inr: float
    max_loss_inr: float              # Positive float or math.inf for open-ended tail risk
    breakeven_prices: List[float]
    aggregate_delta: float
    aggregate_gamma: float
    aggregate_theta: float
    aggregate_vega: float
    total_margin_required_inr: float
    sebi_calendar_benefit_allowed: bool
    is_risk_acceptable: bool
    rejection_reason: Optional[str] = None
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "structure_type": self.structure_type.value,
            "underlying_spot": self.underlying_spot,
            "legs_count": len(self.legs),
            "net_debit_or_credit_inr": self.net_debit_or_credit_inr,
            "max_profit_inr": self.max_profit_inr,
            "max_loss_inr": self.max_loss_inr,
            "breakeven_prices": self.breakeven_prices,
            "aggregate_delta": self.aggregate_delta,
            "aggregate_gamma": self.aggregate_gamma,
            "aggregate_theta": self.aggregate_theta,
            "aggregate_vega": self.aggregate_vega,
            "total_margin_required_inr": self.total_margin_required_inr,
            "sebi_calendar_benefit_allowed": self.sebi_calendar_benefit_allowed,
            "is_risk_acceptable": self.is_risk_acceptable,
            "rejection_reason": self.rejection_reason,
            "score": self.score,
        }


class OptionsStructureScreener:
    """Quantitative screener for calendar, diagonal, and 1x2 ratio option structures."""

    SLOPE_THRESHOLD: float = 0.02
    ANNUAL_DAYS: float = 365.0

    @classmethod
    def analyze_term_structure(
        cls,
        *,
        near_dte_days: int,
        near_iv: float,
        far_dte_days: int,
        far_iv: float,
    ) -> TermStructureCurve:
        """Computes annualized IV term structure slope between two expiries."""
        t_near = max(1.0, near_dte_days) / cls.ANNUAL_DAYS
        t_far = max(2.0, far_dte_days) / cls.ANNUAL_DAYS

        sqrt_diff = math.sqrt(t_far) - math.sqrt(t_near)
        if sqrt_diff <= 0.0001:
            slope = 0.0
        else:
            slope = round((far_iv - near_iv) / sqrt_diff, 4)

        if slope > cls.SLOPE_THRESHOLD:
            regime = TermStructureRegime.CONTANGO
        elif slope < -cls.SLOPE_THRESHOLD:
            regime = TermStructureRegime.BACKWARDATION
        else:
            regime = TermStructureRegime.FLAT

        return TermStructureCurve(
            near_dte_days=near_dte_days,
            far_dte_days=far_dte_days,
            near_iv=round(near_iv, 4),
            far_iv=round(far_iv, 4),
            term_slope=slope,
            regime=regime,
        )

    @classmethod
    def screen_calendar_spread(
        cls,
        *,
        spot: float,
        strike: float,
        near_dte_days: int,
        near_iv: float,
        far_dte_days: int,
        far_iv: float,
        is_call: bool = True,
        is_near_expiry_day: bool = False,
        lots: int = 1,
    ) -> OptionsStructureProposal:
        """Evaluates a Long Calendar Spread: Sell Near-Month, Buy Far-Month at same strike."""
        units = lots * BankNiftyContractSpec.LOT_SIZE
        t_near = max(0.1, near_dte_days) / cls.ANNUAL_DAYS
        t_far = max(1.0, far_dte_days) / cls.ANNUAL_DAYS

        # Near leg Greeks (Short)
        near_greeks = OptionsMath.calculate_greeks(
            spot=spot,
            strike=strike,
            time_to_expiry_years=t_near,
            volatility=near_iv,
            is_call=is_call,
        )
        near_premium = round(near_greeks["price"], 2)

        # Far leg Greeks (Long)
        far_greeks = OptionsMath.calculate_greeks(
            spot=spot,
            strike=strike,
            time_to_expiry_years=t_far,
            volatility=far_iv,
            is_call=is_call,
        )
        far_premium = round(far_greeks["price"], 2)

        # Net Debit (Long far - Short near)
        net_debit_per_unit = round(far_premium - near_premium, 2)
        total_net_debit = round(net_debit_per_unit * units, 2)

        # Legs setup
        opt_suffix = "CE" if is_call else "PE"
        near_leg = SpreadLeg(
            symbol=f"BANKNIFTY_{near_dte_days}D_{int(strike)}{opt_suffix}",
            side=OrderSide.SELL,
            units=units,
            strike=strike,
            dte_days=near_dte_days,
            is_call=is_call,
            iv=near_iv,
            premium=near_premium,
            delta=round(-near_greeks["delta"] * units, 3),
            gamma=round(-near_greeks["gamma"] * units, 5),
            theta=round(-near_greeks["theta"] * units, 2),  # Positive theta contribution from short leg
            vega=round(-near_greeks["vega"] * units, 2),
        )

        far_leg = SpreadLeg(
            symbol=f"BANKNIFTY_{far_dte_days}D_{int(strike)}{opt_suffix}",
            side=OrderSide.BUY,
            units=units,
            strike=strike,
            dte_days=far_dte_days,
            is_call=is_call,
            iv=far_iv,
            premium=far_premium,
            delta=round(far_greeks["delta"] * units, 3),
            gamma=round(far_greeks["gamma"] * units, 5),
            theta=round(far_greeks["theta"] * units, 2),   # Negative theta drag from long leg
            vega=round(far_greeks["vega"] * units, 2),     # Positive vega from long leg
        )

        agg_delta = round(near_leg.delta + far_leg.delta, 3)
        agg_gamma = round(near_leg.gamma + far_leg.gamma, 5)
        agg_theta = round(near_leg.theta + far_leg.theta, 2)
        agg_vega = round(near_leg.vega + far_leg.vega, 2)

        # SEBI Margin Calculation per Circular 2024/132
        # Calendar spread benefit allowed ONLY when near leg is NOT expiring today
        calendar_benefit_allowed = not is_near_expiry_day
        if calendar_benefit_allowed:
            # Margin reduced to maximum loss + basis risk buffer (~30% of standard short option SPAN)
            margin_req = round(max(total_net_debit, units * spot * 0.035), 2)
        else:
            # On expiry day, both legs required full independent margin:
            # 100% upfront premium for long + full SPAN + 5.5% ELM for short leg
            short_notional = units * spot
            short_span_elm = short_notional * (0.10 + 0.055)
            long_upfront = total_net_debit + (near_premium * units)
            margin_req = round(short_span_elm + long_upfront, 2)

        # Estimated Max Profit occurs at strike at near expiry:
        # Near leg decays to 0, far leg retains residual value
        far_residual = OptionsMath.black_scholes_price(
            spot=strike,
            strike=strike,
            time_to_expiry_years=max(0.1, far_dte_days - near_dte_days) / cls.ANNUAL_DAYS,
            volatility=far_iv,
            is_call=is_call,
        )
        max_profit = round((far_residual - net_debit_per_unit) * units, 2)
        max_profit = max(0.0, max_profit)
        max_loss = max(0.0, total_net_debit)

        # Scoring
        score = 0.0
        if max_loss > 0 and margin_req > 0:
            theta_yield = max(0.0, agg_theta) / margin_req * 100.0
            rr_ratio = max_profit / max_loss
            score = round(rr_ratio * 10.0 + theta_yield * 50.0 + (agg_vega * 0.1), 2)

        return OptionsStructureProposal(
            proposal_id=f"PROP-CAL-{int(strike)}-{near_dte_days}D-{far_dte_days}D",
            structure_type=StructureType.LONG_CALENDAR_SPREAD,
            underlying_spot=spot,
            legs=[near_leg, far_leg],
            net_debit_or_credit_inr=total_net_debit,
            max_profit_inr=max_profit,
            max_loss_inr=max_loss,
            breakeven_prices=[round(strike - (net_debit_per_unit * 1.5), 2), round(strike + (net_debit_per_unit * 1.5), 2)],
            aggregate_delta=agg_delta,
            aggregate_gamma=agg_gamma,
            aggregate_theta=agg_theta,
            aggregate_vega=agg_vega,
            total_margin_required_inr=margin_req,
            sebi_calendar_benefit_allowed=calendar_benefit_allowed,
            is_risk_acceptable=total_net_debit > 0 and max_profit > 0,
            score=score,
        )

    @classmethod
    def screen_ratio_spread(
        cls,
        *,
        spot: float,
        long_strike: float,
        short_strike: float,
        dte_days: int,
        atm_iv: float,
        is_call: bool = True,
        is_expiry_day: bool = False,
        lots: int = 1,
        max_capital_risk_inr: float = 100_000.0,
    ) -> OptionsStructureProposal:
        """Evaluates a 1x2 Ratio Spread: Buy 1 ATM/near-OTM, Sell 2 further OTM options."""
        base_units = lots * BankNiftyContractSpec.LOT_SIZE
        t_exp = max(0.1, dte_days) / cls.ANNUAL_DAYS

        # Model skew: short strike OTM has lower or higher IV based on Call/Put wing
        wing_iv = round(atm_iv * (0.95 if is_call else 1.08), 4)

        long_greeks = OptionsMath.calculate_greeks(
            spot=spot,
            strike=long_strike,
            time_to_expiry_years=t_exp,
            volatility=atm_iv,
            is_call=is_call,
        )
        long_premium = round(long_greeks["price"], 2)

        short_greeks = OptionsMath.calculate_greeks(
            spot=spot,
            strike=short_strike,
            time_to_expiry_years=t_exp,
            volatility=wing_iv,
            is_call=is_call,
        )
        short_premium = round(short_greeks["price"], 2)

        # 1x2 structure: 1 Long, 2 Short
        long_units = base_units
        short_units = base_units * 2

        # Net cash flow: (2 * short_premium) - long_premium
        # If positive, it's a net credit collected (expressed as negative net debit)
        net_cash_flow_per_lot = (2.0 * short_premium) - long_premium
        net_debit_or_credit = round(-net_cash_flow_per_lot * base_units, 2)  # negative = net credit

        opt_suffix = "CE" if is_call else "PE"
        leg1 = SpreadLeg(
            symbol=f"BANKNIFTY_{dte_days}D_{int(long_strike)}{opt_suffix}",
            side=OrderSide.BUY,
            units=long_units,
            strike=long_strike,
            dte_days=dte_days,
            is_call=is_call,
            iv=atm_iv,
            premium=long_premium,
            delta=round(long_greeks["delta"] * long_units, 3),
            gamma=round(long_greeks["gamma"] * long_units, 5),
            theta=round(long_greeks["theta"] * long_units, 2),
            vega=round(long_greeks["vega"] * long_units, 2),
        )

        leg2 = SpreadLeg(
            symbol=f"BANKNIFTY_{dte_days}D_{int(short_strike)}{opt_suffix}",
            side=OrderSide.SELL,
            units=short_units,
            strike=short_strike,
            dte_days=dte_days,
            is_call=is_call,
            iv=wing_iv,
            premium=short_premium,
            delta=round(-short_greeks["delta"] * short_units, 3),
            gamma=round(-short_greeks["gamma"] * short_units, 5),
            theta=round(-short_greeks["theta"] * short_units, 2),
            vega=round(-short_greeks["vega"] * short_units, 2),
        )

        agg_delta = round(leg1.delta + leg2.delta, 3)
        agg_gamma = round(leg1.gamma + leg2.gamma, 5)
        agg_theta = round(leg1.theta + leg2.theta, 2)
        agg_vega = round(leg1.vega + leg2.vega, 2)

        # Strike width
        width = abs(short_strike - long_strike)
        # Max profit occurs exactly at short strike at expiry
        max_profit_per_unit = width + net_cash_flow_per_lot
        max_profit = round(max_profit_per_unit * base_units, 2)

        # Uncapped tail risk occurs beyond the short strike:
        # Breakeven = short_strike + width + net_credit_per_unit
        if is_call:
            breakeven = round(short_strike + max_profit_per_unit, 2)
            breakevens = [breakeven]
        else:
            breakeven = round(short_strike - max_profit_per_unit, 2)
            breakevens = [breakeven]

        # SEBI Margin requirement:
        # The 1 long leg offsets 1 short leg as a vertical credit/debit spread.
        # The remaining 1 short leg is naked, requiring standard SPAN + Exposure margin (plus 2% ELM on expiry).
        spread_margin = round(width * base_units, 2)
        naked_notional = base_units * spot
        elm_rate = 0.055 if is_expiry_day else 0.035
        naked_short_margin = round(naked_notional * (0.10 + elm_rate), 2)
        total_margin = round(spread_margin + naked_short_margin, 2)

        # Risk validation: Max loss is theoretically uncapped beyond breakeven
        # Tail loss at 5% underlying move beyond short strike
        tail_move = spot * 0.05
        tail_loss_est = round(tail_move * base_units, 2)

        is_acceptable = True
        rejection_reason = None
        if total_margin > (max_capital_risk_inr * 10.0):
            is_acceptable = False
            rejection_reason = f"Margin required (₹{total_margin:,.2f}) exceeds risk ceiling"
        elif tail_loss_est > (max_capital_risk_inr * 2.0):
            is_acceptable = False
            rejection_reason = f"Unhedged tail risk (₹{tail_loss_est:,.2f}) exceeds disaster buffer"

        # Ratio spread score: rewards net credit and theta decay with margin efficiency
        score = 0.0
        if total_margin > 0:
            credit_score = max(0.0, -net_debit_or_credit) / total_margin * 100.0
            theta_eff = max(0.0, agg_theta) / total_margin * 100.0
            score = round(credit_score * 20.0 + theta_eff * 30.0 + (max_profit / total_margin * 10.0), 2)

        return OptionsStructureProposal(
            proposal_id=f"PROP-RATIO-{int(long_strike)}x{int(short_strike)}-{dte_days}D",
            structure_type=StructureType.RATIO_1X2_SPREAD,
            underlying_spot=spot,
            legs=[leg1, leg2],
            net_debit_or_credit_inr=net_debit_or_credit,
            max_profit_inr=max_profit,
            max_loss_inr=float("inf"),  # Asymmetric tail risk
            breakeven_prices=breakevens,
            aggregate_delta=agg_delta,
            aggregate_gamma=agg_gamma,
            aggregate_theta=agg_theta,
            aggregate_vega=agg_vega,
            total_margin_required_inr=total_margin,
            sebi_calendar_benefit_allowed=True,
            is_risk_acceptable=is_acceptable,
            rejection_reason=rejection_reason,
            score=score,
        )

    @classmethod
    def rank_proposals(
        cls,
        proposals: List[OptionsStructureProposal],
    ) -> List[OptionsStructureProposal]:
        """Filters and ranks proposals by composite quantitative score descending."""
        valid_proposals = [p for p in proposals if p.is_risk_acceptable]
        return sorted(valid_proposals, key=lambda p: p.score, reverse=True)

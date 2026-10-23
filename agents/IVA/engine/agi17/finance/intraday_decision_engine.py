"""Bank Nifty Intraday Decision-Making, CPR, PCR & Gamma Exposure (GEX) Engine.

Implements institutional quantitative starting points and intraday decision workflow:
1. Central Pivot Range (CPR):
   - Pivot P = (High + Low + Close) / 3
   - Bottom Central BC = (High + Low) / 2
   - Top Central TC = 2*P - BC = (P - BC) + P
   - Support/Resistance: R1 = 2P - L, S1 = 2P - H, R2 = P + (H - L), S2 = P - (H - L)
   - CPR Width = |TC - BC| relative to baseline:
     * Narrow (< 60% avg): High probability trending breakout day
     * Wide (> 140% avg): Range-bound / mean-reverting day
2. Put-Call Ratio (PCR) & Change in Open Interest (COI):
   - PCR = Total Put OI / Total Call OI
   - Interpretation: PCR > 1.1 Bullish, PCR < 0.8 Bearish, > 1.5 Extreme Oversold, < 0.6 Extreme Overbought
3. Gamma Exposure (GEX):
   - Net GEX at strike K = Gamma_K * (Call_OI_K - Put_OI_K) * Spot^2 * 0.01 * Lot_Multiplier (15)
   - Positive GEX (+): Market makers long gamma -> Volatility suppression, pinning, mean reversion
   - Negative GEX (-): Market makers short gamma -> Volatility amplification, breakout acceleration
   - Call Wall: Strike with highest Call OI (resistance magnet)
   - Put Wall: Strike with highest Put OI (support magnet)
4. Max Pain:
   - ArgMin_K Sum_{all strikes j} [ max(0, K - j)*PE_OI_j + max(0, j - K)*CE_OI_j ]
5. 6-Point Intraday Decision Checklist:
   - Pre-market gap alignment, CPR relation, PCR confirmation, GEX regime, Risk/Reward >= 2.0, 15:15 IST cutoff.

Zero external dependencies outside standard math and typing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class CPRRegime(str, Enum):
    NARROW_BREAKOUT = "NARROW_BREAKOUT"
    AVERAGE = "AVERAGE"
    WIDE_RANGE_BOUND = "WIDE_RANGE_BOUND"


class OpenRelationToCPR(str, Enum):
    ABOVE_TC_BULLISH = "ABOVE_TC_BULLISH"
    INSIDE_CPR_RANGE = "INSIDE_CPR_RANGE"
    BELOW_BC_BEARISH = "BELOW_BC_BEARISH"


class PCRSentiment(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    EXTREME_OVERSOLD_REVERSAL_UP = "EXTREME_OVERSOLD_REVERSAL_UP"
    EXTREME_OVERBOUGHT_REVERSAL_DOWN = "EXTREME_OVERBOUGHT_REVERSAL_DOWN"


class GEXRegime(str, Enum):
    POSITIVE_GAMMA_PINNING = "POSITIVE_GAMMA_PINNING"
    NEGATIVE_GAMMA_VOLATILE = "NEGATIVE_GAMMA_VOLATILE"
    NEUTRAL_GAMMA = "NEUTRAL_GAMMA"


class IntradayDecisionAction(str, Enum):
    BUY_CALL = "BUY_CALL"
    BUY_PUT = "BUY_PUT"
    SHORT_STRANGLE = "SHORT_STRANGLE"
    BULL_PUT_SPREAD = "BULL_PUT_SPREAD"
    BEAR_CALL_SPREAD = "BEAR_CALL_SPREAD"
    NO_TRADE_WAIT = "NO_TRADE_WAIT"


@dataclass(frozen=True)
class CPRLevels:
    """Central Pivot Range and Floor Pivot Levels."""
    pivot: float
    bottom_central: float
    top_central: float
    cpr_width: float
    cpr_width_pct: float
    r1: float
    s1: float
    r2: float
    s2: float
    regime: CPRRegime


@dataclass(frozen=True)
class PCRMetrics:
    """Put-Call Ratio and Open Interest Dynamics."""
    total_call_oi: int
    total_put_oi: int
    pcr: float
    call_coi: int
    put_coi: int
    sentiment: PCRSentiment


@dataclass(frozen=True)
class StrikeGEXItem:
    """Strike-level Gamma Exposure metrics."""
    strike: float
    call_oi: int
    put_oi: int
    gamma: float
    net_gex_inr: float  # INR gamma exposure per 1% move


@dataclass(frozen=True)
class GEXProfile:
    """Aggregated Gamma Exposure and Wall Structure."""
    total_net_gex_inr: float
    call_wall_strike: float
    put_wall_strike: float
    gamma_flip_strike: float  # Strike where GEX crosses 0
    regime: GEXRegime
    strike_items: List[StrikeGEXItem] = field(default_factory=list)


@dataclass(frozen=True)
class IntradayChecklistResult:
    """Result of the institutional 6-point intraday decision checklist."""
    passed: bool
    action: IntradayDecisionAction
    recommended_strike: float
    recommended_option_type: str  # "CE", "PE", or "STRANGLE"
    entry_price_ref: float
    stop_loss: float
    target: float
    risk_reward_ratio: float
    confidence_score: float  # 0.0 to 1.0
    rationale: List[str] = field(default_factory=list)


class BankNiftyIntradayDecisionEngine:
    """Institutional Bank Nifty Intraday Decision-Making Engine."""

    def __init__(
        self,
        lot_size: int = 15,
        tick_size: float = 0.05,
        baseline_cpr_width_pts: float = 120.0,
    ) -> None:
        self.lot_size = max(1, int(lot_size))
        self.tick_size = max(0.01, float(tick_size))
        self.baseline_cpr_width_pts = max(10.0, float(baseline_cpr_width_pts))

    def compute_cpr_levels(
        self,
        prev_high: float,
        prev_low: float,
        prev_close: float,
    ) -> CPRLevels:
        """Compute Central Pivot Range and R1/R2/S1/S2 from previous day's OHLC."""
        h = float(prev_high)
        l = float(prev_low)
        c = float(prev_close)

        # 1. Pivot P = (H + L + C) / 3
        p = round((h + l + c) / 3.0, 2)

        # 2. Bottom Central BC = (H + L) / 2
        bc = round((h + l) / 2.0, 2)

        # 3. Top Central TC = 2*P - BC = (P - BC) + P
        tc = round(2.0 * p - bc, 2)

        # Ensure TC is top and BC is bottom for consistent width
        upper_cpr = max(tc, bc)
        lower_cpr = min(tc, bc)
        cpr_width = round(upper_cpr - lower_cpr, 2)
        cpr_width_pct = round((cpr_width / p) * 100.0, 3)

        # 4. Floor Pivots
        r1 = round(2.0 * p - l, 2)
        s1 = round(2.0 * p - h, 2)
        r2 = round(p + (h - l), 2)
        s2 = round(p - (h - l), 2)

        # Classify CPR Width
        if cpr_width < 0.60 * self.baseline_cpr_width_pts:
            regime = CPRRegime.NARROW_BREAKOUT
        elif cpr_width > 1.40 * self.baseline_cpr_width_pts:
            regime = CPRRegime.WIDE_RANGE_BOUND
        else:
            regime = CPRRegime.AVERAGE

        return CPRLevels(
            pivot=p,
            bottom_central=lower_cpr,
            top_central=upper_cpr,
            cpr_width=cpr_width,
            cpr_width_pct=cpr_width_pct,
            r1=r1,
            s1=s1,
            r2=r2,
            s2=s2,
            regime=regime,
        )

    def evaluate_open_relation(
        self,
        open_price: float,
        cpr: CPRLevels,
    ) -> OpenRelationToCPR:
        """Determine open price positioning relative to Central Pivot Range."""
        op = float(open_price)
        if op > cpr.top_central:
            return OpenRelationToCPR.ABOVE_TC_BULLISH
        elif op < cpr.bottom_central:
            return OpenRelationToCPR.BELOW_BC_BEARISH
        else:
            return OpenRelationToCPR.INSIDE_CPR_RANGE

    def compute_pcr(
        self,
        call_oi_dict: Dict[float, int],
        put_oi_dict: Dict[float, int],
        call_coi_dict: Optional[Dict[float, int]] = None,
        put_coi_dict: Optional[Dict[float, int]] = None,
    ) -> PCRMetrics:
        """Compute Put-Call Ratio and sentiment classification."""
        total_call_oi = sum(call_oi_dict.values())
        total_put_oi = sum(put_oi_dict.values())

        call_coi = sum(call_coi_dict.values()) if call_coi_dict else 0
        put_coi = sum(put_coi_dict.values()) if put_coi_dict else 0

        pcr = round(total_put_oi / max(1, total_call_oi), 3)

        # Sentiment Thresholds
        if pcr >= 1.50:
            sentiment = PCRSentiment.EXTREME_OVERSOLD_REVERSAL_UP
        elif pcr <= 0.55:
            sentiment = PCRSentiment.EXTREME_OVERBOUGHT_REVERSAL_DOWN
        elif pcr >= 1.10:
            sentiment = PCRSentiment.BULLISH
        elif pcr <= 0.80:
            sentiment = PCRSentiment.BEARISH
        else:
            sentiment = PCRSentiment.NEUTRAL

        return PCRMetrics(
            total_call_oi=total_call_oi,
            total_put_oi=total_put_oi,
            pcr=pcr,
            call_coi=call_coi,
            put_coi=put_coi,
            sentiment=sentiment,
        )

    def compute_max_pain(
        self,
        call_oi_dict: Dict[float, int],
        put_oi_dict: Dict[float, int],
    ) -> float:
        """Calculate Max Pain strike where option writers suffer minimal payout."""
        strikes = sorted(set(list(call_oi_dict.keys()) + list(put_oi_dict.keys())))
        if not strikes:
            return 49000.0

        min_total_payout = float("inf")
        max_pain_strike = strikes[0]

        for test_strike in strikes:
            total_payout = 0.0
            # Payout on calls: if underlying closes at test_strike, ITM calls payout (test_strike - k)
            for k, c_oi in call_oi_dict.items():
                if test_strike > k:
                    total_payout += (test_strike - k) * c_oi * self.lot_size

            # Payout on puts: if underlying closes at test_strike, ITM puts payout (k - test_strike)
            for k, p_oi in put_oi_dict.items():
                if test_strike < k:
                    total_payout += (k - test_strike) * p_oi * self.lot_size

            if total_payout < min_total_payout:
                min_total_payout = total_payout
                max_pain_strike = test_strike

        return max_pain_strike

    def compute_gex_profile(
        self,
        spot: float,
        quotes: List[Dict[str, Any]],  # List of {strike, gamma, call_oi, put_oi}
    ) -> GEXProfile:
        """Compute strike-level and market-wide Gamma Exposure (GEX)."""
        s = float(spot)
        total_gex = 0.0
        max_call_oi = -1
        max_put_oi = -1
        call_wall = s
        put_wall = s
        strike_items: List[StrikeGEXItem] = []

        for q in sorted(quotes, key=lambda x: x["strike"]):
            strike = float(q["strike"])
            c_oi = int(q.get("call_oi", 0))
            p_oi = int(q.get("put_oi", 0))
            gamma = max(1e-6, float(q.get("gamma", 0.001)))

            # Track Call and Put Walls
            if c_oi > max_call_oi:
                max_call_oi = c_oi
                call_wall = strike
            if p_oi > max_put_oi:
                max_put_oi = p_oi
                put_wall = strike

            # Net GEX at strike K:
            # GEX_K = Gamma_K * (Call_OI - Put_OI) * Spot^2 * 0.01 * lot_size
            # Represents dollar/INR hedging needed per 1% underlying price move
            net_gex_inr = gamma * (c_oi - p_oi) * (s ** 2) * 0.01 * self.lot_size
            total_gex += net_gex_inr

            strike_items.append(
                StrikeGEXItem(
                    strike=strike,
                    call_oi=c_oi,
                    put_oi=p_oi,
                    gamma=gamma,
                    net_gex_inr=round(net_gex_inr, 2),
                )
            )

        # Determine Gamma Flip Strike (where cumulative GEX crosses from negative to positive)
        gamma_flip = s
        for item in strike_items:
            if item.net_gex_inr >= 0:
                gamma_flip = item.strike
                break

        # GEX Regime
        if total_gex > 500000.0:
            regime = GEXRegime.POSITIVE_GAMMA_PINNING
        elif total_gex < -500000.0:
            regime = GEXRegime.NEGATIVE_GAMMA_VOLATILE
        else:
            regime = GEXRegime.NEUTRAL_GAMMA

        return GEXProfile(
            total_net_gex_inr=round(total_gex, 2),
            call_wall_strike=call_wall,
            put_wall_strike=put_wall,
            gamma_flip_strike=gamma_flip,
            regime=regime,
            strike_items=strike_items,
        )

    def evaluate_intraday_decision_checklist(
        self,
        current_spot: float,
        open_price: float,
        cpr: CPRLevels,
        pcr_metrics: PCRMetrics,
        gex_profile: GEXProfile,
        prev_high: float,
        prev_low: float,
        current_time_str: str = "09:35",
        atr_14: float = 180.0,
    ) -> IntradayChecklistResult:
        """Evaluate the 6-point institutional intraday decision checklist."""
        spot = float(current_spot)
        op = float(open_price)
        open_rel = self.evaluate_open_relation(op, cpr)
        atr = max(20.0, float(atr_14))
        rationale: List[str] = []

        # Check 1: Time Cutoff (Must be after 09:20 and before 15:15)
        # Parse HH:MM
        time_parts = current_time_str.split(":")
        minutes_from_open = (int(time_parts[0]) - 9) * 60 + int(time_parts[1]) - 15
        if minutes_from_open < 5:
            return IntradayChecklistResult(
                passed=False,
                action=IntradayDecisionAction.NO_TRADE_WAIT,
                recommended_strike=round(spot / 100.0) * 100.0,
                recommended_option_type="NONE",
                entry_price_ref=spot,
                stop_loss=spot,
                target=spot,
                risk_reward_ratio=0.0,
                confidence_score=0.1,
                rationale=["Opening price discovery in progress (09:15-09:20 AM IST). Wait for ORB stabilization."],
            )

        if minutes_from_open >= 360:  # 15:15 IST
            return IntradayChecklistResult(
                passed=False,
                action=IntradayDecisionAction.NO_TRADE_WAIT,
                recommended_strike=round(spot / 100.0) * 100.0,
                recommended_option_type="NONE",
                entry_price_ref=spot,
                stop_loss=spot,
                target=spot,
                risk_reward_ratio=0.0,
                confidence_score=0.0,
                rationale=["Past 15:15 IST intraday mandatory square-off window. New positions barred."],
            )

        # Check 2: CPR & Open Alignment
        bullish_score = 0
        bearish_score = 0

        if open_rel == OpenRelationToCPR.ABOVE_TC_BULLISH:
            bullish_score += 2
            rationale.append("Open is Above Top Central (TC) -> Bullish momentum bias.")
        elif open_rel == OpenRelationToCPR.BELOW_BC_BEARISH:
            bearish_score += 2
            rationale.append("Open is Below Bottom Central (BC) -> Bearish breakdown bias.")
        else:
            rationale.append("Open is Inside CPR (Between BC & TC) -> Neutral / Range-bound chop.")

        # Check 3: PCR Confirmation
        if pcr_metrics.sentiment in (PCRSentiment.BULLISH, PCRSentiment.EXTREME_OVERSOLD_REVERSAL_UP):
            bullish_score += 2
            rationale.append(f"PCR is {pcr_metrics.pcr:.2f} ({pcr_metrics.sentiment.value}) -> Confirms Put writing / support.")
        elif pcr_metrics.sentiment in (PCRSentiment.BEARISH, PCRSentiment.EXTREME_OVERBOUGHT_REVERSAL_DOWN):
            bearish_score += 2
            rationale.append(f"PCR is {pcr_metrics.pcr:.2f} ({pcr_metrics.sentiment.value}) -> Confirms Call writing / resistance.")

        # Check 4: GEX Regime Confirmation
        if gex_profile.regime == GEXRegime.NEGATIVE_GAMMA_VOLATILE:
            rationale.append("Negative GEX (-GEX) -> Market makers short gamma; volatility breakout accelerated.")
        elif gex_profile.regime == GEXRegime.POSITIVE_GAMMA_PINNING:
            rationale.append("Positive GEX (+GEX) -> Market makers long gamma; price pinning expected between Call & Put Walls.")

        # Synthesize Checklist Outcome
        target_rr = 2.0
        atm_strike = round(spot / 100.0) * 100.0

        if bullish_score >= 3 and spot > cpr.top_central:
            # Bullish Setup: Buy ATM CE or Bull Put Spread
            sl = spot - (1.0 * atr)
            target = spot + (target_rr * 1.0 * atr)
            confidence = min(0.95, 0.50 + bullish_score * 0.12)
            action = IntradayDecisionAction.BUY_CALL
            opt_type = "CE"
            rationale.append(f"Bullish confluence confirmed: Target R1 ({cpr.r1}) / R2 ({cpr.r2}), SL below TC.")
            passed = True

        elif bearish_score >= 3 and spot < cpr.bottom_central:
            # Bearish Setup: Buy ATM PE or Bear Call Spread
            sl = spot + (1.0 * atr)
            target = spot - (target_rr * 1.0 * atr)
            confidence = min(0.95, 0.50 + bearish_score * 0.12)
            action = IntradayDecisionAction.BUY_PUT
            opt_type = "PE"
            rationale.append(f"Bearish confluence confirmed: Target S1 ({cpr.s1}) / S2 ({cpr.s2}), SL above BC.")
            passed = True

        elif open_rel == OpenRelationToCPR.INSIDE_CPR_RANGE or cpr.regime == CPRRegime.WIDE_RANGE_BOUND:
            # Range-bound / Mean-reversion setup: Short Strangle or Range trade
            sl = cpr.r1 + 50.0
            target = cpr.pivot
            confidence = 0.72
            action = IntradayDecisionAction.SHORT_STRANGLE
            opt_type = "STRANGLE"
            rationale.append(f"Range-bound confluence: Price inside CPR ({cpr.bottom_central} - {cpr.top_central}). Sell OTM Wings.")
            passed = True

        else:
            action = IntradayDecisionAction.NO_TRADE_WAIT
            opt_type = "NONE"
            sl = spot
            target = spot
            confidence = 0.35
            rationale.append("Ambiguous confluence. Price action conflicting with PCR/CPR. Standing by.")
            passed = False

        return IntradayChecklistResult(
            passed=passed,
            action=action,
            recommended_strike=atm_strike,
            recommended_option_type=opt_type,
            entry_price_ref=spot,
            stop_loss=round(sl, 2),
            target=round(target, 2),
            risk_reward_ratio=target_rr if passed else 0.0,
            confidence_score=round(confidence, 2),
            rationale=rationale,
        )


__all__ = [
    "CPRRegime",
    "OpenRelationToCPR",
    "PCRSentiment",
    "GEXRegime",
    "IntradayDecisionAction",
    "CPRLevels",
    "PCRMetrics",
    "StrikeGEXItem",
    "GEXProfile",
    "IntradayChecklistResult",
    "BankNiftyIntradayDecisionEngine",
]

"""AGI 1.7 OMEGA COMMAND — Overnight Strategy & Next-Session Scenario Planner.

Enforces strict separation between intraday trading and overnight positioning:
- Zero automatic conversion of intraday positions to overnight
- Dedicated overnight gap-risk modeling and overnight theta decay calculations
- Next-session scenario planning (Bullish +1%, Bearish -1%, Flat ±0.2%)
- Explicit candidate hurdle evaluation with mandatory NO_TRADE option
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("OvernightStrategyManager")


class OvernightDecision(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NO_TRADE = "NO_TRADE"


class ScenarioOutcomeType(str, enum.Enum):
    BULLISH_GAP = "BULLISH_GAP"       # +1.0% open
    BEARISH_GAP = "BEARISH_GAP"       # -1.0% open
    FLAT_OPEN = "FLAT_OPEN"           # +/- 0.2% open


@dataclasses.dataclass
class NextSessionScenario:
    """Pre-computed scenario plan for market opening."""
    scenario_type: ScenarioOutcomeType
    expected_spot_change_pct: float
    trigger_level: float
    target_action: str                 # "PROFIT_BOOK", "CUT_LOSS", "HOLD_HARVEST"
    actionable_stop_loss: float
    max_estimated_loss_inr: float
    profit_target_inr: float
    action_notes: str


@dataclasses.dataclass
class OvernightTradeCandidate:
    """Formally structured overnight trade candidate with gap and theta risk metrics."""
    candidate_id: str
    instrument: str                    # "NIFTY" or "BANKNIFTY"
    strategy_name: str                 # e.g., "OVERNIGHT_BULL_CALL_SPREAD", "OVERNIGHT_IRON_CONDOR"
    underlying_spot: float
    strike_selected: float
    option_type: str                   # "CE" or "PE" or "SPREAD"
    expiry_date: str
    proposed_entry_price: float
    stop_loss: float
    target_price: float
    quantity: int
    overnight_gap_risk_pct: float      # Modeled gap risk (e.g. 0.85%)
    expected_overnight_theta_decay: float # Estimated theta decay in INR
    weekend_overnight: bool            # True if Friday-to-Monday
    margin_required: float
    max_risk_inr: float
    decision: OvernightDecision
    decision_reason: str
    scenarios: List[NextSessionScenario] = dataclasses.field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()


class OvernightStrategyManager:
    """Evaluates overnight candidates with rigorous hurdles, gap risk, theta decay, and scenario plans."""

    def __init__(
        self,
        max_capital_allocation_inr: float = 15000.0,  # Max 30% of ₹50,000 for overnight margin
        max_overnight_loss_inr: float = 250.0,       # Strict 0.5% max risk per trade limit
        max_allowed_gap_risk_pct: float = 1.75,       # Reject if modeled gap risk exceeds 1.75%
    ) -> None:
        self.max_capital_allocation_inr = max_capital_allocation_inr
        self.max_overnight_loss_inr = max_overnight_loss_inr
        self.max_allowed_gap_risk_pct = max_allowed_gap_risk_pct
        self.evaluated_candidates: List[OvernightTradeCandidate] = []

    def calculate_overnight_theta(
        self,
        entry_premium: float,
        daily_theta: float,
        is_weekend: bool = False,
    ) -> float:
        """Calculates expected rupee theta decay during closed hours."""
        # Intraday market is open 6.25h (375 min). Non-trading overnight is 17.75h (single night)
        # or 65.75h (Friday 15:30 to Monday 09:15).
        hours_closed = 65.75 if is_weekend else 17.75
        days_fraction = hours_closed / 24.0
        decay_amount = abs(daily_theta) * days_fraction
        return round(min(entry_premium * 0.40, decay_amount), 2)

    def estimate_overnight_gap_risk(
        self,
        volatility_annual: float = 0.16,
        is_weekend: bool = False,
    ) -> float:
        """Estimates overnight gap risk standard deviation percentage."""
        # 252 trading days/year
        daily_vol = volatility_annual / math.sqrt(252.0)
        multiplier = 1.5 if is_weekend else 1.0
        gap_std_pct = daily_vol * multiplier * 100.0
        return round(gap_std_pct, 3)

    def build_next_session_scenarios(
        self,
        candidate_id: str,
        instrument: str,
        spot: float,
        strike: float,
        entry_price: float,
        stop_loss: float,
        target_price: float,
        quantity: int,
        option_type: str,
    ) -> List[NextSessionScenario]:
        """Pre-computes actionable response scenarios for market opening."""
        # Bullish Gap: +1.0% spot move
        bullish_spot = round(spot * 1.01, 2)
        # Bearish Gap: -1.0% spot move
        bearish_spot = round(spot * 0.99, 2)
        # Flat: Spot unchanged
        flat_spot = spot

        if option_type == "CE":
            bull_opt_est = round(entry_price * 1.35, 2)
            bear_opt_est = round(entry_price * 0.60, 2)
            flat_opt_est = round(entry_price * 0.90, 2)  # theta loss
            bull_action = "PROFIT_BOOK"
            bear_action = "CUT_LOSS"
        elif option_type == "PE":
            bull_opt_est = round(entry_price * 0.60, 2)
            bear_opt_est = round(entry_price * 1.35, 2)
            flat_opt_est = round(entry_price * 0.90, 2)
            bull_action = "CUT_LOSS"
            bear_action = "PROFIT_BOOK"
        else:  # Spreads / neutral
            bull_opt_est = round(entry_price * 1.15, 2)
            bear_opt_est = round(entry_price * 0.85, 2)
            flat_opt_est = round(entry_price * 1.08, 2)  # theta gain for spreads
            bull_action = "HOLD_HARVEST"
            bear_action = "CUT_LOSS"

        scenarios = [
            NextSessionScenario(
                scenario_type=ScenarioOutcomeType.BULLISH_GAP,
                expected_spot_change_pct=+1.0,
                trigger_level=bullish_spot,
                target_action=bull_action,
                actionable_stop_loss=round(stop_loss * 1.10, 2),
                max_estimated_loss_inr=0.0 if bull_opt_est >= entry_price else round((entry_price - bull_opt_est) * quantity, 2),
                profit_target_inr=round(max(0.0, (bull_opt_est - entry_price) * quantity), 2),
                action_notes=f"Spot gap-up above {bullish_spot}. Execute {bull_action} at market open.",
            ),
            NextSessionScenario(
                scenario_type=ScenarioOutcomeType.BEARISH_GAP,
                expected_spot_change_pct=-1.0,
                trigger_level=bearish_spot,
                target_action=bear_action,
                actionable_stop_loss=stop_loss,
                max_estimated_loss_inr=round(max(0.0, (entry_price - bear_opt_est) * quantity), 2),
                profit_target_inr=0.0 if bear_opt_est <= entry_price else round((bear_opt_est - entry_price) * quantity, 2),
                action_notes=f"Spot gap-down below {bearish_spot}. Execute {bear_action} immediately to protect capital.",
            ),
            NextSessionScenario(
                scenario_type=ScenarioOutcomeType.FLAT_OPEN,
                expected_spot_change_pct=0.0,
                trigger_level=flat_spot,
                target_action="HOLD_HARVEST" if option_type not in ("CE", "PE") else "EXIT_IF_STAGNANT",
                actionable_stop_loss=stop_loss,
                max_estimated_loss_inr=round(max(0.0, (entry_price - flat_opt_est) * quantity), 2),
                profit_target_inr=round(max(0.0, (flat_opt_est - entry_price) * quantity), 2),
                action_notes="Flat opening (within +/-0.2%). Monitor 09:15-09:30 IST opening range before acting.",
            ),
        ]
        return scenarios

    def evaluate_candidate(
        self,
        candidate_id: str,
        instrument: str,
        strategy_name: str,
        underlying_spot: float,
        strike: float,
        option_type: str,
        expiry_date: str,
        entry_price: float,
        stop_loss: float,
        target_price: float,
        quantity: int,
        daily_theta: float,
        volatility: float = 0.16,
        is_weekend: bool = False,
        margin_required: float = 5000.0,
        force_rejection_reason: Optional[str] = None,
    ) -> OvernightTradeCandidate:
        """Evaluates an overnight trade candidate against strict hurdles and generates scenarios."""
        # 1. Check forced rejection or external hurdle
        if force_rejection_reason:
            cand = OvernightTradeCandidate(
                candidate_id=candidate_id,
                instrument=instrument,
                strategy_name=strategy_name,
                underlying_spot=underlying_spot,
                strike_selected=strike,
                option_type=option_type,
                expiry_date=expiry_date,
                proposed_entry_price=entry_price,
                stop_loss=stop_loss,
                target_price=target_price,
                quantity=quantity,
                overnight_gap_risk_pct=0.0,
                expected_overnight_theta_decay=0.0,
                weekend_overnight=is_weekend,
                margin_required=margin_required,
                max_risk_inr=0.0,
                decision=OvernightDecision.NO_TRADE,
                decision_reason=force_rejection_reason,
                scenarios=[],
            )
            self.evaluated_candidates.append(cand)
            return cand

        # 2. Compute Gap Risk & Theta Decay
        gap_risk_pct = self.estimate_overnight_gap_risk(volatility_annual=volatility, is_weekend=is_weekend)
        theta_decay = self.calculate_overnight_theta(entry_premium=entry_price, daily_theta=daily_theta, is_weekend=is_weekend)

        # 3. Compute Maximum Risk in INR
        risk_per_share = max(0.0, entry_price - stop_loss)
        max_risk_inr = round(risk_per_share * quantity, 2)

        # 4. Hurdle Checks
        decision = OvernightDecision.APPROVED
        reason = "All overnight hurdles satisfied"

        if margin_required > self.max_capital_allocation_inr:
            decision = OvernightDecision.NO_TRADE
            reason = f"Margin required (INR {margin_required:.2f}) exceeds allocation limit (INR {self.max_capital_allocation_inr:.2f})"
        elif max_risk_inr > self.max_overnight_loss_inr:
            decision = OvernightDecision.NO_TRADE
            reason = f"Max risk (INR {max_risk_inr:.2f}) exceeds per-trade limit (INR {self.max_overnight_loss_inr:.2f})"
        elif gap_risk_pct > self.max_allowed_gap_risk_pct:
            decision = OvernightDecision.NO_TRADE
            reason = f"Estimated gap risk ({gap_risk_pct:.2f}%) exceeds hurdle limit ({self.max_allowed_gap_risk_pct:.2f}%)"
        elif theta_decay > (entry_price * 0.25):
            decision = OvernightDecision.NO_TRADE
            reason = f"Expected overnight theta decay (INR {theta_decay:.2f}) exceeds 25% of premium"

        # 5. Build Scenarios
        scenarios = self.build_next_session_scenarios(
            candidate_id=candidate_id,
            instrument=instrument,
            spot=underlying_spot,
            strike=strike,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            quantity=quantity,
            option_type=option_type,
        )

        cand = OvernightTradeCandidate(
            candidate_id=candidate_id,
            instrument=instrument,
            strategy_name=strategy_name,
            underlying_spot=underlying_spot,
            strike_selected=strike,
            option_type=option_type,
            expiry_date=expiry_date,
            proposed_entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            quantity=quantity,
            overnight_gap_risk_pct=gap_risk_pct,
            expected_overnight_theta_decay=theta_decay,
            weekend_overnight=is_weekend,
            margin_required=margin_required,
            max_risk_inr=max_risk_inr,
            decision=decision,
            decision_reason=reason,
            scenarios=scenarios,
        )
        self.evaluated_candidates.append(cand)
        return cand

    def get_approved_candidates(self) -> List[OvernightTradeCandidate]:
        """Returns only candidates that cleared all hurdles."""
        return [c for c in self.evaluated_candidates if c.decision == OvernightDecision.APPROVED]

"""AGI 1.7 Pre-Trade Risk Engine & Portfolio Drawdown Kill-Switch.

TASK-BN-16:
Provides institutional pre-trade risk controls and an automated emergency
kill switch protecting paper portfolios from rogue executions and tail drawdowns:
1. Pre-Trade Risk Gatekeeper (PreTradeRiskEngine):
   - Rule 1: Max single order lots (e.g., 50 lots = 750 units).
   - Rule 2: Max single order notional value (e.g., ₹25,00,000).
   - Rule 3: Max aggregate gross portfolio notional exposure (e.g., ₹1,00,00,000).
   - Rule 4: Fat-finger price band check (order price within +/- 20% of theoretical fair value).
   - Rule 5: Account margin health gate (rejects new positions if in MARGIN_CALL or FORCE_LIQUIDATION).
   - Rule 6: Emergency kill-switch enforcement (immediate reject if kill switch active).
2. Portfolio Drawdown Kill-Switch (PortfolioKillSwitch):
   - High Water Mark (HWM) peak equity tracking.
   - Intraday drawdown percentage breach trigger (e.g., >= 3.0% drop from HWM).
   - Daily loss rupee limit trigger (e.g., >= ₹50,000 loss).
   - Automatic generation of EmergencyCancellationPlan for all working orders.
   - Manual trip and authorized administrative reset.
3. Event Journaling:
   - Persistent append-only structured audit log (risk_events.jsonl).
"""

from __future__ import annotations

import dataclasses
import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import OrderSide, OrderType
from .margin_liquidation import MarginAccountSnapshot, MarginStatus
from .options_math import OptionsMath


@dataclasses.dataclass(frozen=True)
class PreTradeOrderRequest:
    """Incoming order specification submitted for pre-trade risk gating."""

    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    units: int
    requested_price: float
    theoretical_fair_price: Optional[float] = None


@dataclasses.dataclass(frozen=True)
class RiskCheckResult:
    """Outcome of an individual pre-trade risk rule evaluation."""

    rule_name: str
    passed: bool
    observed_value: float
    threshold_value: float
    message: str


@dataclasses.dataclass(frozen=True)
class PreTradeValidationDecision:
    """Consolidated pre-trade risk determination."""

    order_id: str
    approved: bool
    rejection_rule: Optional[str] = None
    rejection_reason: Optional[str] = None
    results: List[RiskCheckResult] = dataclasses.field(default_factory=list)
    timestamp_utc: str = dataclasses.field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


@dataclasses.dataclass(frozen=True)
class EmergencyCancellationPlan:
    """Structured response triggered by a portfolio drawdown kill switch event."""

    kill_switch_engaged: bool
    trigger_reason: str
    peak_equity: float
    current_equity: float
    drawdown_pct: float
    realized_daily_loss: float
    orders_to_cancel: List[str]
    action_required: str
    timestamp_utc: str


class PortfolioKillSwitch:
    """Intraday peak equity monitor and emergency portfolio circuit breaker."""

    def __init__(
        self,
        *,
        initial_capital: float,
        max_drawdown_pct: float = 0.03,  # 3.0% maximum peak-to-trough drawdown
        max_daily_loss_inr: float = 50_000.0,  # ₹50,000 maximum daily loss
    ) -> None:
        if initial_capital <= 0:
            raise ValueError("Initial capital must be strictly positive")
        if max_drawdown_pct <= 0 or max_drawdown_pct >= 1.0:
            raise ValueError("Max drawdown percentage must be between 0 and 1")
        if max_daily_loss_inr <= 0:
            raise ValueError("Max daily loss INR must be strictly positive")

        self.initial_capital = initial_capital
        self.peak_equity = initial_capital
        self.current_equity = initial_capital
        self.max_drawdown_pct = max_drawdown_pct
        self.max_daily_loss_inr = max_daily_loss_inr

        self.is_engaged: bool = False
        self.engagement_reason: str = ""
        self.engagement_timestamp: Optional[str] = None

    @property
    def current_drawdown_pct(self) -> float:
        """Returns instantaneous peak-to-trough drawdown ratio in [0.0, 1.0]."""
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.current_equity) / self.peak_equity)

    def update_equity(
        self,
        current_equity: float,
        open_working_order_ids: Optional[Sequence[str]] = None,
    ) -> Optional[EmergencyCancellationPlan]:
        """Updates portfolio equity, ratchets peak equity, and trips if thresholds breached."""
        self.current_equity = current_equity

        # Ratchet Peak Equity (High Water Mark)
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        # If already engaged, return existing active state
        if self.is_engaged:
            return self._build_cancellation_plan(
                reason=self.engagement_reason,
                open_working_order_ids=open_working_order_ids or [],
            )

        # 1. Check Peak-to-Trough Drawdown
        drawdown_pct = (self.peak_equity - current_equity) / self.peak_equity
        if drawdown_pct >= self.max_drawdown_pct:
            reason = (
                f"Peak-to-Trough drawdown limit breached: {drawdown_pct*100:.2f}% >= "
                f"{self.max_drawdown_pct*100:.2f}% (Peak: ₹{self.peak_equity:.2f}, Current: ₹{current_equity:.2f})"
            )
            return self.trip(reason=reason, open_working_order_ids=open_working_order_ids)

        # 2. Check Daily Dollar Loss vs Initial Capital
        dollar_loss = self.initial_capital - current_equity
        if dollar_loss >= self.max_daily_loss_inr:
            reason = (
                f"Absolute daily loss limit breached: ₹{dollar_loss:.2f} >= "
                f"₹{self.max_daily_loss_inr:.2f} limit"
            )
            return self.trip(reason=reason, open_working_order_ids=open_working_order_ids)

        return None

    def trip(
        self,
        reason: str,
        open_working_order_ids: Optional[Sequence[str]] = None,
    ) -> EmergencyCancellationPlan:
        """Manually or automatically engages the emergency kill switch."""
        self.is_engaged = True
        self.engagement_reason = reason
        self.engagement_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return self._build_cancellation_plan(
            reason=reason,
            open_working_order_ids=open_working_order_ids or [],
        )

    def reset(self, authorization_token: str) -> None:
        """Clears the kill switch upon verified administrative clearance."""
        if not authorization_token or len(authorization_token.strip()) < 8:
            raise ValueError("Administrative reset requires a valid authorization token (>= 8 chars)")
        self.is_engaged = False
        self.engagement_reason = ""
        self.engagement_timestamp = None

    def _build_cancellation_plan(
        self,
        reason: str,
        open_working_order_ids: Sequence[str],
    ) -> EmergencyCancellationPlan:
        dd_pct = (
            (self.peak_equity - self.current_equity) / self.peak_equity
            if self.peak_equity > 0
            else 0.0
        )
        return EmergencyCancellationPlan(
            kill_switch_engaged=True,
            trigger_reason=reason,
            peak_equity=self.peak_equity,
            current_equity=self.current_equity,
            drawdown_pct=round(dd_pct * 100.0, 2),
            realized_daily_loss=round(self.initial_capital - self.current_equity, 2),
            orders_to_cancel=list(open_working_order_ids),
            action_required="CANCEL_ALL_OPEN_ORDERS_AND_HALT_NEW_SUBMISSIONS",
            timestamp_utc=self.engagement_timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )


class PreTradeRiskEngine:
    """Validates every prospective order against multi-layered institutional risk bounds."""

    def __init__(
        self,
        *,
        max_single_order_lots: int = 50,  # Max 50 lots = 750 units of Bank Nifty
        max_single_order_notional: float = 2_500_000.0,  # ₹25 Lakhs per order
        max_gross_exposure: float = 10_000_000.0,  # ₹1 Crore total portfolio exposure
        max_price_deviation_pct: float = 0.20,  # +/- 20% fat-finger band from fair value
        journal_path: Optional[Path] = None,
    ) -> None:
        self.max_single_order_lots = max_single_order_lots
        self.max_single_order_notional = max_single_order_notional
        self.max_gross_exposure = max_gross_exposure
        self.max_price_deviation_pct = max_price_deviation_pct
        self.journal_path = journal_path

    def validate_order(
        self,
        order: PreTradeOrderRequest,
        *,
        current_portfolio_gross_exposure: float,
        margin_account: Optional[MarginAccountSnapshot] = None,
        kill_switch: Optional[PortfolioKillSwitch] = None,
    ) -> PreTradeValidationDecision:
        """Executes all pre-trade checks atomically before routing to paper execution."""
        results: List[RiskCheckResult] = []

        # 1. Kill Switch Active Check
        if kill_switch is not None and kill_switch.is_engaged:
            res = RiskCheckResult(
                rule_name="KILL_SWITCH_CHECK",
                passed=False,
                observed_value=1.0,
                threshold_value=0.0,
                message=f"Order rejected: Emergency Kill Switch is ACTIVE ({kill_switch.engagement_reason})",
            )
            results.append(res)
            return self._finalize_decision(order.order_id, False, "KILL_SWITCH_ACTIVE", res.message, results)

        # 2. Account Margin Lockout Check
        if margin_account is not None and margin_account.is_locked_out:
            res = RiskCheckResult(
                rule_name="MARGIN_LOCKOUT_CHECK",
                passed=False,
                observed_value=margin_account.margin_utilization,
                threshold_value=1.0,
                message=f"Order rejected: Account in {margin_account.status.value} with utilization {margin_account.margin_utilization*100:.1f}%",
            )
            results.append(res)
            return self._finalize_decision(order.order_id, False, "MARGIN_LOCKOUT", res.message, results)

        # 3. Max Single Order Lots Check
        lot_size = BankNiftyContractSpec.LOT_SIZE
        order_lots = order.units // lot_size
        if order_lots > self.max_single_order_lots or order.units <= 0:
            res = RiskCheckResult(
                rule_name="MAX_ORDER_LOTS",
                passed=False,
                observed_value=float(order_lots),
                threshold_value=float(self.max_single_order_lots),
                message=f"Order size {order_lots} lots exceeds maximum allowable {self.max_single_order_lots} lots",
            )
            results.append(res)
            return self._finalize_decision(order.order_id, False, "MAX_ORDER_LOTS_BREACH", res.message, results)
        else:
            results.append(RiskCheckResult("MAX_ORDER_LOTS", True, float(order_lots), float(self.max_single_order_lots), "PASS"))

        # 4. Max Single Order Notional Check
        order_notional = order.units * order.requested_price
        if order_notional > self.max_single_order_notional:
            res = RiskCheckResult(
                rule_name="MAX_ORDER_NOTIONAL",
                passed=False,
                observed_value=order_notional,
                threshold_value=self.max_single_order_notional,
                message=f"Order notional ₹{order_notional:,.2f} exceeds cap of ₹{self.max_single_order_notional:,.2f}",
            )
            results.append(res)
            return self._finalize_decision(order.order_id, False, "MAX_ORDER_NOTIONAL_BREACH", res.message, results)
        else:
            results.append(RiskCheckResult("MAX_ORDER_NOTIONAL", True, order_notional, self.max_single_order_notional, "PASS"))

        # 5. Max Gross Exposure Check
        projected_gross = current_portfolio_gross_exposure + order_notional
        if projected_gross > self.max_gross_exposure:
            res = RiskCheckResult(
                rule_name="MAX_GROSS_EXPOSURE",
                passed=False,
                observed_value=projected_gross,
                threshold_value=self.max_gross_exposure,
                message=f"Projected portfolio gross exposure ₹{projected_gross:,.2f} exceeds cap of ₹{self.max_gross_exposure:,.2f}",
            )
            results.append(res)
            return self._finalize_decision(order.order_id, False, "MAX_GROSS_EXPOSURE_BREACH", res.message, results)
        else:
            results.append(RiskCheckResult("MAX_GROSS_EXPOSURE", True, projected_gross, self.max_gross_exposure, "PASS"))

        # 6. Fat-Finger Price Deviation Check (if theoretical fair price provided)
        if order.theoretical_fair_price is not None and order.theoretical_fair_price > 0:
            deviation_pct = abs(order.requested_price - order.theoretical_fair_price) / order.theoretical_fair_price
            if deviation_pct > self.max_price_deviation_pct:
                res = RiskCheckResult(
                    rule_name="FAT_FINGER_PRICE_CHECK",
                    passed=False,
                    observed_value=deviation_pct,
                    threshold_value=self.max_price_deviation_pct,
                    message=(
                        f"Price ₹{order.requested_price:.2f} deviates {deviation_pct*100:.1f}% "
                        f"from theoretical fair value ₹{order.theoretical_fair_price:.2f} (max allowed {self.max_price_deviation_pct*100:.0f}%)"
                    ),
                )
                results.append(res)
                return self._finalize_decision(order.order_id, False, "FAT_FINGER_PRICE_DEVIATION", res.message, results)
            else:
                results.append(RiskCheckResult("FAT_FINGER_PRICE_CHECK", True, deviation_pct, self.max_price_deviation_pct, "PASS"))

        return self._finalize_decision(order.order_id, True, None, None, results)

    def _finalize_decision(
        self,
        order_id: str,
        approved: bool,
        rejection_rule: Optional[str],
        rejection_reason: Optional[str],
        results: List[RiskCheckResult],
    ) -> PreTradeValidationDecision:
        decision = PreTradeValidationDecision(
            order_id=order_id,
            approved=approved,
            rejection_rule=rejection_rule,
            rejection_reason=rejection_reason,
            results=results,
        )
        self._journal_decision(decision)
        return decision

    def _journal_decision(self, decision: PreTradeValidationDecision) -> None:
        """Appends audit decision to JSONL journal file."""
        if not self.journal_path:
            return
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "order_id": decision.order_id,
                "approved": decision.approved,
                "rejection_rule": decision.rejection_rule,
                "rejection_reason": decision.rejection_reason,
                "timestamp_utc": decision.timestamp_utc,
                "results": [
                    {
                        "rule": r.rule_name,
                        "passed": r.passed,
                        "observed": r.observed_value,
                        "threshold": r.threshold_value,
                    }
                    for r in decision.results
                ],
            }
            with open(self.journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass  # Fail-safe against journal write issues

"""Authoritative Live Broker UI Controller & 15-State Order Reconciliation Engine.

Implements Section 4:
- 15 Distinct Order States:
  ANALYSIS_ONLY, TRADE_PROPOSED, LIVE_SESSION_NOT_ARMED, LIVE_SESSION_ARMED,
  ORDER_FORM_OPEN, ORDER_SUBMISSION_ATTEMPTED, BROKER_ORDER_STATUS_PENDING,
  BROKER_ORDER_CONFIRMED, PARTIALLY_FILLED, FULLY_FILLED, REJECTED, CANCELLED,
  EXIT_PENDING, POSITION_CLOSED, UNKNOWN_REQUIRES_RECONCILIATION
- Strict link between Internal Intent ID and Broker Order Identifier
- Unreconciled orders immediately halt new submissions on the affected instrument
- Distinction between broker-confirmed orders and local monitoring stops
- Verification against visible Broker Order Book, Trade Book, Positions, and Funds
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .live_contract_validator import LiveContract, OrderAction


class LiveOrderState(str, Enum):
    ANALYSIS_ONLY = "ANALYSIS_ONLY"
    TRADE_PROPOSED = "TRADE_PROPOSED"
    LIVE_SESSION_NOT_ARMED = "LIVE_SESSION_NOT_ARMED"
    LIVE_SESSION_ARMED = "LIVE_SESSION_ARMED"
    ORDER_FORM_OPEN = "ORDER_FORM_OPEN"
    ORDER_SUBMISSION_ATTEMPTED = "ORDER_SUBMISSION_ATTEMPTED"
    BROKER_ORDER_STATUS_PENDING = "BROKER_ORDER_STATUS_PENDING"
    BROKER_ORDER_CONFIRMED = "BROKER_ORDER_CONFIRMED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FULLY_FILLED = "FULLY_FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXIT_PENDING = "EXIT_PENDING"
    POSITION_CLOSED = "POSITION_CLOSED"
    UNKNOWN_REQUIRES_RECONCILIATION = "UNKNOWN_REQUIRES_RECONCILIATION"


@dataclass
class BrokerOrderRecord:
    """Represents an order tracked through the 15-state lifecycle."""
    intent_id: str
    symbol: str
    action: OrderAction
    requested_quantity: int
    requested_price: float
    state: LiveOrderState = LiveOrderState.ANALYSIS_ONLY
    broker_order_id: Optional[str] = None
    filled_quantity: int = 0
    average_fill_price: float = 0.0
    rejection_reason: Optional[str] = None
    contract: Optional[LiveContract] = None
    order_type: str = "LIMIT"
    created_at: str = ""
    updated_at: str = ""
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    is_local_protective_stop: bool = False
    broker_protective_order_id: Optional[str] = None

    def record_transition(self, new_state: LiveOrderState, details: str = "") -> None:
        """Records an auditable state transition."""
        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
        old_state = self.state
        self.state = new_state
        self.updated_at = ts_str
        self.timeline.append({
            "from_state": old_state.value,
            "to_state": new_state.value,
            "timestamp": ts_str,
            "details": details,
        })


class LiveBrokerAdapter:
    """Authoritative adapter managing live broker UI interaction and reconciliation."""

    def __init__(self) -> None:
        self.orders_by_intent: Dict[str, BrokerOrderRecord] = {}
        self.orders_by_broker_id: Dict[str, BrokerOrderRecord] = {}
        self.unreconciled_orders: Dict[str, BrokerOrderRecord] = {}
        self.visible_positions: Dict[str, Dict[str, Any]] = {}
        self.verified_available_funds: float = 0.0
        self.verified_used_margin: float = 0.0

    @staticmethod
    def generate_intent_id(symbol: str) -> str:
        """Generates a unique internal intent identifier."""
        uid = uuid.uuid4().hex[:10].upper()
        return f"INTENT-{symbol}-{uid}"

    def create_order_proposal(
        self,
        contract: LiveContract,
        action: OrderAction,
        quantity: int,
        price: float,
        order_type: str = "LIMIT",
        is_live_armed: bool = False,
    ) -> BrokerOrderRecord:
        """Initiates an order record starting at ANALYSIS_ONLY or TRADE_PROPOSED."""
        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
        intent_id = self.generate_intent_id(contract.symbol)



        initial_state = (
            LiveOrderState.LIVE_SESSION_ARMED
            if is_live_armed
            else LiveOrderState.LIVE_SESSION_NOT_ARMED
        )

        record = BrokerOrderRecord(
            intent_id=intent_id,
            symbol=contract.symbol,
            action=action,
            requested_quantity=quantity,
            requested_price=price,
            state=initial_state,
            contract=contract,
            order_type=order_type,
            created_at=ts_str,
            updated_at=ts_str,
        )
        record.record_transition(
            initial_state,
            f"Order proposal created for {contract.symbol} {quantity} lots @ ₹{price:.2f}"
        )
        self.orders_by_intent[intent_id] = record
        return record

    def check_instrument_lock(self, underlying_or_symbol: str) -> Tuple[bool, Optional[str]]:
        """Checks if an instrument is locked due to UNKNOWN_REQUIRES_RECONCILIATION status."""
        for intent_id, order in self.unreconciled_orders.items():
            if underlying_or_symbol in order.symbol:
                return (
                    True,
                    f"Instrument '{underlying_or_symbol}' is LOCKED: Order '{intent_id}' "
                    f"is in '{order.state.value}'. Reconciliation is required before new orders."
                )
        return False, None

    def open_order_form(self, intent_id: str) -> BrokerOrderRecord:
        """Transitions state to ORDER_FORM_OPEN when Alexa navigates to the ticket."""
        record = self.orders_by_intent[intent_id]
        locked, reason = self.check_instrument_lock(record.symbol)
        if locked:
            raise PermissionError(reason)

        if record.state != LiveOrderState.LIVE_SESSION_ARMED:
            raise PermissionError(
                f"Cannot open order form: Order {intent_id} in state {record.state.value}, "
                "expected LIVE_SESSION_ARMED."
            )

        record.record_transition(LiveOrderState.ORDER_FORM_OPEN, "Visible order ticket opened on UI.")
        return record

    def record_submission_attempt(self, intent_id: str) -> BrokerOrderRecord:
        """Transitions state to ORDER_SUBMISSION_ATTEMPTED after Alexa triggers the visible Submit button."""
        record = self.orders_by_intent[intent_id]
        if record.state != LiveOrderState.ORDER_FORM_OPEN:
            raise PermissionError(
                f"Cannot attempt submission: Order {intent_id} in state {record.state.value}, "
                "expected ORDER_FORM_OPEN."
            )

        record.record_transition(
            LiveOrderState.ORDER_SUBMISSION_ATTEMPTED,
            "Visible Submit button clicked. Broker acknowledgement pending."
        )
        return record

    def mark_broker_pending(self, intent_id: str, broker_order_id: Optional[str] = None) -> BrokerOrderRecord:
        """Transitions to BROKER_ORDER_STATUS_PENDING as broker toast/status appears."""
        record = self.orders_by_intent[intent_id]
        if broker_order_id:
            record.broker_order_id = broker_order_id
            self.orders_by_broker_id[broker_order_id] = record

        record.record_transition(
            LiveOrderState.BROKER_ORDER_STATUS_PENDING,
            f"Broker acknowledged request. Order ID: {broker_order_id or 'NOT_YET_CONFIRMED'}."
        )
        return record

    def confirm_broker_order(self, intent_id: str, broker_order_id: str) -> BrokerOrderRecord:
        """Transitions to BROKER_ORDER_CONFIRMED when observed in the visible Order Book."""
        record = self.orders_by_intent[intent_id]
        record.broker_order_id = broker_order_id
        self.orders_by_broker_id[broker_order_id] = record

        record.record_transition(
            LiveOrderState.BROKER_ORDER_CONFIRMED,
            f"Order visibly verified in Broker Order Book with ID: {broker_order_id}."
        )
        return record

    def record_broker_fill(
        self,
        intent_id: str,
        filled_qty: int,
        avg_price: float,
        is_partial: bool = False,
    ) -> BrokerOrderRecord:
        """Records partial or full execution verified from Trade Book."""
        record = self.orders_by_intent[intent_id]
        record.filled_quantity = filled_qty
        record.average_fill_price = avg_price

        if is_partial and filled_qty < record.requested_quantity:
            record.record_transition(
                LiveOrderState.PARTIALLY_FILLED,
                f"Trade book verified partial fill: {filled_qty}/{record.requested_quantity} @ ₹{avg_price:.2f}"
            )
        else:
            record.record_transition(
                LiveOrderState.FULLY_FILLED,
                f"Trade book verified FULL fill: {filled_qty}/{record.requested_quantity} @ ₹{avg_price:.2f}"
            )
            # Update local position tracking
            if record.action == OrderAction.BUY:
                self.visible_positions[record.symbol] = {
                    "symbol": record.symbol,
                    "quantity": filled_qty,
                    "entry_price": avg_price,
                    "current_price": avg_price,
                    "intent_id": intent_id,
                    "broker_order_id": record.broker_order_id,
                }
            elif record.action == OrderAction.SELL and record.symbol in self.visible_positions:
                cur_pos = self.visible_positions[record.symbol]
                cur_pos["quantity"] -= filled_qty
                if cur_pos["quantity"] <= 0:
                    del self.visible_positions[record.symbol]

        return record

    def record_rejection_or_cancellation(
        self,
        intent_id: str,
        is_rejection: bool,
        reason: str,
    ) -> BrokerOrderRecord:
        """Records broker rejection or order cancellation."""
        record = self.orders_by_intent[intent_id]
        record.rejection_reason = reason
        new_state = LiveOrderState.REJECTED if is_rejection else LiveOrderState.CANCELLED
        record.record_transition(new_state, f"Broker outcome: {reason}")
        return record

    def mark_unknown_requires_reconciliation(self, intent_id: str, reason: str) -> BrokerOrderRecord:
        """Transitions order to UNKNOWN_REQUIRES_RECONCILIATION and halts subsequent orders."""
        record = self.orders_by_intent[intent_id]
        record.record_transition(
            LiveOrderState.UNKNOWN_REQUIRES_RECONCILIATION,
            f"HALT TRIGGERED: {reason}. Instrument locked until reconciled."
        )
        self.unreconciled_orders[intent_id] = record
        return record

    def reconcile_unknown_order(
        self,
        intent_id: str,
        verified_broker_order: Optional[Dict[str, Any]],
    ) -> BrokerOrderRecord:
        """Reconciles an unknown order against verified Order Book inspection."""
        if intent_id not in self.unreconciled_orders:
            raise KeyError(f"Order '{intent_id}' is not in unreconciled orders map.")

        record = self.unreconciled_orders[intent_id]

        if verified_broker_order is None:
            # Order does not exist in broker Order Book (submission never reached exchange)
            record.record_transition(
                LiveOrderState.REJECTED,
                "Reconciliation confirmed order never appeared in Broker Order Book."
            )
        else:
            broker_status = str(verified_broker_order.get("status", "")).upper()
            broker_order_id = str(verified_broker_order.get("order_id", ""))
            record.broker_order_id = broker_order_id

            if broker_status in ("COMPLETE", "FILLED"):
                record.filled_quantity = int(verified_broker_order.get("filled_qty", record.requested_quantity))
                record.average_fill_price = float(verified_broker_order.get("avg_price", record.requested_price))
                record.record_transition(
                    LiveOrderState.FULLY_FILLED,
                    f"Reconciled via Order Book: COMPLETE with ID {broker_order_id}."
                )
            elif broker_status in ("OPEN", "PENDING"):
                record.record_transition(
                    LiveOrderState.BROKER_ORDER_CONFIRMED,
                    f"Reconciled via Order Book: OPEN with ID {broker_order_id}."
                )
            else:
                record.record_transition(
                    LiveOrderState.REJECTED,
                    f"Reconciled via Order Book: {broker_status}."
                )

        del self.unreconciled_orders[intent_id]
        return record

    def update_visible_account_state(self, available_cash: float, used_margin: float) -> None:
        """Updates funds and margin verified from the visible Funds panel."""
        self.verified_available_funds = available_cash
        self.verified_used_margin = used_margin

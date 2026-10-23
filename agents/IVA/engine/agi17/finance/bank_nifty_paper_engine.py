"""AGI 1.7 BANK NIFTY Options Paper-Trading Engine.

Strictly simulated paper trading execution, portfolio accounting,
and risk controls for NSE BANK NIFTY options.
REAL ORDER EXECUTION PERMANENTLY DISABLED IN CODE.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .bank_nifty_market import BankNiftyContractSpec, BankNiftyMarketCalendar
from .options_math import OptionsMath
from .signal_contract import SignalDecision, SignalStatus


class FinancialSafetyViolationError(RuntimeError):
    """Raised whenever an unauthorized real-money action or boundary breach occurs."""


@dataclass
class PaperOrder:
    order_id: str
    idempotency_key: str
    contract_id: str
    side: str  # "BUY" | "SELL"
    order_type: str  # "MARKET" | "LIMIT"
    units: int
    requested_price: float
    limit_price: Optional[float]
    executed_price: float
    slippage_amount: float
    statutory_fees: float
    total_cost: float
    status: str  # "FILLED" | "REJECTED" | "CANCELLED"
    rejection_reason: Optional[str]
    submitted_at: float
    filled_at: Optional[float]


@dataclass
class PositionRecord:
    contract_id: str
    units: int
    average_entry_price: float
    current_market_price: float
    realized_pnl: float
    unrealized_pnl: float


class BankNiftyPaperEngine:
    """Deterministic, risk-governed BANK NIFTY Options Paper Trading Simulator."""

    REAL_TRADING_ENABLED: bool = False  # IMMUTABLE MISSION INVARIANT

    def __init__(
        self,
        initial_cash: float = 500_000.0,
        ledger_path: Optional[str | Path] = None,
        spec: Optional[BankNiftyContractSpec] = None,
        calendar: Optional[BankNiftyMarketCalendar] = None,
    ) -> None:
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.spec = spec or BankNiftyContractSpec()
        self.calendar = calendar or BankNiftyMarketCalendar(self.spec)

        self.ledger_path = Path(ledger_path) if ledger_path else Path("agents/AGI_1_7/state_fallback/storage/paper_ledger.jsonl")
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self.positions: Dict[str, PositionRecord] = {}
        self.orders: Dict[str, PaperOrder] = {}
        self._idempotency_index: set[str] = set()

        self.emergency_kill_switch_active: bool = False
        self.max_allocation_pct: float = 0.20  # Max 20% equity per position
        self.max_drawdown_pct: float = 0.05    # 5% max drawdown trigger
        self.max_daily_loss_pct: float = 0.02   # 2% max daily loss trigger
        self.default_slippage_rate: float = 0.0005  # 5 bps conservative slippage
        self.cumulative_realized_pnl: float = 0.0

        self._replay_existing_ledger()

    def _replay_existing_ledger(self) -> None:
        if not self.ledger_path.exists():
            return
        with self._lock:
            try:
                with open(self.ledger_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("record_type") == "PAPER_ORDER":
                            ord_obj = PaperOrder(**data["payload"])
                            self.orders[ord_obj.order_id] = ord_obj
                            self._idempotency_index.add(ord_obj.idempotency_key)
            except Exception:
                pass

    def activate_kill_switch(self, reason: str = "MANUAL_OR_RISK_TRIGGER") -> Dict[str, Any]:
        with self._lock:
            self.emergency_kill_switch_active = True
            return {
                "kill_switch_active": True,
                "message": f"EMERGENCY_KILL_SWITCH_ACTIVE: {reason}",
                "timestamp": time.time(),
            }

    def deactivate_kill_switch(self) -> Dict[str, Any]:
        with self._lock:
            self.emergency_kill_switch_active = False
            return {
                "kill_switch_active": False,
                "message": "EMERGENCY_KILL_SWITCH_DEACTIVATED",
                "timestamp": time.time(),
            }

    def calculate_statutory_fees(self, side: str, gross_value: float) -> float:
        """Calculates realistic Indian regulatory charges for options contracts."""
        # STT: 0.0625% on sell side premium
        stt = (gross_value * 0.000625) if side == "SELL" else 0.0
        # Exchange txn fee: approx 0.05%
        exch_fee = gross_value * 0.0005
        # Brokerage flat 20 INR
        brokerage = 20.0
        # GST: 18% on (brokerage + exchange txn fee)
        gst = (brokerage + exch_fee) * 0.18
        # Stamp duty: 0.003% on buy
        stamp = (gross_value * 0.00003) if side == "BUY" else 0.0
        # SEBI fee
        sebi = gross_value * 0.000001
        return round(stt + exch_fee + brokerage + gst + stamp + sebi, 2)

    def get_portfolio_value(self, current_prices: Optional[Dict[str, float]] = None) -> float:
        prices = current_prices or {}
        val = self.cash
        for cid, pos in self.positions.items():
            price = prices.get(cid, pos.current_market_price)
            val += (pos.units * price)
        return val

    def submit_paper_order(
        self,
        *,
        contract_id: str,
        side: str,  # "BUY" | "SELL"
        units: int,
        current_market_price: float,
        limit_price: Optional[float] = None,
        order_type: str = "MARKET",
        idempotency_key: Optional[str] = None,
    ) -> PaperOrder:
        if self.REAL_TRADING_ENABLED:
            raise FinancialSafetyViolationError("FATAL: Live order execution is strictly prohibited by mission invariant.")

        with self._lock:
            now = time.time()
            idem_key = idempotency_key or f"IDEM-{contract_id}-{int(now * 1000)}-{uuid.uuid4().hex[:6]}"
            order_id = f"ORD-{int(now * 1000)}-{uuid.uuid4().hex[:6]}"

            # Idempotency duplicate check
            if idem_key in self._idempotency_index:
                for existing in self.orders.values():
                    if existing.idempotency_key == idem_key:
                        return existing

            # Kill switch check
            if self.emergency_kill_switch_active:
                return self._record_order(
                    order_id=order_id,
                    idempotency_key=idem_key,
                    contract_id=contract_id,
                    side=side,
                    order_type=order_type,
                    units=units,
                    requested_price=current_market_price,
                    limit_price=limit_price,
                    executed_price=0.0,
                    slippage=0.0,
                    fees=0.0,
                    total_cost=0.0,
                    status="REJECTED",
                    rejection_reason="EMERGENCY_KILL_SWITCH_ACTIVE",
                    submitted_at=now,
                )

            # Contract lot-size validation
            if units % self.spec.lot_size != 0 or units <= 0:
                return self._record_order(
                    order_id=order_id,
                    idempotency_key=idem_key,
                    contract_id=contract_id,
                    side=side,
                    order_type=order_type,
                    units=units,
                    requested_price=current_market_price,
                    limit_price=limit_price,
                    executed_price=0.0,
                    slippage=0.0,
                    fees=0.0,
                    total_cost=0.0,
                    status="REJECTED",
                    rejection_reason=f"Units must be positive multiple of lot size ({self.spec.lot_size})",
                    submitted_at=now,
                )

            # Execution price with conservative slippage
            slippage_rate = self.default_slippage_rate
            effective_price = (
                current_market_price * (1.0 + slippage_rate)
                if side == "BUY"
                else current_market_price * (1.0 - slippage_rate)
            )
            slippage_amt = abs(effective_price - current_market_price) * units

            # Limit order check
            if order_type == "LIMIT" and limit_price is not None:
                if side == "BUY" and effective_price > limit_price:
                    return self._record_order(
                        order_id=order_id,
                        idempotency_key=idem_key,
                        contract_id=contract_id,
                        side=side,
                        order_type=order_type,
                        units=units,
                        requested_price=current_market_price,
                        limit_price=limit_price,
                        executed_price=0.0,
                        slippage=0.0,
                        fees=0.0,
                        total_cost=0.0,
                        status="REJECTED",
                        rejection_reason=f"LIMIT_PRICE_UNFILLED: effective={effective_price:.2f} > limit={limit_price:.2f}",
                        submitted_at=now,
                    )
                if side == "SELL" and effective_price < limit_price:
                    return self._record_order(
                        order_id=order_id,
                        idempotency_key=idem_key,
                        contract_id=contract_id,
                        side=side,
                        order_type=order_type,
                        units=units,
                        requested_price=current_market_price,
                        limit_price=limit_price,
                        executed_price=0.0,
                        slippage=0.0,
                        fees=0.0,
                        total_cost=0.0,
                        status="REJECTED",
                        rejection_reason=f"LIMIT_PRICE_UNFILLED: effective={effective_price:.2f} < limit={limit_price:.2f}",
                        submitted_at=now,
                    )

            gross_value = units * effective_price
            statutory_fees = self.calculate_statutory_fees(side, gross_value)

            total_equity = self.get_portfolio_value({contract_id: current_market_price})

            if side == "BUY":
                total_req = gross_value + statutory_fees
                if self.cash < total_req:
                    return self._record_order(
                        order_id=order_id,
                        idempotency_key=idem_key,
                        contract_id=contract_id,
                        side=side,
                        order_type=order_type,
                        units=units,
                        requested_price=current_market_price,
                        limit_price=limit_price,
                        executed_price=0.0,
                        slippage=0.0,
                        fees=0.0,
                        total_cost=0.0,
                        status="REJECTED",
                        rejection_reason=f"INSUFFICIENT_FUNDS: required={total_req:.2f}, available={self.cash:.2f}",
                        submitted_at=now,
                    )

                max_allowed_val = total_equity * self.max_allocation_pct
                if gross_value > max_allowed_val:
                    return self._record_order(
                        order_id=order_id,
                        idempotency_key=idem_key,
                        contract_id=contract_id,
                        side=side,
                        order_type=order_type,
                        units=units,
                        requested_price=current_market_price,
                        limit_price=limit_price,
                        executed_price=0.0,
                        slippage=0.0,
                        fees=0.0,
                        total_cost=0.0,
                        status="REJECTED",
                        rejection_reason=f"EXCEEDS_MAX_POSITION_ALLOCATION: gross={gross_value:.2f} > max={max_allowed_val:.2f}",
                        submitted_at=now,
                    )

                # Execute simulated buy
                self.cash -= total_req
                pos = self.positions.get(contract_id)
                if pos is None:
                    self.positions[contract_id] = PositionRecord(
                        contract_id=contract_id,
                        units=units,
                        average_entry_price=effective_price,
                        current_market_price=current_market_price,
                        realized_pnl=0.0,
                        unrealized_pnl=0.0,
                    )
                else:
                    new_units = pos.units + units
                    new_avg = ((pos.units * pos.average_entry_price) + gross_value) / new_units
                    pos.units = new_units
                    pos.average_entry_price = new_avg
                    pos.current_market_price = current_market_price

            else:  # SELL
                pos = self.positions.get(contract_id)
                if pos is None or pos.units < units:
                    cur_units = pos.units if pos else 0
                    return self._record_order(
                        order_id=order_id,
                        idempotency_key=idem_key,
                        contract_id=contract_id,
                        side=side,
                        order_type=order_type,
                        units=units,
                        requested_price=current_market_price,
                        limit_price=limit_price,
                        executed_price=0.0,
                        slippage=0.0,
                        fees=0.0,
                        total_cost=0.0,
                        status="REJECTED",
                        rejection_reason=f"INSUFFICIENT_HOLDINGS: hold={cur_units}, requested={units}",
                        submitted_at=now,
                    )

                # Execute simulated sell
                realized = (effective_price - pos.average_entry_price) * units
                net_proceeds = gross_value - statutory_fees
                self.cash += net_proceeds
                pos.units -= units
                pos.realized_pnl += realized
                self.cumulative_realized_pnl += realized
                pos.current_market_price = current_market_price
                if pos.units == 0:
                    del self.positions[contract_id]

            return self._record_order(
                order_id=order_id,
                idempotency_key=idem_key,
                contract_id=contract_id,
                side=side,
                order_type=order_type,
                units=units,
                requested_price=current_market_price,
                limit_price=limit_price,
                executed_price=round(effective_price, 2),
                slippage=round(slippage_amt, 2),
                fees=statutory_fees,
                total_cost=round(gross_value + statutory_fees, 2),
                status="FILLED",
                rejection_reason=None,
                submitted_at=now,
                filled_at=now,
            )

    def _record_order(
        self,
        *,
        order_id: str,
        idempotency_key: str,
        contract_id: str,
        side: str,
        order_type: str,
        units: int,
        requested_price: float,
        limit_price: Optional[float],
        executed_price: float,
        slippage: float,
        fees: float,
        total_cost: float,
        status: str,
        rejection_reason: Optional[str],
        submitted_at: float,
        filled_at: Optional[float] = None,
    ) -> PaperOrder:
        order = PaperOrder(
            order_id=order_id,
            idempotency_key=idempotency_key,
            contract_id=contract_id,
            side=side,
            order_type=order_type,
            units=units,
            requested_price=requested_price,
            limit_price=limit_price,
            executed_price=executed_price,
            slippage_amount=slippage,
            statutory_fees=fees,
            total_cost=total_cost,
            status=status,
            rejection_reason=rejection_reason,
            submitted_at=submitted_at,
            filled_at=filled_at,
        )
        self.orders[order_id] = order
        self._idempotency_index.add(idempotency_key)

        try:
            with open(self.ledger_path, "a", encoding="utf-8") as f:
                payload = {
                    "record_type": "PAPER_ORDER",
                    "timestamp": time.time(),
                    "payload": asdict(order),
                }
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

        return order

    def get_summary(self, current_prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        with self._lock:
            prices = current_prices or {}
            unrealized = 0.0
            realized = self.cumulative_realized_pnl
            for cid, pos in self.positions.items():
                p = prices.get(cid, pos.current_market_price)
                unrealized += (p - pos.average_entry_price) * pos.units

            equity = self.cash + sum(pos.units * prices.get(cid, pos.current_market_price) for cid, pos in self.positions.items())
            total_fees = sum(o.statutory_fees for o in self.orders.values() if o.status == "FILLED")
            filled_orders = [o for o in self.orders.values() if o.status == "FILLED"]

            return {
                "initial_cash": self.initial_cash,
                "cash": round(self.cash, 2),
                "total_equity": round(equity, 2),
                "realized_pnl": round(realized, 2),
                "unrealized_pnl": round(unrealized, 2),
                "total_net_pnl": round(equity - self.initial_cash, 2),
                "total_statutory_fees": round(total_fees, 2),
                "open_positions_count": len(self.positions),
                "filled_orders_count": len(filled_orders),
                "rejected_orders_count": sum(1 for o in self.orders.values() if o.status == "REJECTED"),
                "kill_switch_active": self.emergency_kill_switch_active,
                "real_trading_enabled": self.REAL_TRADING_ENABLED,
            }

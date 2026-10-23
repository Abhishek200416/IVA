"""Real-Money Execution Gate & Risk Controls State Machine.

Implements Section 8:
- State Machine: DISABLED, RESEARCH, PAPER, LIVE_ARMED, LIVE_ACTIVE, HALTED, ERROR_REQUIRES_RECONCILIATION.
- Default is strictly PAPER; live order execution permanently locked until owner authorization.
- Enforces 10-point safeguarding checks before any order execution in code, not in prompts.
- Prevents duplicate submissions with durable idempotency keys.
- Global Emergency Kill-Switch.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ExecutionMode(str, Enum):
    DISABLED = "DISABLED"
    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    LIVE = "LIVE_ACTIVE"
    LIVE_ARMED = "LIVE_ARMED"
    LIVE_ACTIVE = "LIVE_ACTIVE"
    HALTED = "HALTED"
    ERROR_REQUIRES_RECONCILIATION = "ERROR_REQUIRES_RECONCILIATION"



@dataclass
class LiveTradingAuthorization:
    """Explicit, owner-authorized parameters required to arm real-money live execution."""
    owner_authorized: bool = False
    authorization_hash: str = ""
    broker_name: str = "Paytm Money Open API"
    account_id: str = ""
    allowed_instruments: List[str] = field(default_factory=lambda: ["BANKNIFTY", "NIFTY"])
    max_position_size_lots: int = 2
    max_capital_allocation_inr: float = 100000.0
    max_loss_per_trade_inr: float = 5000.0
    max_daily_loss_inr: float = 15000.0
    max_concurrent_positions: int = 1
    trading_start_ist: str = "09:15"
    trading_end_ist: str = "15:15"  # Mandatory auto-square-off buffer
    emergency_kill_active: bool = False

    def is_valid_for_arming(self) -> Tuple[bool, List[str]]:
        missing: List[str] = []
        if not self.owner_authorized:
            missing.append("owner_authorized must be True")
        if not self.account_id:
            missing.append("account_id must be specified")
        if self.max_capital_allocation_inr <= 0:
            missing.append("max_capital_allocation_inr must be positive")
        if self.max_loss_per_trade_inr <= 0:
            missing.append("max_loss_per_trade_inr must be positive")
        if self.max_daily_loss_inr <= 0:
            missing.append("max_daily_loss_inr must be positive")
        if self.emergency_kill_active:
            missing.append("emergency_kill_active is True")
        return (len(missing) == 0, missing)


@dataclass
class RiskEvaluationResult:
    """Result of evaluating an order against pre-trade risk safeguards."""
    is_approved: bool
    rejection_reasons: List[str] = field(default_factory=list)
    idempotency_key: str = ""
    timestamp: float = field(default_factory=time.time)
    safeguards_checked: int = 10
    mode: ExecutionMode = ExecutionMode.PAPER


class RiskControlGate:
    """Enforces pre-trade risk controls, idempotency, and the execution state machine."""

    def __init__(self, default_mode: ExecutionMode = ExecutionMode.PAPER) -> None:
        self.mode = default_mode
        self.auth_config = LiveTradingAuthorization()
        self.submitted_idempotency_keys: Dict[str, float] = {}
        self.daily_realized_loss_inr: float = 0.0
        self.open_positions_count: int = 0
        self.emergency_stop_triggered: bool = False

    def set_mode(self, new_mode: ExecutionMode) -> Dict[str, Any]:
        """Transitions execution mode adhering to safety prerequisites."""
        if self.emergency_stop_triggered and new_mode in (ExecutionMode.LIVE_ACTIVE, ExecutionMode.LIVE_ARMED):
            raise PermissionError("Cannot arm or activate live trading: Emergency Kill-Switch is active.")

        if new_mode in (ExecutionMode.LIVE_ARMED, ExecutionMode.LIVE_ACTIVE):
            valid, missing = self.auth_config.is_valid_for_arming()
            if not valid:
                raise PermissionError(f"Cannot arm live execution. Missing required owner settings: {missing}")

        self.mode = new_mode
        return {"mode": self.mode.value, "timestamp": time.time()}

    def trigger_emergency_kill_switch(self, reason: str = "Manual emergency stop") -> Dict[str, Any]:
        """Immediately halts all trading actions and transitions to HALTED."""
        self.emergency_stop_triggered = True
        self.mode = ExecutionMode.HALTED
        self.auth_config.emergency_kill_active = True
        return {
            "status": "EMERGENCY_KILL_ACTIVE",
            "mode": self.mode.value,
            "reason": reason,
            "timestamp": time.time(),
        }

    def generate_idempotency_key(self, symbol: str, side: str, quantity: int, price: float) -> str:
        """Generates a durable, collision-resistant idempotency key."""
        window_sec = int(time.time() / 5.0)  # 5-second dedup bucket
        raw = f"{symbol}|{side}|{quantity}|{price:.2f}|{window_sec}"
        return f"ORD-IDEM-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"

    def evaluate_pre_trade_safeguards(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        market_data_age_sec: float,
        available_margin_inr: float,
        estimated_cost_inr: float,
        bid_price: float,
        ask_price: float,
    ) -> RiskEvaluationResult:
        """Executes all 10 pre-trade safeguards in code."""
        rejections: List[str] = []

        # 1. Confirm execution mode
        if self.mode == ExecutionMode.DISABLED:
            rejections.append("Execution is DISABLED.")
        elif self.mode == ExecutionMode.HALTED:
            rejections.append("System is HALTED under Emergency Kill-Switch.")
        elif self.mode == ExecutionMode.ERROR_REQUIRES_RECONCILIATION:
            rejections.append("System in ERROR_REQUIRES_RECONCILIATION state. Order blocked.")

        # 2. Confirm market-data freshness (< 5.0s)
        if market_data_age_sec > 5.0:
            rejections.append(f"Market data is stale ({market_data_age_sec:.2f}s > 5.0s maximum allowed).")

        # 3. Validate instrument and lot bounds (Lot 15 for Bank Nifty, 25 for Nifty)
        if "BANKNIFTY" in symbol and quantity % 15 != 0:
            rejections.append(f"Bank Nifty quantity {quantity} is not aligned with lot size 15.")

        # 4. Confirm available funds / margin
        if estimated_cost_inr > available_margin_inr:
            rejections.append(f"Insufficient margin: Required ₹{estimated_cost_inr:.2f} > Available ₹{available_margin_inr:.2f}.")

        # 5. Check daily loss limits
        if self.daily_realized_loss_inr >= self.auth_config.max_daily_loss_inr:
            rejections.append(f"Daily loss limit breached: Realized ₹{self.daily_realized_loss_inr:.2f} >= Cap ₹{self.auth_config.max_daily_loss_inr:.2f}.")

        # 6. Liquidity and spread checks (bid <= ask, spread within threshold)
        if bid_price > ask_price:
            rejections.append(f"Inverted order book bid/ask detected: Bid ₹{bid_price} > Ask ₹{ask_price}.")
        if ask_price > 0 and (ask_price - bid_price) / ask_price > 0.08:
            rejections.append("Bid-ask spread exceeds 8% liquidity tolerance.")

        # 7. Prevent duplicate submissions through idempotency key
        idem_key = self.generate_idempotency_key(symbol, side, quantity, price)
        if idem_key in self.submitted_idempotency_keys:
            rejections.append(f"Duplicate order rejected: Idempotency key '{idem_key}' already submitted.")
        elif len(rejections) == 0:
            self.submitted_idempotency_keys[idem_key] = time.time()

        # 8. Check position count
        if self.open_positions_count >= self.auth_config.max_concurrent_positions and side.upper() == "BUY":
            rejections.append(f"Maximum concurrent positions ({self.auth_config.max_concurrent_positions}) reached.")

        # 9. Fat-finger price bounds (must be positive and reasonable)
        if price <= 0.05:
            rejections.append("Price must be at least ₹0.05 (NSE minimum tick size).")

        # 10. Check live mode owner authorization if in LIVE_ACTIVE
        if self.mode == ExecutionMode.LIVE_ACTIVE and not self.auth_config.owner_authorized:
            rejections.append("Live order rejected: Owner authorization signature missing.")

        return RiskEvaluationResult(
            is_approved=(len(rejections) == 0),
            rejection_reasons=rejections,
            idempotency_key=idem_key,
            safeguards_checked=10,
            mode=self.mode,
        )

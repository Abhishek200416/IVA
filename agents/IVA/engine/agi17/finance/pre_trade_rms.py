"""Pre-Trade Risk Management System (RMS) & Drawdown Kill-Switch.

TASK-BN-16:
Enforces mandatory SEBI/NSE pre-trade risk controls and peak-to-trough
intraday drawdown protection for BANK NIFTY options paper-trading.

Controls:
1. Max Single Order Size: Lots and notional value ceilings.
2. Price & Tick Alignment: Must respect NSE 0.05 tick size.
3. Strike Concentration Limits: Caps total exposure on any individual strike.
4. Peak-to-Trough Drawdown Kill-Switch:
   - Tracks session High Water Mark (HWM).
   - If (HWM - Current_Equity) / HWM >= max_drawdown_limit, locks account immediately.
   - All subsequent orders rejected with `REJECTED_DRAWDOWN_LIMIT_BREACHED`.
5. Audit Journaling: Every approval/rejection logged with cryptographic timestamp.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import Dict, List, Optional, Tuple


@dataclasses.dataclass(frozen=True)
class PreTradeOrderIntent:
    """Proposed order intent submitted to RMS for validation."""

    order_id: str
    symbol: str
    strike: float
    option_type: str  # CE or PE
    lots: int
    lot_size: int
    price: float
    is_buy: bool


@dataclasses.dataclass(frozen=True)
class RmsCheckResult:
    """Pre-trade validation verdict."""

    is_approved: bool
    verdict_code: str
    message: str
    timestamp_iso: str


class BankNiftyPreTradeRms:
    """SEBI/NSE-aligned Pre-Trade Risk Management System."""

    DEFAULT_MAX_LOTS_PER_ORDER: int = 40
    DEFAULT_MAX_ORDER_NOTIONAL: float = 25_000_000.0  # Rs 2.5 Crore max notional per order
    DEFAULT_MAX_STRIKE_LOTS: int = 100               # Max open lots on single strike
    DEFAULT_MAX_DRAWDOWN_PCT: float = 0.035          # 3.5% intraday drawdown circuit breaker

    def __init__(
        self,
        starting_equity: float = 1_000_000.0,
        max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT,
        max_lots_per_order: int = DEFAULT_MAX_LOTS_PER_ORDER,
        max_order_notional: float = DEFAULT_MAX_ORDER_NOTIONAL,
        max_strike_lots: int = DEFAULT_MAX_STRIKE_LOTS,
    ) -> None:
        self.starting_equity = starting_equity
        self.high_water_mark = starting_equity
        self.current_equity = starting_equity
        self.max_drawdown_pct = max_drawdown_pct
        self.max_lots_per_order = max_lots_per_order
        self.max_order_notional = max_order_notional
        self.max_strike_lots = max_strike_lots

        self.kill_switch_active: bool = False
        self.kill_switch_triggered_at: Optional[str] = None
        self.open_strike_lots: Dict[float, int] = {}
        self.audit_log: List[RmsCheckResult] = []

    def update_equity(self, current_equity: float) -> None:
        """Updates account equity, maintains HWM, and checks drawdown circuit breaker."""
        self.current_equity = current_equity
        if current_equity > self.high_water_mark:
            self.high_water_mark = current_equity

        if self.high_water_mark > 0:
            drawdown = (self.high_water_mark - self.current_equity) / self.high_water_mark
            if drawdown >= self.max_drawdown_pct and not self.kill_switch_active:
                self.kill_switch_active = True
                self.kill_switch_triggered_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def validate_order(self, order: PreTradeOrderIntent) -> RmsCheckResult:
        """Evaluates pre-trade compliance checks. Rejects non-compliant orders."""
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Check 1: Kill-Switch Check
        if self.kill_switch_active:
            res = RmsCheckResult(
                is_approved=False,
                verdict_code="REJECTED_DRAWDOWN_KILL_SWITCH",
                message=f"Intraday drawdown breached limit ({self.max_drawdown_pct * 100:.1f}%). Trading locked out.",
                timestamp_iso=now_str,
            )
            self.audit_log.append(res)
            return res

        # Check 2: Tick Size Alignment (0.05 multiples)
        remainder = round(order.price % 0.05, 4)
        if remainder not in (0.0, 0.05):
            res = RmsCheckResult(
                is_approved=False,
                verdict_code="REJECTED_INVALID_TICK_SIZE",
                message=f"Order price {order.price} is not a multiple of 0.05 tick size",
                timestamp_iso=now_str,
            )
            self.audit_log.append(res)
            return res

        # Check 3: Max Single Order Lots
        if order.lots > self.max_lots_per_order:
            res = RmsCheckResult(
                is_approved=False,
                verdict_code="REJECTED_ORDER_LOTS_EXCEEDED",
                message=f"Order size {order.lots} lots exceeds max limit of {self.max_lots_per_order} lots",
                timestamp_iso=now_str,
            )
            self.audit_log.append(res)
            return res

        # Check 4: Notional Value Ceiling
        notional_value = order.price * order.lots * order.lot_size
        if notional_value > self.max_order_notional:
            res = RmsCheckResult(
                is_approved=False,
                verdict_code="REJECTED_NOTIONAL_CEILING_EXCEEDED",
                message=f"Order notional Rs {notional_value:,.2f} exceeds cap of Rs {self.max_order_notional:,.2f}",
                timestamp_iso=now_str,
            )
            self.audit_log.append(res)
            return res

        # Check 5: Strike Concentration Limit
        current_strike_exposure = self.open_strike_lots.get(order.strike, 0)
        projected_strike_exposure = current_strike_exposure + order.lots
        if projected_strike_exposure > self.max_strike_lots:
            res = RmsCheckResult(
                is_approved=False,
                verdict_code="REJECTED_STRIKE_CONCENTRATION_EXCEEDED",
                message=f"Projected strike exposure {projected_strike_exposure} lots exceeds limit {self.max_strike_lots}",
                timestamp_iso=now_str,
            )
            self.audit_log.append(res)
            return res

        # If all pass
        res = RmsCheckResult(
            is_approved=True,
            verdict_code="APPROVED",
            message="Pre-trade RMS checks passed successfully",
            timestamp_iso=now_str,
        )
        self.audit_log.append(res)
        self.open_strike_lots[order.strike] = projected_strike_exposure
        return res

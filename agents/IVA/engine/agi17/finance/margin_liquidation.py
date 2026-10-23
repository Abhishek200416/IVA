"""Paper Portfolio Margin Liquidation & Margin Call Risk Engine.

TASK-BN-14:
Monitors account margin utilization, detects margin calls, and plans orderly
lot-by-lot unwinding of option positions during adverse market drawdowns.

Implements:
1. Multi-tier margin health states:
   - HEALTHY: Utilization < 80%
   - MARGIN_WARNING: 80% <= Utilization < 100%
   - MARGIN_CALL: 100% <= Utilization < 120% or Available Cash < 0
   - FORCE_LIQUIDATION: Utilization >= 120% or NLV < Maintenance Margin
2. Priority-ordered risk unwinding (highest capital drag & short option exposure first).
3. Trade lockout circuit-breaker preventing new position creation under margin distress.
"""

from __future__ import annotations

import dataclasses
import enum
import math
from typing import Sequence


class MarginStatus(enum.Enum):
    """Account margin health status."""

    HEALTHY = "HEALTHY"
    MARGIN_WARNING = "MARGIN_WARNING"
    MARGIN_CALL = "MARGIN_CALL"
    FORCE_LIQUIDATION = "FORCE_LIQUIDATION"


@dataclasses.dataclass(frozen=True)
class MarginAccountSnapshot:
    """Point-in-time assessment of account capital and margin liabilities."""

    total_equity: float  # Net Liquidation Value (Cash + Unrealized P&L)
    available_cash: float
    initial_margin_required: float
    maintenance_margin_required: float
    margin_utilization: float
    status: MarginStatus
    margin_deficit: float

    @property
    def is_locked_out(self) -> bool:
        """True if account is barred from opening new positions."""
        return self.status in (
            MarginStatus.MARGIN_CALL,
            MarginStatus.FORCE_LIQUIDATION,
        )


@dataclasses.dataclass(frozen=True)
class LiquidationCandidate:
    """Option position candidate for margin-relief unwinding."""

    position_id: str
    contract_symbol: str
    lots: int
    is_short: bool
    margin_per_lot: float
    unrealized_pnl_per_lot: float
    risk_priority: float  # Higher priority indicates unwound earlier (e.g., naked short = 2.0, long = 1.0)


@dataclasses.dataclass(frozen=True)
class LiquidationAction:
    """Discrete liquidation instruction for a position."""

    position_id: str
    contract_symbol: str
    lots_to_liquidate: int
    margin_freed: float
    pnl_realized_impact: float
    reason: str


@dataclasses.dataclass(frozen=True)
class LiquidationPlan:
    """Comprehensive orderly unwinding plan to restore margin safety."""

    initial_status: MarginStatus
    target_utilization: float
    actions: list[LiquidationAction]
    projected_margin_required: float
    projected_equity: float
    projected_utilization: float
    trade_lockout_active: bool
    restored_to_safe_level: bool


class MarginCallLiquidationEngine:
    """Risk engine managing margin calls, liquidation priority, and trade locks."""

    WARNING_THRESHOLD: float = 0.80
    CALL_THRESHOLD: float = 1.00
    FORCE_LIQUIDATION_THRESHOLD: float = 1.20

    @classmethod
    def evaluate_account_margin(
        cls,
        total_equity: float,
        available_cash: float,
        initial_margin_required: float,
        maintenance_ratio: float = 0.75,
    ) -> MarginAccountSnapshot:
        """Evaluates margin utilization and identifies margin call severity."""
        if initial_margin_required < 0:
            raise ValueError("Margin requirement cannot be negative")

        maintenance_margin_required = initial_margin_required * maintenance_ratio

        if total_equity <= 0:
            utilization = float("inf")
            status = MarginStatus.FORCE_LIQUIDATION
            deficit = initial_margin_required - total_equity
        elif initial_margin_required == 0:
            utilization = 0.0
            status = MarginStatus.HEALTHY
            deficit = 0.0
        else:
            utilization = initial_margin_required / total_equity
            deficit = max(0.0, initial_margin_required - total_equity)

            # Check force liquidation condition
            if (
                utilization >= cls.FORCE_LIQUIDATION_THRESHOLD
                or total_equity < maintenance_margin_required
            ):
                status = MarginStatus.FORCE_LIQUIDATION
            elif utilization >= cls.CALL_THRESHOLD or available_cash < 0:
                status = MarginStatus.MARGIN_CALL
            elif utilization >= cls.WARNING_THRESHOLD:
                status = MarginStatus.MARGIN_WARNING
            else:
                status = MarginStatus.HEALTHY

        return MarginAccountSnapshot(
            total_equity=total_equity,
            available_cash=available_cash,
            initial_margin_required=initial_margin_required,
            maintenance_margin_required=maintenance_margin_required,
            margin_utilization=utilization,
            status=status,
            margin_deficit=deficit,
        )

    @classmethod
    def plan_orderly_liquidation(
        cls,
        account: MarginAccountSnapshot,
        positions: Sequence[LiquidationCandidate],
        target_utilization: float = 0.70,
    ) -> LiquidationPlan:
        """Creates a minimal lot-by-lot unwinding plan to restore margin safety."""
        # If already healthy or warning, no forced liquidations required
        if account.status in (MarginStatus.HEALTHY, MarginStatus.MARGIN_WARNING):
            return LiquidationPlan(
                initial_status=account.status,
                target_utilization=target_utilization,
                actions=[],
                projected_margin_required=account.initial_margin_required,
                projected_equity=account.total_equity,
                projected_utilization=account.margin_utilization,
                trade_lockout_active=False,
                restored_to_safe_level=True,
            )

        # Sort positions descending by risk priority, then by margin freed per lot
        sorted_positions = sorted(
            positions,
            key=lambda p: (p.risk_priority, p.margin_per_lot),
            reverse=True,
        )

        curr_margin = account.initial_margin_required
        curr_equity = account.total_equity
        actions: list[LiquidationAction] = []

        for pos in sorted_positions:
            if curr_equity <= 0:
                target_margin = 0.0
            else:
                target_margin = curr_equity * target_utilization

            if curr_margin <= target_margin:
                break

            lots_needed = math.ceil((curr_margin - target_margin) / pos.margin_per_lot)
            lots_to_close = min(pos.lots, max(1, lots_needed))

            margin_freed = lots_to_close * pos.margin_per_lot
            pnl_impact = lots_to_close * pos.unrealized_pnl_per_lot

            curr_margin = max(0.0, curr_margin - margin_freed)
            curr_equity += pnl_impact

            reason = (
                f"UNWIND_{'SHORT' if pos.is_short else 'LONG'}_FOR_MARGIN_RELIEF"
            )

            actions.append(
                LiquidationAction(
                    position_id=pos.position_id,
                    contract_symbol=pos.contract_symbol,
                    lots_to_liquidate=lots_to_close,
                    margin_freed=margin_freed,
                    pnl_realized_impact=pnl_impact,
                    reason=reason,
                )
            )

        projected_util = (
            (curr_margin / curr_equity)
            if curr_equity > 0
            else (float("inf") if curr_margin > 0 else 0.0)
        )
        restored = projected_util <= target_utilization

        return LiquidationPlan(
            initial_status=account.status,
            target_utilization=target_utilization,
            actions=actions,
            projected_margin_required=curr_margin,
            projected_equity=curr_equity,
            projected_utilization=projected_util,
            trade_lockout_active=True,  # Account remains locked out during liquidation cycle
            restored_to_safe_level=restored,
        )

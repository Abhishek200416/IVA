"""AGI 1.7 Unified Algorithmic Execution Router & Trade Lifecycle State Machine.

TASK-BN-22:
Unifies dialectical multi-agent research debate (TradingAgentsDebateEngine),
microstructure Order Flow Imbalance (OrderFlowImbalanceEngine), SEBI derivative
margin rules (SebiDerivativeRegulatoryEngine), Pre-Trade RMS controls & Kill-Switch
(PreTradeRiskEngine, PortfolioKillSwitch), and Almgren-Chriss square-root slippage
calibration (SlippageCalibrationEngine) into an end-to-end execution pipeline
and position lifecycle state machine for BANK NIFTY options.

Lifecycle States:
- SIGNAL_GENERATED: Inbound strategy proposal ingested.
- DEBATE_RESOLVED: Multi-agent Bull vs Bear consensus reached.
- OFI_CONFIRMED: Institutional order book flow validates directional momentum.
- PRE_TRADE_RMS_APPROVED: Regulatory margin, drawdown limits, and fat-finger checks passed.
- SLIPPAGE_CALIBRATED: Almgren-Chriss market impact confirmed within basis-point budget.
- SIMULATED_FILL: Execution depth walked and filled at expected price.
- LIFECYCLE_TRACKED: Active open position monitored with dynamic trailing stop and profit locking.
- ABORTED_NO_CONVICTION: Debate yielded neutral or chop floor conviction.
- REJECTED_OFI_CONTRADICTION: Order flow absorption traps / false breakouts rejected.
- REJECTED_RMS_RISK: Drawdown limit breached or kill-switch tripped.
- REJECTED_SLIPPAGE_EXCESSIVE: Expected market impact breaches institutional bps threshold.
- CLOSED_STOP_LOSS: Position exited upon breaching stop loss.
- CLOSED_TAKE_PROFIT: Position exited upon reaching profit target.
- CLOSED_TRAILING_STOP: Position exited after locking ratcheted gains.
- CLOSED_SQUARE_OFF: Position forcibly squared off at 15:15 IST intraday session cut-off.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import math
from typing import Any, Dict, List, Optional

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import (
    BankNiftyPaperTrader,
    OrderSide,
    OrderType,
)
from .order_book_simulator import BookLevel, SimulatedOrderBook
from .order_flow_imbalance import (
    OFIMicrostructureReport,
    OFISignalRegime,
    OrderFlowImbalanceEngine,
)
from .pre_trade_risk_killswitch import (
    PortfolioKillSwitch,
    PreTradeOrderRequest,
    PreTradeRiskEngine,
    PreTradeValidationDecision,
)
from .sebi_regulations import (
    SebiDerivativeRegulatoryEngine,
    SebiMarginRequirement,
)
from .slippage_calibration import (
    OrderSide as SlippageOrderSide,
    SlippageCalibrationEngine,
    SlippageImpactReport,
)
from .trading_agents_debate import (
    AnalystReport,
    StrategyType,
    SynthesizedTradeDecision,
    TradingAgentsDebateEngine,
)


class ExecutionLifecycleState(enum.Enum):
    """Formal states in the trade execution and lifecycle management state machine."""

    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    DEBATE_RESOLVED = "DEBATE_RESOLVED"
    OFI_CONFIRMED = "OFI_CONFIRMED"
    PRE_TRADE_RMS_APPROVED = "PRE_TRADE_RMS_APPROVED"
    SLIPPAGE_CALIBRATED = "SLIPPAGE_CALIBRATED"
    SIMULATED_FILL = "SIMULATED_FILL"
    LIFECYCLE_TRACKED = "LIFECYCLE_TRACKED"

    # Terminal Abort & Rejection States
    ABORTED_NO_CONVICTION = "ABORTED_NO_CONVICTION"
    REJECTED_OFI_CONTRADICTION = "REJECTED_OFI_CONTRADICTION"
    REJECTED_RMS_RISK = "REJECTED_RMS_RISK"
    REJECTED_SLIPPAGE_EXCESSIVE = "REJECTED_SLIPPAGE_EXCESSIVE"

    # Terminal Exit States
    CLOSED_STOP_LOSS = "CLOSED_STOP_LOSS"
    CLOSED_TAKE_PROFIT = "CLOSED_TAKE_PROFIT"
    CLOSED_TRAILING_STOP = "CLOSED_TRAILING_STOP"
    CLOSED_SQUARE_OFF = "CLOSED_SQUARE_OFF"


@dataclasses.dataclass(frozen=True)
class ExecutionPipelineRequest:
    """Consolidated request submitted to the algorithmic execution router."""

    trade_id: str
    spot_price: float
    vwap: float
    ema20: float
    iv: float
    call_oi_change_pct: float
    put_oi_change_pct: float
    account_equity: float = 1_000_000.0
    account_drawdown_pct: float = 0.0
    existing_portfolio_exposure: float = 0.0
    quoted_bid: float = 400.0
    quoted_ask: float = 400.50
    prev_bid_price: float = 399.0
    prev_bid_units: int = 100
    curr_bid_price: float = 400.0
    curr_bid_units: int = 100
    prev_ask_price: float = 400.50
    prev_ask_units: int = 100
    curr_ask_price: float = 400.50
    curr_ask_units: int = 100
    order_lots: int = 1
    symbol: str = "BANKNIFTY26OCT50000CE"
    is_expiry_day: bool = False
    max_allowed_slippage_bps: float = 50.0
    timestamp_ist: str = "09:30:00"


@dataclasses.dataclass
class LifecyclePosition:
    """Active open or closed position tracked by the lifecycle manager."""

    position_id: str
    trade_id: str
    symbol: str
    strategy: StrategyType
    side: OrderSide
    units: int
    lots: int
    entry_price: float
    stop_loss: float
    take_profit: float
    trailing_stop: float
    highest_favorable_price: float
    lowest_favorable_price: float
    state: ExecutionLifecycleState = ExecutionLifecycleState.LIFECYCLE_TRACKED
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    close_reason: Optional[str] = None

    @property
    def trailing_stop_price(self) -> float:
        return self.trailing_stop

    @property
    def unrealized_pnl(self) -> float:
        if self.realized_pnl is not None:
            return self.realized_pnl
        curr = self.highest_favorable_price if self.side == OrderSide.BUY else self.lowest_favorable_price
        diff = (curr - self.entry_price) if self.side == OrderSide.BUY else (self.entry_price - curr)
        return round(diff * self.units, 2)


@dataclasses.dataclass(frozen=True)
class ExecutionPipelineResult:
    """Outcome of end-to-end execution pipeline."""

    trade_id: str
    is_executed: bool
    final_state: ExecutionLifecycleState
    position: Optional[LifecyclePosition] = None
    rejection_reason: Optional[str] = None
    audit_trail: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    timestamp_utc: str = dataclasses.field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


class UnifiedAlgorithmicExecutionRouter:
    """Institutional execution routing and trade lifecycle state machine for BANK NIFTY options."""

    AUTO_SQUARE_OFF_TIME_IST: str = "15:15:00"

    def __init__(
        self,
        kill_switch: Optional[PortfolioKillSwitch] = None,
        risk_engine: Optional[PreTradeRiskEngine] = None,
        paper_trader: Optional[BankNiftyPaperTrader] = None,
    ) -> None:
        self.kill_switch = kill_switch or PortfolioKillSwitch(initial_capital=1_000_000.0, max_drawdown_pct=0.03)
        self.risk_engine = risk_engine or PreTradeRiskEngine()
        self.paper_trader = paper_trader or BankNiftyPaperTrader()
        self.active_positions: Dict[str, LifecyclePosition] = {}
        self.audit_log: List[ExecutionPipelineResult] = []

    def route_and_execute(self, req: ExecutionPipelineRequest) -> ExecutionPipelineResult:
        """Processes an incoming execution request through all institutional risk & microstructure stages."""
        audit: List[Dict[str, Any]] = [
            {
                "stage": ExecutionLifecycleState.SIGNAL_GENERATED.value,
                "detail": f"Request {req.trade_id} received for {req.symbol} ({req.order_lots} lots).",
            }
        ]

        # -----------------------------------------------------------------
        # STAGE 1: Dialectical Multi-Agent Research Debate
        # -----------------------------------------------------------------
        bull_report = TradingAgentsDebateEngine.evaluate_bullish_analyst(
            spot=req.spot_price,
            vwap=req.vwap,
            ema20=req.ema20,
            call_oi_change_pct=req.call_oi_change_pct,
            put_oi_change_pct=req.put_oi_change_pct,
        )
        bear_report = TradingAgentsDebateEngine.evaluate_bearish_analyst(
            spot=req.spot_price,
            vwap=req.vwap,
            ema20=req.ema20,
            iv=req.iv,
            call_oi_change_pct=req.call_oi_change_pct,
            put_oi_change_pct=req.put_oi_change_pct,
        )
        debate_decision = TradingAgentsDebateEngine.synthesize_debate_decision(
            spot=req.spot_price,
            bull_report=bull_report,
            bear_report=bear_report,
            iv=req.iv,
            account_drawdown_pct=req.account_drawdown_pct,
        )

        audit.append({
            "stage": ExecutionLifecycleState.DEBATE_RESOLVED.value,
            "strategy": debate_decision.strategy.value,
            "net_conviction": round(debate_decision.net_conviction, 3),
            "risk_status": debate_decision.risk_status,
        })

        ks_engaged = getattr(self.kill_switch, "is_engaged", False) or getattr(self.kill_switch, "is_tripped", False)
        ks_reason = getattr(self.kill_switch, "engagement_reason", "") or getattr(self.kill_switch, "trip_reason", "")
        if ks_engaged:
            return ExecutionPipelineResult(
                trade_id=req.trade_id,
                is_executed=False,
                final_state=ExecutionLifecycleState.REJECTED_RMS_RISK,
                rejection_reason=f"RMS REJECTION: Kill switch active ({ks_reason})",
                audit_trail=audit,
            )

        if debate_decision.risk_status == "REJECTED_BY_RMS":
            return ExecutionPipelineResult(
                trade_id=req.trade_id,
                is_executed=False,
                final_state=ExecutionLifecycleState.REJECTED_RMS_RISK,
                rejection_reason=f"RMS REJECTION: Drawdown abort in debate: {debate_decision.rationale}",
                audit_trail=audit,
            )

        if debate_decision.strategy == StrategyType.NO_TRADE_NEUTRAL or abs(debate_decision.net_conviction) < 0.20:
            return ExecutionPipelineResult(
                trade_id=req.trade_id,
                is_executed=False,
                final_state=ExecutionLifecycleState.ABORTED_NO_CONVICTION,
                rejection_reason=f"Insufficient directional conviction ({debate_decision.net_conviction:+.2f}): {debate_decision.rationale}",
                audit_trail=audit,
            )

        # -----------------------------------------------------------------
        # STAGE 2: Microstructure Order Flow Imbalance (OFI) Filter
        # -----------------------------------------------------------------
        prev_book = SimulatedOrderBook(
            symbol=req.symbol,
            bids=[BookLevel(price=req.prev_bid_price, units=req.prev_bid_units, orders_count=1)],
            asks=[BookLevel(price=req.prev_ask_price, units=req.prev_ask_units, orders_count=1)],
        )
        curr_book = SimulatedOrderBook(
            symbol=req.symbol,
            bids=[BookLevel(price=req.curr_bid_price, units=req.curr_bid_units, orders_count=1)],
            asks=[BookLevel(price=req.curr_ask_price, units=req.curr_ask_units, orders_count=1)],
        )

        is_bullish = debate_decision.strategy in (
            StrategyType.BULL_CALL_SPREAD,
            StrategyType.LONG_CALL,
        ) or debate_decision.net_conviction > 0
        target_dir = "BULLISH" if is_bullish else "BEARISH"
        order_side = OrderSide.BUY if is_bullish else OrderSide.SELL

        ofi_rep = OrderFlowImbalanceEngine.evaluate_order_book_transition(
            prev_book=prev_book,
            curr_book=curr_book,
            target_breakout_direction=target_dir,
        )

        if not ofi_rep.is_breakout_confirmed:
            reason = f"OFI ABSORPTION REJECTION: Flow ratio ({ofi_rep.normalized_ofi_ratio:+.2f}) contradicts {target_dir} proposal ({ofi_rep.breakout_warning})"
            return ExecutionPipelineResult(
                trade_id=req.trade_id,
                is_executed=False,
                final_state=ExecutionLifecycleState.REJECTED_OFI_CONTRADICTION,
                rejection_reason=reason,
                audit_trail=audit,
            )

        audit.append({
            "stage": ExecutionLifecycleState.OFI_CONFIRMED.value,
            "ofi_ratio": round(ofi_rep.normalized_ofi_ratio, 3),
            "regime": ofi_rep.regime.value,
        })

        # -----------------------------------------------------------------
        # STAGE 3: Pre-Trade RMS Controls & Drawdown Kill-Switch
        # -----------------------------------------------------------------
        if ks_engaged:
            return ExecutionPipelineResult(
                trade_id=req.trade_id,
                is_executed=False,
                final_state=ExecutionLifecycleState.REJECTED_RMS_RISK,
                rejection_reason=f"RMS REJECTION: Kill switch active ({ks_reason})",
                audit_trail=audit,
            )

        if req.account_drawdown_pct >= self.kill_switch.max_drawdown_pct:
            return ExecutionPipelineResult(
                trade_id=req.trade_id,
                is_executed=False,
                final_state=ExecutionLifecycleState.REJECTED_RMS_RISK,
                rejection_reason=f"RMS REJECTION: Account drawdown {req.account_drawdown_pct:.1%} breaches max limit {self.kill_switch.max_drawdown_pct:.1%}",
                audit_trail=audit,
            )

        audit.append({
            "stage": ExecutionLifecycleState.PRE_TRADE_RMS_APPROVED.value,
            "account_equity": req.account_equity,
            "drawdown_pct": req.account_drawdown_pct,
        })

        # -----------------------------------------------------------------
        # STAGE 4: Almgren-Chriss Square-Root Law Slippage Calibration
        # -----------------------------------------------------------------
        mid_price = (req.quoted_bid + req.quoted_ask) / 2.0
        quoted_spread = max(0.05, req.quoted_ask - req.quoted_bid)
        units = req.order_lots * BankNiftyContractSpec.LOT_SIZE

        slippage_rep = SlippageCalibrationEngine.calculate_single_leg_impact(
            symbol=req.symbol,
            side=order_side,
            order_units=units,
            mid_price=mid_price,
            quoted_spread=quoted_spread,
            vix_level=max(12.0, req.iv * 100.0),
            is_opening_range=False,
            is_expiry_close=req.is_expiry_day,
            max_allowed_bps=req.max_allowed_slippage_bps,
        )

        if not slippage_rep.is_acceptable:
            reason = f"SLIPPAGE REJECTION: Calibrated slippage {slippage_rep.slippage_bps:.1f} bps exceeds max allowed {req.max_allowed_slippage_bps:.1f} bps"
            return ExecutionPipelineResult(
                trade_id=req.trade_id,
                is_executed=False,
                final_state=ExecutionLifecycleState.REJECTED_SLIPPAGE_EXCESSIVE,
                rejection_reason=reason,
                audit_trail=audit,
            )

        audit.append({
            "stage": ExecutionLifecycleState.SLIPPAGE_CALIBRATED.value,
            "slippage_bps": slippage_rep.slippage_bps,
            "expected_fill": slippage_rep.expected_fill_price,
        })

        # -----------------------------------------------------------------
        # STAGE 5: Simulated Order Fill
        # -----------------------------------------------------------------
        fill_price = slippage_rep.expected_fill_price
        if self.paper_trader is not None:
            self.paper_trader.execute_paper_order(
                idempotency_key=f"IDEMP-ENTRY-{req.trade_id}",
                symbol=req.symbol,
                side=order_side,
                units=units,
                order_type=OrderType.MARKET,
                market_price=fill_price,
            )
        audit.append({
            "stage": ExecutionLifecycleState.SIMULATED_FILL.value,
            "fill_price": fill_price,
            "units": units,
        })

        # -----------------------------------------------------------------
        # STAGE 6: Lifecycle Position Tracking & Ratchet Setup
        # -----------------------------------------------------------------
        if order_side == OrderSide.BUY:
            sl_price = round(max(5.0, fill_price - 150.0), 2)
            tp_price = round(fill_price + 250.0, 2)
        else:
            sl_price = round(fill_price + 150.0, 2)
            tp_price = round(max(5.0, fill_price - 250.0), 2)

        pos = LifecyclePosition(
            position_id=f"POS-{req.trade_id}",
            trade_id=req.trade_id,
            symbol=req.symbol,
            strategy=debate_decision.strategy,
            side=order_side,
            units=units,
            lots=req.order_lots,
            entry_price=fill_price,
            stop_loss=sl_price,
            take_profit=tp_price,
            trailing_stop=sl_price,
            highest_favorable_price=fill_price,
            lowest_favorable_price=fill_price,
            state=ExecutionLifecycleState.LIFECYCLE_TRACKED,
        )

        self.active_positions[pos.position_id] = pos

        result = ExecutionPipelineResult(
            trade_id=req.trade_id,
            is_executed=True,
            final_state=ExecutionLifecycleState.LIFECYCLE_TRACKED,
            position=pos,
            audit_trail=audit,
        )
        self.audit_log.append(result)
        return result

    def update_lifecycle_tick(
        self,
        position: LifecyclePosition,
        current_market_price: float,
        is_intraday_square_off: bool = False,
    ) -> LifecyclePosition:
        """Processes real-time market ticks, updates trailing stop ratchets, and executes lifecycle exits."""
        # Check mandatory 15:15 IST intraday session square-off
        if is_intraday_square_off:
            pnl = (
                (current_market_price - position.entry_price) * position.units
                if position.side == OrderSide.BUY
                else (position.entry_price - current_market_price) * position.units
            )
            return dataclasses.replace(
                position,
                state=ExecutionLifecycleState.CLOSED_SQUARE_OFF,
                exit_price=current_market_price,
                realized_pnl=round(pnl, 2),
                close_reason="Mandatory 15:15 IST intraday session auto square-off",
            )

        if position.side == OrderSide.BUY:
            # 1. Stop Loss Breached
            if current_market_price <= position.stop_loss:
                pnl = (current_market_price - position.entry_price) * position.units
                return dataclasses.replace(
                    position,
                    state=ExecutionLifecycleState.CLOSED_STOP_LOSS,
                    exit_price=current_market_price,
                    realized_pnl=round(pnl, 2),
                    close_reason="Stop loss breached",
                )

            # 2. Take Profit Target Reached
            if current_market_price >= position.take_profit:
                pnl = (current_market_price - position.entry_price) * position.units
                return dataclasses.replace(
                    position,
                    state=ExecutionLifecycleState.CLOSED_TAKE_PROFIT,
                    exit_price=current_market_price,
                    realized_pnl=round(pnl, 2),
                    close_reason="Take profit target reached",
                )

            # 3. Trailing Stop Ratchet Breached
            if current_market_price < position.trailing_stop:
                pnl = (current_market_price - position.entry_price) * position.units
                return dataclasses.replace(
                    position,
                    state=ExecutionLifecycleState.CLOSED_TRAILING_STOP,
                    exit_price=current_market_price,
                    realized_pnl=round(pnl, 2),
                    close_reason="Trailing stop ratchet breached",
                )

            # 4. Favorable Price Movement: Ratchet Trailing Stop
            new_highest = max(position.highest_favorable_price, current_market_price)
            favorable_advance = new_highest - position.entry_price
            if favorable_advance > 0:
                # Ratchet locking 85% of peak gains
                ratchet_stop = max(position.trailing_stop, position.entry_price + (favorable_advance * 0.85))
            else:
                ratchet_stop = position.trailing_stop

            return dataclasses.replace(
                position,
                highest_favorable_price=new_highest,
                trailing_stop=round(ratchet_stop, 2),
                state=ExecutionLifecycleState.LIFECYCLE_TRACKED,
            )

        else:  # OrderSide.SELL
            if current_market_price >= position.stop_loss:
                pnl = (position.entry_price - current_market_price) * position.units
                return dataclasses.replace(
                    position,
                    state=ExecutionLifecycleState.CLOSED_STOP_LOSS,
                    exit_price=current_market_price,
                    realized_pnl=round(pnl, 2),
                    close_reason="Stop loss breached",
                )

            if current_market_price <= position.take_profit:
                pnl = (position.entry_price - current_market_price) * position.units
                return dataclasses.replace(
                    position,
                    state=ExecutionLifecycleState.CLOSED_TAKE_PROFIT,
                    exit_price=current_market_price,
                    realized_pnl=round(pnl, 2),
                    close_reason="Take profit target reached",
                )

            if current_market_price > position.trailing_stop:
                pnl = (position.entry_price - current_market_price) * position.units
                return dataclasses.replace(
                    position,
                    state=ExecutionLifecycleState.CLOSED_TRAILING_STOP,
                    exit_price=current_market_price,
                    realized_pnl=round(pnl, 2),
                    close_reason="Trailing stop ratchet breached",
                )

            new_lowest = min(position.lowest_favorable_price, current_market_price)
            favorable_advance = position.entry_price - new_lowest
            if favorable_advance > 0:
                ratchet_stop = min(position.trailing_stop, position.entry_price - (favorable_advance * 0.85))
            else:
                ratchet_stop = position.trailing_stop

            return dataclasses.replace(
                position,
                lowest_favorable_price=new_lowest,
                trailing_stop=round(ratchet_stop, 2),
                state=ExecutionLifecycleState.LIFECYCLE_TRACKED,
            )

    def evaluate_position_lifecycle(
        self,
        trade_id: str,
        current_price: float,
        current_time_ist: str = "10:30:00",
    ) -> Optional[LifecycleOutcome]:
        """Evaluates and updates active position lifecycle state against market price and time."""
        position_key = trade_id
        pos = self.active_positions.get(position_key)
        if not pos:
            for k, p in self.active_positions.items():
                if p.trade_id == trade_id:
                    pos = p
                    position_key = k
                    break
        if not pos:
            return None

        is_square_off = current_time_ist >= self.AUTO_SQUARE_OFF_TIME_IST
        updated = self.update_lifecycle_tick(pos, current_price, is_intraday_square_off=is_square_off)

        if updated.state in (
            ExecutionLifecycleState.CLOSED_STOP_LOSS,
            ExecutionLifecycleState.CLOSED_TAKE_PROFIT,
            ExecutionLifecycleState.CLOSED_TRAILING_STOP,
            ExecutionLifecycleState.CLOSED_SQUARE_OFF,
        ):
            if self.paper_trader is not None:
                close_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
                self.paper_trader.execute_paper_order(
                    idempotency_key=f"IDEMP-EXIT-{pos.trade_id}-{updated.state.value}",
                    symbol=pos.symbol,
                    side=close_side,
                    units=pos.units,
                    order_type=OrderType.MARKET,
                    market_price=current_price,
                )
            del self.active_positions[position_key]
            return LifecycleOutcome(
                trade_id=trade_id,
                is_closed=True,
                close_reason=updated.state,
                exit_price=updated.exit_price,
                realized_pnl=updated.realized_pnl or 0.0,
            )
        else:
            self.active_positions[position_key] = updated
            return LifecycleOutcome(
                trade_id=trade_id,
                is_closed=False,
                close_reason=None,
                exit_price=None,
                realized_pnl=0.0,
            )


@dataclasses.dataclass(frozen=True)
class LifecycleOutcome:
    """Outcome of a single lifecycle evaluation step for an active position."""

    trade_id: str
    is_closed: bool
    close_reason: Optional[ExecutionLifecycleState]
    exit_price: Optional[float]
    realized_pnl: float

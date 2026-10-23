"""AGI 1.7 Full-Stack Paper Trading Engine Orchestrator & Quantitative Performance Teardown.

TASK-BN-27:
Unifies the complete institutional Indian options research and simulation pipeline:
1. Multi-Agent Dialectical Consensus (TradingAgentsDebateEngine).
2. Microstructure Absorption & Toxicity Filters (OrderFlowImbalanceEngine & StreamingMarketDepthAdapter VPIN).
3. Pre-Trade Risk & SEBI Regulatory Controls (SebiDerivativeRegulatoryEngine, PreTradeRiskEngine, PortfolioKillSwitch).
4. Market Impact & Dynamic Slippage (Almgren-Chriss Square-Root Law).
5. Indian Statutory Charges & Friction Deduction (STT, GST 18%, Exchange Turnover, SEBI Fee, Stamp Duty, Brokerage).
6. Algorithmic Execution Routing & State Machine (UnifiedAlgorithmicExecutionRouter).
7. Monotonic Trailing Stop Ratchets & 15:15 IST Mandatory Auto Square-Off.
8. Quantitative Performance Teardown & Tear-Sheet Generator (QuantitativePerformanceTearSheet).
"""

from __future__ import annotations

import dataclasses
import datetime
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bank_nifty_market import BankNiftyContractSpec
from .bank_nifty_paper_trader import (
    BankNiftyPaperTrader,
    OrderSide,
    OrderType,
)
from .execution_router import (
    ExecutionLifecycleState,
    ExecutionPipelineRequest,
    ExecutionPipelineResult,
    LifecyclePosition,
    UnifiedAlgorithmicExecutionRouter,
)
from .market_depth_streaming import (
    MarketDepthTick,
    StreamingMarketDepthAdapter,
    ToxicityRegime,
)
from .portfolio_risk import PortfolioGreeksRiskEngine
from .pre_trade_risk_killswitch import PortfolioKillSwitch, PreTradeRiskEngine
from .sebi_regulations import SebiDerivativeRegulatoryEngine


@dataclasses.dataclass(frozen=True)
class QuantitativePerformanceTearSheet:
    """Institutional-grade quantitative performance tear-sheet for BANK NIFTY options."""

    session_id: str
    initial_capital_inr: float
    ending_capital_inr: float
    peak_capital_inr: float
    net_profit_loss_inr: float
    return_on_capital_pct: float
    annualized_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    max_drawdown_inr: float
    calmar_ratio: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    avg_trade_pnl_inr: float
    largest_win_inr: float
    largest_loss_inr: float
    total_stt_inr: float
    total_exchange_turnover_inr: float
    total_gst_inr: float
    total_sebi_charges_inr: float
    total_stamp_duty_inr: float
    total_brokerage_inr: float
    total_friction_inr: float
    friction_drag_pct: float
    vpin_halts_count: int
    ofi_rejections_count: int
    rms_rejections_count: int
    trailing_stop_exits_count: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert tear-sheet metrics to JSON-serializable dictionary."""
        return dataclasses.asdict(self)

    def to_markdown(self) -> str:
        """Format metrics as an institutional Markdown tear-sheet table."""
        return f"""# Quantitative Performance Tear-Sheet: {self.session_id}

## 1. Capital & Risk-Adjusted Returns
| Metric | Value |
| :--- | :--- |
| **Initial Capital** | ₹{self.initial_capital_inr:,.2f} |
| **Ending Capital** | ₹{self.ending_capital_inr:,.2f} |
| **Net Realized P&L** | ₹{self.net_profit_loss_inr:,.2f} ({self.return_on_capital_pct:+.2f}%) |
| **Annualized Return** | {self.annualized_return_pct:+.2f}% |
| **Sharpe Ratio (Ann.)** | {self.sharpe_ratio:.2f} |
| **Sortino Ratio (Ann.)** | {self.sortino_ratio:.2f} |
| **Max Drawdown (Peak-to-Trough)** | -{self.max_drawdown_pct:.2f}% (-₹{self.max_drawdown_inr:,.2f}) |
| **Calmar Ratio** | {self.calmar_ratio:.2f} |

## 2. Trade Statistics & Expectancy
| Metric | Value |
| :--- | :--- |
| **Total Closed Trades** | {self.total_trades} |
| **Winning Trades** | {self.winning_trades} ({self.win_rate_pct:.1f}%) |
| **Losing Trades** | {self.losing_trades} |
| **Profit Factor** | {self.profit_factor:.2f} |
| **Average Trade P&L** | ₹{self.avg_trade_pnl_inr:,.2f} |
| **Largest Win** | ₹{self.largest_win_inr:,.2f} |
| **Largest Loss** | ₹{self.largest_loss_inr:,.2f} |

## 3. Indian Statutory Friction & Transaction Costs
| Friction Component | Deducted (INR) |
| :--- | :--- |
| **Securities Transaction Tax (STT)** | ₹{self.total_stt_inr:,.2f} |
| **Exchange Turnover Charges** | ₹{self.total_exchange_turnover_inr:,.2f} |
| **GST (18% on Brokerage & Turnover)** | ₹{self.total_gst_inr:,.2f} |
| **SEBI Turnover Fees** | ₹{self.total_sebi_charges_inr:,.2f} |
| **Stamp Duty** | ₹{self.total_stamp_duty_inr:,.2f} |
| **Flat Brokerage** | ₹{self.total_brokerage_inr:,.2f} |
| **Total Friction Deducted** | **₹{self.total_friction_inr:,.2f}** |
| **Friction Drag Ratio** | {self.friction_drag_pct:.2f}% |

## 4. Microstructure & Pre-Trade Risk Shields
| Risk Guardrail | Event Count |
| :--- | :--- |
| **VPIN Adverse Selection Halts** | {self.vpin_halts_count} |
| **OFI Microstructure Breakout Rejections** | {self.ofi_rejections_count} |
| **Pre-Trade RMS / SEBI Margin Blocks** | {self.rms_rejections_count} |
| **Monotonic Trailing Stop Exits** | {self.trailing_stop_exits_count} |
"""


class PaperTradingOrchestrator:
    """Top-level full-stack orchestrator for Bank Nifty options paper trading."""

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        max_drawdown_pct: float = 0.03,
        vpin_bucket_size: int = 75,
    ) -> None:
        self.initial_capital = initial_capital
        self.paper_trader = BankNiftyPaperTrader(initial_capital=initial_capital)
        self.kill_switch = PortfolioKillSwitch(initial_capital=initial_capital, max_drawdown_pct=max_drawdown_pct)
        self.risk_engine = PreTradeRiskEngine()
        self.depth_adapter = StreamingMarketDepthAdapter(bucket_size_units=vpin_bucket_size)

        self.router = UnifiedAlgorithmicExecutionRouter(
            kill_switch=self.kill_switch,
            risk_engine=self.risk_engine,
            paper_trader=self.paper_trader,
        )

        self.equity_curve: List[Tuple[str, float]] = [("09:15:00", initial_capital)]
        self.closed_trades: List[Dict[str, Any]] = []

        # Filter counters
        self.vpin_halts_count: int = 0
        self.ofi_rejections_count: int = 0
        self.rms_rejections_count: int = 0
        self.trailing_stop_exits_count: int = 0

    def evaluate_tick(
        self,
        *,
        trade_id: str,
        spot_price: float,
        vwap: float,
        ema20: float,
        iv: float,
        call_oi_change_pct: float,
        put_oi_change_pct: float,
        depth_tick: Optional[MarketDepthTick] = None,
        quoted_bid: float = 400.0,
        quoted_ask: float = 400.5,
        current_time_ist: str = "10:30:00",
        order_lots: int = 1,
    ) -> Dict[str, Any]:
        """Processes a single chronological market event across the complete end-to-end pipeline."""
        # 1. Update Market Depth & Check VPIN Adverse Selection
        vpin_safe = True
        if depth_tick is not None:
            metrics = self.depth_adapter.on_depth_tick(depth_tick)
            if not metrics.is_safe_for_writing:
                vpin_safe = False
                self.vpin_halts_count += 1

        # 2. Check and advance active position lifecycles (Trailing Stops / Take Profit / 15:15 IST Square-Off)
        for active_id, pos in list(self.router.active_positions.items()):
            est_opt_price = quoted_ask if pos.side == OrderSide.BUY else quoted_bid
            outcome = self.router.evaluate_position_lifecycle(
                trade_id=active_id,
                current_price=est_opt_price,
                current_time_ist=current_time_ist,
            )
            if outcome.is_closed:
                if outcome.close_reason == ExecutionLifecycleState.CLOSED_TRAILING_STOP:
                    self.trailing_stop_exits_count += 1
                self.closed_trades.append({
                    "trade_id": active_id,
                    "symbol": pos.symbol,
                    "side": pos.side.value,
                    "entry_price": pos.entry_price,
                    "exit_price": outcome.exit_price,
                    "realized_pnl": outcome.realized_pnl,
                    "close_reason": outcome.close_reason.value if outcome.close_reason else "CLOSED",
                })

        # 3. If VPIN indicates extreme adverse selection, halt new trade entry
        if not vpin_safe:
            curr_equity = self._calculate_current_equity(spot_price)
            self.equity_curve.append((current_time_ist, curr_equity))
            return {
                "trade_id": trade_id,
                "status": "HALTED_BY_VPIN",
                "reason": "Volume-Synchronized Probability of Toxicity exceeds threshold (adverse selection guardrail)",
                "current_equity": curr_equity,
            }

        # 4. Mandatory 15:15 IST Cutoff: Halt all new trade initiations
        if current_time_ist >= "15:15:00":
            curr_equity = self._calculate_current_equity(spot_price)
            self.equity_curve.append((current_time_ist, curr_equity))
            return {
                "trade_id": trade_id,
                "status": "SESSION_CLOSED_FOR_ENTRY",
                "is_executed": False,
                "rejection_reason": "Intraday session past 15:15 IST auto square-off cutoff",
                "current_equity": curr_equity,
            }

        # 5. If an active position is already open, do not initiate another position
        if len(self.router.active_positions) >= 1:
            curr_equity = self._calculate_current_equity(spot_price)
            self.equity_curve.append((current_time_ist, curr_equity))
            return {
                "trade_id": trade_id,
                "status": "POSITION_HELD",
                "is_executed": False,
                "rejection_reason": "Active position already open for strategy management",
                "current_equity": curr_equity,
            }

        # 6. Route new trade opportunity through dialectical debate, RMS, slippage, and execution
        req = ExecutionPipelineRequest(
            trade_id=trade_id,
            spot_price=spot_price,
            vwap=vwap,
            ema20=ema20,
            iv=iv,
            call_oi_change_pct=call_oi_change_pct,
            put_oi_change_pct=put_oi_change_pct,
            account_equity=self.kill_switch.current_equity,
            account_drawdown_pct=self.kill_switch.current_drawdown_pct,
            quoted_bid=quoted_bid,
            quoted_ask=quoted_ask,
            order_lots=order_lots,
        )

        res: ExecutionPipelineResult = self.router.route_and_execute(req)

        # Categorize rejections
        if res.final_state == ExecutionLifecycleState.REJECTED_OFI_CONTRADICTION:
            self.ofi_rejections_count += 1
        elif res.final_state == ExecutionLifecycleState.REJECTED_RMS_RISK:
            self.rms_rejections_count += 1

        curr_equity = self._calculate_current_equity(spot_price)
        self.equity_curve.append((current_time_ist, curr_equity))

        return {
            "trade_id": trade_id,
            "status": res.final_state.value,
            "is_executed": res.is_executed,
            "rejection_reason": res.rejection_reason,
            "current_equity": curr_equity,
        }

    def _calculate_current_equity(self, current_spot: float) -> float:
        """Computes instantaneous mark-to-market portfolio equity."""
        cash = self.paper_trader.cash
        pos_pnl = 0.0
        for active_pos in self.router.active_positions.values():
            pos_pnl += active_pos.unrealized_pnl
        return round(cash + pos_pnl, 2)

    def generate_tear_sheet(self, session_id: str = "SESSION-BN-WALKFORWARD") -> QuantitativePerformanceTearSheet:
        """Computes comprehensive quantitative performance statistics and builds tear-sheet."""
        ending_equity = self.equity_curve[-1][1] if self.equity_curve else self.initial_capital
        net_pnl = round(ending_equity - self.initial_capital, 2)
        roc_pct = round((net_pnl / self.initial_capital) * 100.0, 2)

        # Annualized return assuming 252 trading days (or 1-day equivalent scaled)
        annualized_return = round(roc_pct * 252.0, 2)

        # High Water Mark & Drawdowns
        hwm = self.initial_capital
        max_dd_inr = 0.0
        max_dd_pct = 0.0
        peak_equity = self.initial_capital

        for _, eq in self.equity_curve:
            if eq > hwm:
                hwm = eq
            if eq > peak_equity:
                peak_equity = eq
            dd_inr = hwm - eq
            dd_pct = (dd_inr / hwm) * 100.0 if hwm > 0 else 0.0
            if dd_inr > max_dd_inr:
                max_dd_inr = dd_inr
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        # Returns series for Sharpe / Sortino
        returns: List[float] = []
        for i in range(1, len(self.equity_curve)):
            prev_eq = self.equity_curve[i - 1][1]
            curr_eq = self.equity_curve[i][1]
            if prev_eq > 0:
                returns.append((curr_eq - prev_eq) / prev_eq)

        if returns:
            mean_r = sum(returns) / len(returns)
            variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            std_r = math.sqrt(variance) if variance > 0 else 0.0001
            sharpe = round((mean_r / std_r) * math.sqrt(252), 2)

            downside_variance = sum(min(0.0, r) ** 2 for r in returns) / len(returns)
            downside_std = math.sqrt(downside_variance) if downside_variance > 0 else 0.0001
            sortino = round((mean_r / downside_std) * math.sqrt(252), 2)
        else:
            sharpe = 0.0
            sortino = 0.0

        calmar = round(annualized_return / max_dd_pct, 2) if max_dd_pct > 0 else 99.0

        # Trade metrics
        total_trades = len(self.closed_trades)
        wins = [t for t in self.closed_trades if t["realized_pnl"] > 0]
        losses = [t for t in self.closed_trades if t["realized_pnl"] < 0]

        win_rate = round((len(wins) / total_trades) * 100.0, 1) if total_trades > 0 else 0.0
        gross_profit = sum(t["realized_pnl"] for t in wins)
        gross_loss = abs(sum(t["realized_pnl"] for t in losses))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        avg_trade_pnl = round(net_pnl / total_trades, 2) if total_trades > 0 else 0.0
        largest_win = round(max((t["realized_pnl"] for t in wins), default=0.0), 2)
        largest_loss = round(min((t["realized_pnl"] for t in losses), default=0.0), 2)

        # Statutory friction extraction from paper trader
        stt = 0.0
        turnover = 0.0
        gst = 0.0
        sebi = 0.0
        stamp = 0.0
        brokerage = 0.0

        for trade in self.paper_trader.executed_trades:
            chg = trade.charges_breakdown
            stt += chg.get("stt", 0.0)
            turnover += chg.get("exchange_turnover", 0.0)
            gst += chg.get("gst", 0.0)
            sebi += chg.get("sebi_charges", 0.0)
            stamp += chg.get("stamp_duty", 0.0)
            brokerage += chg.get("brokerage", 0.0)

        total_friction = round(stt + turnover + gst + sebi + stamp + brokerage, 2)
        friction_drag = round((total_friction / gross_profit) * 100.0, 2) if gross_profit > 0 else 0.0

        return QuantitativePerformanceTearSheet(
            session_id=session_id,
            initial_capital_inr=self.initial_capital,
            ending_capital_inr=ending_equity,
            peak_capital_inr=round(peak_equity, 2),
            net_profit_loss_inr=net_pnl,
            return_on_capital_pct=roc_pct,
            annualized_return_pct=annualized_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown_pct=round(max_dd_pct, 2),
            max_drawdown_inr=round(max_dd_inr, 2),
            calmar_ratio=calmar,
            total_trades=total_trades,
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate_pct=win_rate,
            profit_factor=profit_factor,
            avg_trade_pnl_inr=avg_trade_pnl,
            largest_win_inr=largest_win,
            largest_loss_inr=largest_loss,
            total_stt_inr=round(stt, 2),
            total_exchange_turnover_inr=round(turnover, 2),
            total_gst_inr=round(gst, 2),
            total_sebi_charges_inr=round(sebi, 2),
            total_stamp_duty_inr=round(stamp, 2),
            total_brokerage_inr=round(brokerage, 2),
            total_friction_inr=total_friction,
            friction_drag_pct=friction_drag,
            vpin_halts_count=self.vpin_halts_count,
            ofi_rejections_count=self.ofi_rejections_count,
            rms_rejections_count=self.rms_rejections_count,
            trailing_stop_exits_count=self.trailing_stop_exits_count,
        )

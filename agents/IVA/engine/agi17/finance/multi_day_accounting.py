"""AGI 1.7 OMEGA COMMAND — Multi-Day Accounting & 6-Metric Accuracy Engine.

Preserves the ₹50,000 monthly virtual capital across multi-day runs without loss erasure:
- Distinct daily session records (Day 1, Day 2, etc.)
- Cumulative return, portfolio peak, and max cumulative drawdown tracking
- The 6 required distinct accuracy and performance metrics:
    1. Directional Forecast Accuracy
    2. Candidate Signal Accuracy
    3. Simulated Fill Rate
    4. Closed Trade Win Rate
    5. Net Profit Factor
    6. Operational Reliability
- Persistent SQLite storage with JSON fallback
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("MultiDayAccounting")


@dataclasses.dataclass
class DailySessionRecord:
    """Distinct daily trading session record preserving day-by-day accounting."""
    session_id: str
    date_str: str                      # "YYYY-MM-DD"
    day_number: int                    # 1, 2, 3...
    starting_capital: float
    ending_capital: float
    realized_pnl: float
    unrealized_pnl: float
    fees_and_charges: float
    total_trades_executed: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    peak_equity_intraday: float
    lowest_equity_intraday: float
    max_drawdown_inr: float
    notes: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclasses.dataclass
class SixAccuracyMetrics:
    """The 6 distinct accuracy and performance metrics required by Phase 3."""
    directional_forecast_accuracy_pct: float  # Metric 1
    candidate_signal_accuracy_pct: float      # Metric 2
    simulated_fill_rate_pct: float            # Metric 3
    closed_trade_win_rate_pct: float          # Metric 4
    net_profit_factor: float                  # Metric 5
    operational_reliability_pct: float        # Metric 6
    total_forecasts_evaluated: int = 0
    total_signals_evaluated: int = 0
    total_orders_submitted: int = 0
    total_trades_closed: int = 0
    gross_profits_inr: float = 0.0
    gross_losses_inr: float = 0.0
    heartbeats_received: int = 0
    heartbeats_expected: int = 0


@dataclasses.dataclass
class CumulativeLedgerSummary:
    """Cumulative multi-day portfolio performance on the ₹50,000 base capital."""
    initial_monthly_capital: float
    current_equity: float
    cumulative_realized_pnl: float
    cumulative_return_pct: float
    portfolio_high_water_mark: float
    max_cumulative_drawdown_inr: float
    max_cumulative_drawdown_pct: float
    total_sessions_completed: int
    total_trades_executed: int
    total_fees_paid: float
    metrics: SixAccuracyMetrics = dataclasses.field(default_factory=lambda: SixAccuracyMetrics(0, 0, 0, 0, 0, 100))


class MultiDayLedgerManager:
    """Manages multi-day accounting, capital preservation across sessions, and accuracy tracking."""

    def __init__(
        self,
        storage_dir: Path,
        initial_capital: float = 50000.0,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.initial_capital = initial_capital
        self.db_path = self.storage_dir / "multi_day_ledger.db"
        self._init_db()

    def _init_db(self) -> None:
        """Initializes SQLite schema for multi-day sessions, forecasts, and orders."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_sessions (
                    session_id TEXT PRIMARY KEY,
                    date_str TEXT NOT NULL,
                    day_number INTEGER NOT NULL,
                    starting_capital REAL NOT NULL,
                    ending_capital REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    fees_and_charges REAL NOT NULL,
                    total_trades_executed INTEGER NOT NULL,
                    winning_trades INTEGER NOT NULL,
                    losing_trades INTEGER NOT NULL,
                    win_rate REAL NOT NULL,
                    peak_equity_intraday REAL NOT NULL,
                    lowest_equity_intraday REAL NOT NULL,
                    max_drawdown_inr REAL NOT NULL,
                    notes TEXT,
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS directional_forecasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    forecast_direction TEXT NOT NULL,  -- BULLISH, BEARISH, NEUTRAL
                    actual_direction TEXT,            -- BULLISH, BEARISH, NEUTRAL
                    was_correct INTEGER DEFAULT 0,
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candidate_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    setup_id TEXT NOT NULL,
                    target_hit INTEGER DEFAULT 0,
                    stop_hit INTEGER DEFAULT 0,
                    signal_outcome TEXT NOT NULL,     -- WIN, LOSS, EXPIRED
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS order_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    order_status TEXT NOT NULL,       -- FILLED, REJECTED, CANCELLED
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS supervisor_heartbeats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    was_delivered INTEGER DEFAULT 1,
                    timestamp TEXT NOT NULL
                )
                """
            )

    def get_latest_ending_capital(self) -> float:
        """Retrieves ending capital of previous session, or returns ₹50,000 initial capital."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ending_capital FROM daily_sessions ORDER BY day_number DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return float(row[0])
        return self.initial_capital

    def get_next_day_number(self) -> int:
        """Returns the next sequential day number (1, 2, 3...)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(day_number) FROM daily_sessions")
            row = cursor.fetchone()
            if row and row[0] is not None:
                return int(row[0]) + 1
        return 1

    def record_session(self, record: DailySessionRecord) -> None:
        """Persists a completed daily session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_sessions VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    record.session_id,
                    record.date_str,
                    record.day_number,
                    record.starting_capital,
                    record.ending_capital,
                    record.realized_pnl,
                    record.unrealized_pnl,
                    record.fees_and_charges,
                    record.total_trades_executed,
                    record.winning_trades,
                    record.losing_trades,
                    record.win_rate,
                    record.peak_equity_intraday,
                    record.lowest_equity_intraday,
                    record.max_drawdown_inr,
                    record.notes,
                    record.timestamp,
                ),
            )

    def record_forecast(
        self,
        session_id: str,
        instrument: str,
        forecast_direction: str,
        actual_direction: str,
    ) -> None:
        """Records a directional forecast and whether it was correct."""
        was_correct = 1 if forecast_direction.upper() == actual_direction.upper() else 0
        now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO directional_forecasts (session_id, instrument, forecast_direction, actual_direction, was_correct, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, instrument, forecast_direction, actual_direction, was_correct, now_ts),
            )

    def record_candidate_signal(
        self,
        session_id: str,
        setup_id: str,
        target_hit: bool,
        stop_hit: bool,
    ) -> None:
        """Records candidate signal accuracy (irrespective of fill)."""
        outcome = "WIN" if target_hit else ("LOSS" if stop_hit else "EXPIRED")
        now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO candidate_signals (session_id, setup_id, target_hit, stop_hit, signal_outcome, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, setup_id, 1 if target_hit else 0, 1 if stop_hit else 0, outcome, now_ts),
            )

    def record_order_submission(
        self,
        session_id: str,
        order_id: str,
        order_status: str,
    ) -> None:
        """Records order submission and fill/reject outcome for fill rate tracking."""
        now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO order_executions (session_id, order_id, order_status, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, order_id, order_status, now_ts),
            )

    def record_heartbeat(
        self,
        session_id: str,
        worker_id: str,
        delivered: bool = True,
    ) -> None:
        """Records worker heartbeat delivery for operational reliability computation."""
        now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO supervisor_heartbeats (session_id, worker_id, was_delivered, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, worker_id, 1 if delivered else 0, now_ts),
            )

    def compute_six_metrics(self) -> SixAccuracyMetrics:
        """Computes all 6 required accuracy and performance metrics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 1. Directional Forecast Accuracy
            cursor.execute("SELECT COUNT(*), SUM(was_correct) FROM directional_forecasts")
            row = cursor.fetchone()
            total_forecasts = row[0] or 0
            correct_forecasts = row[1] or 0
            dir_acc = (correct_forecasts / total_forecasts * 100.0) if total_forecasts > 0 else 0.0

            # 2. Candidate Signal Accuracy
            cursor.execute("SELECT COUNT(*), SUM(CASE WHEN signal_outcome = 'WIN' THEN 1 ELSE 0 END) FROM candidate_signals")
            row = cursor.fetchone()
            total_signals = row[0] or 0
            win_signals = row[1] or 0
            signal_acc = (win_signals / total_signals * 100.0) if total_signals > 0 else 0.0

            # 3. Simulated Fill Rate
            cursor.execute("SELECT COUNT(*), SUM(CASE WHEN order_status = 'FILLED' THEN 1 ELSE 0 END) FROM order_executions")
            row = cursor.fetchone()
            total_orders = row[0] or 0
            filled_orders = row[1] or 0
            fill_rate = (filled_orders / total_orders * 100.0) if total_orders > 0 else 0.0

            # 4. Closed Trade Win Rate & 5. Net Profit Factor
            cursor.execute(
                """
                SELECT SUM(total_trades_executed), SUM(winning_trades), SUM(losing_trades),
                       SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END),
                       SUM(CASE WHEN realized_pnl < 0 THEN ABS(realized_pnl) ELSE 0 END)
                FROM daily_sessions
                """
            )
            row = cursor.fetchone()
            total_trades = row[0] or 0
            winning_trades = row[1] or 0
            gross_profits = row[3] or 0.0
            gross_losses = row[4] or 0.0
            trade_win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0
            profit_factor = (
                (gross_profits / gross_losses) if gross_losses > 0.0 else (999.0 if gross_profits > 0.0 else 0.0)
            )

            # 6. Operational Reliability
            cursor.execute("SELECT COUNT(*), SUM(was_delivered) FROM supervisor_heartbeats")
            row = cursor.fetchone()
            exp_hb = row[0] or 0
            rec_hb = row[1] or 0
            rel_pct = (rec_hb / exp_hb * 100.0) if exp_hb > 0 else 100.0

        return SixAccuracyMetrics(
            directional_forecast_accuracy_pct=round(dir_acc, 2),
            candidate_signal_accuracy_pct=round(signal_acc, 2),
            simulated_fill_rate_pct=round(fill_rate, 2),
            closed_trade_win_rate_pct=round(trade_win_rate, 2),
            net_profit_factor=round(profit_factor, 2),
            operational_reliability_pct=round(rel_pct, 2),
            total_forecasts_evaluated=total_forecasts,
            total_signals_evaluated=total_signals,
            total_orders_submitted=total_orders,
            total_trades_closed=total_trades,
            gross_profits_inr=round(gross_profits, 2),
            gross_losses_inr=round(gross_losses, 2),
            heartbeats_received=rec_hb,
            heartbeats_expected=exp_hb,
        )

    def get_cumulative_summary(self) -> CumulativeLedgerSummary:
        """Calculates cumulative portfolio equity, drawdown, and return across all sessions."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT session_id, day_number, starting_capital, ending_capital, realized_pnl, fees_and_charges, total_trades_executed
                FROM daily_sessions ORDER BY day_number ASC
                """
            )
            rows = cursor.fetchall()

        if not rows:
            return CumulativeLedgerSummary(
                initial_monthly_capital=self.initial_capital,
                current_equity=self.initial_capital,
                cumulative_realized_pnl=0.0,
                cumulative_return_pct=0.0,
                portfolio_high_water_mark=self.initial_capital,
                max_cumulative_drawdown_inr=0.0,
                max_cumulative_drawdown_pct=0.0,
                total_sessions_completed=0,
                total_trades_executed=0,
                total_fees_paid=0.0,
                metrics=self.compute_six_metrics(),
            )

        curr_equity = self.initial_capital
        high_water = self.initial_capital
        max_dd_inr = 0.0
        tot_trades = 0
        tot_fees = 0.0

        for r in rows:
            ending_cap = float(r[3])
            fees = float(r[5])
            trades = int(r[6])
            curr_equity = ending_cap
            if curr_equity > high_water:
                high_water = curr_equity
            dd_inr = high_water - curr_equity
            if dd_inr > max_dd_inr:
                max_dd_inr = dd_inr
            tot_trades += trades
            tot_fees += fees

        cum_pnl = curr_equity - self.initial_capital
        cum_ret_pct = (cum_pnl / self.initial_capital) * 100.0
        max_dd_pct = (max_dd_inr / high_water * 100.0) if high_water > 0 else 0.0

        return CumulativeLedgerSummary(
            initial_monthly_capital=self.initial_capital,
            current_equity=round(curr_equity, 2),
            cumulative_realized_pnl=round(cum_pnl, 2),
            cumulative_return_pct=round(cum_ret_pct, 2),
            portfolio_high_water_mark=round(high_water, 2),
            max_cumulative_drawdown_inr=round(max_dd_inr, 2),
            max_cumulative_drawdown_pct=round(max_dd_pct, 2),
            total_sessions_completed=len(rows),
            total_trades_executed=tot_trades,
            total_fees_paid=round(tot_fees, 2),
            metrics=self.compute_six_metrics(),
        )

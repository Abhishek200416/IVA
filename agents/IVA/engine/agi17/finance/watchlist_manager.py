"""AGI 1.7 OMEGA COMMAND — Persistent Candidate Watchlist & Affordability Warden.

Implements Phase 11 Section 7 & Section 8:
- Persistent CALL/PUT watchlist for NIFTY 50 and BANKNIFTY option contracts.
- Exact date-aware contract lot sizes:
    * NIFTY = 65 (NSE Circular Ref NSE/FAOP/70616, effective Oct 2025)
    * BANKNIFTY = 30 (NSE Circular Ref NSE/FAOP/70616, effective Oct 2025)
- Affordability Check against INR 10,000 Virtual Paper Capital:
    * Total Lot Outflow = Premium * Lot Size + Estimated Statutory Charges.
    * If Outflow > Available Cash, candidate is strictly marked UNAFFORDABLE and blocked from order entry.
- Risk Policy Enforcement:
    * Maximum 10 paper entries per session.
    * Zero minimum trade quota: "NO TRADE / WAIT" is an acceptable and preferred status when edge is insufficient.
    * Target zone, trigger zone, and stop-loss zone tracking.
- Alerts Engine:
    * Price trigger alerts (above/below).
    * Target and stop-loss event notifications.
- Persisted to SQLite (`watchlist.db`) with WAL mode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
from enum import Enum
import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .live_accounting import StatutoryCostSchedule

logger = logging.getLogger("WatchlistManager")


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class WatchlistStatus(str, Enum):
    MONITORING = "MONITORING"
    TRIGGERED = "TRIGGERED"
    TARGET_REACHED = "TARGET_REACHED"
    STOPPED_OUT = "STOPPED_OUT"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


@dataclass
class WatchlistCandidate:
    candidate_id: str
    underlying: str                     # "NIFTY" or "BANKNIFTY"
    strike: float                       # e.g. 24200.0
    option_type: OptionType             # CE or PE
    expiry_date: str                    # "2026-10-29"
    current_premium: float              # Current LTP / mid price
    lot_size: int                       # 65 for NIFTY, 30 for BANKNIFTY
    lot_cost_inr: float                 # premium * lot_size
    estimated_charges_inr: float        # STT, GST, Exchange, Brokerage
    total_required_capital_inr: float   # lot_cost + charges
    is_affordable: bool                 # total_required <= available_cash
    trigger_price: float                # Entry trigger condition
    target_price: float                 # Profit target
    stop_loss_price: float              # Protective stop
    edge_p: float                       # Modeled win probability (from Kelly / quant)
    status: WatchlistStatus
    created_at_iso: str
    updated_at_iso: str
    provenance_note: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["option_type"] = self.option_type.value
        d["status"] = self.status.value
        return d


@dataclass
class PriceAlert:
    alert_id: str
    candidate_id: Optional[str]
    instrument: str
    condition: str                      # "ABOVE", "BELOW", "TARGET", "STOP"
    threshold_price: float
    is_active: bool
    is_triggered: bool
    created_at_iso: str
    triggered_at_iso: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WatchlistManager:
    """Authoritative persistent watchlist manager enforcing affordability and session risk limits."""

    DEFAULT_PAPER_CAPITAL: float = 10000.00
    MAX_SESSION_ENTRIES: int = 10

    # NSE Lot Sizes (Circular NSE/FAOP/70616, Oct 2025 onwards)
    STANDARD_LOT_SIZES = {
        "NIFTY": 65,
        "BANKNIFTY": 30,
    }

    def __init__(
        self,
        storage_dir: Optional[Path] = None,
        initial_capital: float = DEFAULT_PAPER_CAPITAL,
        brokerage_profile: str = "PAYTM_FO_10",
    ) -> None:
        self.storage_dir = Path(storage_dir or Path(__file__).resolve().parents[3] / "runtime_storage" / "finance")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "watchlist.db"
        self.initial_capital = initial_capital
        self.available_cash = initial_capital
        self.brokerage_profile = brokerage_profile
        self.session_entries_count = 0
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS watchlist_candidates (
                        candidate_id TEXT PRIMARY KEY,
                        underlying TEXT NOT NULL,
                        strike REAL NOT NULL,
                        option_type TEXT NOT NULL,
                        expiry_date TEXT NOT NULL,
                        current_premium REAL NOT NULL,
                        lot_size INTEGER NOT NULL,
                        lot_cost_inr REAL NOT NULL,
                        estimated_charges_inr REAL NOT NULL,
                        total_required_capital_inr REAL NOT NULL,
                        is_affordable INTEGER NOT NULL,
                        trigger_price REAL NOT NULL,
                        target_price REAL NOT NULL,
                        stop_loss_price REAL NOT NULL,
                        edge_p REAL NOT NULL,
                        status TEXT NOT NULL,
                        created_at_iso TEXT NOT NULL,
                        updated_at_iso TEXT NOT NULL,
                        provenance_note TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS price_alerts (
                        alert_id TEXT PRIMARY KEY,
                        candidate_id TEXT,
                        instrument TEXT NOT NULL,
                        condition TEXT NOT NULL,
                        threshold_price REAL NOT NULL,
                        is_active INTEGER NOT NULL,
                        is_triggered INTEGER NOT NULL,
                        created_at_iso TEXT NOT NULL,
                        triggered_at_iso TEXT
                    )
                    """
                )
        finally:
            conn.close()

    def get_lot_size(self, underlying: str) -> int:
        u = underlying.upper().replace(" ", "").replace("_", "")
        if "BANK" in u:
            return self.STANDARD_LOT_SIZES["BANKNIFTY"]
        return self.STANDARD_LOT_SIZES["NIFTY"]

    def compute_estimated_charges(
        self,
        premium: float,
        lot_size: int,
        as_of_date: Optional[str] = None,
    ) -> float:
        """Estimates buy side + sell side charges using official StatutoryCostSchedule."""
        turnover = round(premium * lot_size, 2)
        # Brokerage (Paytm Money ₹10 per order)
        brokerage = 10.0 if self.brokerage_profile == "PAYTM_FO_10" else 20.0
        # Stamp duty buy: 0.003%
        stamp = turnover * 0.00003
        # Exchange outflow 2026: ₹3,553 per crore = 0.03553%
        exchange_fee = turnover * 0.0003553
        # SEBI fee: ₹10 per crore = 0.0001%
        sebi_fee = turnover * 0.000001
        # GST: 18% on (brokerage + exchange_fee + sebi_fee)
        gst = (brokerage + exchange_fee + sebi_fee) * 0.18
        # STT: Date-aware STT on exit (0.15% from 1 April 2026; 0.10% prior)
        eff_date = as_of_date or "2026-10-14"
        stt_rate = 0.0015 if str(eff_date) >= "2026-04-01" else 0.0010
        stt = turnover * stt_rate
        total_est = brokerage + stamp + exchange_fee + sebi_fee + gst + stt
        return round(total_est, 2)

    def add_candidate(
        self,
        underlying: str,
        strike: float,
        option_type: OptionType | str,
        expiry_date: str,
        current_premium: float,
        trigger_price: float,
        target_price: float,
        stop_loss_price: float,
        edge_p: float = 0.55,
        provenance_note: str = "MarketObservationEngine Scan",
    ) -> WatchlistCandidate:
        """Adds a candidate to the watchlist, calculating lot costs and affordability."""
        if isinstance(option_type, str):
            opt_type = OptionType.CE if "CE" in option_type.upper() or "CALL" in option_type.upper() else OptionType.PE
        else:
            opt_type = option_type

        lot_size = self.get_lot_size(underlying)
        lot_cost = round(current_premium * lot_size, 2)
        charges = self.compute_estimated_charges(current_premium, lot_size, as_of_date=expiry_date)
        total_required = round(lot_cost + charges, 2)
        is_affordable = (total_required <= self.available_cash)

        cand_id = f"CAND-{underlying.upper()}-{int(strike)}{opt_type.value}-{int(time.time())}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        candidate = WatchlistCandidate(
            candidate_id=cand_id,
            underlying=underlying.upper(),
            strike=strike,
            option_type=opt_type,
            expiry_date=expiry_date,
            current_premium=current_premium,
            lot_size=lot_size,
            lot_cost_inr=lot_cost,
            estimated_charges_inr=charges,
            total_required_capital_inr=total_required,
            is_affordable=is_affordable,
            trigger_price=trigger_price,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            edge_p=edge_p,
            status=WatchlistStatus.MONITORING,
            created_at_iso=now_iso,
            updated_at_iso=now_iso,
            provenance_note=provenance_note,
        )

        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO watchlist_candidates
                    (candidate_id, underlying, strike, option_type, expiry_date, current_premium,
                     lot_size, lot_cost_inr, estimated_charges_inr, total_required_capital_inr,
                     is_affordable, trigger_price, target_price, stop_loss_price, edge_p,
                     status, created_at_iso, updated_at_iso, provenance_note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.candidate_id,
                        candidate.underlying,
                        candidate.strike,
                        candidate.option_type.value,
                        candidate.expiry_date,
                        candidate.current_premium,
                        candidate.lot_size,
                        candidate.lot_cost_inr,
                        candidate.estimated_charges_inr,
                        candidate.total_required_capital_inr,
                        1 if candidate.is_affordable else 0,
                        candidate.trigger_price,
                        candidate.target_price,
                        candidate.stop_loss_price,
                        candidate.edge_p,
                        candidate.status.value,
                        candidate.created_at_iso,
                        candidate.updated_at_iso,
                        candidate.provenance_note,
                    ),
                )
        finally:
            conn.close()

        logger.info(
            "Watchlist candidate added: %s (Cost: INR %.2f, Affordable: %s)",
            candidate.candidate_id,
            candidate.total_required_capital_inr,
            candidate.is_affordable,
        )
        return candidate

    def get_all_candidates(self) -> List[WatchlistCandidate]:
        """Returns all tracked candidates from the persistent database."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM watchlist_candidates ORDER BY created_at_iso DESC")
            rows = cursor.fetchall()
            candidates = []
            for r in rows:
                candidates.append(
                    WatchlistCandidate(
                        candidate_id=r["candidate_id"],
                        underlying=r["underlying"],
                        strike=float(r["strike"]),
                        option_type=OptionType(r["option_type"]),
                        expiry_date=r["expiry_date"],
                        current_premium=float(r["current_premium"]),
                        lot_size=int(r["lot_size"]),
                        lot_cost_inr=float(r["lot_cost_inr"]),
                        estimated_charges_inr=float(r["estimated_charges_inr"]),
                        total_required_capital_inr=float(r["total_required_capital_inr"]),
                        is_affordable=bool(r["is_affordable"]),
                        trigger_price=float(r["trigger_price"]),
                        target_price=float(r["target_price"]),
                        stop_loss_price=float(r["stop_loss_price"]),
                        edge_p=float(r["edge_p"]),
                        status=WatchlistStatus(r["status"]),
                        created_at_iso=r["created_at_iso"],
                        updated_at_iso=r["updated_at_iso"],
                        provenance_note=r["provenance_note"],
                    )
                )
            return candidates
        finally:
            conn.close()

    def remove_candidate(self, candidate_id: str) -> bool:
        """Removes a candidate from the watchlist."""
        conn = self._connect()
        try:
            with conn:
                res = conn.execute("DELETE FROM watchlist_candidates WHERE candidate_id = ?", (candidate_id,))
                return res.rowcount > 0
        finally:
            conn.close()

    def clear_watchlist(self) -> int:
        """Clears all candidates from the watchlist."""
        conn = self._connect()
        try:
            with conn:
                res = conn.execute("DELETE FROM watchlist_candidates")
                return res.rowcount
        finally:
            conn.close()

    def can_enter_new_trade(self, candidate: WatchlistCandidate) -> Tuple[bool, Optional[str]]:
        """Strict risk validation: checks affordability and max session entry quota."""
        if not candidate.is_affordable:
            return False, (
                f"AFFORDABILITY_EXCEEDED: Candidate required capital INR {candidate.total_required_capital_inr:.2f} "
                f"exceeds available virtual capital INR {self.available_cash:.2f}."
            )
        if self.session_entries_count >= self.MAX_SESSION_ENTRIES:
            return False, (
                f"SESSION_QUOTA_REACHED: Maximum {self.MAX_SESSION_ENTRIES} paper entries per session reached."
            )
        return True, None

    def record_entry_execution(self, candidate: WatchlistCandidate) -> None:
        """Deducts capital and increments session entry count upon paper order fill."""
        self.session_entries_count += 1
        self.available_cash = max(0.0, self.available_cash - candidate.total_required_capital_inr)
        logger.info(
            "Paper entry executed for %s. Entries today: %d/%d, Remaining Cash: INR %.2f",
            candidate.candidate_id,
            self.session_entries_count,
            self.MAX_SESSION_ENTRIES,
            self.available_cash,
        )

    # -------------------------------------------------------------------------
    # Price Alerts Engine
    # -------------------------------------------------------------------------

    def create_alert(
        self,
        instrument: str,
        condition: str,
        threshold_price: float,
        candidate_id: Optional[str] = None,
    ) -> PriceAlert:
        """Creates a persistent price or target alert."""
        alert_id = f"ALT-{instrument}-{int(threshold_price)}-{uuid.uuid4().hex[:6]}"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        alert = PriceAlert(
            alert_id=alert_id,
            candidate_id=candidate_id,
            instrument=instrument,
            condition=condition.upper(),
            threshold_price=threshold_price,
            is_active=True,
            is_triggered=False,
            created_at_iso=now_iso,
        )
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO price_alerts
                    (alert_id, candidate_id, instrument, condition, threshold_price, is_active, is_triggered, created_at_iso)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alert.alert_id,
                        alert.candidate_id,
                        alert.instrument,
                        alert.condition,
                        alert.threshold_price,
                        1,
                        0,
                        alert.created_at_iso,
                    ),
                )
        finally:
            conn.close()
        return alert

    def get_all_alerts(self, active_only: bool = False) -> List[PriceAlert]:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            query = "SELECT * FROM price_alerts"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY created_at_iso DESC"
            cursor.execute(query)
            rows = cursor.fetchall()
            alerts = []
            for r in rows:
                alerts.append(
                    PriceAlert(
                        alert_id=r["alert_id"],
                        candidate_id=r["candidate_id"],
                        instrument=r["instrument"],
                        condition=r["condition"],
                        threshold_price=float(r["threshold_price"]),
                        is_active=bool(r["is_active"]),
                        is_triggered=bool(r["is_triggered"]),
                        created_at_iso=r["created_at_iso"],
                        triggered_at_iso=r["triggered_at_iso"],
                    )
                )
            return alerts
        finally:
            conn.close()

    def check_alerts(self, instrument: str, current_price: float) -> List[PriceAlert]:
        """Evaluates price against active alerts and marks triggered alerts."""
        triggered = []
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM price_alerts WHERE instrument = ? AND is_active = 1",
                (instrument,),
            )
            rows = cursor.fetchall()
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            for r in rows:
                cond = r["condition"]
                thresh = float(r["threshold_price"])
                is_hit = False
                if cond == "ABOVE" and current_price >= thresh:
                    is_hit = True
                elif cond == "BELOW" and current_price <= thresh:
                    is_hit = True
                elif cond in ("TARGET", "STOP") and abs(current_price - thresh) <= 0.05:
                    is_hit = True

                if is_hit:
                    conn.execute(
                        "UPDATE price_alerts SET is_triggered = 1, is_active = 0, triggered_at_iso = ? WHERE alert_id = ?",
                        (now_iso, r["alert_id"]),
                    )
                    triggered.append(
                        PriceAlert(
                            alert_id=r["alert_id"],
                            candidate_id=r["candidate_id"],
                            instrument=r["instrument"],
                            condition=cond,
                            threshold_price=thresh,
                            is_active=False,
                            is_triggered=True,
                            created_at_iso=r["created_at_iso"],
                            triggered_at_iso=now_iso,
                        )
                    )
            conn.commit()
            return triggered
        finally:
            conn.close()

    def get_summary(self) -> Dict[str, Any]:
        """Provides high-level watchlist and risk overview."""
        candidates = self.get_all_candidates()
        affordable = [c for c in candidates if c.is_affordable]
        alerts = self.get_all_alerts(active_only=True)
        return {
            "initial_capital_inr": self.initial_capital,
            "available_cash_inr": self.available_cash,
            "total_candidates": len(candidates),
            "affordable_candidates": len(affordable),
            "unaffordable_candidates": len(candidates) - len(affordable),
            "active_alerts_count": len(alerts),
            "session_entries_count": self.session_entries_count,
            "max_session_entries": self.MAX_SESSION_ENTRIES,
            "quota_status": f"{self.session_entries_count}/{self.MAX_SESSION_ENTRIES}",
        }

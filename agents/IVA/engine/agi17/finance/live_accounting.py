"""Separate Live Accounting Ledger & Statutory Charges Engine for Phase 4.

Implements Section 11:
- Authoritative live performance record isolated from paper trading
- Strictly separated SQLite storage in `live_broker_ledger.db`
- Exact Indian NSE equity derivative charges:
  * STT (Securities Transaction Tax): 0.1% on sell premium
  * Stamp Duty: 0.003% on buy premium
  * Exchange Turnover Fee: 0.05% on premium
  * SEBI Turnover Charges: ₹10 per crore (0.0001%)
  * GST: 18% on (Brokerage + Exchange Fee + SEBI Fee)
  * Paytm Money flat brokerage: ₹20 per executed order
- Peak equity, drawdown, and net P&L calculations
- Honest reporting: Missing/unverified records reported as "UNAVAILABLE" rather than fabricated
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class StatutoryRateMetadata:
    """Metadata documenting official source and basis for statutory charges."""
    name: str
    rate_pct: float
    source: str
    effective_date: str
    applicable_transaction_type: str
    calculation_basis: str


class StatutoryCostSchedule:
    """Official statutory rate schedule for NSE index equity derivatives."""
    RATES = {
        "STT_SALE_2026": StatutoryRateMetadata(
            name="STT (Sale of Option)",
            rate_pct=0.15,
            source="NSE Circular & Finance Act Schedule (Effective 1 April 2026)",
            effective_date="2026-04-01",
            applicable_transaction_type="SELL",
            calculation_basis="Option Premium Turnover (Quantity * Premium)",
        ),
        "STT_SALE_HISTORICAL": StatutoryRateMetadata(
            name="STT (Sale of Option Historical)",
            rate_pct=0.10,
            source="Finance Act 2024 (Prior to 1 April 2026)",
            effective_date="2024-10-01",
            applicable_transaction_type="SELL",
            calculation_basis="Option Premium Turnover (Quantity * Premium)",
        ),
        "STAMP_DUTY_BUY": StatutoryRateMetadata(
            name="Stamp Duty",
            rate_pct=0.003,
            source="Indian Stamp Act / NSE Schedule",
            effective_date="2020-07-01",
            applicable_transaction_type="BUY",
            calculation_basis="Option Premium Turnover (Quantity * Premium)",
        ),
        "EXCHANGE_TURNOVER": StatutoryRateMetadata(
            name="Exchange Turnover Charge (Historical Pre-March 2026)",
            rate_pct=0.05,
            source="NSE Transaction Charges Schedule (Pre-March 2026)",
            effective_date="2023-01-01",
            applicable_transaction_type="BUY_AND_SELL",
            calculation_basis="Option Premium Turnover (0.05% / ₹5,000 per crore)",
        ),
        "EXCHANGE_TURNOVER_2026": StatutoryRateMetadata(
            name="Exchange Turnover Charge (NSE Circular NSE/FA/73061)",
            rate_pct=0.0355299,
            source="NSE Circular Ref NSE/FA/73061 (Effective 1 March 2026)",
            effective_date="2026-03-01",
            applicable_transaction_type="BUY_AND_SELL",
            calculation_basis="₹3,552.99 per crore (0.0355299% of Option Premium Turnover)",
        ),
        "EXCHANGE_IPFT_2026": StatutoryRateMetadata(
            name="Investor Protection Fund Trust (NSE Circular NSE/FA/73061)",
            rate_pct=0.0000001,  # Exact percentage: 0.0000001% (₹0.01 per crore = 1e-9 decimal fraction)
            source="NSE Circular Ref NSE/FA/73061 (Effective 1 March 2026)",
            effective_date="2026-03-01",
            applicable_transaction_type="BUY_AND_SELL",
            calculation_basis="₹0.01 per crore (0.0000001% of Option Premium Turnover / 1e-9 decimal fraction)",
        ),
        "EXCHANGE_IPFT_HISTORICAL": StatutoryRateMetadata(
            name="Investor Protection Fund Trust (Historical Pre-March 2026)",
            rate_pct=0.0005,
            source="NSE Investor Protection Fund Trust Regulations (Pre-March 2026)",
            effective_date="2023-04-01",
            applicable_transaction_type="BUY_AND_SELL",
            calculation_basis="₹50 per crore (0.0005% of Option Premium Turnover)",
        ),
        "EXCHANGE_TOTAL_OUTFLOW_2026": StatutoryRateMetadata(
            name="Total Exchange Outflow (NSE Circular NSE/FA/73061)",
            rate_pct=0.03553,
            source="NSE Circular Ref NSE/FA/73061 (Effective 1 March 2026)",
            effective_date="2026-03-01",
            applicable_transaction_type="BUY_AND_SELL",
            calculation_basis="₹3,553.00 per crore total outflow (₹3,552.99 txn + ₹0.01 IPFT)",
        ),
        "SEBI_TURNOVER": StatutoryRateMetadata(
            name="SEBI Turnover Fee",
            rate_pct=0.0001,
            source="SEBI (Fees and Charges) Regulations",
            effective_date="2021-06-01",
            applicable_transaction_type="BUY_AND_SELL",
            calculation_basis="₹10 per crore (0.0001% of Turnover)",
        ),
        "GST": StatutoryRateMetadata(
            name="GST",
            rate_pct=18.0,
            source="Goods and Services Tax Act",
            effective_date="2017-07-01",
            applicable_transaction_type="SERVICE_CHARGES",
            calculation_basis="18% on Taxable Services (Brokerage + Exchange Turnover Charges + SEBI Fees)",
        ),
        "BROKERAGE": StatutoryRateMetadata(
            name="Paytm Money Flat Brokerage",
            rate_pct=0.0,
            source="Paytm Money Tariff Sheet",
            effective_date="2023-01-01",
            applicable_transaction_type="BUY_AND_SELL",
            calculation_basis="₹20 flat per executed order",
        ),
        "BROKERAGE_PAYTM_FO_10": StatutoryRateMetadata(
            name="Paytm Money F&O Flat Brokerage",
            rate_pct=0.0,
            source="Paytm Money F&O FAQ & Official Tariff",
            effective_date="2021-03-01",
            applicable_transaction_type="BUY_AND_SELL",
            calculation_basis="₹10 flat per unique executed order",
        ),
        "BROKERAGE_PAYTM_STANDARD_20": StatutoryRateMetadata(
            name="Paytm Money Standard Brokerage",
            rate_pct=0.0,
            source="Paytm Money Standard Tariff Sheet",
            effective_date="2023-01-01",
            applicable_transaction_type="BUY_AND_SELL",
            calculation_basis="₹20 flat per executed order",
        ),
    }

    # Direct rate float constants
    EXCHANGE_TURNOVER_2026: float = 0.000355299  # ₹3,552.99 per crore (NSE/FA/73061)
    EXCHANGE_IPFT_2026: float = 0.000000001      # ₹0.01 per crore (NSE/FA/73061) = 0.0000001% = 1e-9
    EXCHANGE_TOTAL_OUTFLOW_2026: float = 0.000355300  # ₹3,553.00 per crore total
    NSE_CIRCULAR_REF_2026: str = "NSE/FA/73061"
    EFFECTIVE_DATE_2026: str = "2026-03-01"
    EXCHANGE_TURNOVER_HISTORICAL: float = 0.0005      # 0.05% = ₹5,000 per crore
    EXCHANGE_IPFT_HISTORICAL: float = 0.000005        # ₹50 per crore = 0.0005%
    EXCHANGE_IPFT: float = 0.000000001                # Default to revised 2026 schedule (₹0.01/cr)
    STT_SALE_2026: float = 0.0015  # 0.15% (Effective 1 April 2026)
    STT_SALE_HISTORICAL: float = 0.0010  # 0.10% (Finance Act 2024)
    STAMP_DUTY_BUY: float = 0.00003  # 0.003%
    SEBI_TURNOVER: float = 0.000001  # ₹10 per crore = 0.0001%
    BROKERAGE_PAYTM_FO_10: float = 10.0
    BROKERAGE_PAYTM_STANDARD_20: float = 20.0

    @staticmethod
    def rupees_per_crore_to_fraction(rpc: float) -> float:
        """Converts rupees per crore into turnover decimal fraction (e.g. ₹0.01/cr -> 1e-9)."""
        return rpc / 10_000_000.0

    @staticmethod
    def rupees_per_crore_to_pct(rpc: float) -> float:
        """Converts rupees per crore into percentage (e.g. ₹0.01/cr -> 0.0000001%)."""
        return (rpc / 10_000_000.0) * 100.0

    @staticmethod
    def pct_to_fraction(pct: float) -> float:
        """Converts percentage into decimal fraction (e.g. 0.0000001% -> 1e-9)."""
        return pct / 100.0

    @staticmethod
    def fraction_to_rupees_per_crore(fraction: float) -> float:
        """Converts decimal fraction into rupees per crore (e.g. 1e-9 -> ₹0.01/cr)."""
        return fraction * 10_000_000.0


class StatutoryChargeBreakdown(dict):
    """Statutory charge breakdown dictionary supporting both key and attribute access."""

    def __getattr__(self, name: str) -> Any:
        if name in self:
            return self[name]
        alt_names = {
            "exchange_turnover_charge": "exchange_turnover_inr",
            "exchange_turnover_charges": "exchange_turnover_inr",
            "exchange_fee": "exchange_turnover_inr",
            "exchange_txn_charge": "exchange_turnover_inr",
            "exchange_txn_charge_inr": "exchange_turnover_inr",
            "exchange_ipft_charge": "ipft_inr",
            "ipft": "ipft_inr",
            "ipft_charges": "ipft_inr",
            "brokerage": "brokerage_inr",
            "stt": "stt_inr",
            "stamp_duty": "stamp_duty_inr",
            "sebi_fee": "sebi_fee_inr",
            "gst": "gst_inr",
            "total_charges": "total_charges_inr",
            "total_exchange_outflow": "total_exchange_outflow_inr",
        }
        if name in alt_names and alt_names[name] in self:
            return self[alt_names[name]]
        raise AttributeError(f"'StatutoryChargeBreakdown' object has no attribute '{name}'")


class LiveBrokerLedger:
    """Manages the isolated live brokerage ledger database."""

    def __init__(
        self,
        storage_dir: Optional[Path | str] = None,
        db_path: Optional[Path | str] = None,
        initial_live_capital: float = 100000.0,
    ) -> None:
        if db_path is not None:
            self.db_path = Path(db_path)
            self.storage_dir = self.db_path.parent
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        elif storage_dir is not None:
            self.storage_dir = Path(storage_dir)
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = self.storage_dir / "live_broker_ledger.db"
        else:
            self.storage_dir = Path("./live_storage")
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = self.storage_dir / "live_broker_ledger.db"
        self.initial_live_capital = initial_live_capital
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_database(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS live_sessions (
                    session_id TEXT PRIMARY KEY,
                    date_ist TEXT NOT NULL,
                    starting_capital REAL NOT NULL,
                    ending_capital REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    total_charges REAL NOT NULL,
                    orders_submitted INTEGER NOT NULL,
                    orders_filled INTEGER NOT NULL,
                    orders_rejected INTEGER NOT NULL,
                    peak_equity REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    verified_funds REAL,
                    verified_margin REAL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS live_orders (
                    intent_id TEXT PRIMARY KEY,
                    broker_order_id TEXT,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    requested_price REAL NOT NULL,
                    filled_quantity INTEGER DEFAULT 0,
                    average_fill_price REAL DEFAULT 0.0,
                    status TEXT NOT NULL,
                    statutory_charges REAL DEFAULT 0.0,
                    net_realized_pnl REAL DEFAULT 0.0,
                    submitted_at TEXT NOT NULL,
                    filled_at TEXT,
                    rejection_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS live_audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    intent_id TEXT,
                    broker_order_id TEXT,
                    details TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
            """)

    @staticmethod
    def calculate_statutory_charges(
        side: str = "BUY",
        quantity: int = 1,
        premium: float = 0.0,
        premium_turnover: Optional[float] = None,
        broker_fee_flat: Optional[float] = None,
        as_of_date: Optional[str | datetime.date] = None,
        trade_date: Optional[str | datetime.date] = None,
        estimated_slippage_pts: float = 0.0,
        estimated_spread_cost_pts: float = 0.0,
        net_trade_pnl: Optional[float] = None,
        broker_tariff_model: str = "PAYTM_DEFAULT",
        allow_percentage_cap: bool = False,
        provisional_tax_rate: Optional[float] = None,
        action: Optional[str] = None,
        tariff_profile: Optional[str] = None,
        is_exercise: bool = False,
        settlement_intrinsic_value: Optional[float] = None,
        is_sell: Optional[bool] = None,
    ) -> StatutoryChargeBreakdown:
        """Calculates precise statutory charges for NSE index options.

        Supports date-aware statutory and exchange scheduling:
        - Exchange Charges (NSE Circular Ref NSE/FA/73061 effective March 1, 2026):
          * Transaction charges: ₹3,552.99 per crore (0.0355299% of premium turnover) on each side.
          * NSE IPFT contribution: ₹0.01 per crore (0.000001% of premium turnover) on each side.
          * Total exchange outflow: ₹3,553.00 per crore (0.0355300% of premium turnover) on each side.
          * Pre-March 1, 2026 historical schedule: 0.05% (₹5,000/cr) txn charge + ₹50/cr (0.0005%) IPFT.
        - STT:
          * As of 2026-04-01 onwards: 0.15% on sell premium.
          * Historical / default: 0.10% on sell premium (Finance Act 2024).
        - Stamp Duty:
          * 0.003% on buy premium turnover.
        - SEBI Turnover Fee:
          * ₹10 per crore (0.0001% of premium turnover).
        - Brokerage:
          * Account-specific resolution: 'PAYTM_FO_10' = flat ₹10 per executed order.
          * 'PAYTM_STANDARD_20' = flat ₹20 per executed order.
          * 'PAYTM_FO_15' = flat ₹15 per executed order.
          * Percentage cap (min ₹10 or 0.05%) strictly disabled for options unless allow_percentage_cap=True.
        - GST:
          * 18% on Taxable Services (Brokerage + Exchange Turnover Charge + SEBI Turnover Fee).
          * Excludes IPFT (trust levy), Stamp Duty, and STT.
        - Advance Income Tax:
          * Explicitly configurable provisional estimate under Section 43(5) (non-speculative business income).
        """
        if is_sell is not None:
            side = "SELL" if is_sell else "BUY"
        if action is not None:
            side = action
        if tariff_profile is not None:
            broker_tariff_model = tariff_profile
        turnover = premium_turnover if premium_turnover is not None else (quantity * premium)
        side_upper = side.upper()
        effective_date = as_of_date or trade_date
        if isinstance(effective_date, datetime.datetime):
            effective_date = effective_date.date()

        # Date-aware STT determination
        use_2026_stt = False
        use_2026_exchange = False
        if effective_date is not None:
            if isinstance(effective_date, str):
                eff_upper = effective_date.upper()
                if eff_upper in ("LATEST", "CURRENT"):
                    use_2026_stt = True
                    use_2026_exchange = True
                else:
                    if effective_date >= "2026-04-01":
                        use_2026_stt = True
                    if effective_date >= "2026-03-01":
                        use_2026_exchange = True
            elif isinstance(effective_date, datetime.date):
                if effective_date >= datetime.date(2026, 4, 1):
                    use_2026_stt = True
                if effective_date >= datetime.date(2026, 3, 1):
                    use_2026_exchange = True

        stt_rate = 0.0015 if use_2026_stt else 0.0010

        # 1. STT: on sell turnover or option exercise
        if is_exercise or side_upper == "EXERCISE":
            # Under Finance Act and NSE schedule, STT on exercise of option is 0.125% of intrinsic settlement value, payable by exerciser
            taxable_base = settlement_intrinsic_value if settlement_intrinsic_value is not None else turnover
            stt = taxable_base * 0.00125
        elif side_upper == "SELL":
            stt = turnover * stt_rate
        else:
            stt = 0.0

        # 2. Stamp Duty: 0.003% on buy turnover
        stamp_duty = turnover * 0.00003 if side_upper == "BUY" and not (is_exercise or side_upper == "EXERCISE") else 0.0

        # 3. Exchange Turnover Charge & IPFT (NSE Circular NSE/FA/73061 vs Historical)
        if use_2026_exchange:
            # NSE Circular Ref NSE/FA/73061 effective 1 March 2026
            exchange_turnover_rate = StatutoryCostSchedule.EXCHANGE_TURNOVER_2026  # 0.000355299 (₹3,552.99/cr)
            exchange_turnover_charge = turnover * exchange_turnover_rate
            ipft_rate = StatutoryCostSchedule.EXCHANGE_IPFT_2026  # 0.000000001 (₹0.01/cr)
            ipft = turnover * ipft_rate
            total_exchange_outflow = exchange_turnover_charge + ipft  # ₹3,553.00 per crore
            exchange_basis = "NSE Circular Ref NSE/FA/73061 (₹3,552.99/cr txn + ₹0.01/cr IPFT = ₹3,553.00/cr total outflow)"
        else:
            # Historical schedule prior to March 1, 2026
            exchange_turnover_rate = StatutoryCostSchedule.EXCHANGE_TURNOVER_HISTORICAL  # 0.0005 (0.05% / ₹5,000/cr)
            exchange_turnover_charge = turnover * exchange_turnover_rate
            ipft_rate = StatutoryCostSchedule.EXCHANGE_IPFT_HISTORICAL  # 0.000005 (₹50/cr)
            ipft = turnover * ipft_rate
            total_exchange_outflow = exchange_turnover_charge + ipft
            exchange_basis = "NSE Historical Standard Schedule (₹5,000/cr txn + ₹50/cr IPFT)"

        # 4. SEBI Turnover Fee: ₹10 per crore = 0.0001%
        sebi_fee = turnover * 0.000001

        # 5. Brokerage: Account-specific tariff resolution
        if broker_fee_flat is not None:
            brokerage = float(broker_fee_flat)
            broker_basis = f"Account Contract Note Tariff (₹{brokerage:.2f} flat per order)"
        elif broker_tariff_model.upper() in ("PAYTM_FO_10", "FO_10", "PAYTM_10"):
            # Official Paytm Money F&O FAQ: flat ₹10 per unique executed order
            if allow_percentage_cap:
                brokerage = min(10.0, turnover * 0.0005) if turnover > 0 else 10.0
                broker_basis = "Paytm Money F&O Tariff with 0.05% cap (₹10 or 0.05% if lower)"
            else:
                brokerage = 10.0
                broker_basis = "Paytm Money F&O FAQ Authoritative Tariff (₹10 flat per executed order)"
        elif broker_tariff_model.upper() in ("PAYTM_FO_15", "FO_15"):
            brokerage = 15.0
            broker_basis = "Paytm Money Account Cohort Tariff (₹15 flat per executed order)"
        elif broker_tariff_model.upper() in ("PAYTM_STANDARD_20", "STANDARD_20", "PAYTM_DEFAULT", "DEFAULT"):
            brokerage = 20.0
            broker_basis = "Paytm Money Standard Tariff (₹20 flat per executed order)"
        else:
            brokerage = 20.0
            broker_basis = f"Configured Account Tariff Model: {broker_tariff_model} (₹{brokerage:.2f})"

        # 6. GST: 18% on Taxable Services (Brokerage + Exchange Turnover Charge + SEBI Fee)
        # Note: IPFT is an Investor Protection Fund Trust levy exempt from GST; Stamp Duty and STT are direct taxes.
        taxable_services = brokerage + exchange_turnover_charge + sebi_fee
        gst = taxable_services * 0.18

        # 7. Execution costs
        slippage_cost = quantity * estimated_slippage_pts
        spread_cost = quantity * estimated_spread_cost_pts

        total_charges = stt + stamp_duty + exchange_turnover_charge + ipft + sebi_fee + brokerage + gst

        # 8. Provisional Advance Tax estimate (Section 43(5))
        income_tax_estimate = 0.0
        applied_tax_rate = 0.0
        if net_trade_pnl is not None and net_trade_pnl > 0:
            applied_tax_rate = provisional_tax_rate if provisional_tax_rate is not None else 0.20
            income_tax_estimate = round(net_trade_pnl * applied_tax_rate, 2)
        elif provisional_tax_rate is not None:
            applied_tax_rate = provisional_tax_rate

        return StatutoryChargeBreakdown({
            "turnover_inr": round(turnover, 2),
            "brokerage_inr": round(brokerage, 2),
            "broker_tariff_basis": broker_basis,
            "stt_inr": round(stt, 2),
            "stt_rate_pct": 0.125 if (is_exercise or side_upper == "EXERCISE") else (0.15 if use_2026_stt else 0.10),
            "stt_effective_date": "2026-04-01" if (use_2026_stt or is_exercise or side_upper == "EXERCISE") else "2024-10-01",
            "stamp_duty_inr": round(stamp_duty, 2),
            "exchange_turnover_inr": round(exchange_turnover_charge, 2),
            "exchange_rate_pct": round(exchange_turnover_rate * 100.0, 5),
            "exchange_circular_basis": exchange_basis,
            "ipft_inr": round(ipft, 2),
            "total_exchange_outflow_inr": round(total_exchange_outflow, 2),
            "sebi_fee_inr": round(sebi_fee, 2),
            "gst_inr": round(gst, 2),
            "slippage_cost_inr": round(slippage_cost, 2),
            "spread_cost_inr": round(spread_cost, 2),
            "total_charges_inr": round(total_charges, 2),
            "income_tax_estimate_inr": income_tax_estimate,
            "provisional_tax_rate_pct": round(applied_tax_rate * 100.0, 2),
            "tax_statutory_basis": "Income Tax Act 1961 Section 43(5) - F&O classified as non-speculative business income. Taxable at applicable assessee slab rates. Subject to quarterly Advance Tax installments under Sec 208/211. Transaction estimate is strictly provisional.",
            "tax_disclaimer": "ESTIMATE_ONLY: Transaction charges are distinct from final income-tax liability. Final tax depends on individual filing regime, business expenses, and eligible deductions under the Income Tax Act.",
        })

    @staticmethod
    def calculate_advance_tax_estimate(
        gross_profit: float,
        provisional_rate: float = 0.20,
    ) -> Dict[str, Any]:
        """Calculates provisional advance tax estimate under Income Tax Act Section 43(5)."""
        provisional_tax = max(0.0, round(gross_profit * provisional_rate, 2)) if gross_profit > 0 else 0.0
        return {
            "gross_profit_inr": gross_profit,
            "provisional_rate_pct": round(provisional_rate * 100.0, 2),
            "provisional_tax_inr": provisional_tax,
            "is_statutory_levy": False,
            "statutory_notes": "Income Tax Act 1961 Section 43(5) - F&O treated as non-speculative business income. Subject to individual/corporate income tax slabs and advance tax quarterly installments under Sec 208/211.",
            "disclaimer": "PROVISIONAL ESTIMATE ONLY: Not a statutory transaction levy or final tax liability.",
        }

    def record_order_submission(
        self,
        intent_id: str,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        status: str,
        broker_order_id: Optional[str] = None,
    ) -> None:
        """Records an initial order submission attempt."""
        if "TEST-FIXTURE" in intent_id.upper() or (broker_order_id and "SYNTHETIC" in broker_order_id.upper()):
            raise ValueError("FIXTURE_REJECTED: Real live broker ledger strictly prohibits synthetic test fixtures or mock broker IDs.")

        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")


        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO live_orders (
                    intent_id, broker_order_id, symbol, action, quantity,
                    requested_price, status, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (intent_id, broker_order_id, symbol, action, quantity, price, status, ts_str))

        self.record_audit_event("ORDER_SUBMISSION", f"Submitted {action} {quantity} {symbol} @ ₹{price:.2f}", intent_id, broker_order_id)

    def record_order_fill(
        self,
        intent_id: str,
        filled_qty: int,
        avg_price: float,
        status: str,
        broker_order_id: Optional[str] = None,
    ) -> Dict[str, float]:
        """Records verified execution and deducts exact statutory charges."""
        if "TEST-FIXTURE" in intent_id.upper() or (broker_order_id and "SYNTHETIC" in broker_order_id.upper()):
            raise ValueError("FIXTURE_REJECTED: Real live broker ledger strictly prohibits synthetic test fixtures or mock broker IDs.")

        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")


        with self._get_connection() as conn:
            cur = conn.execute("SELECT action FROM live_orders WHERE intent_id = ?", (intent_id,))
            row = cur.fetchone()
            side = row["action"] if row else "BUY"

            charges = self.calculate_statutory_charges(side, filled_qty, avg_price)
            total_charges = charges["total_charges_inr"]

            conn.execute("""
                UPDATE live_orders SET
                    filled_quantity = ?,
                    average_fill_price = ?,
                    status = ?,
                    statutory_charges = ?,
                    broker_order_id = COALESCE(?, broker_order_id),
                    filled_at = ?
                WHERE intent_id = ?
            """, (filled_qty, avg_price, status, total_charges, broker_order_id, ts_str, intent_id))

        self.record_audit_event(
            "ORDER_FILL",
            f"Fill verified: {filled_qty} @ ₹{avg_price:.2f} (Charges: ₹{total_charges:.2f})",
            intent_id,
            broker_order_id,
        )
        return charges

    def record_audit_event(
        self,
        event_type: str,
        details: str,
        intent_id: Optional[str] = None,
        broker_order_id: Optional[str] = None,
    ) -> None:
        """Stores an immutable audit trail entry."""
        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        ts_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO live_audit_events (event_type, intent_id, broker_order_id, details, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (event_type, intent_id, broker_order_id, details, ts_str))

    def get_live_performance_summary(
        self,
        verified_funds: Optional[float] = None,
        verified_margin: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Returns the authoritative live performance ledger summary."""
        with self._get_connection() as conn:
            cur_orders = conn.execute("""
                SELECT
                    COUNT(*) as total_submitted,
                    SUM(CASE WHEN status = 'FULLY_FILLED' THEN 1 ELSE 0 END) as total_filled,
                    SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END) as total_rejected,
                    SUM(statutory_charges) as sum_charges,
                    SUM(net_realized_pnl) as sum_realized_pnl
                FROM live_orders
            """)
            orders_summary = cur_orders.fetchone()

        tot_submitted = orders_summary["total_submitted"] or 0
        tot_filled = orders_summary["total_filled"] or 0
        tot_rejected = orders_summary["total_rejected"] or 0
        tot_charges = float(orders_summary["sum_charges"] or 0.0)
        tot_realized_pnl = float(orders_summary["sum_realized_pnl"] or 0.0)
        net_pnl = tot_realized_pnl - tot_charges

        return {
            "starting_live_capital_inr": self.initial_live_capital,
            "verified_funds_inr": verified_funds if verified_funds is not None else "UNAVAILABLE",
            "verified_margin_inr": verified_margin if verified_margin is not None else "UNAVAILABLE",
            "orders_submitted": tot_submitted,
            "orders_filled": tot_filled,
            "orders_rejected": tot_rejected,
            "gross_realized_pnl_inr": round(tot_realized_pnl, 2),
            "total_statutory_charges_inr": round(tot_charges, 2),
            "net_realized_pnl_inr": round(net_pnl, 2),
            "current_live_equity_inr": round(self.initial_live_capital + net_pnl, 2),
            "unrealized_pnl_inr": "UNAVAILABLE",  # Honest disclosure until active live position verified
            "peak_equity_inr": round(max(self.initial_live_capital, self.initial_live_capital + net_pnl), 2),
            "max_drawdown_pct": 0.0 if net_pnl >= 0 else round(abs(net_pnl) / self.initial_live_capital * 100, 2),
            "data_source": "Paytm Money Visible Broker Interface (Isolated from Paper)",
        }


# Module-level convenience aliases
calculate_statutory_charges = LiveBrokerLedger.calculate_statutory_charges


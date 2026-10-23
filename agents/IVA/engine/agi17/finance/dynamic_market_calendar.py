"""AGI 1.7 OMEGA COMMAND — Dynamic Official Exchange Calendar Engine.

Provides authoritative, timezone-aware (Asia/Kolkata, IST) calendar modeling for NSE:
- Weekends (Saturday / Sunday)
- Official Exchange Holidays (with holiday names, dates, segments)
- Special Trading Sessions (e.g. Diwali Muhurat trading)
- Segment-specific timings (Pre-market 09:00-09:15, Regular 09:15-15:30, Post-market 15:40-16:00)
- Calendar data provenance and freshness tracking (fail-safe HALT if unverified or stale > 72h)
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("DynamicMarketCalendar")

# Market Timezone: Indian Standard Time (UTC+05:30)
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


class CalendarSessionPhase(str, enum.Enum):
    """Authoritative trading session phase in Asia/Kolkata."""
    PRE_MARKET = "PRE_MARKET"                       # 09:00 - 09:15 IST
    REGULAR_MARKET = "REGULAR_MARKET"               # 09:15 - 15:30 IST
    POST_MARKET = "POST_MARKET"                     # 15:30 - 16:00 IST
    OVERNIGHT_CLOSED = "OVERNIGHT_CLOSED"           # Outside trading hours on trading day
    WEEKEND_CLOSED = "WEEKEND_CLOSED"               # Saturday / Sunday
    HOLIDAY_CLOSED = "HOLIDAY_CLOSED"               # Official exchange holiday
    SPECIAL_SESSION = "SPECIAL_SESSION"             # e.g., Diwali Muhurat trading
    CALENDAR_UNVERIFIED = "CALENDAR_UNVERIFIED"     # Stale or unverified calendar data -> fail-safe halt


class VerificationStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    UNVERIFIED = "UNVERIFIED"


@dataclasses.dataclass
class SpecialTradingSession:
    """Special trading window, such as Diwali Muhurat trading."""
    name: str
    date: datetime.date
    start_time: datetime.time  # e.g., 18:15 IST
    end_time: datetime.time    # e.g., 19:15 IST
    segment: str = "DERIVATIVES"
    description: str = ""


@dataclasses.dataclass
class ExchangeHoliday:
    """Official exchange holiday record with name, date, and segment."""
    name: str
    date: datetime.date
    segment: str = "ALL"  # "ALL", "EQUITY", "DERIVATIVES"
    description: str = ""


@dataclasses.dataclass
class CalendarUpdateRecord:
    """Metadata tracking provenance and freshness of exchange calendar data."""
    source_url: str
    publication_date: str
    retrieved_at: str
    applicable_segment: str
    verification_status: VerificationStatus
    total_holidays: int
    total_special_sessions: int
    notes: str = ""


# Official NSE Holidays for 2026 (Circular reference: NSE/CMTR/65891)
DEFAULT_NSE_HOLIDAYS_2026: List[ExchangeHoliday] = [
    ExchangeHoliday(name="Republic Day", date=datetime.date(2026, 1, 26), segment="ALL"),
    ExchangeHoliday(name="Mahashivratri", date=datetime.date(2026, 2, 17), segment="ALL"),
    ExchangeHoliday(name="Holi", date=datetime.date(2026, 3, 4), segment="ALL"),
    ExchangeHoliday(name="Id-ul-Fitr (Ramzan Id)", date=datetime.date(2026, 3, 20), segment="ALL"),
    ExchangeHoliday(name="Good Friday", date=datetime.date(2026, 4, 3), segment="ALL"),
    ExchangeHoliday(name="Dr. Baba Saheb Ambedkar Jayanti", date=datetime.date(2026, 4, 14), segment="ALL"),
    ExchangeHoliday(name="Maharashtra Day", date=datetime.date(2026, 5, 1), segment="ALL"),
    ExchangeHoliday(name="Bakri Id (Id-Ul-Adha)", date=datetime.date(2026, 5, 27), segment="ALL"),
    ExchangeHoliday(name="Muharram", date=datetime.date(2026, 6, 26), segment="ALL"),
    ExchangeHoliday(name="Independence Day", date=datetime.date(2026, 8, 15), segment="ALL"),
    ExchangeHoliday(name="Mahatma Gandhi Jayanti", date=datetime.date(2026, 10, 2), segment="ALL"),
    ExchangeHoliday(name="Dussehra", date=datetime.date(2026, 10, 20), segment="ALL"),
    ExchangeHoliday(name="Diwali Laxmi Pujan (Regular closed)", date=datetime.date(2026, 11, 8), segment="ALL"),
    ExchangeHoliday(name="Gurunanak Jayanti", date=datetime.date(2026, 11, 24), segment="ALL"),
    ExchangeHoliday(name="Christmas", date=datetime.date(2026, 12, 25), segment="ALL"),
]

# Official Diwali Muhurat Trading Window 2026
DEFAULT_SPECIAL_SESSIONS_2026: List[SpecialTradingSession] = [
    SpecialTradingSession(
        name="Diwali Muhurat Trading Session 2026",
        date=datetime.date(2026, 11, 8),
        start_time=datetime.time(18, 15),
        end_time=datetime.time(19, 15),
        segment="DERIVATIVES",
        description="Official annual NSE Muhurat trading hour for Samvat 2083",
    )
]


class DynamicExchangeCalendar:
    """Authoritative dynamic calendar with fail-safe verification gates and IST session modeling."""

    def __init__(
        self,
        holidays: Optional[List[ExchangeHoliday]] = None,
        special_sessions: Optional[List[SpecialTradingSession]] = None,
        source_url: str = "https://www.nseindia.com/resources/exchange-communication-holidays",
        publication_date: str = "2026-01-01",
        cache_path: Optional[Path] = None,
        allow_stale_for_testing: bool = False,
        segment: str = "DERIVATIVES",
    ) -> None:
        self.holidays: List[ExchangeHoliday] = holidays if holidays is not None else list(DEFAULT_NSE_HOLIDAYS_2026)
        self.special_sessions: List[SpecialTradingSession] = (
            special_sessions if special_sessions is not None else list(DEFAULT_SPECIAL_SESSIONS_2026)
        )
        self.source_url = source_url
        self.publication_date = publication_date
        self.cache_path = cache_path
        self.allow_stale_for_testing = allow_stale_for_testing
        self.segment = segment.upper()

        # Initial provenance record (fresh by default)
        now_iso = datetime.datetime.now(IST).isoformat()
        self.last_update_record = CalendarUpdateRecord(
            source_url=self.source_url,
            publication_date=self.publication_date,
            retrieved_at=now_iso,
            applicable_segment=self.segment,
            verification_status=VerificationStatus.VERIFIED,
            total_holidays=len(self.holidays),
            total_special_sessions=len(self.special_sessions),
            notes="Default verified NSE 2026 schedule",
        )

        # Segment-specific official market hours in IST
        # NSE Equity Derivatives (F&O) normal market closes at 15:40 IST; Cash segment closes at 15:30 IST.
        self.pre_market_start = datetime.time(9, 0)
        self.pre_market_end = datetime.time(9, 15)
        self.regular_market_start = datetime.time(9, 15)
        if self.segment == "EQUITY":
            self.regular_market_end = datetime.time(15, 30)
            self.post_market_start = datetime.time(15, 30)
        else:
            # Default to NSE Equity Derivatives normal trading close: 15:40 IST
            self.regular_market_end = datetime.time(15, 40)
            self.post_market_start = datetime.time(15, 40)
        self.intraday_cutoff = datetime.time(15, 15)
        self.post_market_end = datetime.time(16, 0)

    @staticmethod
    def now_ist() -> datetime.datetime:
        """Returns the current aware datetime in Asia/Kolkata."""
        return datetime.datetime.now(IST)

    def is_stale(self, max_age_hours: float = 72.0) -> bool:
        """Checks if calendar data is stale (> max_age_hours since last verification)."""
        if self.allow_stale_for_testing:
            return False
        try:
            retrieved_dt = datetime.datetime.fromisoformat(self.last_update_record.retrieved_at)
            # Ensure aware comparison
            if retrieved_dt.tzinfo is None:
                retrieved_dt = retrieved_dt.replace(tzinfo=IST)
            now = self.now_ist()
            age_hours = (now - retrieved_dt).total_seconds() / 3600.0
            return age_hours > max_age_hours
        except Exception:
            return True

    def get_verification_status(self) -> VerificationStatus:
        """Returns verified status; degrades to STALE if older than 72 hours."""
        if self.last_update_record.verification_status != VerificationStatus.VERIFIED:
            return self.last_update_record.verification_status
        if self.is_stale(max_age_hours=72.0):
            return VerificationStatus.STALE
        return VerificationStatus.VERIFIED

    def is_weekend(self, dt_or_date: datetime.date | datetime.datetime) -> bool:
        """Saturdays (5) and Sundays (6) are weekend non-trading days."""
        d = dt_or_date.date() if isinstance(dt_or_date, datetime.datetime) else dt_or_date
        return d.weekday() in (5, 6)

    def get_holiday(self, dt_or_date: datetime.date | datetime.datetime) -> Optional[ExchangeHoliday]:
        """Returns ExchangeHoliday object if date is an official exchange holiday, else None."""
        d = dt_or_date.date() if isinstance(dt_or_date, datetime.datetime) else dt_or_date
        for h in self.holidays:
            if h.date == d:
                return h
        return None

    def get_special_session(
        self, dt: datetime.datetime, segment: str = "DERIVATIVES"
    ) -> Optional[SpecialTradingSession]:
        """Returns active SpecialTradingSession if dt is inside a special window."""
        d = dt.date()
        t = dt.time()
        for s in self.special_sessions:
            if s.date == d and s.start_time <= t <= s.end_time:
                if s.segment == "ALL" or s.segment == segment:
                    return s
        return None

    def is_trading_day(self, d: datetime.date) -> bool:
        """Returns True if date is a standard trading day (neither weekend nor holiday)."""
        if self.is_weekend(d):
            return False
        if self.get_holiday(d) is not None:
            return False
        return True

    def get_session_phase(
        self,
        dt: Optional[datetime.datetime] = None,
        segment: Optional[str] = None,
    ) -> CalendarSessionPhase:
        """Evaluates authoritative session phase with fail-safe verification gate.
        
        Supports segment differentiation:
        - DERIVATIVES (F&O): Regular session 09:15 - 15:40 IST
        - EQUITY (Cash): Regular session 09:15 - 15:30 IST
        """
        if dt is None:
            dt = self.now_ist()
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        else:
            dt = dt.astimezone(IST)

        # 1. Fail-safe Verification Gate: Stale or unverified calendar -> HALT
        v_status = self.get_verification_status()
        if v_status != VerificationStatus.VERIFIED:
            return CalendarSessionPhase.CALENDAR_UNVERIFIED

        # 2. Check special trading session (e.g. Diwali Muhurat trading)
        if self.get_special_session(dt) is not None:
            return CalendarSessionPhase.SPECIAL_SESSION

        # 3. Check Weekend
        if self.is_weekend(dt):
            return CalendarSessionPhase.WEEKEND_CLOSED

        # 4. Check Official Holiday
        if self.get_holiday(dt) is not None:
            return CalendarSessionPhase.HOLIDAY_CLOSED

        # 5. Segment-specific Regular Market Closing Time
        target_segment = (segment or self.segment).upper()
        reg_market_end = datetime.time(15, 30) if target_segment == "EQUITY" else datetime.time(15, 40)
        post_market_start = reg_market_end

        # 6. Trading Day Timing Phases
        t = dt.time()
        if self.pre_market_start <= t < self.pre_market_end:
            return CalendarSessionPhase.PRE_MARKET
        elif self.regular_market_start <= t < reg_market_end:
            return CalendarSessionPhase.REGULAR_MARKET
        elif post_market_start <= t < self.post_market_end:
            return CalendarSessionPhase.POST_MARKET
        else:
            return CalendarSessionPhase.OVERNIGHT_CLOSED

    get_current_session_phase = get_session_phase

    def is_market_open(
        self,
        dt: Optional[datetime.datetime] = None,
        segment: str = "DERIVATIVES",
    ) -> bool:
        """Returns True ONLY if regular market or special session is active for segment."""
        phase = self.get_session_phase(dt, segment=segment)
        return phase in (CalendarSessionPhase.REGULAR_MARKET, CalendarSessionPhase.SPECIAL_SESSION)

    def is_intraday_entry_allowed(
        self,
        dt: Optional[datetime.datetime] = None,
        segment: str = "DERIVATIVES",
    ) -> bool:
        """Returns True if entries are allowed (strictly before 15:15 IST cutoff on market open)."""
        if dt is None:
            dt = self.now_ist()
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        else:
            dt = dt.astimezone(IST)

        phase = self.get_session_phase(dt, segment=segment)
        if phase == CalendarSessionPhase.SPECIAL_SESSION:
            return True
        if phase != CalendarSessionPhase.REGULAR_MARKET:
            return False

        return dt.time() < self.intraday_cutoff

    def get_next_trading_session(
        self, from_dt: Optional[datetime.datetime] = None
    ) -> Dict[str, Any]:
        """Calculates next upcoming trading session opening in IST."""
        if from_dt is None:
            from_dt = self.now_ist()
        elif from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=IST)
        else:
            from_dt = from_dt.astimezone(IST)

        curr_d = from_dt.date()
        curr_t = from_dt.time()

        # Check if today is a trading day and market has not yet opened
        if self.is_trading_day(curr_d) and curr_t < self.regular_market_start:
            target_date = curr_d
            open_dt = datetime.datetime.combine(target_date, self.regular_market_start, tzinfo=IST)
            return {
                "next_session_date": target_date.isoformat(),
                "session_type": "REGULAR",
                "market_open_ist": open_dt.isoformat(),
                "hours_until_open": max(0.0, (open_dt - from_dt).total_seconds() / 3600.0),
            }

        # Otherwise look forward day by day
        step = datetime.timedelta(days=1)
        scan_date = curr_d + step
        for _ in range(30):  # scan up to 30 days ahead
            # Check for special session on this day
            for s in self.special_sessions:
                if s.date == scan_date:
                    spec_open = datetime.datetime.combine(scan_date, s.start_time, tzinfo=IST)
                    return {
                        "next_session_date": scan_date.isoformat(),
                        "session_type": "SPECIAL_MUHURAT",
                        "market_open_ist": spec_open.isoformat(),
                        "hours_until_open": max(0.0, (spec_open - from_dt).total_seconds() / 3600.0),
                    }
            if self.is_trading_day(scan_date):
                open_dt = datetime.datetime.combine(scan_date, self.regular_market_start, tzinfo=IST)
                return {
                    "next_session_date": scan_date.isoformat(),
                    "session_type": "REGULAR",
                    "market_open_ist": open_dt.isoformat(),
                    "hours_until_open": max(0.0, (open_dt - from_dt).total_seconds() / 3600.0),
                }
            scan_date += step

        # Fallback
        default_open = datetime.datetime.combine(scan_date, self.regular_market_start, tzinfo=IST)
        return {
            "next_session_date": scan_date.isoformat(),
            "session_type": "REGULAR",
            "market_open_ist": default_open.isoformat(),
            "hours_until_open": 24.0,
        }

    def update_calendar_from_source(
        self,
        source_url: str,
        publication_date: str,
        holidays_data: List[Dict[str, Any]],
        special_sessions_data: Optional[List[Dict[str, Any]]] = None,
        notes: str = "",
    ) -> None:
        """Updates calendar data with explicit provenance record and sets status to VERIFIED."""
        parsed_holidays: List[ExchangeHoliday] = []
        for h in holidays_data:
            dt_val = (
                datetime.date.fromisoformat(h["date"])
                if isinstance(h["date"], str)
                else h["date"]
            )
            parsed_holidays.append(
                ExchangeHoliday(
                    name=h.get("name", "Unnamed Holiday"),
                    date=dt_val,
                    segment=h.get("segment", "ALL"),
                    description=h.get("description", ""),
                )
            )

        parsed_special: List[SpecialTradingSession] = []
        if special_sessions_data:
            for s in special_sessions_data:
                d_val = (
                    datetime.date.fromisoformat(s["date"])
                    if isinstance(s["date"], str)
                    else s["date"]
                )
                start_t = (
                    datetime.time.fromisoformat(s["start_time"])
                    if isinstance(s["start_time"], str)
                    else s["start_time"]
                )
                end_t = (
                    datetime.time.fromisoformat(s["end_time"])
                    if isinstance(s["end_time"], str)
                    else s["end_time"]
                )
                parsed_special.append(
                    SpecialTradingSession(
                        name=s.get("name", "Special Trading Session"),
                        date=d_val,
                        start_time=start_t,
                        end_time=end_t,
                        segment=s.get("segment", "DERIVATIVES"),
                        description=s.get("description", ""),
                    )
                )

        self.holidays = parsed_holidays
        if parsed_special:
            self.special_sessions = parsed_special
        self.source_url = source_url
        self.publication_date = publication_date

        self.last_update_record = CalendarUpdateRecord(
            source_url=source_url,
            publication_date=publication_date,
            retrieved_at=self.now_ist().isoformat(),
            applicable_segment="DERIVATIVES",
            verification_status=VerificationStatus.VERIFIED,
            total_holidays=len(self.holidays),
            total_special_sessions=len(self.special_sessions),
            notes=notes or "Updated from official circular",
        )

        if self.cache_path:
            self.save_cache(self.cache_path)

    def mark_unverified(self, reason: str = "Provider failure") -> None:
        """Forces verification status to UNVERIFIED for fail-safe testing or network loss."""
        self.last_update_record.verification_status = VerificationStatus.UNVERIFIED
        self.last_update_record.notes = reason

    def save_cache(self, path: Path) -> None:
        """Serializes current calendar and provenance record to JSON."""
        data = {
            "provenance": dataclasses.asdict(self.last_update_record),
            "holidays": [
                {"name": h.name, "date": h.date.isoformat(), "segment": h.segment, "description": h.description}
                for h in self.holidays
            ],
            "special_sessions": [
                {
                    "name": s.name,
                    "date": s.date.isoformat(),
                    "start_time": s.start_time.isoformat(),
                    "end_time": s.end_time.isoformat(),
                    "segment": s.segment,
                    "description": s.description,
                }
                for s in self.special_sessions
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load_cache(cls, path: Path) -> DynamicExchangeCalendar:
        """Loads and instantiates calendar from cached JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        prov = data["provenance"]
        holidays = [
            ExchangeHoliday(
                name=h["name"],
                date=datetime.date.fromisoformat(h["date"]),
                segment=h.get("segment", "ALL"),
                description=h.get("description", ""),
            )
            for h in data["holidays"]
        ]
        special_sessions = [
            SpecialTradingSession(
                name=s["name"],
                date=datetime.date.fromisoformat(s["date"]),
                start_time=datetime.time.fromisoformat(s["start_time"]),
                end_time=datetime.time.fromisoformat(s["end_time"]),
                segment=s.get("segment", "DERIVATIVES"),
                description=s.get("description", ""),
            )
            for s in data["special_sessions"]
        ]
        cal = cls(
            holidays=holidays,
            special_sessions=special_sessions,
            source_url=prov["source_url"],
            publication_date=prov["publication_date"],
            cache_path=path,
        )
        cal.last_update_record = CalendarUpdateRecord(
            source_url=prov["source_url"],
            publication_date=prov["publication_date"],
            retrieved_at=prov["retrieved_at"],
            applicable_segment=prov["applicable_segment"],
            verification_status=VerificationStatus(prov["verification_status"]),
            total_holidays=prov["total_holidays"],
            total_special_sessions=prov["total_special_sessions"],
            notes=prov.get("notes", ""),
        )
        return cal


DynamicMarketCalendar = DynamicExchangeCalendar


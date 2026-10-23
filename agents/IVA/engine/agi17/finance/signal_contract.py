"""AGI 1.7 Trading Signal Contract & Decision Data Model.

Implements the strict signal contract defined in Section 7.3:
- Decision timestamp in IST and data timestamps
- Underlying index value and source
- Instrument/contract ID, expiry, strike, CE/PE type
- Strategy name/version and market regime
- Entry/invalidation conditions, stops, max modeled loss
- All-in costs and liquidity filters
- Decision status: PAPER_SIGNAL | NO_TRADE | DATA_INVALID | RISK_BLOCKED | RESEARCH_ONLY
- Abstention (NO_TRADE) is favored whenever edge or data quality is uncertain
"""

from __future__ import annotations

import datetime
import enum
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


class SignalStatus(str, enum.Enum):
    PAPER_SIGNAL = "PAPER_SIGNAL"
    NO_TRADE = "NO_TRADE"
    DATA_INVALID = "DATA_INVALID"
    RISK_BLOCKED = "RISK_BLOCKED"
    RESEARCH_ONLY = "RESEARCH_ONLY"


class MarketRegime(str, enum.Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGE_BOUND = "RANGE_BOUND"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNCERTAIN = "UNCERTAIN"


@dataclass
class SignalDecision:
    decision_id: str
    decision_status: SignalStatus
    timestamp_ist: str
    data_timestamp: float
    underlying_symbol: str
    underlying_price: float
    market_regime: MarketRegime
    strategy_name: str
    strategy_version: str
    rationale: str

    # Option Contract details (if contract selected)
    contract_id: Optional[str] = None
    option_type: Optional[str] = None  # "CE" | "PE"
    strike_price: Optional[float] = None
    expiry_date: Optional[str] = None

    # Trade parameters & Risk Management
    action: Optional[str] = None  # "BUY" | "SELL"
    simulated_entry_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    target_price: Optional[float] = None
    quantity_units: int = 0
    estimated_all_in_cost: float = 0.0
    maximum_modeled_loss: float = 0.0

    # Invalidation & Quality Filters
    invalidation_condition: str = "Invalidated on technical breach or regime shift"
    quote_quality: str = "VERIFIED_VALID"
    confidence_score: float = 0.0
    known_limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def create_no_trade(
        cls,
        *,
        decision_id: str,
        underlying_price: float,
        reason: str,
        strategy_name: str = "BankNiftyAdaptiveStrategy",
        strategy_version: str = "1.7.0",
        regime: MarketRegime = MarketRegime.UNCERTAIN,
    ) -> SignalDecision:
        now_ist_str = datetime.datetime.now(IST).isoformat()
        return cls(
            decision_id=decision_id,
            decision_status=SignalStatus.NO_TRADE,
            timestamp_ist=now_ist_str,
            data_timestamp=datetime.datetime.now(datetime.timezone.utc).timestamp(),
            underlying_symbol="BANKNIFTY",
            underlying_price=underlying_price,
            market_regime=regime,
            strategy_name=strategy_name,
            strategy_version=strategy_version,
            rationale=reason,
            confidence_score=0.0,
            known_limitations=["Edge uncertain or signal conditions unmet; capital preserved."],
        )

    @classmethod
    def create_data_invalid(
        cls,
        *,
        decision_id: str,
        reason: str,
        underlying_price: float = 0.0,
    ) -> SignalDecision:
        now_ist_str = datetime.datetime.now(IST).isoformat()
        return cls(
            decision_id=decision_id,
            decision_status=SignalStatus.DATA_INVALID,
            timestamp_ist=now_ist_str,
            data_timestamp=datetime.datetime.now(datetime.timezone.utc).timestamp(),
            underlying_symbol="BANKNIFTY",
            underlying_price=underlying_price,
            market_regime=MarketRegime.UNCERTAIN,
            strategy_name="DataIntegrityFilter",
            strategy_version="1.7.0",
            rationale=f"Data verification rejected quote/candle: {reason}",
            confidence_score=0.0,
            known_limitations=["Stale, missing, or contradictory feed blocked position entry."],
        )

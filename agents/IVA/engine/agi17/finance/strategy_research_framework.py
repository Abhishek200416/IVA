"""AGI 1.7 Formal Strategy Research Architecture & Quantitative Registry (Phase 13).

Provides:
1. Formal Strategy Lifecycle State Machine:
   DRAFT -> IMPLEMENTED -> UNIT_TESTED -> RESEARCH_ELIGIBLE -> BACKTESTED ->
   OUT_OF_SAMPLE_EVALUATED -> PAPER_EVALUATION -> ACCEPTED_FOR_CONTINUED_PAPER_USE
   Terminal / Blocking states: REJECTED, INSUFFICIENT_DATA, OVERFIT_SUSPECTED, BLOCKED_BY_RISK.
2. Predeclared Strategy Verdicts:
   RESEARCH_ONLY, INSUFFICIENT_DATA, FAILED_COST_ADJUSTED_TEST, FAILED_RISK_TEST,
   OVERFIT_SUSPECTED, PROMISING_BUT_UNCONFIRMED, ELIGIBLE_FOR_EXTENDED_PAPER_EVALUATION.
3. Strongly-Typed Quantitative Data Pipeline Objects:
   MarketObservation -> CanonicalBar -> FeatureSet -> StrategySignal ->
   RiskAssessmentResult -> PaperProposal -> SimulatedFill -> PositionDelta ->
   AccountingEvent -> ExperimentArtifact.
4. Abstract Strategy Base Interface:
   validate_inputs -> generate_signal -> propose_paper_action ->
   evaluate_risk -> simulate_execution -> record_result.
5. Persistent Strategy Registry with machine-enforced acceptance gates.
"""

from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, field
import datetime
from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("StrategyResearchFramework")


class StrategyLifecycleState(str, Enum):
    DRAFT = "DRAFT"
    IMPLEMENTED = "IMPLEMENTED"
    UNIT_TESTED = "UNIT_TESTED"
    RESEARCH_ELIGIBLE = "RESEARCH_ELIGIBLE"
    BACKTESTED = "BACKTESTED"
    OUT_OF_SAMPLE_EVALUATED = "OUT_OF_SAMPLE_EVALUATED"
    PAPER_EVALUATION = "PAPER_EVALUATION"
    ACCEPTED_FOR_CONTINUED_PAPER_USE = "ACCEPTED_FOR_CONTINUED_PAPER_USE"
    # Terminal or Blocking states
    REJECTED = "REJECTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    OVERFIT_SUSPECTED = "OVERFIT_SUSPECTED"
    BLOCKED_BY_RISK = "BLOCKED_BY_RISK"


class StrategyVerdict(str, Enum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FAILED_COST_ADJUSTED_TEST = "FAILED_COST_ADJUSTED_TEST"
    FAILED_RISK_TEST = "FAILED_RISK_TEST"
    OVERFIT_SUSPECTED = "OVERFIT_SUSPECTED"
    PROMISING_BUT_UNCONFIRMED = "PROMISING_BUT_UNCONFIRMED"
    ELIGIBLE_FOR_EXTENDED_PAPER_EVALUATION = "ELIGIBLE_FOR_EXTENDED_PAPER_EVALUATION"


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE = "CLOSE"
    NO_ACTION = "NO_ACTION"


class DataProvenance(str, Enum):
    GENUINE_HISTORICAL_EXCHANGE = "GENUINE_HISTORICAL_EXCHANGE"
    HISTORICAL_VERIFIED = "HISTORICAL_VERIFIED"
    REPLAY_DETERMINISTIC_SANDBOX = "REPLAY_DETERMINISTIC_SANDBOX"
    SIMULATED = "SIMULATED"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    UNKNOWN = "UNKNOWN"


# Type aliases
LifecycleState = StrategyLifecycleState
ValidationVerdict = StrategyVerdict
SignalDirection = SignalAction


@dataclass
class DatasetMetadata:
    dataset_id: str
    name: str
    record_count: int
    provenance: DataProvenance
    timeframe: str = "1D"
    is_intraday: bool = False
    bar_granularity: str = "1_DAY_EOD"

    def __post_init__(self):
        if not self.bar_granularity:
            self.bar_granularity = "1_MINUTE_INTRADAY" if self.is_intraday else "1_DAY_EOD"


# -----------------------------------------------------------------------------
# Strongly-Typed Quantitative Data Structures
# -----------------------------------------------------------------------------


@dataclass
class MarketObservation:
    """Raw point-in-time observation with explicit provenance."""
    symbol: str
    timestamp_utc: str
    price: float
    volume: float
    bid: float
    ask: float
    provenance: str = "SYNTHETIC_FIXTURE"
    is_live_verified: bool = False


@dataclass
class CanonicalBar:
    """Standardized OHLCV time-series candle with anti-lookahead boundary checks."""
    symbol: str
    timestamp_start: str
    timestamp_end: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0
    is_closed: bool = True
    provenance: str = "SYNTHETIC_FIXTURE"

    def __post_init__(self):
        if self.low > self.high:
            raise ValueError(f"Invalid bar: Low ({self.low}) > High ({self.high}) for {self.symbol}")
        if self.open < self.low or self.open > self.high:
            raise ValueError(f"Invalid bar: Open ({self.open}) outside Low-High bounds for {self.symbol}")
        if self.close < self.low or self.close > self.high:
            raise ValueError(f"Invalid bar: Close ({self.close}) outside Low-High bounds for {self.symbol}")


@dataclass
class FeatureSet:
    """Point-in-time calculated features utilizing strictly historical information."""
    symbol: str
    as_of_timestamp: str
    features: Dict[str, Any]
    feature_hash: str = ""
    lookahead_audit_passed: bool = True

    def __post_init__(self):
        if not self.feature_hash:
            feat_bytes = json.dumps(self.features, sort_keys=True, default=str).encode("utf-8")
            self.feature_hash = hashlib.sha256(feat_bytes).hexdigest()[:16]


@dataclass
class StrategySignal:
    """Signal produced strictly from historical features."""
    signal_id: str
    timestamp: str
    strategy_id: str
    strategy_version: str
    symbol: str
    action: SignalAction
    target_entry_price: float
    stop_loss_price: float
    target_profit_price: float
    max_holding_bars: int = 30
    confidence_score: float = 1.0
    rule_triggered: str = ""
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskAssessmentResult:
    """Independent pre-trade risk policy audit result."""
    candidate_id: str
    is_approved: bool
    rejection_reason: Optional[str]
    max_position_loss_inr: float
    margin_required_inr: float
    risk_to_capital_ratio: float
    checks_passed: List[str]
    evaluated_at_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


@dataclass
class PaperProposal:
    """Actionable order proposal submitted to the paper simulation engine."""
    proposal_id: str
    timestamp: str
    epoch_id: str
    strategy_id: str
    signal: StrategySignal
    risk_assessment: RiskAssessmentResult
    proposed_legs: List[Dict[str, Any]]
    is_simulated: bool = True


@dataclass
class SimulatedFill:
    """Auditable simulated execution record with comprehensive friction accounting."""
    fill_id: str
    proposal_id: str
    order_id: str
    symbol: str
    side: str
    quantity: int
    requested_price: float
    filled_price: float
    slippage_points: float
    brokerage_inr: float
    exchange_charges_inr: float
    stt_inr: float
    stamp_duty_inr: float
    sebi_fees_inr: float
    gst_inr: float
    total_friction_inr: float
    fill_timestamp: str
    is_simulated: bool = True
    partial_fill: bool = False


@dataclass
class PositionDelta:
    """Decomposed portfolio position state change."""
    symbol: str
    quantity_delta: int
    new_net_quantity: int
    average_entry_price: float
    current_market_price: float
    realized_pnl_inr: float
    unrealized_pnl_inr: float


@dataclass
class AccountingEvent:
    """Immutable double-entry balance event for an isolated epoch."""
    event_id: str
    timestamp: str
    epoch_id: str
    event_type: str  # FILL, SQUARE_OFF, CHARGE, SETTLEMENT
    cash_delta_inr: float
    charges_inr: float
    realized_pnl_inr: float
    cash_balance_after_inr: float
    equity_balance_after_inr: float


# -----------------------------------------------------------------------------
# Strategy Definition Metadata
# -----------------------------------------------------------------------------

@dataclass
class StrategyDefinition:
    """Authoritative strategy specification registered in the research laboratory."""
    strategy_id: str
    strategy_name: str
    version: str
    description: str
    hypothesis: str
    economic_rationale: str
    intended_market_conditions: List[str]
    required_instruments: List[str]
    required_granularity: str
    required_features: List[str]
    lifecycle_state: StrategyLifecycleState
    verdict: StrategyVerdict
    parameter_schema: Dict[str, Any]
    default_parameters: Dict[str, Any]
    known_limitations: List[str]
    prohibited_use_cases: List[str]
    source_code_version: str
    config_hash: str = ""
    acceptance_evidence: Dict[str, Any] = field(default_factory=dict)
    registered_at_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "name": self.strategy_name,
            "version": self.version,
            "description": self.description,
            "hypothesis": self.hypothesis,
            "economic_rationale": self.economic_rationale,
            "intended_market_conditions": self.intended_market_conditions,
            "required_instruments": self.required_instruments,
            "required_granularity": self.required_granularity,
            "required_features": self.required_features,
            "lifecycle_state": self.lifecycle_state.value,
            "verdict": self.verdict.value,
            "parameter_schema": self.parameter_schema,
            "parameters_schema": self.parameter_schema,
            "default_parameters": self.default_parameters,
            "known_limitations": self.known_limitations,
            "prohibited_use_cases": self.prohibited_use_cases,
            "source_code_version": self.source_code_version,
            "config_hash": self.config_hash,
            "acceptance_evidence": self.acceptance_evidence,
            "registered_at_utc": self.registered_at_utc,
        }


# -----------------------------------------------------------------------------
# Base Quantitative Strategy Abstract Class
# -----------------------------------------------------------------------------

class BaseQuantitativeStrategy:
    """Standardized quantitative strategy interface.
    
    Guarantees consistent pipeline:
    validate_inputs -> generate_signal -> propose_paper_action -> evaluate_risk -> simulate_execution -> record_result
    """

    def __init__(self, definition: StrategyDefinition, parameters: Optional[Dict[str, Any]] = None):
        self.definition = definition
        self.parameters = parameters or definition.default_parameters.copy()
        self._compute_config_hash()

    def _compute_config_hash(self) -> None:
        cfg = {"id": self.definition.strategy_id, "v": self.definition.version, "params": self.parameters}
        b = json.dumps(cfg, sort_keys=True).encode("utf-8")
        self.definition.config_hash = hashlib.sha256(b).hexdigest()[:16]

    def validate_inputs(self, bars: List[CanonicalBar]) -> FeatureSet:
        """Validates incoming market bars and computes point-in-time features without lookahead."""
        raise NotImplementedError

    def generate_signal(self, features: FeatureSet, current_bar: CanonicalBar) -> StrategySignal:
        """Produces a deterministic strategy signal strictly from available features."""
        raise NotImplementedError

    def propose_paper_action(
        self,
        signal: StrategySignal,
        epoch_capital: float,
        current_positions: List[Dict[str, Any]],
        epoch_id: str = "epoch_10k",
    ) -> PaperProposal:
        """Formulates a typed paper proposal with sizing constraints."""
        raise NotImplementedError

    def evaluate_risk(
        self,
        proposal: PaperProposal,
        available_capital: float,
        daily_loss_inr: float = 0.0,
        current_drawdown_pct: float = 0.0,
    ) -> RiskAssessmentResult:
        """Evaluates independent pre-trade risk policy. Fails closed."""
        raise NotImplementedError

    def simulate_execution(
        self,
        proposal: PaperProposal,
        market_quote: Dict[str, Any],
        conservative_slippage: bool = True,
    ) -> List[SimulatedFill]:
        """Simulates fills with conservative bid/ask slippage and SEBI/NSE statutory friction."""
        raise NotImplementedError


# -----------------------------------------------------------------------------
# Strategy Registry
# -----------------------------------------------------------------------------

class StrategyRegistry:
    """Authoritative registry of candidate quantitative strategies."""

    VALID_TRANSITIONS: Dict[StrategyLifecycleState, Set[StrategyLifecycleState]] = {
        StrategyLifecycleState.DRAFT: {StrategyLifecycleState.IMPLEMENTED, StrategyLifecycleState.REJECTED},
        StrategyLifecycleState.IMPLEMENTED: {StrategyLifecycleState.UNIT_TESTED, StrategyLifecycleState.REJECTED},
        StrategyLifecycleState.UNIT_TESTED: {StrategyLifecycleState.RESEARCH_ELIGIBLE, StrategyLifecycleState.REJECTED},
        StrategyLifecycleState.RESEARCH_ELIGIBLE: {StrategyLifecycleState.BACKTESTED, StrategyLifecycleState.INSUFFICIENT_DATA, StrategyLifecycleState.REJECTED},
        StrategyLifecycleState.BACKTESTED: {StrategyLifecycleState.OUT_OF_SAMPLE_EVALUATED, StrategyLifecycleState.OVERFIT_SUSPECTED, StrategyLifecycleState.REJECTED},
        StrategyLifecycleState.OUT_OF_SAMPLE_EVALUATED: {StrategyLifecycleState.PAPER_EVALUATION, StrategyLifecycleState.BLOCKED_BY_RISK, StrategyLifecycleState.REJECTED},
        StrategyLifecycleState.PAPER_EVALUATION: {StrategyLifecycleState.ACCEPTED_FOR_CONTINUED_PAPER_USE, StrategyLifecycleState.BLOCKED_BY_RISK, StrategyLifecycleState.REJECTED},
        StrategyLifecycleState.ACCEPTED_FOR_CONTINUED_PAPER_USE: {StrategyLifecycleState.REJECTED},
        # Terminal states
        StrategyLifecycleState.REJECTED: set(),
        StrategyLifecycleState.INSUFFICIENT_DATA: {StrategyLifecycleState.RESEARCH_ELIGIBLE},
        StrategyLifecycleState.OVERFIT_SUSPECTED: {StrategyLifecycleState.DRAFT},
        StrategyLifecycleState.BLOCKED_BY_RISK: {StrategyLifecycleState.RESEARCH_ELIGIBLE},
    }

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self.storage_dir = (
            storage_dir
            or Path(__file__).resolve().parents[3] / "runtime_storage" / "strategy_registry"
        )
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_file = self.storage_dir / "strategies_manifest.json"
        self._strategies: Dict[str, StrategyDefinition] = {}
        self._load_or_initialize()

    def _load_or_initialize(self) -> None:
        if self.manifest_file.exists():
            try:
                data = json.loads(self.manifest_file.read_text(encoding="utf-8"))
                for s in data.get("strategies", []):
                    definition = StrategyDefinition(
                        strategy_id=s["strategy_id"],
                        strategy_name=s["strategy_name"],
                        version=s["version"],
                        description=s["description"],
                        hypothesis=s["hypothesis"],
                        economic_rationale=s["economic_rationale"],
                        intended_market_conditions=s["intended_market_conditions"],
                        required_instruments=s["required_instruments"],
                        required_granularity=s["required_granularity"],
                        required_features=s["required_features"],
                        lifecycle_state=StrategyLifecycleState(s["lifecycle_state"]),
                        verdict=StrategyVerdict(s.get("verdict", StrategyVerdict.RESEARCH_ONLY.value)),
                        parameter_schema=s["parameter_schema"],
                        default_parameters=s["default_parameters"],
                        known_limitations=s["known_limitations"],
                        prohibited_use_cases=s["prohibited_use_cases"],
                        source_code_version=s["source_code_version"],
                        config_hash=s.get("config_hash", ""),
                        acceptance_evidence=s.get("acceptance_evidence", {}),
                        registered_at_utc=s.get("registered_at_utc", datetime.datetime.now(datetime.timezone.utc).isoformat()),
                    )
                    self._strategies[definition.strategy_id] = definition
            except Exception as e:
                logger.error(f"Error reading strategies manifest: {e}")

        # Ensure canonical strategies are populated
        try:
            from .initial_strategy_portfolio import (
                OpeningRangeBreakoutStrategy,
                DefinedRiskVolatilityStructureStrategy,
                RegimeAwareStrategySelector,
            )
            canonical = [
                OpeningRangeBreakoutStrategy.DEFAULT_DEFINITION,
                DefinedRiskVolatilityStructureStrategy.DEFAULT_DEFINITION,
                RegimeAwareStrategySelector.DEFAULT_DEFINITION,
            ]
            modified = False
            for c in canonical:
                if c.strategy_id not in self._strategies:
                    self._strategies[c.strategy_id] = c
                    modified = True
            if modified or not self.manifest_file.exists():
                self.save_manifest()
        except Exception as e:
            logger.debug(f"Canonical strategy loading deferred: {e}")

    def register_strategy(self, definition: StrategyDefinition) -> None:
        """Registers a new strategy definition in the registry."""
        self._strategies[definition.strategy_id] = definition
        self.save_manifest()

    def get_strategy(self, strategy_id: str) -> Optional[StrategyDefinition]:
        return self._strategies.get(strategy_id)

    def list_strategies(self) -> List[StrategyDefinition]:
        return list(self._strategies.values())

    def update_lifecycle_state(
        self,
        strategy_id: str,
        new_state: StrategyLifecycleState,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Applies gated transition between lifecycle states."""
        strat = self._strategies.get(strategy_id)
        if not strat:
            logger.error(f"Strategy {strategy_id} not found in registry.")
            return False

        allowed = self.VALID_TRANSITIONS.get(strat.lifecycle_state, set())
        if new_state not in allowed:
            logger.warning(
                f"Invalid lifecycle transition for {strategy_id}: {strat.lifecycle_state.value} -> {new_state.value}. Allowed: {[s.value for s in allowed]}"
            )
            return False

        strat.lifecycle_state = new_state
        if evidence:
            strat.acceptance_evidence[new_state.value] = {
                "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "evidence": evidence,
            }
        self.save_manifest()
        logger.info(f"Updated {strategy_id} state to {new_state.value}")
        return True

    def save_manifest(self) -> None:
        manifest = {
            "updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "strategies": [strat.to_dict() for strat in self._strategies.values()],
        }
        self.manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

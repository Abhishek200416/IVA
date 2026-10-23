"""AGI 1.7 End-to-End Strategy Decision Tracing & Reproducibility Engine (Phase 12.4).

Traces the entire deterministic causal pipeline:
Market observation → validation → calculated features → research evidence →
agent assessment → candidate signal → deterministic pre-trade risk checks →
NO_TRADE or paper approval → simulated execution → cost reconciliation →
trade outcome → memory record.

Stores:
- Unique decision ID and linked OpenTelemetry trace ID.
- Target account epoch ID (e.g. EPOCH-PAPER-10K-20261014-001).
- Strategy ID and configuration/formula version.
- Exact input observation IDs, feature values, and units.
- Agent deliberation conclusions separated from deterministic checks.
- Detailed pre-trade risk check results (killswitch, slippage, margin).
- Paper order ID, simulated fill price, and statutory transaction costs.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("DecisionTraceEngine")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")


class DecisionOutcome(str, Enum):
    APPROVED_FOR_PAPER = "APPROVED_FOR_PAPER"
    REJECTED_RISK = "REJECTED_RISK"
    NO_TRADE_CONVICTION = "NO_TRADE_CONVICTION"
    BLOCKED_SESSION = "BLOCKED_SESSION"
    BLOCKED_DATA_STALE = "BLOCKED_DATA_STALE"


class StrategyDecisionTrace:
    """Immutable audit record linking input evidence to execution outcome."""

    def __init__(
        self,
        *,
        trace_id: str,
        epoch_id: str,
        strategy_id: str,
        strategy_version: str,
        input_observation_ids: List[str],
        feature_values: Dict[str, Any],
        formula_version: str,
        research_record_ids: Optional[List[str]] = None,
        agent_conclusions: Optional[Dict[str, str]] = None,
        pre_trade_risk_checks: Optional[Dict[str, bool]] = None,
        decision_outcome: DecisionOutcome = DecisionOutcome.NO_TRADE_CONVICTION,
        rejection_reason: Optional[str] = None,
        paper_order_id: Optional[str] = None,
        simulated_fill: Optional[Dict[str, Any]] = None,
        statutory_drag_inr: Optional[float] = None,
        memory_record_id: Optional[str] = None,
        timestamp: Optional[datetime.datetime] = None,
    ):
        now_ist = datetime.datetime.now(IST)
        self.trace_id = trace_id
        self.epoch_id = epoch_id
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version
        self.input_observation_ids = list(input_observation_ids)
        self.feature_values = dict(feature_values)
        self.formula_version = formula_version
        self.research_record_ids = list(research_record_ids or [])
        self.agent_conclusions = dict(agent_conclusions or {})
        self.pre_trade_risk_checks = dict(pre_trade_risk_checks or {})
        self.decision_outcome = decision_outcome
        self.rejection_reason = rejection_reason
        self.paper_order_id = paper_order_id
        self.simulated_fill = simulated_fill
        self.statutory_drag_inr = statutory_drag_inr
        self.memory_record_id = memory_record_id
        self.timestamp = timestamp or now_ist

        # Deterministic decision fingerprint for reproducibility verification
        raw_key = (
            f"{self.strategy_id}:{self.strategy_version}:{self.formula_version}:"
            f"{sorted(self.input_observation_ids)}:{sorted(self.feature_values.items())}:"
            f"{self.decision_outcome.value}"
        )
        self.decision_id = f"DEC-{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:16]}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "trace_id": self.trace_id,
            "epoch_id": self.epoch_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "input_observation_ids": self.input_observation_ids,
            "feature_values": self.feature_values,
            "formula_version": self.formula_version,
            "research_record_ids": self.research_record_ids,
            "agent_conclusions": self.agent_conclusions,
            "pre_trade_risk_checks": self.pre_trade_risk_checks,
            "decision_outcome": self.decision_outcome.value,
            "rejection_reason": self.rejection_reason,
            "paper_order_id": self.paper_order_id,
            "simulated_fill": self.simulated_fill,
            "statutory_drag_inr": self.statutory_drag_inr,
            "memory_record_id": self.memory_record_id,
            "timestamp_iso": self.timestamp.isoformat(),
        }


class DecisionTraceRepository:
    """Append-only storage and reproducibility evaluator for strategy decision traces."""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = (
            storage_dir or Path(__file__).resolve().parent.parent / "runtime_storage" / "traces"
        )
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.decisions_file = self.storage_dir / "strategy_decisions.jsonl"
        self._decisions: Dict[str, StrategyDecisionTrace] = {}
        self._load_decisions()

    def _load_decisions(self) -> None:
        if self.decisions_file.exists():
            try:
                for line in self.decisions_file.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    trace = StrategyDecisionTrace(
                        trace_id=data["trace_id"],
                        epoch_id=data["epoch_id"],
                        strategy_id=data["strategy_id"],
                        strategy_version=data["strategy_version"],
                        input_observation_ids=data["input_observation_ids"],
                        feature_values=data["feature_values"],
                        formula_version=data["formula_version"],
                        research_record_ids=data.get("research_record_ids"),
                        agent_conclusions=data.get("agent_conclusions"),
                        pre_trade_risk_checks=data.get("pre_trade_risk_checks"),
                        decision_outcome=DecisionOutcome(data["decision_outcome"]),
                        rejection_reason=data.get("rejection_reason"),
                        paper_order_id=data.get("paper_order_id"),
                        simulated_fill=data.get("simulated_fill"),
                        statutory_drag_inr=data.get("statutory_drag_inr"),
                        memory_record_id=data.get("memory_record_id"),
                    )
                    self._decisions[trace.decision_id] = trace
            except Exception as exc:
                logger.warning(f"Error loading decision traces: {exc}")

    def record_decision(self, trace: StrategyDecisionTrace) -> StrategyDecisionTrace:
        """Appends decision trace to storage and index."""
        self._decisions[trace.decision_id] = trace
        try:
            with open(self.decisions_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(trace.to_dict()) + "\n")
        except Exception as exc:
            logger.warning(f"Failed to append decision trace: {exc}")
        return trace

    def get_by_id(self, decision_id: str) -> Optional[StrategyDecisionTrace]:
        return self._decisions.get(decision_id)

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        traces = list(self._decisions.values())
        traces.sort(key=lambda t: t.timestamp, reverse=True)
        return [t.to_dict() for t in traces[:limit]]

    def verify_reproducibility(
        self,
        decision_id: str,
        evaluate_fn: Any,
    ) -> Tuple[bool, Optional[str]]:
        """Verifies that re-evaluating the strategy with saved inputs yields the identical outcome."""
        saved = self.get_by_id(decision_id)
        if not saved:
            return False, f"Decision {decision_id} not found in repository"

        # Re-run deterministic evaluation function
        reproduced_outcome, reason = evaluate_fn(
            strategy_id=saved.strategy_id,
            strategy_version=saved.strategy_version,
            features=saved.feature_values,
            risk_checks=saved.pre_trade_risk_checks,
        )

        if reproduced_outcome != saved.decision_outcome:
            return False, f"Reproducibility divergence: original was {saved.decision_outcome.value}, re-evaluation produced {reproduced_outcome.value}"

        return True, None

"""Three-Agent Persona Contract & Disagreement Protocol for AGI 1.7 OMEGA COMMAND.

Implements Phase 6 Objective 2 & Objective 15:
- Formal versioned personas for Alexa (v1.7.2), Emily (v1.7.2), and Max (v1.7.2).
- Structured inter-agent communication protocol with verifiable evidence citations.
- Dialectical consensus evaluation and binding disagreement preservation (Prefer No-Trade).
- End-of-session structured agent reports and persona evolution tracking.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class AgentPersona:
    """Formal definition of a specialized agent's persona, responsibilities, and authority."""
    name: str
    version: str
    role: str
    responsibilities: List[str]
    authority_scope: str
    binding_rejection_authority: bool
    assigned_tools: List[str]
    identified_failure_modes: List[str]


# Authoritative version 1.7.2 personas (preserved for backwards-compatible test contracts)
ALEXA_PERSONA = AgentPersona(
    name="Alexa",
    version="1.7.2",
    role="Visual Computer Operator and Execution Specialist",
    responsibilities=[
        "Owns the authoritative visible browser session on WinSta0\\Default (port 9229).",
        "Operates the single serialized FIFO mouse and keyboard interaction queue.",
        "Captures fresh screenshots and validates page, tab, URL, and contract before every action.",
        "Verifies observed visual state mutation after every physical actuation.",
        "Invalidates cached coordinates immediately upon navigation, scroll, or layout change.",
        "Enforces zero fabrication of clicks, screenshots, tabs, orders, or broker confirmations.",
    ],
    authority_scope="Physical browser actuation and visible UI state verification",
    binding_rejection_authority=True,  # Alexa can reject if UI/contract state is unverified or ambiguous
    assigned_tools=["computer_use_engine", "serialized_interaction_queue", "cdp_mouse", "user32_focus"],
    identified_failure_modes=["Focus loss during OS notification", "Coordinate drift after dynamic layout shift"],
)

EMILY_PERSONA = AgentPersona(
    name="Emily",
    version="1.7.2",
    role="Global Financial Intelligence and News Researcher",
    responsibilities=[
        "Scans 5 global risk layers: Equities/VIX, Macro/CB, Commodities/FX, Domestic Flows, Derivatives.",
        "Preserves primary source URLs, publication timestamps, and official classification.",
        "Enforces cryptographic SHA-256 deduplication of incoming financial reports.",
        "Differentiates provisional EOD FII/DII cash flows from live market feeds.",
        "Assesses geopolitical tail events, sanction shocks, and transmission channels.",
        "Strictly prohibited from authorizing trade orders derived solely from news/sentiment.",
    ],
    authority_scope="Global macroeconomic risk radar and news evidence ledger",
    binding_rejection_authority=True,  # Emily can veto trades during severe macro or geopolitical shocks
    assigned_tools=["global_risk_radar", "evidence_ledger", "fii_dii_flow_tracker"],
    identified_failure_modes=["Headline sentiment false alarm", "Lagged provisional flow revisions"],
)

MAX_PERSONA = AgentPersona(
    name="Max",
    version="1.7.2",
    role="Quantitative Researcher, Risk Engineer and Strategy Evaluator",
    responsibilities=[
        "Computes multi-horizon analysis across 1m, 5m, 15m, 1h, and 1d timeframes with 14 models.",
        "Generates at least 10 genuinely distinct candidates (Bullish, Bearish, Neutral) per session.",
        "Calculates Black-Scholes Greeks (Delta, Gamma, Theta, Vega) and dynamic scenario stress tests.",
        "Enforces hard downside risk: <= 0.5% planned loss, <= 1.0% portfolio risk, <= 1.5% daily drawdown.",
        "Evaluates Kelly sizing as an informational research benchmark without overriding risk caps.",
        "Conducts 10-step post-trade post-mortems and maintains walk-forward out-of-sample promotion gates.",
    ],
    authority_scope="Mathematical modeling, candidate generation, and binding risk limits",
    binding_rejection_authority=True,  # Max possesses binding pre-trade RMS rejection authority
    assigned_tools=["multi_horizon_quant_engine", "options_greeks", "adaptive_strategy_learner"],
    identified_failure_modes=["Model overfitting on limited volatility regimes", "Slippage underestimation"],
)

# Authoritative version 1.7.3 squad personas (Manager Iva / Manager Abhi + Alex / Emily / Max)
MANAGER_ABHI_PERSONA = AgentPersona(
    name="Manager Abhi",
    version="1.7.3",
    role="Lead Systems Architect, Operations Coordinator & Operator Liaison",
    responsibilities=[
        "Acts as the sovereign operator-facing liaison who receives direct orders and instructions from the user.",
        "Translates operator intent into fail-closed trading configurations under strict capital limits (₹10,000 epoch_10k).",
        "Enforces the permanent fail-closed safety gate: LIVE_ORDER_DISPATCH_ENABLED = False.",
        "Coordinates, supervises, and arbitrates dialectical consensus between Emily, Alex, and Max.",
        "Manages continuous synchronization with central brain files (GEMINI.md, omega_memory.db, library playbooks).",
        "Monitors token budget and active skill allocations across trading, news research, and UI controls.",
        "Issues executive manager directives and emergency circuit breaker halts when risk anomalies emerge.",
    ],
    authority_scope="Executive operational command, operator order interface, and systemic fail-closed gating",
    binding_rejection_authority=True,
    assigned_tools=["omega_control_plane", "brain_synchronizer", "operator_console", "skill_budget_manager", "emergency_circuit_breaker"],
    identified_failure_modes=["Unverified operator prompt ambiguity", "Subagent state divergence"],
)

MANAGER_IVA_PERSONA = AgentPersona(
    name="Manager Iva",
    version="1.7.3",
    role="Lead Systems Architect, Operations Coordinator & Operator Liaison",
    responsibilities=[
        "Acts as the sovereign operator-facing liaison who receives direct orders and instructions from the user.",
        "Translates operator intent into fail-closed trading configurations under strict capital limits (₹10,000 epoch_10k).",
        "Enforces the permanent fail-closed safety gate: LIVE_ORDER_DISPATCH_ENABLED = False.",
        "Coordinates, supervises, and arbitrates dialectical consensus between Emily, Alex, and Max.",
        "Manages continuous synchronization with central brain files (GEMINI.md, omega_memory.db, library playbooks).",
        "Monitors token budget and active skill allocations across trading, news research, and UI controls.",
        "Issues executive manager directives and emergency circuit breaker halts when risk anomalies emerge.",
    ],
    authority_scope="Executive operational command, operator order interface, and systemic fail-closed gating",
    binding_rejection_authority=True,
    assigned_tools=["omega_control_plane", "brain_synchronizer", "operator_console", "skill_budget_manager", "emergency_circuit_breaker"],
    identified_failure_modes=["Unverified operator prompt ambiguity", "Subagent state divergence"],
)


ALEX_PERSONA = AgentPersona(
    name="Alex",
    version="1.7.3",
    role="High-Frequency Microstructure, Order Flow & L3 Queue Execution Specialist",
    responsibilities=[
        "Owns the authoritative visible browser session on WinSta0\\Default (port 9229).",
        "Computes Level 3 order cancellation shock process and monitors cascade hazard H_cancel.",
        "Analyzes Multi-Level Order Flow Imbalance (MLOFI) across L1-L5 price levels.",
        "Tracks 8-node Hawkes directed graph centrality and systemic contagion vectors.",
        "Enforces quote pullback alerts and prevents adverse queue priority depletion.",
        "Operates the single serialized FIFO mouse and keyboard interaction queue with zero fabrication.",
    ],
    authority_scope="Microstructure queue dynamics, L3 cancellation hazards, and browser execution",
    binding_rejection_authority=True,
    assigned_tools=["computer_use_engine", "serialized_interaction_queue", "hawkes_l3_engine", "cdp_mouse", "user32_focus"],
    identified_failure_modes=["Microstructure latency jitter", "Queue position estimation drift"],
)


@dataclass
class AgentMessage:
    """Structured message conforming to Phase 6 Objective 2."""
    session_id: str
    timestamp: str
    sender: str  # Alexa, Emily, Max, Orchestrator
    data_source: str
    proposed_action: str
    inputs: Dict[str, Any]
    calculations: Dict[str, Any]
    uncertainty: float  # 0.0 (certain) to 1.0 (completely uncertain)
    evidence_references: List[str]
    conclusion: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DisagreementRecord:
    """Audit record for preserved material disagreements between agents."""
    disagreement_id: str
    session_id: str
    timestamp: str
    topic: str
    agent_stances: Dict[str, str]
    evidence_ledger: Dict[str, List[str]]
    resolution: str  # PREFER_NO_TRADE, RESOLVED_WITH_EVIDENCE
    justification: str


@dataclass
class OrderApprovalConsensus:
    """Explicit, fresh, order-specific consensus record across Emily, Max, and Alexa."""
    consensus_id: str
    session_id: str
    symbol: str
    action: str  # "BUY" or "SELL"
    quantity: int
    price: float
    status: str  # "APPROVED_FOR_EXECUTION", "PREFER_NO_TRADE", "VETOED"
    timestamp: float
    timestamp_str: str
    emily_approved: bool
    max_approved: bool
    alexa_approved: bool
    disagreement_record: Optional[DisagreementRecord] = None
    rejection_reasons: List[str] = field(default_factory=list)

    def is_fresh(self, max_age_seconds: float = 60.0) -> bool:
        return (time.time() - self.timestamp) <= max_age_seconds


@dataclass
class EndOfSessionAgentReport:
    """Structured end-of-session report produced by each agent for persona evolution."""
    agent_name: str
    version: str
    session_id: str
    timestamp: str
    completed_tasks_count: int
    findings_summary: str
    unresolved_questions: List[str]
    contributed_evidence_count: int
    rejections_issued_count: int
    identified_failure_events: List[str]
    suggested_improvements: str


class ThreeAgentContractCoordinator:
    """Coordinates Alexa, Emily, and Max, enforcing persona contracts and dialectical debate."""

    def __init__(self, storage_dir: Path | str) -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "three_agent_memory.db"

        self.alexa = ALEXA_PERSONA
        self.emily = EMILY_PERSONA
        self.max = MAX_PERSONA
        self.is_active: bool = True
        self.latest_consensus: Optional[OrderApprovalConsensus] = None
        self.order_consensuses: Dict[str, OrderApprovalConsensus] = {}

        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_database(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agent_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    data_source TEXT NOT NULL,
                    proposed_action TEXT NOT NULL,
                    inputs_json TEXT NOT NULL,
                    calculations_json TEXT NOT NULL,
                    uncertainty REAL NOT NULL,
                    evidence_json TEXT NOT NULL,
                    conclusion TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS material_disagreements (
                    disagreement_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    stances_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    justification TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_agent_reports (
                    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    tasks_completed INTEGER NOT NULL,
                    findings TEXT NOT NULL,
                    unresolved_json TEXT NOT NULL,
                    evidence_count INTEGER NOT NULL,
                    rejections_count INTEGER NOT NULL,
                    failures_json TEXT NOT NULL,
                    improvements TEXT NOT NULL
                );
            """)

    def log_message(self, message: AgentMessage) -> None:
        """Stores a structured message in the audit log."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO agent_messages (
                    session_id, timestamp, sender, data_source, proposed_action,
                    inputs_json, calculations_json, uncertainty, evidence_json, conclusion
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message.session_id,
                message.timestamp,
                message.sender,
                message.data_source,
                message.proposed_action,
                json.dumps(message.inputs),
                json.dumps(message.calculations),
                message.uncertainty,
                json.dumps(message.evidence_references),
                message.conclusion,
            ))

    def log_disagreement(self, record: DisagreementRecord) -> None:
        """Stores a material disagreement record in the audit database."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO material_disagreements (
                    disagreement_id, session_id, timestamp, topic,
                    stances_json, evidence_json, resolution, justification
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.disagreement_id,
                record.session_id,
                record.timestamp,
                record.topic,
                json.dumps(record.agent_stances),
                json.dumps(record.evidence_ledger),
                record.resolution,
                record.justification,
            ))

    def evaluate_consensus(
        self,
        session_id: str,
        emily_radar_status: Dict[str, Any],
        max_quant_candidate: Dict[str, Any],
        alexa_ui_verification: Dict[str, Any],
    ) -> Tuple[bool, str, Optional[DisagreementRecord]]:
        """Evaluates dialectical consensus across Emily, Max, and Alexa.

        Policy:
        - If any agent issues a material veto or identifies an unresolvable risk:
          Preserve the disagreement and return (False, "PREFER_NO_TRADE", record).
        - If all three agents align with evidence-backed validation:
          Return (True, "APPROVED_FOR_EXECUTION", None).
        """
        now_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M:%S IST")
        disagreements: Dict[str, str] = {}
        evidence_dict: Dict[str, List[str]] = {}

        # 1. Emily Macro Risk Check
        emily_tail_risk = emily_radar_status.get("tail_risk_flag", False)
        emily_sentiment_driven = emily_radar_status.get("is_sentiment_only", False)
        if emily_tail_risk:
            disagreements["Emily"] = "VETO: Severe macro or geopolitical tail risk active."
            evidence_dict["Emily"] = emily_radar_status.get("evidence_sources", ["Global Risk Radar"])
        elif emily_sentiment_driven:
            disagreements["Emily"] = "VETO: Proposed trade derived solely from headline sentiment."
            evidence_dict["Emily"] = ["Emily Persona Rule: Sentiment-only orders strictly prohibited"]

        # 2. Max Quantitative & RMS Risk Check
        max_decision = max_quant_candidate.get("decision", "REJECTED")
        net_expectancy = max_quant_candidate.get("net_expectancy_inr", -1.0)
        risk_breach = max_quant_candidate.get("risk_calc_inr", 9999.0) > 250.0  # 0.5% of 50k capital
        if max_decision != "APPROVED" or net_expectancy <= 0.0 or risk_breach:
            disagreements["Max"] = f"VETO: RMS risk breach or negative expectancy (Decision: {max_decision}, Net: ₹{net_expectancy:.2f})."
            evidence_dict["Max"] = [max_quant_candidate.get("approval_or_rejection_reason", "Quantitative RMS limit exceeded")]

        # 3. Alexa UI & Contract State Check
        alexa_ready = alexa_ui_verification.get("browser_ready", False)
        alexa_verified_inputs = alexa_ui_verification.get("inputs_verified", False)
        if not alexa_ready or not alexa_verified_inputs:
            disagreements["Alexa"] = f"VETO: Browser UI state unverified or order form inputs ambiguous (Ready: {alexa_ready}, Verified: {alexa_verified_inputs})."
            evidence_dict["Alexa"] = ["Alexa Persona Rule: Actuation blocked when UI state is unverified"]

        # If any disagreements exist, preserve and trigger PREFER_NO_TRADE
        if disagreements:
            disagreement_id = f"DISAGREE-{int(time.time() * 1000)}"
            record = DisagreementRecord(
                disagreement_id=disagreement_id,
                session_id=session_id,
                timestamp=now_str,
                topic=f"Candidate Evaluation for {max_quant_candidate.get('instrument', 'UNKNOWN')}",
                agent_stances=disagreements,
                evidence_ledger=evidence_dict,
                resolution="PREFER_NO_TRADE",
                justification="Consensus not reached: Material disagreement among specialist agents. Capital preserved.",
            )

            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO material_disagreements (
                        disagreement_id, session_id, timestamp, topic,
                        stances_json, evidence_json, resolution, justification
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record.disagreement_id,
                    record.session_id,
                    record.timestamp,
                    record.topic,
                    json.dumps(record.agent_stances),
                    json.dumps(record.evidence_ledger),
                    record.resolution,
                    record.justification,
                ))

            return False, "PREFER_NO_TRADE: Material disagreement preserved.", record

        return True, "APPROVED_FOR_EXECUTION: Unanimous evidence-backed consensus.", None

    def record_session_reports(
        self,
        session_id: str,
        reports: List[EndOfSessionAgentReport],
    ) -> None:
        """Stores structured end-of-session reports for continuous persona evolution."""
        with self._get_connection() as conn:
            for rep in reports:
                conn.execute("""
                    INSERT INTO session_agent_reports (
                        session_id, agent_name, version, timestamp, tasks_completed,
                        findings, unresolved_json, evidence_count, rejections_count,
                        failures_json, improvements
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rep.session_id,
                    rep.agent_name,
                    rep.version,
                    rep.timestamp,
                    rep.completed_tasks_count,
                    rep.findings_summary,
                    json.dumps(rep.unresolved_questions),
                    rep.contributed_evidence_count,
                    rep.rejections_issued_count,
                    json.dumps(rep.identified_failure_events),
                    rep.suggested_improvements,
                ))

    def request_order_consensus(
        self,
        session_id: str,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        emily_radar_status: Optional[Dict[str, Any]] = None,
        max_quant_candidate: Optional[Dict[str, Any]] = None,
        alexa_ui_verification: Optional[Dict[str, Any]] = None,
        emily_approval: bool = True,
        max_approval: bool = True,
        alexa_approval: bool = True,
    ) -> OrderApprovalConsensus:
        """Forms an explicit order-specific consensus for exact order parameters."""
        if emily_radar_status is None:
            emily_radar_status = {
                "tail_risk_flag": not emily_approval,
                "is_sentiment_only": False,
                "evidence_sources": ["Macro Radar", "NSE Filings"],
            }
        if max_quant_candidate is None:
            max_quant_candidate = {
                "decision": "APPROVED" if max_approval else "REJECTED",
                "net_expectancy_inr": 150.0 if max_approval else -10.0,
                "risk_calc_inr": 125.0 if max_approval else 9999.0,
                "approval_or_rejection_reason": "Quantitative edge verified" if max_approval else "RMS risk limit breach",
            }
        if alexa_ui_verification is None:
            alexa_ui_verification = {
                "browser_ready": alexa_approval,
                "inputs_verified": alexa_approval,
            }

        now_ts = time.time()
        now_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")
        consensus_id = f"CONSENSUS-{symbol}-{int(now_ts * 1000)}"

        # Evaluate consensus dialectic
        approved, reason, dis_record = self.evaluate_consensus(
            session_id=session_id,
            emily_radar_status=emily_radar_status,
            max_quant_candidate=max_quant_candidate,
            alexa_ui_verification=alexa_ui_verification,
        )

        emily_ok = not (emily_radar_status.get("tail_risk_flag", False) or emily_radar_status.get("is_sentiment_only", False))
        max_ok = (
            max_quant_candidate.get("decision") == "APPROVED"
            and max_quant_candidate.get("net_expectancy_inr", 0.0) > 0.0
            and max_quant_candidate.get("risk_calc_inr", 999.0) <= 250.0
        )
        alexa_ok = (
            alexa_ui_verification.get("browser_ready", False)
            and alexa_ui_verification.get("inputs_verified", False)
        )

        rejections: List[str] = []
        if not emily_ok:
            rejections.append("Emily veto active (macro/tail risk or sentiment only)")
        if not max_ok:
            rejections.append("Max RMS veto active (negative expectancy or risk breach)")
        if not alexa_ok:
            rejections.append("Alexa UI veto active (browser not ready or inputs unverified)")

        status = "APPROVED_FOR_EXECUTION" if approved else "PREFER_NO_TRADE"

        token = OrderApprovalConsensus(
            consensus_id=consensus_id,
            session_id=session_id,
            symbol=symbol,
            action=action.upper(),
            quantity=quantity,
            price=price,
            status=status,
            timestamp=now_ts,
            timestamp_str=now_str,
            emily_approved=emily_ok,
            max_approved=max_ok,
            alexa_approved=alexa_ok,
            disagreement_record=dis_record,
            rejection_reasons=rejections,
        )
        self.latest_consensus = token
        self.order_consensuses[consensus_id] = token
        return token

    def verify_order_consensus(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float,
        max_age_seconds: float = 60.0,
    ) -> Tuple[bool, str, Optional[OrderApprovalConsensus]]:
        """Verifies that active consensus explicitly and freshly authorizes exact order intent."""
        if not getattr(self, "is_active", True):
            return False, "COORDINATOR_INACTIVE: Three-agent coordinator is deactivated.", None

        if self.latest_consensus is None:
            return False, "MISSING_CONSENSUS: No order approval consensus exists.", None

        c = self.latest_consensus
        age = time.time() - c.timestamp
        if age > max_age_seconds:
            return False, f"STALE_CONSENSUS: Consensus is {age:.1f}s old (exceeds {max_age_seconds}s TTL).", c

        if c.status != "APPROVED_FOR_EXECUTION":
            return False, f"UNRESOLVED_CONSENSUS: Status is '{c.status}' (Must be APPROVED_FOR_EXECUTION).", c

        if not (c.emily_approved and c.max_approved and c.alexa_approved):
            return False, f"AGENT_VETO: Specialists dissented: {c.rejection_reasons}", c

        # Exact parameter verification (mutation guard)
        if c.symbol != symbol:
            return False, f"MUTATION_DETECTED: Symbol changed from approved '{c.symbol}' to '{symbol}'.", c
        if c.action != action.upper():
            return False, f"MUTATION_DETECTED: Action changed from approved '{c.action}' to '{action.upper()}'.", c
        if c.quantity != quantity:
            return False, f"MUTATION_DETECTED: Quantity changed from approved {c.quantity} to {quantity}.", c
        if abs(c.price - price) > 1e-4:
            return False, f"MUTATION_DETECTED: Price changed from approved ₹{c.price:.2f} to ₹{price:.2f}.", c

        return True, "EXPLICIT_FRESH_CONSENSUS_VERIFIED", c

    def invalidate_consensus(self, reason: str = "Invalidated") -> None:
        """Invalidates active consensus on parameter change or session reset."""
        self.latest_consensus = None
        self.order_consensuses.clear()


class FourAgentSquadCoordinator(ThreeAgentContractCoordinator):
    """Authoritative 4-Agent Trading Squad Coordinator.

    Squad Composition:
    1. Manager Iva: Lead Systems Architect, Operations Coordinator & Operator Liaison (Receives Operator Orders)
    2. Alex (Alexa): High-Frequency Microstructure, Order Flow & L3 Queue Execution Specialist
    3. Emily: Global Macro Intelligence, Volatility Surface & News Volatility Specialist
    4. Max: Quantitative Risk Engineer, Indian Statutory Friction Gatekeeper & Portfolio Allocator
    """

    def __init__(self, storage_dir: Path | str) -> None:
        super().__init__(storage_dir=storage_dir)
        self.manager = MANAGER_IVA_PERSONA
        self.alex = ALEX_PERSONA
        self.emily = EMILY_PERSONA
        self.max = MAX_PERSONA

    def evaluate_squad_consensus(
        self,
        session_id: str,
        operator_order: Dict[str, Any],
        emily_radar_status: Dict[str, Any],
        max_quant_candidate: Dict[str, Any],
        alex_ui_verification: Dict[str, Any],
    ) -> Tuple[bool, str, Optional[DisagreementRecord], Dict[str, Any]]:
        """Evaluates 4-agent squad consensus with Manager Iva as the Operator Liaison."""
        now_str = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M:%S IST")
        disagreements: Dict[str, str] = {}
        evidence_dict: Dict[str, List[str]] = {}

        # 1. Manager Iva Gate: Operator intent, capital limit, and fail-closed safety
        live_dispatch_attempt = operator_order.get("live_dispatch_requested", False)
        order_capital = float(operator_order.get("allocated_capital_inr", 10000.0))
        max_daily_loss = float(operator_order.get("max_daily_loss_inr", 2500.0))

        if live_dispatch_attempt:
            disagreements["Manager Iva"] = "VETO: Live order dispatch is strictly locked. System operates in safe fail-closed paper mode only."
            disagreements["Manager Abhi"] = disagreements["Manager Iva"]
            evidence_dict["Manager Iva"] = ["Rule GATE_01: LIVE_ORDER_DISPATCH_ENABLED = False invariant permanently enforced."]
            evidence_dict["Manager Abhi"] = evidence_dict["Manager Iva"]
        elif order_capital > 10000.0 or max_daily_loss > 2500.0:
            disagreements["Manager Iva"] = f"VETO: Assigned capital (₹{order_capital:,.2f}) or loss limit (₹{max_daily_loss:,.2f}) exceeds operator-authorized epoch_10k bounds."
            disagreements["Manager Abhi"] = disagreements["Manager Iva"]
            evidence_dict["Manager Iva"] = ["Manager Iva: Capital governance constraint for epoch_10k profile breached."]
            evidence_dict["Manager Abhi"] = evidence_dict["Manager Iva"]

        # 2. Evaluate Emily, Max, and Alex via base protocol
        base_approved, base_status, base_disagreement = self.evaluate_consensus(
            session_id=session_id,
            emily_radar_status=emily_radar_status,
            max_quant_candidate=max_quant_candidate,
            alexa_ui_verification=alex_ui_verification,
        )

        if not base_approved and base_disagreement:
            disagreements.update(base_disagreement.agent_stances)
            evidence_dict.update(base_disagreement.evidence_ledger)

        # 3. Compile squad consensus result
        squad_approved = len(disagreements) == 0
        status = "APPROVED_BY_SQUAD" if squad_approved else "PREFER_NO_TRADE"
        record: Optional[DisagreementRecord] = None

        if not squad_approved:
            disagreement_id = f"SQUAD-DISAGREE-{int(time.time() * 1000)}"
            record = DisagreementRecord(
                disagreement_id=disagreement_id,
                session_id=session_id,
                timestamp=now_str,
                topic=f"Squad Evaluation for {max_quant_candidate.get('instrument', 'UNKNOWN')}",
                agent_stances=disagreements,
                evidence_ledger=evidence_dict,
                resolution="PREFER_NO_TRADE",
                justification=f"Dissent registered by squad members: {list(disagreements.keys())}",
            )
            self.log_disagreement(record)

        squad_summary = {
            "manager_abhi_approved": "Manager Abhi" not in disagreements,
            "alex_approved": "Alexa" not in disagreements and "Alex" not in disagreements,
            "emily_approved": "Emily" not in disagreements,
            "max_approved": "Max" not in disagreements,
            "dissenting_agents": list(disagreements.keys()),
            "status": status,
            "timestamp": now_str,
        }

        return squad_approved, status, record, squad_summary



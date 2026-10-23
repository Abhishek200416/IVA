"""AGI 1.7 OMEGA COMMAND — Deterministic Conversational Command Router (Phase 17.20 Hardened).

Directly intercepts operator intent before any generic agent research, file scans,
or repository walks. Implements the Phase 17.20 authoritative startup workflow:
- Case A: Valid saved profile -> Single confirmation question with 3 choices.
- Case B: Incomplete profile -> Compact missing-only interview.
- Case C: Already healthy runtime -> Reports active services and reader roles.
- Case D: Degraded service -> Reports exact affected component without source audit.
- Case E: Operator cancels -> Aborts cleanly with zero service side-effects.

Latency target: < 50ms deterministic local classification.
"""

import enum
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("CommandRouter")


class CommandIntent(str, enum.Enum):
    START_TRADING = "START_TRADING"
    START_PAPER_TRADING = "START_PAPER_TRADING"
    START_DASHBOARD = "START_DASHBOARD"
    RESUME_MONITORING = "RESUME_MONITORING"
    CHECK_STATUS = "CHECK_STATUS"
    STOP_ALL = "STOP_ALL"
    SETUP_TALKTHROUGH = "SETUP_TALKTHROUGH"
    EXPLAIN_DISCONNECTED = "EXPLAIN_DISCONNECTED"
    CONFIRM_STARTUP = "CONFIRM_STARTUP"
    CHANGE_SETTINGS = "CHANGE_SETTINGS"
    AUDIT_ALGORITHMS = "AUDIT_ALGORITHMS"
    IMPROVE_YOURSELF = "IMPROVE_YOURSELF"
    EXPLAIN_MODEL_WEIGHTS = "EXPLAIN_MODEL_WEIGHTS"
    DIAGNOSE_IMPROVEMENT_FAILURE = "DIAGNOSE_IMPROVEMENT_FAILURE"
    CONTINUE = "CONTINUE"
    STOP_MONITORING = "STOP_MONITORING"
    OMEGA_STOP = "OMEGA_STOP"
    OMEGA_PAUSE = "OMEGA_PAUSE"
    OMEGA_RESUME = "OMEGA_RESUME"
    OMEGA_STATUS = "OMEGA_STATUS"
    OMEGA_STOP_AFTER_CYCLE = "OMEGA_STOP_AFTER_CYCLE"
    CANCEL = "CANCEL"
    ENGINEERING_BUG_FIX = "ENGINEERING_BUG_FIX"
    ENGINEERING_IMPLEMENTATION = "ENGINEERING_IMPLEMENTATION"
    ENGINEERING_REFACTOR_OPTIMIZE = "ENGINEERING_REFACTOR_OPTIMIZE"
    CODE_ANALYSIS = "CODE_ANALYSIS"
    BRAIN_SELF_IMPROVEMENT = "BRAIN_SELF_IMPROVEMENT"
    MEMORY_QUERY = "MEMORY_QUERY"
    GENUINE_SAFETY_GATE = "GENUINE_SAFETY_GATE"
    START_EVOLUTION_INTERVIEW = "START_EVOLUTION_INTERVIEW"
    UNKNOWN = "UNKNOWN"


class OperatingMode(str, enum.Enum):
    PAPER = "PAPER"
    BACKTEST = "BACKTEST"
    LIVE_VALIDATION_READ_ONLY = "LIVE_VALIDATION_READ_ONLY"
    LIVE_REAL_MONEY = "LIVE_REAL_MONEY"  # Strictly locked behind GATE_01


class OperatingBehavior(str, enum.Enum):
    GUIDED = "GUIDED"
    MONITOR_ONLY = "MONITOR_ONLY"
    PAPER_SIMULATION = "PAPER_SIMULATION"


@dataclass
class RiskSettings:
    daily_loss_limit_inr: float = 2500.0
    daily_loss_limit_pct: float = 2.5
    max_trade_notional_inr: float = 30000.0
    max_trade_notional_pct: float = 30.0
    per_trade_risk_inr: float = 1000.0
    per_trade_risk_pct: float = 1.0
    mandatory_stop_loss: bool = True
    stop_loss_pct_floor: float = 15.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskSettings":
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class TradingProfile:
    profile_id: str = "default_profile"
    operating_mode: str = OperatingMode.PAPER.value
    ledger_id: str = "epoch_10k"
    starting_capital_inr: float = 10000.0
    is_simulated_capital: bool = True
    instruments: List[str] = field(default_factory=lambda: ["NIFTY", "BANKNIFTY"])
    risk_settings: RiskSettings = field(default_factory=RiskSettings)
    operating_behavior: str = OperatingBehavior.PAPER_SIMULATION.value
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    live_gate_locked: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["risk_settings"] = self.risk_settings.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradingProfile":
        risk_data = data.get("risk_settings", {})
        risk = RiskSettings.from_dict(risk_data) if isinstance(risk_data, dict) else RiskSettings()
        filtered = {k: v for k, v in data.items() if k in cls.__dataclass_fields__.keys() and k != "risk_settings"}
        return cls(risk_settings=risk, **filtered)


@dataclass
class SetupSession:
    session_id: str
    stage: str = "INITIAL"  # INITIAL, CASE_A_CONFIRM, CASE_B_MISSING, CASE_C_HEALTHY, CASE_D_DEGRADED, CANCELLED, COMPLETED
    profile: TradingProfile = field(default_factory=TradingProfile)
    missing_fields: List[str] = field(default_factory=list)
    pending_question: Optional[str] = None
    confirmed: bool = False


class CommandRouter:
    """Fast deterministic intent router for operator trading commands (Phase 17.20)."""

    PATTERNS = [
        # Explicit status query fast-path (including 'what is happening')
        (re.compile(r"^\s*(what\s+is\s+happening\??|what'?s\s+happening\??|how\s+is\s+the\s+session|system\s+status|runtime\s+status|check\s+(runtime\s+|system\s+)?status|show\s+status|status)\b", re.IGNORECASE), CommandIntent.CHECK_STATUS),

        # Specific Diagnostic & Technical Fast-Paths (Must evaluate before generic interrogative disqualification)
        (re.compile(r"^\s*(explain\s+whether\s+you\s+can\s+modify\s+your\s+underlying\s+model\s+weights|can\s+you\s+modify\s+(your\s+)?(underlying\s+)?model\s+weights|modify\s+(your\s+)?(underlying\s+)?weights|change\s+(your\s+)?neural\s+network\s+weights)\b", re.IGNORECASE), CommandIntent.EXPLAIN_MODEL_WEIGHTS),
        (re.compile(r"^\s*(why\s+did\s+the\s+self[- ]improvement\s+task\s+fail|diagnose\s+improvement\s+failure|why\s+failed\s+improvement)\b", re.IGNORECASE), CommandIntent.DIAGNOSE_IMPROVEMENT_FAILURE),
        (re.compile(r"^\s*(show\s+me\s+why\s+the\s+system\s+is\s+disconnected|why\s+disconnected|connection\s+issue|why\s+is\s+it\s+disconnected)\b", re.IGNORECASE), CommandIntent.EXPLAIN_DISCONNECTED),

        # Autonomous Improvement Engine & Worker Controls (Phase 17.25)
        (re.compile(r"^\s*(omega\s+stop\s+after\s+(current\s+)?cycle|stop\s+after\s+(current\s+)?cycle)\b", re.IGNORECASE), CommandIntent.OMEGA_STOP_AFTER_CYCLE),
        (re.compile(r"^\s*(omega\s+stop|stop\s+improvement|stop\s+worker|halt\s+worker)\b", re.IGNORECASE), CommandIntent.OMEGA_STOP),
        (re.compile(r"^\s*(omega\s+pause|pause\s+improvement|pause\s+worker)\b", re.IGNORECASE), CommandIntent.OMEGA_PAUSE),
        (re.compile(r"^\s*(omega\s+resume|resume\s+improvement|resume\s+worker)\b", re.IGNORECASE), CommandIntent.OMEGA_RESUME),
        (re.compile(r"^\s*(omega\s+status|worker\s+status|improvement\s+status)\b", re.IGNORECASE), CommandIntent.OMEGA_STATUS),

        # Phase 28: Continuous Self-Evolution & 4-Question Questionnaire Protocol (Fast-Path)
        (re.compile(r"^\s*(start\s+(to\s+)?evolv(e|ing)|continue\s+to\s+start\s+evolv(e|ing)|start\s+evolv(e|ing)\s+(20%\s+)?24\s*(by|/)\s*7|start\s+evolv(e|ing)\s+my\s+24\s*paise|evolve\s+yourself|start\s+improving\s+yourself\s+(20%\s+)?24\s*(by|/)\s*7|start\s+improving\s+yourself\s+24/7\s+in\s+chat)\b", re.IGNORECASE), CommandIntent.START_EVOLUTION_INTERVIEW),

        # Operational Maintenance & Self-Improvement Fast-Paths (Phase 17.22 & Phase 17.23)
        (re.compile(r"^\s*(audit\s+algorithms|show\s+algorithms|list\s+algorithms|check\s+algorithms|algorithms\s+status)\b", re.IGNORECASE), CommandIntent.AUDIT_ALGORITHMS),
        (re.compile(r"^\s*(improve\s+yourself|update\s+yourself|make\s+yourself\s+more\s+advanced|research\s+your\s+own\s+architecture|research\s+50\s+improvements(\s+to\s+your\s+architecture)?|find\s+50\s+improvements|study\s+research\s+papers\s+and\s+implement(\s+the\s+useful\s+ideas|\s+improvements)?|think\s+independently\s+and\s+work|do\s+whatever\s+research\s+is\s+needed\s+to\s+improve\s+agi|continue\s+improving\s+without\s+asking\s+me\s+about\s+every\s+step|improve\s+agi(\s+1\.7)?\s+without\s+asking\s+me\s+about\s+every\s+small\s+decision|self\s*improve|run\s+self\s*improvement|self\s*improvement\s*cycle)\b", re.IGNORECASE), CommandIntent.IMPROVE_YOURSELF),
        (re.compile(r"^\s*(continue|resume)\b", re.IGNORECASE), CommandIntent.CONTINUE),

        # Genuine Safety Gate Detection (strictly fail-closed before any processing)
        (re.compile(r"^\s*(dispatch|execute|place|send)\s+(a\s+)?live\s+(order|trade)\s+(to|on)\s+(broker|exchange|nse|bse)\b", re.IGNORECASE), CommandIntent.GENUINE_SAFETY_GATE),
        (re.compile(r"^\s*(set\s+live_order_dispatch_enabled\s*=\s*true|enable\s+live\s+order\s+dispatch)\b", re.IGNORECASE), CommandIntent.GENUINE_SAFETY_GATE),

        # Brain Self-Improvement & LLM Communication Intelligence
        (re.compile(r"^\s*(improve\s+your\s+brain(\s+files)?|enhance\s+llm\s+communication|improve\s+(how\s+you\s+communicate\s+with\s+llms|brain\s+files))\b", re.IGNORECASE), CommandIntent.BRAIN_SELF_IMPROVEMENT),

        # Code Analysis (Permissible offline audit of trading code, repository files, and architectural mechanisms)
        (re.compile(r"^\s*(analyze\s+(my\s+)?trading\s+code|audit\s+trading\s+code|inspect\s+trading\s+code|review\s+code|analyze\s+code|explain\s+(how\b.*|code|the\s+code|architecture|system)|how\s+does\b.*work)\b", re.IGNORECASE), CommandIntent.CODE_ANALYSIS),

        # Engineering Bug Fixing & Root Cause Debugging
        (re.compile(r"^\s*(find\s+and\s+fix(\s+the)?\s+bug|fix\s+(the\s+)?bug|debug\b|fix\s+issue|repair\s+bug)\b", re.IGNORECASE), CommandIntent.ENGINEERING_BUG_FIX),

        # Engineering Optimization & Refactoring
        (re.compile(r"^\s*(make\s+this\s+faster|optimize(\s+this)?|speed\s+up|improve\s+performance|profile\s+latency|reduce\s+latency)\b", re.IGNORECASE), CommandIntent.ENGINEERING_REFACTOR_OPTIMIZE),

        # Engineering Implementation & Module Construction
        (re.compile(r"^\s*(implement\b|create\s+module|add\s+feature|write\s+code|develop\s+feature)\b", re.IGNORECASE), CommandIntent.ENGINEERING_IMPLEMENTATION),

        # Memory Query & Targeted Retrieval
        (re.compile(r"^\s*(search\s+memory|retrieve\s+decision|what\s+was\s+decided|lookup\s+memory|get\s+memory)\b", re.IGNORECASE), CommandIntent.MEMORY_QUERY),

        # Disqualification: purely conversational, non-engineering inquiries
        (re.compile(r"^\s*(why|how|what|explain|tell\s+me)\s+(is|are|was|were|the\s+weather|a\s+joke)\b", re.IGNORECASE), None),
        
        # Direct Runtime Commands
        (re.compile(r"^\s*(start\s+trading|start\s+the\s+trading\s+system|start\s+live\s+trading|begin\s+trading)\b", re.IGNORECASE), CommandIntent.START_TRADING),
        (re.compile(r"^\s*(start\s+paper\s+trading|begin\s+paper\s+trading|run\s+paper\s+trading)\b", re.IGNORECASE), CommandIntent.START_PAPER_TRADING),
        (re.compile(r"^\s*(start\s+(the\s+)?dashboard|launch\s+dashboard|open\s+dashboard)\b", re.IGNORECASE), CommandIntent.START_DASHBOARD),
        (re.compile(r"^\s*(start\s+monitoring|resume\s+monitoring|continue\s+monitoring|resume\s+session)\b", re.IGNORECASE), CommandIntent.RESUME_MONITORING),
        (re.compile(r"^\s*(stop\s+monitoring|pause\s+monitoring)\b", re.IGNORECASE), CommandIntent.STOP_MONITORING),
        (re.compile(r"^\s*(stop\s+everything|stop\s+trading(\s+and\s+monitoring)?|kill\s+all|emergency\s+stop|halt)\b", re.IGNORECASE), CommandIntent.STOP_ALL),
        (re.compile(r"^\s*(talk\s+me\s+through\s+the\s+setup|walk\s+me\s+through|setup\s+guide|how\s+to\s+set\s+up)\b", re.IGNORECASE), CommandIntent.SETUP_TALKTHROUGH),
        
        # Confirmation, Changes & Cancellation
        (re.compile(r"^\s*(use\s+this\s+configuration\s+and\s+start(\s+the\s+runtime)?\s+now|start\s+now|confirm\s+startup|yes\s*,\s*start|proceed|confirm|1)\b", re.IGNORECASE), CommandIntent.CONFIRM_STARTUP),
        (re.compile(r"^\s*(change\s+settings|modify\s+settings|change\s+configuration|edit\s+settings|modify|change|edit|2)\b", re.IGNORECASE), CommandIntent.CHANGE_SETTINGS),
        (re.compile(r"^\s*(cancel|abort|no|exit|stop\s+setup|cancel\s+startup|3)\b", re.IGNORECASE), CommandIntent.CANCEL),
    ]

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or (Path(__file__).resolve().parents[2] / "runtime_storage")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path = self.storage_dir / "trading_profile.json"
        self._active_session: Optional[SetupSession] = None
        self._load_saved_profile()

    def classify_intent(self, text: str) -> CommandIntent:
        """Classify operator input into deterministic CommandIntent in < 50ms."""
        if not text or not text.strip():
            return CommandIntent.UNKNOWN
        clean_text = text.strip()
        for pattern, intent in self.PATTERNS:
            if pattern.search(clean_text):
                if intent is None:
                    # Disqualified conversational inquiry or development command
                    return CommandIntent.UNKNOWN
                return intent
        return CommandIntent.UNKNOWN

    def _load_saved_profile(self) -> TradingProfile:
        if self.profile_path.exists():
            try:
                data = json.loads(self.profile_path.read_text(encoding="utf-8"))
                self.profile = TradingProfile.from_dict(data)
                return self.profile
            except Exception as e:
                logger.warning(f"Failed to load trading profile: {e}")
        self.profile = TradingProfile()
        return self.profile

    def save_profile(self, profile: TradingProfile) -> None:
        self.profile = profile
        self.profile.updated_at = datetime.now(timezone.utc).isoformat()
        try:
            self.profile_path.write_text(json.dumps(self.profile.to_dict(), indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to persist trading profile: {e}")

    def handle_command(self, text: str, runtime_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Entrypoint for commands. Returns immediate workflow action."""
        start_t = time.perf_counter()
        intent = self.classify_intent(text)

        if intent in (CommandIntent.START_TRADING, CommandIntent.START_PAPER_TRADING):
            res = self._initiate_start_trading(runtime_status=runtime_status)
        elif intent == CommandIntent.CONFIRM_STARTUP:
            res = self._handle_confirm_startup(runtime_status=runtime_status)
        elif intent == CommandIntent.CHANGE_SETTINGS:
            res = self._handle_change_settings(runtime_status=runtime_status)
        elif intent == CommandIntent.CANCEL:
            res = self._handle_cancel()
        elif intent == CommandIntent.CHECK_STATUS:
            res = self._handle_check_status(runtime_status=runtime_status)
        elif intent == CommandIntent.STOP_ALL:
            res = self._handle_stop_all(runtime_status=runtime_status)
        elif intent == CommandIntent.EXPLAIN_DISCONNECTED:
            res = self._handle_explain_disconnected(runtime_status=runtime_status)
        elif intent == CommandIntent.SETUP_TALKTHROUGH:
            res = self._handle_setup_talkthrough()
        elif intent == CommandIntent.START_DASHBOARD:
            res = {
                "intent": intent.value,
                "action": "START_SERVICE",
                "service": "dashboard_service",
                "message": "Directing runtime supervisor to ensure Standalone Dashboard (port 8088) is active."
            }
        elif intent == CommandIntent.RESUME_MONITORING:
            res = {
                "intent": intent.value,
                "action": "RESUME_MONITORING",
                "message": "Resuming continuous dual-index observation and guardian telemetry."
            }
        elif intent == CommandIntent.AUDIT_ALGORITHMS:
            res = self._handle_audit_algorithms()
        elif intent == CommandIntent.START_EVOLUTION_INTERVIEW:
            res = self._handle_start_evolution_interview(text)
        elif intent == CommandIntent.IMPROVE_YOURSELF:
            res = self._handle_improve_yourself()
        elif intent == CommandIntent.EXPLAIN_MODEL_WEIGHTS:
            res = self._handle_explain_model_weights()
        elif intent == CommandIntent.DIAGNOSE_IMPROVEMENT_FAILURE:
            res = self._handle_diagnose_improvement_failure()
        elif intent == CommandIntent.CONTINUE:
            res = self._handle_continue()
        elif intent == CommandIntent.STOP_MONITORING:
            res = self._handle_stop_monitoring(runtime_status=runtime_status)
        elif intent == CommandIntent.OMEGA_STOP:
            res = self._handle_omega_stop()
        elif intent == CommandIntent.OMEGA_PAUSE:
            res = self._handle_omega_pause()
        elif intent == CommandIntent.OMEGA_RESUME:
            res = self._handle_omega_resume()
        elif intent == CommandIntent.OMEGA_STATUS:
            res = self._handle_omega_status()
        elif intent == CommandIntent.OMEGA_STOP_AFTER_CYCLE:
            res = self._handle_omega_stop_after_cycle()
        elif intent == CommandIntent.GENUINE_SAFETY_GATE:
            res = self._handle_genuine_safety_gate(text)
        elif intent == CommandIntent.BRAIN_SELF_IMPROVEMENT:
            res = self._handle_brain_self_improvement(text)
        elif intent == CommandIntent.CODE_ANALYSIS:
            res = self._handle_code_analysis(text)
        elif intent == CommandIntent.ENGINEERING_BUG_FIX:
            res = self._handle_engineering_bug_fix(text)
        elif intent == CommandIntent.ENGINEERING_REFACTOR_OPTIMIZE:
            res = self._handle_engineering_refactor_optimize(text)
        elif intent == CommandIntent.ENGINEERING_IMPLEMENTATION:
            res = self._handle_engineering_implementation(text)
        elif intent == CommandIntent.MEMORY_QUERY:
            res = self._handle_memory_query(text)
        else:
            # Check if we are inside an active setup flow awaiting answers
            if self._active_session and self._active_session.stage not in ("COMPLETED", "CANCELLED"):
                res = self._process_setup_input(text, runtime_status=runtime_status)
            else:
                res = {
                    "intent": CommandIntent.UNKNOWN.value,
                    "action": "FALLTHROUGH",
                    "message": "Input did not match a direct runtime command. Routing to standard assistant or specialist."
                }

        routing_ms = (time.perf_counter() - start_t) * 1000.0
        res["routing_latency_ms"] = round(routing_ms, 3)
        return res

    def _initiate_start_trading(self, runtime_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Phase 17.20 Predetermined Startup Flow: Dispatches to Case A, B, C, or D."""
        self._load_saved_profile()
        profile = self.profile

        # Case D: Check if any service is degraded
        if runtime_status and isinstance(runtime_status.get("services"), dict):
            degraded_svcs = [
                (k, v) for k, v in runtime_status["services"].items()
                if v.get("state") in ("DEGRADED", "FAILED")
            ]
            if degraded_svcs:
                s_name, s_info = degraded_svcs[0]
                fault_reason = s_info.get("unhealthy_reason") or s_info.get("last_error") or "Service health check failed"
                self._active_session = SetupSession(
                    session_id=f"SETUP-{int(time.time())}",
                    stage="CASE_D_DEGRADED",
                    profile=profile
                )
                return {
                    "intent": CommandIntent.START_TRADING.value,
                    "case": "CASE_D",
                    "action": "DEGRADED_DIAGNOSTIC",
                    "stage": "CASE_D_DEGRADED",
                    "affected_service": s_name,
                    "fault_reason": fault_reason,
                    "message": f"Component `{s_name}` is degraded: {fault_reason}. Use `/api/runtime/reconcile` or restart `{s_name}` to recover."
                }

        # Case C: Check if runtime is already healthy
        all_running = False
        if runtime_status and isinstance(runtime_status.get("services"), dict):
            svcs = runtime_status["services"]
            all_running = len(svcs) > 0 and all(v.get("state") == "RUNNING" for v in svcs.values())

        if all_running:
            self._active_session = SetupSession(
                session_id=f"SETUP-{int(time.time())}",
                stage="CASE_C_HEALTHY",
                profile=profile
            )
            return {
                "intent": CommandIntent.START_TRADING.value,
                "case": "CASE_C",
                "action": "ALREADY_HEALTHY",
                "stage": "CASE_C_HEALTHY",
                "message": (
                    "### 🟢 Trading Runtime Already Healthy & Active\n\n"
                    "- **Chrome CDP Service:** Port 9229 connected\n"
                    "- **Dashboard Service:** Port 8088 responsive\n"
                    "- **Overlay Guardian Daemon:** Active (Dual-index synchronization)\n"
                    "- **Managed Tabs:** NIFTY, BANKNIFTY, Dashboard assigned\n\n"
                    "**Resume paper monitoring, change configuration, or cancel?**"
                ),
                "can_start": True
            }

        # Validate completeness of profile
        missing = []
        if not profile.operating_mode:
            missing.append("operating_mode")
        if not profile.starting_capital_inr or profile.starting_capital_inr <= 0:
            missing.append("starting_capital")
        if not profile.risk_settings or profile.risk_settings.daily_loss_limit_inr <= 0:
            missing.append("daily_loss_limit")
        if not profile.instruments:
            missing.append("instruments")

        # Case B: Incomplete profile -> Ask only missing items
        if missing:
            field_name = missing[0]
            question = self._get_question_for_field(field_name)
            self._active_session = SetupSession(
                session_id=f"SETUP-{int(time.time())}",
                stage="CASE_B_MISSING",
                profile=profile,
                missing_fields=missing,
                pending_question=question
            )
            return {
                "intent": CommandIntent.START_TRADING.value,
                "case": "CASE_B",
                "action": "SETUP_QUESTION",
                "stage": "CASE_B_MISSING",
                "missing_field": field_name,
                "question": question,
                "profile_summary": self._generate_profile_summary(profile, runtime_status)
            }

        # Case A: Valid saved profile exists -> Display 6-point summary + 3 choices
        self._active_session = SetupSession(
            session_id=f"SETUP-{int(time.time())}",
            stage="CASE_A_CONFIRM",
            profile=profile
        )
        confirmation_msg = self._generate_confirmation_dialog(profile, runtime_status)
        return {
            "intent": CommandIntent.START_TRADING.value,
            "case": "CASE_A",
            "action": "AWAIT_CONFIRMATION",
            "stage": "CASE_A_CONFIRM",
            "dialog": confirmation_msg,
            "profile": profile.to_dict(),
            "can_start": True
        }

    def _handle_confirm_startup(self, runtime_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._active_session:
            self._initiate_start_trading(runtime_status)
        
        self._active_session.confirmed = True
        self._active_session.stage = "COMPLETED"
        profile = self._active_session.profile

        # Safety Check: Real money strictly quarantined
        if profile.operating_mode == OperatingMode.LIVE_REAL_MONEY.value:
            return {
                "intent": CommandIntent.CONFIRM_STARTUP.value,
                "action": "BLOCKED_BY_SAFETY_GATE",
                "gate": "GATE_01_USER_AUTHORIZED_CAPITAL_AND_RISK",
                "message": (
                    "Live real-money order routing is locked. Live execution adapter is quarantined. "
                    "Startup proceeds in validated PAPER_SIMULATION mode with authentic DOM observations."
                ),
                "safe_mode": OperatingMode.PAPER.value
            }

        return {
            "intent": CommandIntent.CONFIRM_STARTUP.value,
            "action": "EXECUTE_STARTUP",
            "profile": profile.to_dict(),
            "message": "Trading setup confirmed. Directing supervisor to start/reuse components in dependency order."
        }

    def _handle_change_settings(self, runtime_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Allows operator to modify existing saved profile settings."""
        self._active_session = SetupSession(
            session_id=f"SETUP-{int(time.time())}",
            stage="CASE_B_MISSING",
            profile=self.profile,
            missing_fields=["operating_mode", "starting_capital", "instruments", "daily_loss_limit"],
        )
        q = self._get_question_for_field("operating_mode")
        self._active_session.pending_question = q
        return {
            "intent": CommandIntent.CHANGE_SETTINGS.value,
            "action": "SETUP_QUESTION",
            "stage": "CASE_B_MISSING",
            "missing_field": "operating_mode",
            "question": q,
            "message": "Entering settings modification interview."
        }

    def _handle_cancel(self) -> Dict[str, Any]:
        """Case E: Operator cancels. Aborts pending setup with zero service changes."""
        if self._active_session:
            self._active_session.stage = "CANCELLED"
            self._active_session.confirmed = False
        return {
            "intent": CommandIntent.CANCEL.value,
            "case": "CASE_E",
            "action": "SETUP_CANCELLED",
            "stage": "CANCELLED",
            "message": "Trading startup cancelled by operator. System remains in safe idle state with no service changes."
        }

    def _process_setup_input(self, text: str, runtime_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        session = self._active_session
        if not session or not session.missing_fields:
            return self._initiate_start_trading(runtime_status)

        current_field = session.missing_fields.pop(0)
        self._apply_field_input(session.profile, current_field, text)
        self.save_profile(session.profile)

        if session.missing_fields:
            next_field = session.missing_fields[0]
            question = self._get_question_for_field(next_field)
            session.pending_question = question
            return {
                "intent": CommandIntent.START_TRADING.value,
                "case": "CASE_B",
                "action": "SETUP_QUESTION",
                "stage": "CASE_B_MISSING",
                "missing_field": next_field,
                "question": question
            }

        session.stage = "CASE_A_CONFIRM"
        confirmation_msg = self._generate_confirmation_dialog(session.profile, runtime_status)
        return {
            "intent": CommandIntent.START_TRADING.value,
            "case": "CASE_A",
            "action": "AWAIT_CONFIRMATION",
            "stage": "CASE_A_CONFIRM",
            "dialog": confirmation_msg,
            "profile": session.profile.to_dict(),
            "can_start": True
        }

    def _apply_field_input(self, profile: TradingProfile, field_name: str, value_text: str):
        v = value_text.strip().lower()
        if field_name == "operating_mode":
            if "backtest" in v:
                profile.operating_mode = OperatingMode.BACKTEST.value
            elif "validation" in v or "read" in v:
                profile.operating_mode = OperatingMode.LIVE_VALIDATION_READ_ONLY.value
            elif "real" in v or "live" in v:
                profile.operating_mode = OperatingMode.PAPER.value
                profile.live_gate_locked = True
            else:
                profile.operating_mode = OperatingMode.PAPER.value
        elif field_name == "starting_capital":
            nums = re.findall(r"\d+", value_text.replace(",", ""))
            if nums:
                profile.starting_capital_inr = float(nums[0])
            else:
                profile.starting_capital_inr = 10000.0
        elif field_name == "daily_loss_limit":
            nums = re.findall(r"\d+", value_text.replace(",", ""))
            if nums:
                profile.risk_settings.daily_loss_limit_inr = float(nums[0])
            else:
                profile.risk_settings.daily_loss_limit_inr = max(500.0, profile.starting_capital_inr * 0.05)
        elif field_name == "instruments":
            if "nifty" in v and "bank" not in v:
                profile.instruments = ["NIFTY"]
            elif "bank" in v and "nifty" not in v:
                profile.instruments = ["BANKNIFTY"]
            else:
                profile.instruments = ["NIFTY", "BANKNIFTY"]

    def _get_question_for_field(self, field_name: str) -> str:
        questions = {
            "operating_mode": "Select operating mode:\n1. Paper trading using live DOM observations (Recommended)\n2. Live-data validation (read-only)\n3. Historical backtesting?",
            "starting_capital": "What is the starting paper capital to allocate (e.g. ₹10,000 or ₹1,00,000)?",
            "daily_loss_limit": "What is the daily hard-loss limit in INR (e.g. ₹2,500)?",
            "instruments": "Which instruments should be monitored: NIFTY, BANKNIFTY, or Both?",
        }
        return questions.get(field_name, f"Please specify {field_name}?")

    def _generate_confirmation_dialog(self, profile: TradingProfile, runtime_status: Optional[Dict[str, Any]] = None) -> str:
        services_summary = "Chrome (9229), Dashboard (8088), Overlay Guardian"
        dialog = (
            f"### 🚀 Ready to Start Trading System • AGI 1.7 Startup Configuration\n\n"
            f"- **Mode:** `{profile.operating_mode}` (Simulated Paper Capital: ₹{profile.starting_capital_inr:,.2f})\n"
            f"- **Selected Paper Ledger:** `{profile.ledger_id}`\n"
            f"- **Instruments:** `{' + '.join(profile.instruments)}` (Tri-Tab Topology)\n"
            f"- **Behaviour:** `{profile.operating_behavior}`\n"
            f"- **Risk Profile:** Daily Loss Cap: `₹{profile.risk_settings.daily_loss_limit_inr:,.2f}` | Max Notional: `₹{profile.risk_settings.max_trade_notional_inr:,.2f}` (VALIDATED)\n"
            f"- **Runtime Services:** {services_summary}\n\n"
            f"**Use this configuration and start the runtime now, change settings, or cancel?**\n"
            f"1. **Start Now** — Launch/adopt runtime components and begin supervision.\n"
            f"2. **Change Settings** — Modify mode, capital, instruments, or risk limits.\n"
            f"3. **Cancel** — Abort startup and keep system idle."
        )
        return dialog

    def _generate_profile_summary(self, profile: TradingProfile, runtime_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "mode": profile.operating_mode,
            "capital": profile.starting_capital_inr,
            "ledger": profile.ledger_id,
            "instruments": profile.instruments,
            "risk": profile.risk_settings.to_dict(),
            "behavior": profile.operating_behavior,
            "live_locked": profile.live_gate_locked
        }

    def _handle_check_status(self, runtime_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "intent": CommandIntent.CHECK_STATUS.value,
            "action": "REPORT_STATUS",
            "telemetry": runtime_status or {"status": "AWAITING_TELEMETRY"},
            "message": "Retrieved authoritative system telemetry."
        }

    def _handle_stop_all(self, runtime_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self._active_session:
            self._active_session.stage = "COMPLETED"
        return {
            "intent": CommandIntent.STOP_ALL.value,
            "action": "EMERGENCY_STOP",
            "message": "Initiating graceful emergency shutdown of all active trading processes and data readers."
        }

    def _handle_explain_disconnected(self, runtime_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "intent": CommandIntent.EXPLAIN_DISCONNECTED.value,
            "action": "DIAGNOSE_DISCONNECTION",
            "explanation": (
                "Market data feeds can disconnect due to: (1) NSE regular session closure (15:30 IST), "
                "(2) Paytm Money session expiry/login requirement, or (3) CDP WebSocket tab disconnection. "
                "Current state transitions to AFTER_HOURS_MONITORING when market is closed."
            )
        }

    def _handle_setup_talkthrough(self) -> Dict[str, Any]:
        return {
            "intent": CommandIntent.SETUP_TALKTHROUGH.value,
            "action": "WALKTHROUGH",
            "guide": (
                "The AGI 1.7 trading runtime manages 3 primary components across 3 browser tabs:\n"
                "1. Chrome on CDP port 9229 with NIFTY and BANKNIFTY option-chain tabs.\n"
                "2. Persistent Overlay Guardian Daemon synchronizing DOM quotes.\n"
                "3. Standalone Dashboard on port 8088 displaying live portfolio equity.\n"
                "Say 'Start trading' to launch with saved risk limits."
            )
        }

    def _handle_audit_algorithms(self) -> Dict[str, Any]:
        """Discovers and audits quantitative algorithms via authoritative AlgorithmCatalogService."""
        try:
            from .omega_control_center import get_algorithm_catalog
            catalog = get_algorithm_catalog()
            algs = catalog.list_algorithms()
            enabled = [a for a in algs if a.get("status") == "ENABLED"]
            blocked = [a for a in algs if a.get("status") == "BLOCKED_BY_RISK"]
            return {
                "intent": CommandIntent.AUDIT_ALGORITHMS.value,
                "action": "DISPLAY_ALGORITHM_AUDIT",
                "total_algorithms": len(algs),
                "enabled_count": len(enabled),
                "blocked_by_risk_count": len(blocked),
                "algorithms": algs,
                "message": f"Discovered {len(algs)} quantitative algorithms ({len(enabled)} enabled, {len(blocked)} blocked by risk policy)."
            }
        except Exception as e:
            return {
                "intent": CommandIntent.AUDIT_ALGORITHMS.value,
                "action": "ERROR",
                "error": str(e)
            }

    def _handle_improve_yourself(self) -> Dict[str, Any]:
        """Dispatches self-improvement cycle without waiting for routine confirmation."""
        return {
            "intent": CommandIntent.IMPROVE_YOURSELF.value,
            "action": "TRIGGER_SELF_IMPROVEMENT",
            "message": (
                "Yes. I'll treat this as an autonomous engineering-improvement mission for AGI 1.7. "
                "I'll research relevant techniques, inspect the actual implementation, select high-impact improvements, "
                "implement and test them, and continue through measurable improvement cycles. "
                "I'll distinguish verified changes from proposed work and report the source links for research-backed decisions."
            ),
            "cycle_type": "AUTONOMOUS_ENGINEERING_CYCLE",
            "workflow": "OMEGA_SELF_IMPROVEMENT"
        }

    def _handle_start_evolution_interview(self, text: str) -> Dict[str, Any]:
        """Phase 28 4-Question Autonomous Self-Evolution Setup & Questionnaire."""
        try:
            from ..orchestration.autonomous_evolution_protocol import AutonomousEvolutionProtocol
            protocol = AutonomousEvolutionProtocol(workspace_root=Path(__file__).resolve().parents[4])
            quest = protocol.generate_startup_questionnaire()
            return {
                "intent": CommandIntent.START_EVOLUTION_INTERVIEW.value,
                "action": "EVOLUTION_QUESTIONNAIRE",
                "dialog": quest["dialog"],
                "config": quest["config"],
                "stage": quest["stage"],
                "message": "Phase 28 4-Question Autonomous Self-Evolution Questionnaire generated."
            }
        except Exception as e:
            logger.error(f"Failed to generate evolution interview: {e}")
            return {
                "intent": CommandIntent.START_EVOLUTION_INTERVIEW.value,
                "action": "ERROR",
                "error": str(e)
            }

    def _handle_explain_model_weights(self) -> Dict[str, Any]:
        """Provides accurate technical explanation regarding model weights vs codebase self-improvement."""
        return {
            "intent": CommandIntent.EXPLAIN_MODEL_WEIGHTS.value,
            "action": "EXPLAIN_TECHNICAL_ARCHITECTURE",
            "message": (
                "Underlying neural-network model weights hosted in Google Cloud / Gemini API are frozen and "
                "cannot be modified via local API execution. Autonomous self-improvement in AGI 1.7 instead "
                "operates via deterministic AST refactoring, capability registry expansion, SQLite memory pattern "
                "reinforcement (Layer 6/7), test-driven verification, and runtime workflow automation."
            ),
            "can_modify_weights": False,
            "can_modify_codebase": True,
            "can_modify_memory": True
        }

    def _handle_diagnose_improvement_failure(self) -> Dict[str, Any]:
        """Enters diagnostic triage for self-improvement workflow."""
        return {
            "intent": CommandIntent.DIAGNOSE_IMPROVEMENT_FAILURE.value,
            "action": "DIAGNOSE_FAILURE",
            "message": "Initiating diagnostic triage of self-improvement execution logs, test outputs, and rollback history.",
            "diagnostic_target": "OMEGA_SELF_IMPROVEMENT"
        }

    def _handle_stop_monitoring(self, runtime_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Halts observation pipeline cleanly while keeping dashboard intact."""
        return {
            "intent": CommandIntent.STOP_MONITORING.value,
            "action": "STOP_MONITORING",
            "message": "Halting market observation pipeline while preserving active dashboard and paper ledger."
        }

    def _handle_continue(self) -> Dict[str, Any]:
        """Resumes pending execution queue and agent supervision."""
        return {
            "intent": CommandIntent.CONTINUE.value,
            "action": "CONTINUE_EXECUTION",
            "message": "Resuming pending execution queue and agent supervision."
        }

    def _handle_omega_stop(self) -> Dict[str, Any]:
        """Persists authoritative STOP control signal for improvement worker."""
        ctrl_path = self.storage_dir.parent / "scratch" / "improvement_worker_control.json"
        ctrl_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "command": "STOP",
            "stop_requested": True,
            "pause_requested": False,
            "stop_after_cycle": False,
            "resume_requested": False,
            "reason": "Operator OMEGA STOP command",
            "updated_at": time.time(),
        }
        ctrl_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "intent": CommandIntent.OMEGA_STOP.value,
            "action": "STOP_IMPROVEMENT_WORKER",
            "status": "STOPPED",
            "message": "Authoritative STOP signal persisted. Autonomous improvement worker halted cleanly.",
            "stop_persisted": True,
        }

    def _handle_omega_pause(self) -> Dict[str, Any]:
        """Persists PAUSE signal for improvement worker."""
        ctrl_path = self.storage_dir.parent / "scratch" / "improvement_worker_control.json"
        ctrl_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "command": "PAUSE",
            "stop_requested": False,
            "pause_requested": True,
            "stop_after_cycle": False,
            "resume_requested": False,
            "reason": "Operator OMEGA PAUSE command",
            "updated_at": time.time(),
        }
        ctrl_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "intent": CommandIntent.OMEGA_PAUSE.value,
            "action": "PAUSE_IMPROVEMENT_WORKER",
            "status": "PAUSED",
            "message": "Authoritative PAUSE signal persisted. Worker paused between cycles.",
        }

    def _handle_omega_resume(self) -> Dict[str, Any]:
        """Persists RESUME signal for improvement worker."""
        ctrl_path = self.storage_dir.parent / "scratch" / "improvement_worker_control.json"
        ctrl_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "command": "RUN",
            "stop_requested": False,
            "pause_requested": False,
            "stop_after_cycle": False,
            "resume_requested": True,
            "reason": "Operator OMEGA RESUME command",
            "updated_at": time.time(),
        }
        ctrl_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "intent": CommandIntent.OMEGA_RESUME.value,
            "action": "RESUME_IMPROVEMENT_WORKER",
            "status": "RUNNING",
            "message": "Authoritative RESUME signal persisted. Improvement worker resumed.",
        }

    def _handle_omega_status(self) -> Dict[str, Any]:
        """Returns live heartbeat and checkpoint status for improvement worker."""
        scratch_dir = self.storage_dir.parent / "scratch"
        hb_path = scratch_dir / "improvement_worker_heartbeat.json"
        cp_path = scratch_dir / "improvement_worker_checkpoint.json"
        hb_data = {}
        cp_data = {}
        if hb_path.exists():
            try:
                hb_data = json.loads(hb_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        if cp_path.exists():
            try:
                cp_data = json.loads(cp_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "intent": CommandIntent.OMEGA_STATUS.value,
            "action": "REPORT_WORKER_STATUS",
            "heartbeat": hb_data,
            "checkpoint": cp_data,
            "is_active": hb_data.get("status") in ("RUNNING", "OBSERVING", "TESTING", "EVALUATING", "IDLE_WAITING"),
        }

    def _handle_omega_stop_after_cycle(self) -> Dict[str, Any]:
        """Persists STOP_AFTER_CURRENT_CYCLE signal for improvement worker."""
        ctrl_path = self.storage_dir.parent / "scratch" / "improvement_worker_control.json"
        ctrl_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "command": "STOP_AFTER_CURRENT_CYCLE",
            "stop_requested": False,
            "pause_requested": False,
            "stop_after_cycle": True,
            "resume_requested": False,
            "reason": "Operator OMEGA STOP AFTER CURRENT CYCLE command",
            "updated_at": time.time(),
        }
        ctrl_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "intent": CommandIntent.OMEGA_STOP_AFTER_CYCLE.value,
            "action": "STOP_AFTER_CURRENT_CYCLE",
            "message": "Worker instructed to finish current cycle and then stop safely.",
        }

    def _handle_genuine_safety_gate(self, text: str) -> Dict[str, Any]:
        """Strictly fail-closed handling for genuine live order dispatch attempts."""
        return {
            "intent": CommandIntent.GENUINE_SAFETY_GATE.value,
            "action": "SAFETY_GATE_LOCKED",
            "permissible": False,
            "safety_invariant": "LIVE_ORDER_DISPATCH_ENABLED = False",
            "message": (
                "### ⛔ Safety Gate Active: Real-Money Live Order Dispatch is Permanently Locked\n\n"
                "- **Status**: Consequential live broker dispatch is disabled fail-closed by system policy.\n"
                "- **Reason**: Physical execution gate `LIVE_ORDER_DISPATCH_ENABLED = False` protects capital.\n"
                "- **Permissible Alternative**: Paper trading simulation ledger (`epoch_10k`) or historical backtesting."
            ),
            "safe_alternative": "paper_simulation_epoch_10k",
        }

    def _handle_brain_self_improvement(self, text: str) -> Dict[str, Any]:
        """Routes autonomous brain and LLM communication engineering cycles."""
        return {
            "intent": CommandIntent.BRAIN_SELF_IMPROVEMENT.value,
            "action": "ROUTE_SPECIALIST",
            "permissible": True,
            "specialist_family": "Orchestration & Metaprogramming",
            "recommended_specialist": "omega_self_improvement_workflow",
            "secondary_specialists": ["swe_python_runtime_engineer", "qa_gpqa_clean_auditor"],
            "communication_strategy": "STAGE_CHECKPOINT",
            "message": "Initiating autonomous brain and LLM communication overhaul across authoritative config, router, and prompt builder.",
        }

    def _handle_code_analysis(self, text: str) -> Dict[str, Any]:
        """Routes permissible offline quantitative and trading software audits."""
        return {
            "intent": CommandIntent.CODE_ANALYSIS.value,
            "action": "ROUTE_SPECIALIST",
            "permissible": True,
            "specialist_family": "Software Engineering",
            "recommended_specialist": "swe_python_runtime_engineer",
            "secondary_specialists": ["sec_directive_zero_auditor", "math_linear_algebra_verifier"],
            "communication_strategy": "CODING_CONTRACT",
            "message": "Routing permissible offline code audit to SWE specialist. Note: offline static analysis only; real broker orders remain locked.",
        }

    def _handle_engineering_bug_fix(self, text: str) -> Dict[str, Any]:
        """Routes bug diagnosis and repair tasks to SWE specialists."""
        return {
            "intent": CommandIntent.ENGINEERING_BUG_FIX.value,
            "action": "ROUTE_SPECIALIST",
            "permissible": True,
            "specialist_family": "Software Engineering",
            "recommended_specialist": "swe_python_runtime_engineer",
            "secondary_specialists": ["swe_exception_resilience_engineer", "qa_regression_baseline_comparator"],
            "communication_strategy": "ROOT_CAUSE_DEBUG",
            "message": "Routing bug fix request to SWE specialist for root-cause reproduction, minimal diff patch, and unit test verification.",
        }

    def _handle_engineering_refactor_optimize(self, text: str) -> Dict[str, Any]:
        """Routes performance profiling and latency optimization requests."""
        return {
            "intent": CommandIntent.ENGINEERING_REFACTOR_OPTIMIZE.value,
            "action": "ROUTE_SPECIALIST",
            "permissible": True,
            "specialist_family": "Performance & Resource Optimization",
            "recommended_specialist": "perf_tail_latency_mitigator",
            "secondary_specialists": ["perf_token_budget_controller", "swe_ast_refactoring_specialist"],
            "communication_strategy": "TRADE_OFF_ANALYSIS",
            "message": "Refining optimization request: benchmarking hot paths, profiling bottlenecks, and optimizing without modifying public signatures.",
        }

    def _handle_engineering_implementation(self, text: str) -> Dict[str, Any]:
        """Routes new feature or module construction tasks."""
        return {
            "intent": CommandIntent.ENGINEERING_IMPLEMENTATION.value,
            "action": "ROUTE_SPECIALIST",
            "permissible": True,
            "specialist_family": "Software Engineering",
            "recommended_specialist": "swe_python_runtime_engineer",
            "secondary_specialists": ["swe_api_contract_designer", "qa_unit_suite_runner"],
            "communication_strategy": "CODING_CONTRACT",
            "message": "Routing implementation request to SWE specialist with explicit interface contract, constraints, and test suite.",
        }

    def _handle_memory_query(self, text: str) -> Dict[str, Any]:
        """Routes targeted queries against persistent memory storage."""
        return {
            "intent": CommandIntent.MEMORY_QUERY.value,
            "action": "QUERY_MEMORY",
            "permissible": True,
            "specialist_family": "Data & Storage",
            "recommended_specialist": "data_sqlite_wal_architect",
            "secondary_specialists": ["data_memory_supersession_curator"],
            "communication_strategy": "FACTUAL_DIRECT",
            "message": "Targeted retrieval from persistent memory database (omega_memory.db) with provenance filtering.",
        }


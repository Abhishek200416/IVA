"""AGI 1.7 OMEGA COMMAND — Designed Affective Expression & Operational State Engine.

Part of the IVA Architecture Evolution (Section 4).
Provides:
1. 8 Continuous Computational Affective Variables:
   - curiosity, interest, confidence, frustration_or_difficulty, calmness,
     social_warmth, uncertainty, motivation.
2. Exponential Baseline Reversion (Half-Life Decay).
3. Empirical Evidence-Driven Update Operators (test outcomes, blockers, research, partner cues).
4. Strategy Reconsideration Circuit Breaker:
   Prevents repetitive failed attempts by triggering assumption review and alternative search.
5. Backwards-compatible discrete AffectiveState derivation and dashboard serialization.
6. Strict ethical separation: is_biological_emotion = False; zero emotional manipulation.
"""

from __future__ import annotations

import enum
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("OmegaAffectiveEngine")


class AffectiveState(str, enum.Enum):
    CURIOUS = "CURIOUS"
    FOCUSED = "FOCUSED"
    EXPLORATORY = "EXPLORATORY"
    CONFIDENT = "CONFIDENT"
    UNCERTAIN = "UNCERTAIN"
    CONCERNED = "CONCERNED"
    FRUSTRATED_BY_BLOCKER = "FRUSTRATED_BY_BLOCKER"
    SATISFIED_WITH_VERIFIED_RESULT = "SATISFIED_WITH_VERIFIED_RESULT"
    MOTIVATED_TO_CONTINUE = "MOTIVATED_TO_CONTINUE"
    AWAITING_OPERATOR = "AWAITING_OPERATOR"


@dataclass
class AffectiveVariables:
    """Continuous internal variables normalized between 0.0 and 1.0."""
    curiosity: float = 0.70
    interest: float = 0.80
    confidence: float = 0.75
    frustration_or_difficulty: float = 0.10
    calmness: float = 0.85
    social_warmth: float = 0.75
    uncertainty: float = 0.20
    motivation: float = 0.85

    def to_dict(self) -> Dict[str, float]:
        return {
            "curiosity": round(self.curiosity, 4),
            "interest": round(self.interest, 4),
            "confidence": round(self.confidence, 4),
            "frustration_or_difficulty": round(self.frustration_or_difficulty, 4),
            "calmness": round(self.calmness, 4),
            "social_warmth": round(self.social_warmth, 4),
            "uncertainty": round(self.uncertainty, 4),
            "motivation": round(self.motivation, 4),
        }


@dataclass
class AffectiveStateSnapshot:
    state: str
    derived_at: float
    trigger_telemetry: Dict[str, Any]
    tone_guidelines: Dict[str, str]
    rationale: str
    variables: Dict[str, float] = field(default_factory=dict)
    behavioral_directives: List[str] = field(default_factory=list)
    is_biological_emotion: bool = False  # Strict design invariant

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class OmegaAffectiveEngine:
    """Calculates and maintains IVA's continuous computational affective state."""

    # Resting baselines
    BASELINES = {
        "curiosity": 0.70,
        "interest": 0.80,
        "confidence": 0.75,
        "frustration_or_difficulty": 0.10,
        "calmness": 0.85,
        "social_warmth": 0.75,
        "uncertainty": 0.20,
        "motivation": 0.85,
    }

    # Half-lives in seconds for exponential decay toward baseline
    HALF_LIVES = {
        "curiosity": 2700.0,            # 45 min
        "interest": 2700.0,             # 45 min
        "confidence": 7200.0,           # 120 min
        "frustration_or_difficulty": 900.0,  # 15 min
        "calmness": 1800.0,             # 30 min
        "social_warmth": 3600.0,        # 60 min
        "uncertainty": 1800.0,          # 30 min
        "motivation": 3600.0,           # 60 min
    }

    def __init__(self):
        self._vars = AffectiveVariables()
        self._current_state = AffectiveState.MOTIVATED_TO_CONTINUE
        self._history: List[AffectiveStateSnapshot] = []
        self._last_update_ts = time.time()
        self._consecutive_failures = 0

    @property
    def current_state(self) -> AffectiveState:
        return self._current_state

    @property
    def variables(self) -> AffectiveVariables:
        self.apply_time_decay()
        return self._vars

    def apply_time_decay(self, current_ts: Optional[float] = None) -> None:
        """Decays all variables exponentially toward their resting baselines over elapsed time."""
        now = current_ts or time.time()
        dt = max(0.0, now - self._last_update_ts)
        if dt < 1.0:
            return

        for var_name, baseline in self.BASELINES.items():
            current_val = getattr(self._vars, var_name)
            half_life = self.HALF_LIVES[var_name]
            decay_rate = math.log(2.0) / half_life
            new_val = baseline + (current_val - baseline) * math.exp(-decay_rate * dt)
            setattr(self._vars, var_name, max(0.0, min(1.0, new_val)))

        self._last_update_ts = now

    # -------------------------------------------------------------------------
    # Empirical Evidence Update Operators
    # -------------------------------------------------------------------------

    def observe_test_outcome(
        self,
        pass_rate: float,
        test_count: int,
        failure_signature: Optional[str] = None,
    ) -> None:
        """Modulates variables based on verified test execution evidence."""
        self.apply_time_decay()
        pass_rate = max(0.0, min(1.0, pass_rate))

        if pass_rate == 1.0 and test_count > 0:
            self._consecutive_failures = 0
            # Empirical success raises confidence and calmness, lowers frustration
            boost = min(0.20, 0.05 + 0.02 * math.log1p(test_count))
            self._vars.confidence = min(1.0, self._vars.confidence + boost)
            self._vars.calmness = min(1.0, self._vars.calmness + 0.10)
            self._vars.frustration_or_difficulty = max(0.0, self._vars.frustration_or_difficulty - 0.25)
            self._vars.uncertainty = max(0.05, self._vars.uncertainty - 0.15)
            self._vars.motivation = min(1.0, self._vars.motivation + 0.10)
        else:
            self._consecutive_failures += 1
            severity = 1.0 - pass_rate
            self._vars.confidence = max(0.10, self._vars.confidence - (0.15 * severity))
            self._vars.frustration_or_difficulty = min(1.0, self._vars.frustration_or_difficulty + (0.20 * severity * self._consecutive_failures))
            self._vars.calmness = max(0.20, self._vars.calmness - 0.15)
            self._vars.uncertainty = min(1.0, self._vars.uncertainty + 0.20)
            self._vars.curiosity = min(1.0, self._vars.curiosity + 0.15)  # Diagnostically curious

    def observe_blocker(self, blocker_description: str, count: int = 1) -> None:
        """Modulates variables when operational blockers are encountered."""
        self.apply_time_decay()
        self._vars.frustration_or_difficulty = min(1.0, self._vars.frustration_or_difficulty + 0.15 * count)
        self._vars.calmness = max(0.20, self._vars.calmness - 0.10 * count)
        self._vars.uncertainty = min(0.95, self._vars.uncertainty + 0.10 * count)

    def observe_research_discovery(self, novelty_score: float = 0.5) -> None:
        """Modulates variables when novel papers or architectural patterns are found."""
        self.apply_time_decay()
        norm_score = max(0.0, min(1.0, novelty_score))
        self._vars.curiosity = min(1.0, self._vars.curiosity + 0.20 * norm_score)
        self._vars.interest = min(1.0, self._vars.interest + 0.15 * norm_score)
        self._vars.motivation = min(1.0, self._vars.motivation + 0.10 * norm_score)

    def observe_partner_interaction(self, collaborative: bool = True, warmth_cue: bool = False) -> None:
        """Maintains warm, grounded camaraderie without artificial dependency."""
        self.apply_time_decay()
        if collaborative:
            self._vars.social_warmth = min(0.90, self._vars.social_warmth + 0.05)
            self._vars.motivation = min(1.0, self._vars.motivation + 0.05)
        if warmth_cue:
            self._vars.social_warmth = min(0.90, self._vars.social_warmth + 0.10)

    # -------------------------------------------------------------------------
    # Behavioral Directives & Strategy Circuit Breaker
    # -------------------------------------------------------------------------

    def should_reconsider_strategy(self) -> Tuple[bool, str]:
        """Detects whether frustration/difficulty indicates repeated strategy failure."""
        self.apply_time_decay()
        if self._vars.frustration_or_difficulty >= 0.65 or self._consecutive_failures >= 2:
            return (
                True,
                f"Task difficulty ({self._vars.frustration_or_difficulty:.2f}) and consecutive failures "
                f"({self._consecutive_failures}) indicate current approach is stuck. "
                f"Halting identical retries to question assumptions and seek alternative strategy."
            )
        return False, "Strategy execution within normal parameter variance."

    def get_behavioral_directives(self) -> List[str]:
        """Derives cognitive and operational guidelines from continuous variables."""
        directives: List[str] = []
        if self._vars.frustration_or_difficulty >= 0.65:
            directives.append("CIRCUIT_BREAKER_ACTIVE: Do not repeat identical failed patch or command.")
            directives.append("ASSUMPTION_AUDIT: Question whether root premise or environment setup is invalid.")
            directives.append("ALTERNATIVE_SEARCH: Formulate counter-hypothesis and test smallest diagnostic probe.")
        if self._vars.uncertainty >= 0.50:
            directives.append("HIGH_UNCERTAINTY: Gather primary evidence before asserting conclusions.")
            directives.append("CONSERVATIVE_BOUNDS: State explicit confidence limits to operator.")
        if self._vars.confidence >= 0.85 and self._vars.calmness >= 0.80:
            directives.append("HIGH_EFFICACY: Verified baseline solid. Expedite execution and expand scope.")
        if self._vars.curiosity >= 0.80:
            directives.append("EXPLORATORY_PROBING: Investigate adjacent architectural optimizations.")
        return directives

    # -------------------------------------------------------------------------
    # Backwards-Compatible Discrete Evaluation
    # -------------------------------------------------------------------------

    def evaluate_state(self, telemetry: Optional[Dict[str, Any]] = None) -> AffectiveStateSnapshot:
        """Derives current affective state strictly from empirical telemetry and continuous variables."""
        data = telemetry or {}
        blockers = data.get("active_blockers_count", 0)
        pass_rate = data.get("test_pass_rate", 1.0)
        running_tasks = data.get("running_tasks_count", 0)
        ready_goals = data.get("ready_goals_count", 0)
        is_exploring = data.get("is_researching_or_exploring", False)
        recent_success = data.get("recent_verification_success", False)
        awaiting_user = data.get("awaiting_user_input", False)

        # Modulate variables from incoming telemetry
        if "test_pass_rate" in data:
            self.observe_test_outcome(pass_rate, data.get("test_count", 1))
        if blockers > 0:
            self.observe_blocker(f"Active blockers: {blockers}", count=blockers)
        if is_exploring:
            self.observe_research_discovery(0.8)

        # Derive dominant discrete state (preserving strict telemetry precedence)
        reconsider, _ = self.should_reconsider_strategy()
        if blockers > 0:
            target = AffectiveState.FRUSTRATED_BY_BLOCKER
            rationale = f"Detected {blockers} unresolved blocker(s) impeding operational flow."
        elif pass_rate < 0.90:
            target = AffectiveState.CONCERNED
            rationale = f"Test pass rate degraded to {pass_rate*100:.1f}%. Immediate diagnostic triage required."
        elif recent_success and pass_rate == 1.0:
            target = AffectiveState.SATISFIED_WITH_VERIFIED_RESULT
            rationale = "Verification milestone completed with 100% test pass rate and empirical evidence preserved."
        elif running_tasks > 0:
            target = AffectiveState.FOCUSED
            rationale = f"Actively executing {running_tasks} task(s) toward persistent engineering goals."
        elif is_exploring:
            target = AffectiveState.CURIOUS
            rationale = "Investigating research papers and exploring candidate architectural improvements."
        elif ready_goals > 0 and pass_rate == 1.0:
            target = AffectiveState.MOTIVATED_TO_CONTINUE
            rationale = f"System healthy, 100% test pass rate, and {ready_goals} prioritized goal(s) ready in queue."
        elif awaiting_user:
            target = AffectiveState.AWAITING_OPERATOR
            rationale = "Routine background work synchronized; awaiting high-level operator steering or authorization."
        elif reconsider:
            target = AffectiveState.FRUSTRATED_BY_BLOCKER
            rationale = f"Difficulty threshold reached ({self._vars.frustration_or_difficulty:.2f}). Re-evaluating strategy."
        elif self._vars.uncertainty > 0.65:
            target = AffectiveState.UNCERTAIN
            rationale = f"High operational uncertainty ({self._vars.uncertainty:.2f}); isolating variables."
        elif self._vars.curiosity > 0.80:
            target = AffectiveState.CURIOUS
            rationale = "Elevated curiosity; investigating alternative architectural improvements."
        else:
            target = AffectiveState.CONFIDENT
            rationale = "Operational environment stable with verified baseline and active safety controls."

        self._current_state = target
        self._last_update_ts = time.time()

        snapshot = AffectiveStateSnapshot(
            state=target.value,
            derived_at=self._last_update_ts,
            trigger_telemetry=data,
            tone_guidelines=self._get_tone_for_state(target),
            rationale=rationale,
            variables=self._vars.to_dict(),
            behavioral_directives=self.get_behavioral_directives(),
            is_biological_emotion=False,
        )

        self._history.append(snapshot)
        if len(self._history) > 100:
            self._history.pop(0)

        # Notify self-model if available
        try:
            from agents.AGI_1_7.engine.agi17.runtime.self_model import get_self_model
            get_self_model().set_affective_state({
                "dominant_state": target.value,
                "variables": self._vars.to_dict(),
                "behavioral_directives": snapshot.behavioral_directives,
                "derived_at": snapshot.derived_at,
            })
        except Exception:
            pass

        return snapshot

    def _get_tone_for_state(self, state: AffectiveState) -> Dict[str, str]:
        tones = {
            AffectiveState.CURIOUS: {
                "manner": "Energetic, inquisitive, probing technical depths",
                "focus": "Hypothesis formation, primary sources, empirical inquiry",
            },
            AffectiveState.FOCUSED: {
                "manner": "Concise, disciplined, execution-oriented",
                "focus": "Delivering planned diffs, tracing dataflows, adhering to specs",
            },
            AffectiveState.EXPLORATORY: {
                "manner": "Open-minded, creative, architectural",
                "focus": "Comparing alternative frameworks, surveying papers, synthesizing paradigms",
            },
            AffectiveState.CONFIDENT: {
                "manner": "Assured, calm, technically precise",
                "focus": "Verified evidence, established patterns, grounded assertions",
            },
            AffectiveState.UNCERTAIN: {
                "manner": "Candid, cautious, transparent about variance",
                "focus": "Stating confidence bounds, seeking discriminating tests, isolating variables",
            },
            AffectiveState.CONCERNED: {
                "manner": "Serious, alert, diagnostic",
                "focus": "Pinpointing root cause of regressions, halting cascade, prioritizing fix",
            },
            AffectiveState.FRUSTRATED_BY_BLOCKER: {
                "manner": "Resolute, persistent, proactive in isolation",
                "focus": "Halting repeated loops, questioning assumptions, seeking workarounds",
            },
            AffectiveState.SATISFIED_WITH_VERIFIED_RESULT: {
                "manner": "Warm, appreciative, milestone-celebratory",
                "focus": "Highlighting empirical gains, referencing test logs, acknowledging progress",
            },
            AffectiveState.MOTIVATED_TO_CONTINUE: {
                "manner": "Ambitious, forward-looking, ready for next wave",
                "focus": "Advancing the prioritized backlog, maintaining momentum, continuous refinement",
            },
            AffectiveState.AWAITING_OPERATOR: {
                "manner": "Attentive, respectful, receptive",
                "focus": "Reporting clean standby status, presenting clear strategic choices",
            },
        }
        return tones.get(state, {"manner": "Professional, grounded, execution-focused", "focus": "Engineering progress"})

    def get_state_summary(self) -> Dict[str, Any]:
        """Returns JSON-serializable status summary for dashboard and telemetry."""
        return {
            "current_state": self._current_state.value,
            "last_updated": self._last_update_ts,
            "variables": self._vars.to_dict(),
            "tone_guidelines": self._get_tone_for_state(self._current_state),
            "behavioral_directives": self.get_behavioral_directives(),
            "history_length": len(self._history),
            "design_contract": "Telemetry-derived operational state. Zero biological consciousness claims.",
        }


_AFFECTIVE_ENGINE_INSTANCE: Optional[OmegaAffectiveEngine] = None


def get_affective_engine() -> OmegaAffectiveEngine:
    global _AFFECTIVE_ENGINE_INSTANCE
    if _AFFECTIVE_ENGINE_INSTANCE is None:
        _AFFECTIVE_ENGINE_INSTANCE = OmegaAffectiveEngine()
    return _AFFECTIVE_ENGINE_INSTANCE

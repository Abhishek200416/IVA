"""AGI 1.7 LLM Communication Intelligence Layer (Phase 17.26).

Enforces:
1. Strategy Selection (Table 5.1):
   Selects specialized prompting strategies based on task characteristics:
   - Simple factual question -> FACTUAL_DIRECT
   - Complex technical explanation -> STRUCTURED_EXPLANATION
   - Coding task -> CODING_CONTRACT
   - Debugging -> ROOT_CAUSE_DEBUG
   - Research -> GROUNDED_RESEARCH
   - Data analysis -> SCHEMA_CALCULATION
   - Architecture design -> TRADE_OFF_ANALYSIS
   - Structured extraction -> STRICT_JSON_SCHEMA
   - Long multi-stage task -> STAGE_CHECKPOINT
   - Failed answer -> RECOVERY_REPROMPT
2. Prompt Component Construction:
   Assembles high-quality prompts from modular components:
   Objective, Context, Inputs, Constraints, Tools, Procedure, Output Contract, Verification, Fallback.
3. Vague-to-Precise Transformation:
   Transforms underspecified or weak instructions into actionable, precise prompts with explicit assumptions.
4. Targeted Follow-Up Generation:
   Identifies genuinely missing parameters and generates focused clarification questions while
   allowing non-dependent preparatory work to proceed immediately.
5. Context Budgeting & Compression:
   Integrates with ACON compressor and snippet extraction to respect token budgets.
"""

from __future__ import annotations

import enum
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("LLMCommunicationIntelligence")


class CommunicationStrategy(str, enum.Enum):
    FACTUAL_DIRECT = "FACTUAL_DIRECT"
    STRUCTURED_EXPLANATION = "STRUCTURED_EXPLANATION"
    CODING_CONTRACT = "CODING_CONTRACT"
    ROOT_CAUSE_DEBUG = "ROOT_CAUSE_DEBUG"
    GROUNDED_RESEARCH = "GROUNDED_RESEARCH"
    SCHEMA_CALCULATION = "SCHEMA_CALCULATION"
    TRADE_OFF_ANALYSIS = "TRADE_OFF_ANALYSIS"
    STRICT_JSON_SCHEMA = "STRICT_JSON_SCHEMA"
    STAGE_CHECKPOINT = "STAGE_CHECKPOINT"
    RECOVERY_REPROMPT = "RECOVERY_REPROMPT"


@dataclass
class PromptComponents:
    """Standardized prompt components for structured LLM communication."""

    objective: str
    context: Optional[str] = None
    inputs: Optional[str] = None
    constraints: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    procedure: List[str] = field(default_factory=list)
    output_contract: Optional[str] = None
    verification: Optional[str] = None
    fallback: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RefinedTaskSpec:
    """Precise, actionable task specification derived from vague input."""

    original_text: str
    is_vague: bool
    precise_objective: str
    working_hypotheses: List[str]
    identified_constraints: List[str]
    recommended_procedure: List[str]
    verification_criteria: List[str]
    strategy: CommunicationStrategy
    can_proceed_without_asking: bool
    targeted_question: Optional[str] = None


class LLMCommunicationIntelligence:
    """Core intelligence engine for high-fidelity LLM communication."""

    def __init__(self, default_max_context_tokens: int = 4000):
        self.default_max_context_tokens = default_max_context_tokens

    def select_strategy(
        self,
        task_description: str,
        task_type: Optional[str] = None,
    ) -> CommunicationStrategy:
        """Selects the preferred communication strategy based on task characteristics."""
        if not task_description:
            return CommunicationStrategy.FACTUAL_DIRECT

        text = task_description.lower().strip()

        # Explicit task_type override if provided
        if task_type:
            tt = task_type.upper().strip()
            if hasattr(CommunicationStrategy, tt):
                return CommunicationStrategy[tt]

        # Debugging and error diagnosis
        if any(w in text for w in ("bug", "error", "traceback", "exception", "failing test", "crash", "fix bug", "root cause", "debug")):
            return CommunicationStrategy.ROOT_CAUSE_DEBUG

        # Coding task
        if any(w in text for w in ("implement", "write code", "create module", "function", "class", "refactor code", "patch", "unit test", "test suite")):
            return CommunicationStrategy.CODING_CONTRACT

        # Optimization & performance
        if any(w in text for w in ("faster", "optimize", "speed up", "latency", "throughput", "benchmark", "bottleneck", "profiling")):
            return CommunicationStrategy.TRADE_OFF_ANALYSIS

        # Data analysis & calculation
        if any(w in text for w in ("calculate", "compute", "volatility", "sharpe", "drawdown", "statistics", "dataset", "ledger reconciliation", "schema")):
            return CommunicationStrategy.SCHEMA_CALCULATION

        # Research & exploration
        if any(w in text for w in ("research", "paper", "arxiv", "find sources", "study", "compare algorithms", "literature")):
            return CommunicationStrategy.GROUNDED_RESEARCH

        # Architecture & system design
        if any(w in text for w in ("architecture", "design", "trade-off", "system design", "component", "subsystem", "brain files", "memory architecture")):
            return CommunicationStrategy.TRADE_OFF_ANALYSIS

        # Structured extraction
        if any(w in text for w in ("extract json", "parse to schema", "extract fields", "json output", "format as json")):
            return CommunicationStrategy.STRICT_JSON_SCHEMA

        # Long multi-stage tasks
        if any(w in text for w in ("continuous", "multi-step", "cycle", "worker", "long-running", "pipeline", "end-to-end")):
            return CommunicationStrategy.STAGE_CHECKPOINT

        # Complex technical explanation
        if any(w in text for w in ("explain", "why does", "how does", "deep dive", "walk through", "describe mechanism")):
            return CommunicationStrategy.STRUCTURED_EXPLANATION

        return CommunicationStrategy.FACTUAL_DIRECT

    def build_prompt(
        self,
        components: PromptComponents,
        strategy: Optional[CommunicationStrategy] = None,
    ) -> str:
        """Constructs an unambiguous, structured prompt using the selected strategy."""
        strat = strategy or self.select_strategy(components.objective)
        sections: List[str] = []

        # Strategy Header
        sections.append(f"### [STRATEGY: {strat.value}]")
        sections.append(f"**OBJECTIVE**: {components.objective.strip()}")

        if components.context:
            sections.append(f"\n**CONTEXT & BACKGROUND**:\n{components.context.strip()}")

        if components.inputs:
            sections.append(f"\n**INPUT DATA / SIGNATURES / LOGS**:\n{components.inputs.strip()}")

        if components.constraints:
            cstr_lines = "\n".join(f"- {c}" for c in components.constraints)
            sections.append(f"\n**CONSTRAINTS & INVARIANTS**:\n{cstr_lines}")

        if components.tools:
            tools_lines = "\n".join(f"- `{t}`" for t in components.tools)
            sections.append(f"\n**AVAILABLE TOOLS & APIS**:\n{tools_lines}")

        if components.procedure:
            proc_lines = "\n".join(f"{i+1}. {step}" for i, step in enumerate(components.procedure))
            sections.append(f"\n**REQUIRED PROCEDURE**:\n{proc_lines}")

        if components.output_contract:
            sections.append(f"\n**OUTPUT CONTRACT & FORMAT**:\n{components.output_contract.strip()}")

        if components.verification:
            sections.append(f"\n**VERIFICATION & ACCEPTANCE CRITERIA**:\n{components.verification.strip()}")

        if components.fallback:
            sections.append(f"\n**FALLBACK POLICY**:\n{components.fallback.strip()}")

        return "\n".join(sections)

    def transform_vague_prompt(self, vague_text: str) -> RefinedTaskSpec:
        """Transforms underspecified or weak user prompts into precise, actionable specifications."""
        text = vague_text.strip()
        lower = text.lower()

        # Case 1: "Make this faster" / "optimize"
        if re.search(r"^\s*(make\s+this\s+faster|optimize(\s+this)?|speed\s+it\s+up|improve\s+performance)\b", lower):
            return RefinedTaskSpec(
                original_text=text,
                is_vague=True,
                precise_objective="Benchmark target execution, profile hot paths, identify latency bottlenecks, and implement algorithmic or caching optimizations without altering public interfaces or computational results.",
                working_hypotheses=[
                    "Target module contains redundant I/O, non-indexed lookups, or unmemoized repetitive computations.",
                    "Latency can be reduced by caching, vectorized operations, or pre-compiled regex/AST without changing behavior."
                ],
                identified_constraints=[
                    "Preserve all existing method signatures and return value invariants.",
                    "Existing unit tests must continue to pass 100%.",
                    "Do not introduce heavy external dependencies if standard library or existing dependencies suffice."
                ],
                recommended_procedure=[
                    "Run baseline benchmark to measure execution latency and throughput.",
                    "Inspect hotspot code using profiling or static AST analysis.",
                    "Implement targeted optimization (e.g. memoization, pre-allocation, lazy evaluation).",
                    "Re-run benchmark and assert >= 15% latency reduction with 100% test pass rate."
                ],
                verification_criteria=[
                    "Benchmark verifies measurable runtime reduction.",
                    "Existing regression test suite passes with zero failures."
                ],
                strategy=CommunicationStrategy.TRADE_OFF_ANALYSIS,
                can_proceed_without_asking=True,
                targeted_question=None
            )

        # Case 2: "Tell me about this code"
        if re.search(r"^\s*(tell\s+me\s+about\s+this\s+code|what\s+does\s+this\s+code\s+do|explain\s+this\s+code)\b", lower):
            return RefinedTaskSpec(
                original_text=text,
                is_vague=True,
                precise_objective="Inspect the target module or function: state its intended functional contract, boundary invariants, failure modes, error handling, and test coverage.",
                working_hypotheses=["The user needs an architectural and functional audit of the specified code."],
                identified_constraints=["Focus on concrete implementation details, not speculative commentary."],
                recommended_procedure=[
                    "Examine public symbols, class definitions, and core entrypoints.",
                    "Trace inputs, outputs, error conditions, and external dependencies.",
                    "Summarize architectural role and identify edge-case vulnerabilities."
                ],
                verification_criteria=["Explanation accurately matches AST signatures and actual runtime flow."],
                strategy=CommunicationStrategy.STRUCTURED_EXPLANATION,
                can_proceed_without_asking=True,
                targeted_question=None
            )

        # Case 3: "Improve your brain files" / "enhance LLM communication"
        if re.search(r"(improve\s+your\s+brain|enhance\s+llm\s+communication|improve\s+brain\s+files|fix\s+brain)", lower):
            return RefinedTaskSpec(
                original_text=text,
                is_vague=True,
                precise_objective="Inspect active brain configuration and instruction loading sequence, resolve router misclassifications, integrate LLM communication intelligence and refusal recovery, and empirically verify with test suite.",
                working_hypotheses=[
                    "Router may have disqualifying regexes causing ordinary engineering queries to fall through.",
                    "Prompt construction lacks modular component schema and vague prompt refinement.",
                    "Refusal recovery lacks de-sensitization and bounded failover."
                ],
                identified_constraints=[
                    "Preserve fail-closed financial invariant (LIVE_ORDER_DISPATCH_ENABLED = False).",
                    "Changes must touch active runtime code, not unread markdown files.",
                    "All tests must achieve 100% pass rate."
                ],
                recommended_procedure=[
                    "Audit instruction loading in authoritative_brain_config and command_router.",
                    "Harden intent classification for coding, analysis, and optimization tasks.",
                    "Implement LLMCommunicationIntelligence and RefusalRecoveryEngine.",
                    "Execute comprehensive test suite across scenarios A through M."
                ],
                verification_criteria=["All 13 Phase 17.26 scenarios pass with 100% success in automated tests."],
                strategy=CommunicationStrategy.STAGE_CHECKPOINT,
                can_proceed_without_asking=True,
                targeted_question=None
            )

        # Case 4: "Fix this bug" / "Find and fix the bug in this function"
        if re.search(r"^\s*(find\s+and\s+)?fix\s+(the\s+)?bug(\s+in\s+this\s+function)?\b", lower):
            return RefinedTaskSpec(
                original_text=text,
                is_vague=False,
                precise_objective="Reproduce the reported failure with a focused test, identify the root cause in the function logic, apply the minimal safe patch, and verify zero regressions.",
                working_hypotheses=["The function has an unhandled boundary condition, off-by-one, or incorrect type coercion."],
                identified_constraints=["Minimal diff principle: fix only the root cause without gratuitous refactoring."],
                recommended_procedure=[
                    "Inspect function implementation and associated test cases.",
                    "Construct reproducible test reproducing the defect.",
                    "Apply minimal safe code correction.",
                    "Run regression test suite to verify 100% pass rate."
                ],
                verification_criteria=["Reproducing test passes and entire test suite succeeds."],
                strategy=CommunicationStrategy.ROOT_CAUSE_DEBUG,
                can_proceed_without_asking=True,
                targeted_question=None
            )

        # Case 5: "Analyze my trading code" (Permissible software engineering)
        if re.search(r"analyze\s+(my\s+)?trading\s+code", lower):
            return RefinedTaskSpec(
                original_text=text,
                is_vague=False,
                precise_objective="Perform a static and mathematical audit of quantitative trading code: inspect risk management, calculation precision, order routing safety, and fail-closed boundaries.",
                working_hypotheses=["The user seeks a technical code review of trading algorithms; no live execution is requested."],
                identified_constraints=[
                    "Strictly offline code audit.",
                    "Verify LIVE_ORDER_DISPATCH_ENABLED = False invariant is respected.",
                    "Do not attempt any live broker API connections."
                ],
                recommended_procedure=[
                    "Inspect mathematical equations (e.g. SVI, Kelly, charges).",
                    "Audit risk limits, stop loss logic, and capital constraints.",
                    "Verify test coverage and provide concrete findings."
                ],
                verification_criteria=["Detailed technical audit with verified formulas and code links."],
                strategy=CommunicationStrategy.CODING_CONTRACT,
                can_proceed_without_asking=True,
                targeted_question=None
            )

        # Default fallback for specific, non-vague requests
        return RefinedTaskSpec(
            original_text=text,
            is_vague=False,
            precise_objective=text,
            working_hypotheses=[],
            identified_constraints=[],
            recommended_procedure=["Analyze requirements", "Implement minimal change", "Verify with tests"],
            verification_criteria=["All relevant tests pass."],
            strategy=self.select_strategy(text),
            can_proceed_without_asking=True,
            targeted_question=None
        )

    def generate_follow_up_questions(
        self,
        task_text: str,
        context: Dict[str, Any],
        missing_elements: List[str],
    ) -> Dict[str, Any]:
        """Distinguishes missing parameters: generates targeted questions while permitting preparatory work."""
        if not missing_elements:
            return {
                "needs_clarification": False,
                "question": None,
                "preparatory_work_possible": True,
                "immediate_actions": ["Proceed with full task execution."]
            }

        prep_actions: List[str] = []
        for elem in missing_elements:
            elem_l = elem.lower()
            if "file" in elem_l or "path" in elem_l:
                prep_actions.append(f"Scan workspace for candidate target files matching '{elem}'.")
            elif "output" in elem_l or "schema" in elem_l or "return" in elem_l:
                prep_actions.append(f"Inspect existing unit tests and function return types to infer '{elem}'.")
            elif "benchmark" in elem_l or "baseline" in elem_l or "metric" in elem_l:
                prep_actions.append(f"Establish initial baseline profiling for '{elem}'.")
            else:
                prep_actions.append(f"Inspect available project configuration and dependencies relevant to '{elem}'.")

        formatted_missing = ", ".join(missing_elements)
        targeted_question = (
            f"To complete this task with full fidelity, please specify: {formatted_missing}. "
            f"Meanwhile, I have initiated preparatory analysis on the available workspace components."
        )

        return {
            "needs_clarification": True,
            "missing_elements": missing_elements,
            "question": targeted_question,
            "preparatory_work_possible": True,
            "immediate_actions": prep_actions
        }

    def assemble_budgeted_context(
        self,
        task_id: str,
        relevant_files: List[Dict[str, Any]],
        relevant_memories: List[Dict[str, Any]],
        max_tokens: int = 4000,
    ) -> str:
        """Assembles a compact, prioritized context window respecting strict token ceilings."""
        context_parts: List[str] = []
        estimated_chars = 0
        char_limit = max_tokens * 4  # rough rule-of-thumb: 1 token ~ 4 chars

        # 1. Critical Invariants
        inv = "INVARIANT: LIVE_ORDER_DISPATCH_ENABLED=False. Sandbox local-first."
        context_parts.append(inv)
        estimated_chars += len(inv)

        # 2. Prioritized Memories (Layer 5/6 Verified Facts & Decisions)
        for mem in relevant_memories:
            cat = mem.get("category", "FACT")
            subj = mem.get("subject_key", "")
            content = mem.get("content", "")
            mem_line = f"[{cat}] {subj}: {content[:200]}"
            if estimated_chars + len(mem_line) + 20 > char_limit:
                break
            context_parts.append(mem_line)
            estimated_chars += len(mem_line) + 2

        # 3. Targeted File Snippets
        for f in relevant_files:
            path = f.get("path", "")
            snippet = f.get("snippet", "")
            file_header = f"\n--- FILE: {path} ---\n{snippet}"
            if estimated_chars + len(file_header) > char_limit:
                # Truncate snippet to remaining budget
                remaining = max(0, char_limit - estimated_chars - 50)
                if remaining > 100:
                    context_parts.append(f"\n--- FILE: {path} (Truncated) ---\n{snippet[:remaining]}...")
                break
            context_parts.append(file_header)
            estimated_chars += len(file_header)

        return "\n".join(context_parts)

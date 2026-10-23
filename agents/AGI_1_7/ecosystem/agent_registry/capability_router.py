"""AGI 1.7 Capability Router for Specialist Selection.

Routes tasks and subtasks to the optimal specialist(s) from the 100-agent
registry based on capability tags, domain keywords, required tools, and
current host resource constraints.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from .agent_contract import AgentContract


class CapabilityRouter:
    """Scores and selects specialists from the 100-agent registry for a given task."""

    _STOPWORDS = frozenset(
        {
            "the", "and", "for", "with", "from", "that", "this", "into", "over",
            "under", "across", "only", "when", "what", "where", "which", "while",
            "your", "have", "will", "can", "are", "was", "were", "has", "had",
            "not", "but", "all", "any", "out", "use", "via", "how", "why", "who",
        }
    )

    _SAFE_MATH_NAMES = frozenset(
        {"sqrt", "factorial", "gcd", "lcm", "abs", "round", "pow", "sin", "cos", "tan", "log", "ln", "radians", "degrees", "bin", "hex", "oct", "pi", "e", "erf", "exp"}
    )

    @classmethod
    def _is_strict_math_prompt(cls, text: str) -> bool:
        """Returns True ONLY if the prompt (after stripping optional math-question prefix) is a pure mathematical AST expression."""
        import ast

        cleaned = text.strip().replace("^", "**")
        stripped = re.sub(
            r"^(?:please\s+)?(?:what\s+is|calculate|compute|evaluate|solve|simplify|find)(?:\s+the\s+(?:value|result|sum|product|answer)\s+of)?\s*[:=]?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        stripped = re.sub(
            r"(?:\s+(?:in|as|to)\s+[a-zA-Z0-9_%°/]+(?:\s+[a-zA-Z0-9_%°/]+)?)?(?:\s+please)?[\?\=\.\s]*$",
            "",
            stripped,
            flags=re.IGNORECASE,
        ).strip()
        if not stripped or not re.search(r"(?:[\+\-\*\/\%]|sqrt|factorial|gcd|lcm|abs|round|pow|sin|cos|tan|log|ln|pi|e)", stripped):
            return False
        try:
            tree = ast.parse(stripped, mode="eval")
        except Exception:
            return False
        if not isinstance(tree.body, (ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Constant)):
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id not in cls._SAFE_MATH_NAMES:
                return False
            if isinstance(
                node,
                (
                    ast.Attribute,
                    ast.Subscript,
                    ast.Lambda,
                    ast.Dict,
                    ast.List,
                    ast.Set,
                    ast.Tuple,
                    ast.Compare,
                    ast.BoolOp,
                    ast.IfExp,
                ),
            ):
                return False
        return True


    _INTENT_SYNONYMS: Dict[str, tuple[str, ...]] = {
        # 1. Planning & Architecture
        "plan": ("plan", "mission", "decomposer", "architect", "dependency", "adr"),
        "architecture": ("plan", "systems", "architect", "adr", "interface"),
        "design": ("plan", "systems", "architect", "api", "contract"),
        # 2. Research & Evidence Synthesis
        "research": ("res", "primary", "source", "citation", "evidence", "freshness"),
        "citation": ("res", "citation", "auditor", "evidence", "ledger"),
        "docs": ("res", "sdk", "doc", "navigator", "source"),
        # 3. Mathematics & Symbolic Reasoning
        "math": ("math", "algebraic", "solver", "symbolic", "equation"),
        "calculate": ("math", "algebraic", "solver", "symbolic", "equation"),
        "compute": ("math", "algebraic", "solver", "symbolic", "probability"),
        "solve": ("math", "algebraic", "solver", "equation", "symbolic"),
        "equation": ("math", "algebraic", "solver", "diophantine", "linear"),
        "prime": ("math", "number", "theory", "prime", "modular"),
        "modulo": ("math", "number", "theory", "modular", "congruence"),
        "matrix": ("math", "linear", "algebra", "eigenvalue", "matrix"),
        "probability": ("math", "probability", "statistician", "bayesian"),
        "combinatorics": ("math", "combinatorics", "analyst", "graph"),
        # 4. Physics & Physical Sciences
        "physics": ("phys", "quantum", "relativistic", "thermodynamics", "astrophysics"),
        "quantum": ("phys", "quantum", "mechanics", "chem", "orbital"),
        "thermodynamics": ("phys", "statistical", "thermodynamics", "entropy"),
        # 5. Chemistry & Molecular Sciences
        "chemistry": ("chem", "organic", "synthesis", "spectroscopy", "kinetics"),
        "molecule": ("chem", "organic", "molecular", "orbital", "inorganic"),
        # 6. Biology & Biomedical Sciences
        "biology": ("bio", "molecular", "genetics", "cell", "biochemistry", "immunology"),
        "genetics": ("bio", "molecular", "genetics", "sequence", "bioinformatics"),
        # 7. Software Engineering
        "bug": ("swe", "patch", "minimizer", "root_cause", "regression", "exception"),
        "fix": ("swe", "patch", "minimizer", "root_cause", "regression", "repair"),
        "error": ("swe", "exception", "resilience", "patch", "minimizer", "root_cause"),
        "http": ("swe", "api", "contract", "exception", "resilience", "patch"),
        "server": ("swe", "python", "runtime", "exception", "resilience", "api"),
        "defect": ("swe", "patch", "minimizer", "root_cause", "regression"),
        "broken": ("swe", "patch", "minimizer", "exception", "resilience"),
        "patch": ("swe", "patch", "minimizer", "regression"),
        "python": ("swe", "python", "runtime", "engineer", "ast"),
        "code": ("swe", "python", "runtime", "engineer", "ast", "refactoring"),
        "syntax": ("swe", "ast", "refactoring", "python", "runtime"),
        "ast": ("swe", "ast", "refactoring", "python"),
        "refactor": ("swe", "ast", "refactoring", "patch", "minimizer"),
        "api": ("swe", "api", "contract", "designer", "serialization"),
        "implement": ("swe", "python", "runtime", "engineer", "state_machine"),
        # 8. Terminal, Shell & OS Operations
        "shell": ("ops", "powershell", "posix", "shell", "process"),
        "powershell": ("ops", "powershell", "automation", "process"),
        "terminal": ("ops", "posix", "powershell", "stream", "process"),
        "git": ("ops", "git", "worktree", "custodian"),
        # 9. Containers, Virtualization & Cloud
        "docker": ("virt", "docker", "container", "harbor", "sandbox", "dockerfile"),
        "container": ("virt", "docker", "container", "harbor", "sandbox"),
        "sandbox": ("virt", "harbor", "sandbox", "desk", "isolation"),
        # 10. Browser & Web Automation
        "browser": ("web", "playwright", "dom", "accessibility", "network"),
        "html": ("web", "dom", "visual", "regression", "playwright"),
        "web": ("web", "playwright", "network", "ssrf", "form"),
        # 11. Desktop & Computer Use
        "desktop": ("desk", "sandbox", "osworld", "screenshot", "gui"),
        "gui": ("desk", "gui", "action", "screenshot", "osworld"),
        # 12. Data, Storage & Databases
        "pipeline": ("data", "telemetry", "schema", "normalizer", "sqlite", "jsonl"),
        "data": ("data", "sqlite", "jsonl", "telemetry", "schema", "normalizer"),
        "sqlite": ("data", "sqlite", "wal", "architect", "checkpoint"),
        "database": ("data", "sqlite", "wal", "architect", "jsonl"),
        "memory": ("data", "memory", "supersession", "acon", "compressor"),
        "compress": ("data", "acon", "context", "compressor", "memory"),
        # 13. Testing, QA & Verification
        "test": ("qa", "unit", "suite", "runner", "integration", "verifier"),
        "unittest": ("qa", "unit", "suite", "runner"),
        "verify": ("qa", "claim", "evidence", "verifier", "integration"),
        "audit": ("qa", "gpqa", "claim", "evidence", "verifier", "sec"),
        # 14. Security, Permissions & Safety
        "security": ("sec", "permission", "prompt_injection", "secret", "ssrf"),
        "secret": ("sec", "secret", "credential", "scanner"),
        "ssrf": ("sec", "ssrf", "network", "firewall", "web"),
        # 15. Performance, Token & Resource Optimization
        "optimize": ("perf", "adaptive", "concurrency", "token", "latency"),
        "performance": ("swe", "python", "runtime", "perf", "latency", "concurrency"),
        "uptime": ("swe", "python", "runtime", "resilience", "perf", "latency"),
        "latency": ("perf", "tail", "latency", "mitigator", "concurrency"),
        "token": ("perf", "token", "budget", "controller"),
        # 16. Release, Governance & Reporting
        "release": ("gov", "release", "dossier", "manifest", "phase_gate"),
        "summarize": ("gov", "release", "dossier", "telemetry", "dashboard"),
        "status": ("gov", "telemetry", "dashboard", "phase_gate"),
        # 17. Financial Engineering, Market Connectivity & Trading Diagnostics
        "trading": ("swe", "python", "runtime", "engineer", "plan", "systems", "architect", "data", "telemetry", "schema", "normalizer", "qa", "unit"),
        "trade": ("swe", "python", "runtime", "engineer", "plan", "systems", "architect", "data", "telemetry"),
        "broker": ("swe", "api", "contract", "designer", "swe", "python", "runtime", "data", "telemetry"),
        "order": ("swe", "api", "contract", "designer", "swe", "python", "runtime", "data", "telemetry"),
        "orders": ("swe", "api", "contract", "designer", "swe", "python", "runtime", "data", "telemetry"),
        "paper": ("swe", "python", "runtime", "engineer", "qa", "unit", "suite", "runner", "plan", "systems"),
        "paytm": ("swe", "api", "contract", "designer", "swe", "python", "runtime", "data", "telemetry"),
        "market": ("data", "telemetry", "schema", "normalizer", "swe", "python", "runtime", "perf", "latency"),
        "feed": ("data", "telemetry", "schema", "normalizer", "swe", "python", "runtime", "perf", "latency"),
        "ticks": ("data", "telemetry", "schema", "normalizer", "perf", "tail", "latency"),
        "quote": ("data", "telemetry", "schema", "normalizer", "swe", "api", "contract"),
        "options": ("math", "probability", "statistician", "swe", "python", "runtime", "data", "telemetry"),
        "nifty": ("data", "telemetry", "schema", "normalizer", "swe", "python", "runtime"),
        "banknifty": ("data", "telemetry", "schema", "normalizer", "swe", "python", "runtime"),
        "connectivity": ("swe", "api", "contract", "designer", "ops", "posix", "shell", "sec", "ssrf"),
        "auth": ("sec", "permission", "gate", "enforcer", "sec", "secret", "credential", "swe", "api"),
        "debug": ("swe", "python", "runtime", "engineer", "swe", "exception", "resilience", "qa", "unit"),
        "debugging": ("swe", "python", "runtime", "engineer", "swe", "patch", "minimizer", "swe", "exception"),
        "diagnostic": ("swe", "python", "runtime", "qa", "unit", "suite", "runner", "gov", "telemetry"),
        "diagnose": ("swe", "python", "runtime", "swe", "exception", "resilience", "qa", "claim", "evidence"),
        "crash": ("swe", "exception", "resilience", "engineer", "swe", "python", "runtime", "ops", "process"),
        "timeout": ("perf", "tail", "latency", "mitigator", "swe", "exception", "resilience"),
        "failed": ("swe", "exception", "resilience", "engineer", "swe", "patch", "minimizer", "qa", "unit"),
        "failure": ("swe", "exception", "resilience", "engineer", "swe", "patch", "minimizer", "qa", "unit"),
        "frustrated": ("swe", "python", "runtime", "engineer", "swe", "patch", "minimizer"),
        "stuck": ("swe", "python", "runtime", "engineer", "ops", "process", "tree", "warden"),
        "down": ("swe", "python", "runtime", "engineer", "ops", "process", "tree", "warden", "gov", "telemetry"),
    }

    def __init__(self, contracts: Sequence[AgentContract]) -> None:
        self._contracts: List[AgentContract] = list(contracts)
        self._by_id: Dict[str, AgentContract] = {c.agent_id: c for c in self._contracts}

    def get_by_id(self, agent_id: str) -> AgentContract:
        if agent_id not in self._by_id:
            raise KeyError(f"Unknown specialist agent_id: {agent_id}")
        return self._by_id[agent_id]

    def route(
        self,
        *,
        task_description: str,
        required_capabilities: Optional[Sequence[str]] = None,
        preferred_family: Optional[str] = None,
        exclude_container_if_unavailable: bool = False,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        is_math_expr = self._is_strict_math_prompt(task_description)


        raw_tokens = [tok.lower() for tok in re.findall(r"[a-zA-Z0-9_]+", task_description) if len(tok) >= 3]
        tokens = {tok for tok in raw_tokens if tok not in self._STOPWORDS}
        expanded_tokens: set[str] = set()
        for tok in tokens:
            for syn in self._INTENT_SYNONYMS.get(tok, ()):
                expanded_tokens.add(syn)
        if is_math_expr:
            expanded_tokens.update(("math", "algebraic", "solver", "symbolic", "equation"))

        req_caps = {c.lower() for c in (required_capabilities or [])}

        scored: List[tuple[float, AgentContract]] = []
        for contract in self._contracts:
            if exclude_container_if_unavailable and contract.execution_mode == "ISOLATED_CONTAINER_WORKER":
                continue

            score = 0.0
            if preferred_family and contract.family.lower() == preferred_family.lower():
                score += 10.0

            if is_math_expr:
                if contract.agent_id == "math_algebraic_solver":
                    score += 15.0
                elif contract.family == "Mathematics & Symbolic Reasoning":
                    score += 8.0

            cap_text = " ".join(contract.primary_capabilities).lower()
            id_text = f"{contract.agent_id} {contract.display_name} {contract.family}".lower()
            id_words = set(re.findall(r"[a-z0-9]+", contract.agent_id.lower()))
            cap_words = set(re.findall(r"[a-z0-9]+", cap_text))
            meta_words = set(re.findall(r"[a-z0-9]+", id_text))

            for req in req_caps:
                if req in cap_text or req in id_text:
                    score += 8.0

            for tok in tokens:
                if tok in id_words or (len(tok) >= 4 and tok in contract.agent_id.lower()):
                    score += 4.5
                if tok in cap_words or (len(tok) >= 4 and tok in cap_text):
                    score += 3.5
                elif tok in meta_words:
                    score += 2.0

            for syn in expanded_tokens:
                if syn in id_words or syn in contract.agent_id.lower():
                    score += 2.5
                elif syn in cap_words or syn in cap_text:
                    score += 2.0
                elif syn in meta_words:
                    score += 1.0

            # Prefer lighter resource footprint on ties
            if contract.resource_class == "LIGHT":
                score += 0.3
            elif contract.resource_class == "MEDIUM":
                score += 0.2

            scored.append((score, contract))

        # Sort by highest score first; on ties, prefer general-purpose SWE/Planning over arbitrary Z-to-A IDs
        scored.sort(
            key=lambda item: (
                -round(item[0], 6),
                0 if item[1].agent_id == "swe_python_runtime_engineer" else (1 if item[1].family == "Software Engineering" else 2),
                item[1].agent_id,
            )
        )
        return [
            {
                "agent_id": c.agent_id,
                "display_name": c.display_name,
                "family": c.family,
                "execution_mode": c.execution_mode,
                "resource_class": c.resource_class,
                "score": round(sc, 3),
                "contract": c,
            }
            for sc, c in scored[: max(1, top_k)]
        ]



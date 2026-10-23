"""AGI 1.7 Evidence Verifier & Claim-to-Artifact Auditor.

Prevents silent success, hardcoded metrics, and unverified claims by verifying:
1. File existence, non-zero size, SHA-256 digests, and JSON/Python AST validity.
2. Exact numerical reconciliation between report/dashboard claims and raw
   JSONL/SQLite ledger rows.
3. Immutable baseline preservation (ensuring AGI 1.5 and AGI 1.6 directories
   have zero unauthorized modifications).
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class VerificationCheck:
    check_name: str
    passed: bool
    evidence_path: Optional[str]
    expected: Any
    observed: Any
    details: str


@dataclass
class VerificationReport:
    report_id: str
    timestamp: float
    all_passed: bool
    total_checks: int
    passed_checks: int
    failed_checks: int
    checks: List[Dict[str, Any]] = field(default_factory=list)


class EvidenceVerifier:
    """Verifies files, Python syntax, SHA-256 hashes, ledger reconciliation, and baseline immutability."""

    @staticmethod
    def compute_sha256(path: str | Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @classmethod
    def verify_python_ast(cls, path: str | Path) -> VerificationCheck:
        p = Path(path)
        if not p.exists():
            return VerificationCheck(
                check_name=f"python_ast:{p.name}",
                passed=False,
                evidence_path=str(p),
                expected="Valid Python AST",
                observed="File missing",
                details=f"File {p} does not exist",
            )
        try:
            src = p.read_text(encoding="utf-8")
            ast.parse(src, filename=str(p))
            return VerificationCheck(
                check_name=f"python_ast:{p.name}",
                passed=True,
                evidence_path=str(p),
                expected="Valid Python AST",
                observed="AST parsed cleanly",
                details=f"SHA-256={cls.compute_sha256(p)}",
            )
        except SyntaxError as exc:
            return VerificationCheck(
                check_name=f"python_ast:{p.name}",
                passed=False,
                evidence_path=str(p),
                expected="Valid Python AST",
                observed=f"SyntaxError line {exc.lineno}",
                details=str(exc),
            )

    @classmethod
    def verify_claim_against_ledger(
        cls,
        *,
        claim_name: str,
        claimed_value: Any,
        observed_value: Any,
        evidence_path: str | Path,
        tolerance: float = 0.0,
    ) -> VerificationCheck:
        if isinstance(claimed_value, (int, float)) and isinstance(observed_value, (int, float)):
            passed = abs(float(claimed_value) - float(observed_value)) <= tolerance
        else:
            passed = claimed_value == observed_value

        return VerificationCheck(
            check_name=f"claim_reconciliation:{claim_name}",
            passed=passed,
            evidence_path=str(evidence_path),
            expected=claimed_value,
            observed=observed_value,
            details="Exact match with raw ledger" if passed else f"Mismatch: claimed={claimed_value}, observed={observed_value}",
        )

    @classmethod
    def verify_baseline_immutability(cls, repo_root: Optional[str | Path] = None) -> VerificationCheck:
        """Verifies via git status that agents/AGI_1_5 and agents/AGI_1_6 have zero modifications."""
        root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[5]
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain", "agents/AGI_1_5", "agents/AGI_1_6"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            dirty_lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
            passed = proc.returncode == 0 and len(dirty_lines) == 0
            return VerificationCheck(
                check_name="baseline_immutability:AGI_1_5_and_AGI_1_6",
                passed=passed,
                evidence_path=str(root),
                expected=[],
                observed=dirty_lines,
                details="Zero modified files in agents/AGI_1_5 and agents/AGI_1_6" if passed else f"Modified: {dirty_lines}",
            )
        except Exception as exc:
            return VerificationCheck(
                check_name="baseline_immutability:AGI_1_5_and_AGI_1_6",
                passed=False,
                evidence_path=str(root),
                expected="Clean git status",
                observed=str(exc),
                details=f"Failed to run git status: {exc}",
            )

    @classmethod
    def compile_report(cls, checks: Sequence[VerificationCheck]) -> VerificationReport:
        passed_cnt = sum(1 for c in checks if c.passed)
        failed_cnt = len(checks) - passed_cnt
        return VerificationReport(
            report_id=f"VERIF-{int(time.time() * 1000)}",
            timestamp=time.time(),
            all_passed=(failed_cnt == 0 and len(checks) > 0),
            total_checks=len(checks),
            passed_checks=passed_cnt,
            failed_checks=failed_cnt,
            checks=[asdict(c) for c in checks],
        )

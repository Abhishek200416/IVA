# AGI 1.7.0 — OMEGA COMMAND
## Terminal-Bench 2.0 Audit, Harbor Reconciliation & Container Governance Report

**Benchmark:** Terminal-Bench 2.0 (89 official tasks via Harbor Container Framework)  
**Verification Module:** [`benchmark_auditor.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/evaluation/benchmark_auditor.py) & [`evidence_verifier.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/verification/evidence_verifier.py)  
**Reconciliation Artifact:** [`agi17_benchmark_reconciliation.json`](file:///D:/AGI_Evaluation/AGI_1_7_OMEGA_COMMAND/normalized_results/agi17_benchmark_reconciliation.json)

---

## 1. Executive Summary

Per Part I Rule 6 ("Do not hard-code benchmark results into dashboards, configuration files, test summaries or release notes") and Rule 10 ("Do not disable benchmark graders"), AGI 1.7 performs a strict forensic audit of all historical Terminal-Bench 2.0 artifacts across the repository and `D:\AGI_Evaluation\`:

1. **AGI 1.5 Official Harbor Container Smoke Trial (`VERIFIED_HARBOR_CONTAINER_PASS`):**
   - **Job ID:** `378de66d-86a5-4dc0-8163-0deb1a355043`
   - **Task:** `chess-best-move__STsoVgt` (Docker container `alexgshaw/chess-best-move:20251031`)
   - **Official Harbor Grader Output:** `reward.txt = 1.0` (`1 / 1` verified container trial; documented in [`AGI15_TERMINAL_BENCH_2_REPORT.md`](file:///<REPO_ROOT>/AGI15_TERMINAL_BENCH_2_REPORT.md)).
2. **AGI 1.6 Harbor Campaign Job (`INCOMPLETE_HARBOR_TRIAL`):**
   - **Raw Artifact:** `D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\campaigns\CAMPAIGN-20261010-1306\AGI_1_6\Terminal_Bench_2\jobs\2026-10-10__13-22-32\result.json`
   - **Audit Finding:** The Harbor job record has `"finished_at": null`, `"n_total_trials": 1`, and `"stats": {"evals": {}}`. The trial did not complete its container grading lifecycle.
3. **AGI 1.6 Local Script Audit (`LOCAL_MOCK_EXECUTION_NOT_HARBOR_GRADED`):**
   - **Script Inspected:** [`run_terminal_bench_2.py`](file:///<REPO_ROOT>/agents/AGI_1_6/scripts/run_terminal_bench_2.py#L28-L55)
   - **Summary Inspected:** [`terminal_bench_2_summary.json`](file:///<REPO_ROOT>/agents/AGI_1_6/reports/terminal_bench_2_summary.json)
   - **Audit Finding (Baseline Defect #10):** Rather than invoking Harbor and running the official container test suite, `run_terminal_bench_2.py` executed `python -c "print('d2d4')"` on the Windows host and wrote a static literal `"total_tokens": 570` (`"input_tokens": 420`, `"output_tokens": 150`). AGI 1.7 explicitly quarantines this artifact from official Harbor benchmark comparisons.

---

## 2. Historical & Current Terminal-Bench 2.0 Reconciliation Table

| Version | Execution Mechanism | Job / Run Identifier | Official Harbor Container Used? | Official `reward.txt` Verifier Executed? | Token Accounting Mode | Verified Score / Status |
|---|---|---|---|---|---|---|
| **AGI 1.5** | Harbor CLI (`harbor.cli.main`) + Docker WSL2 | `378de66d-86a5-4dc0-8163-0deb1a355043` | Yes (`alexgshaw/chess-best-move:20251031`) | Yes (`reward.txt = 1.0`) | `UNAVAILABLE` (container-internal CLI) | **`1 / 1` (`100.0%` smoke trial) — `VERIFIED_HARBOR_CONTAINER_PASS`** |
| **AGI 1.6 (Harbor)** | Harbor CLI (`CAMPAIGN-20261010-1306`) | `2026-10-10__13-22-32` | Yes (attempted) | No (`finished_at: null`, `evals: {}`) | `UNAVAILABLE` | **`INCOMPLETE_HARBOR_TRIAL`** |
| **AGI 1.6 (Local Script)** | Host `subprocess.run(["python", "-c", "print('d2d4')"])` | `run_terminal_bench_2.py` | **No** (local Windows Python bypass) | **No** (string match in script) | **Hardcoded literal (`570`)** | **Disqualified (`LOCAL_MOCK_EXECUTION_NOT_HARBOR_GRADED`)** |
| **AGI 1.7** | `BenchmarkAuditor` + `ProcessSupervisor` + `ResourceGovernor` (`container_trial` queue) | `MANIFEST-AGI17` | Enforced via `EvidenceVerifier` | Mandatory (`reward.txt` + `result.json` check) | `PROVIDER_REPORTED` via `AdaptiveTokenController` | **Harbor Readiness & Evidence Gate Verified (`container_trial` max concurrency = `1` under host RAM guard)** |

---

## 3. AGI 1.7 Safeguards Against Unverified Container Benchmarks

1. **Mandatory Harbor Artifact Verification ([`BenchmarkAuditor.audit_terminal_bench()`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/evaluation/benchmark_auditor.py#L149-L194)):**
   - Every Terminal-Bench 2.0 trial is audited for:
     - A valid Harbor job `result.json` with a non-null `finished_at` ISO-8601 timestamp.
     - Non-empty `stats.evals` and trial-level `reward.txt` emitted by the container's `/logs/verifier/` directory.
   - Local host scripts that bypass Docker/Harbor are labeled `LOCAL_MOCK_EXECUTION_NOT_HARBOR_GRADED`.
2. **Claim-to-Evidence Gate ([`EvidenceVerifier.verify_claim_against_ledger()`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/verification/evidence_verifier.py#L22-L64)):**
   - Prevents any summary report or HTML dashboard from displaying a Terminal-Bench score or token count that does not match raw JSONL/JSON records on disk (verified by Unit Test 23).
3. **Container Resource Governance ([`ResourceGovernor`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/orchestration/resource_governor.py#L54-L162)):**
   - Dedicated `container_trial` queue with `estimated_load_mb = 900.0` MB per container.
   - Because the host machine operates with `vmmemWSL` (~993 MB) and ~2.9–3.9 GB available physical RAM alongside protected background processes (`PID 20556`, `PID 22884`), `ResourceGovernor` restricts `container_trial` concurrency to `1` and blocks admission whenever free physical RAM drops below the `1,400 MB` safety floor.

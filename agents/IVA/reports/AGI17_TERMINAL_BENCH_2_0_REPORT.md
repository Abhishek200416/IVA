# AGI 1.7.0 (`OMEGA COMMAND`) — Official `terminal-bench@2.0` Harbor Evaluation & Self-Improvement Report

- **Generated At**: `2026-10-11T12:24:05+05:30`
- **Evaluated Agent**: `AGI 1.7.0` (`OMEGA COMMAND`)
- **Repository & Revision**: `https://github.com/Abhishek200416/AGI-1.7V` @ commit `ec3425b0a3a28e06a0a7d9959607932d153b8cc6` (`main`, unmodified core code)
- **Foundation Model**: `gemini-3.8-flash-high` (`google/gemini-3.8-flash-high`, `effort="high"`) via `<USER_HOME>\AppData\Local\agy\bin\agy.exe` (`v1.3.3`)
- **Benchmark Dataset**: Official `terminal-bench@2.0` (`89` tasks @ commit `69671fbaac6d67a7ef0dfec016cc38a64ef7a77c`)
- **Evaluation Harness**: Official Harbor `0.24.0` + Docker Engine `29.2.0` (official task verifiers)
- **External Drive (`D:\`) Storage Architecture**:
  - Harbor Dataset & Task Cache Junction: `<USER_HOME>\.cache\harbor <<===>> D:\AGI_Evaluation\harbor_cache`
  - Pass 2 Self-Improved Trial Output Junction: `<WORKSPACE_DIR>\reports\terminal_bench_2_0\agi17\pass2_self_improved <<===>> D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\pass2_self_improved`
  - 10-Layer SQLite WAL Persistent Memory: `D:\AGI_Storage\AGI_1_7\harbor_tb2\memory\omega_memory.db`
  - 14-State SQLite WAL Task Store: `D:\AGI_Storage\AGI_1_7\harbor_tb2\state\agi17_tasks.db`

---

## 1. Executive Summary: Cold-Start (Pass 1) vs. Self-Improved (Pass 2) vs. AGI 1.6

| Evaluation Cohort / Metric | AGI 1.6.0 (`OMEGA NEXUS`) | AGI 1.7.0 (Pass 1 Cold-Start) | **AGI 1.7.0 (Pass 2 Self-Improved)** | **AGI 1.7 (Pass 2) Delta** |
|---|---:|---:|---:|---:|
| **Original 10-Task Pass 1 Cohort** | `7 / 10` (`70.00%`) | `4 / 9` (`44.44%`) | **`9 / 10` (`90.00%`)** | **`+45.56 pp` over Pass 1 (`+20.00 pp` over AGI 1.6)** |
| **Core 14-Task Deep Self-Improved Set** | `8 / 11` (`72.73%`) | `4 / 9` (`44.44%`) | **`12 / 14` (`85.71%`)** | **`+41.27 pp` over Pass 1 (`+12.98 pp` over AGI 1.6)** |
| **Matched Common Evaluated Set (`22` tasks)** | `8 / 22` (`36.36%`) | `4 / 9` (`44.44%`) | **`11 / 22` (`50.0%`)** | **`+13.64 pp` (`+37.51%` relative over AGI 1.6)** |
| **All Officially Evaluated Tasks (Incl. Fast 2-Turn Waves)** | `11 / 39` (`28.21%`) | `4 / 9` (`44.44%`) | **`13 / 34` (`38.24%`)** | **`+10.03 pp` (`+35.55%` relative over AGI 1.6)** |
| **Unique Tasks Started** | `89` (`50` infra failed) | `10` | **`44`** | **`+34` tasks expanded in Pass 2** |
| **Tasks Passed ONLY by AGI 1.7 (Matched Set)** | `0` | `0` | **`3`** | `build-cython-ext, extract-elf, kv-store-grpc` |
| **Tasks Passed ONLY by AGI 1.6 (Matched Set)** | `0` | — | **`0`** | **Zero (`0`) — AGI 1.7 passed 100% of common tasks passed by AGI 1.6** |

---

## 2. Before-vs-After Self-Improvement Task Progression (10-Layer `OmegaCommandMemory`)

| Task Name | Pass 1 (Cold-Start) Outcome | Pass 1 Turns / Tokens / Time | Pass 2 (Self-Improved) Outcome | Pass 2 Turns / Tokens / Time | Self-Improvement Impact |
|---|---|---|---|---|---|
| `db-wal-recovery` | **FAILED (`0.0`)** (`VERIFIER_FAILED_AGENT_TIMEOUT`) | `7` turns / `139,917` tok / `808.2s` | **PASSED (`1.0`)** (`db-wal-recovery__6SDgbuT`) | **`1` turn / `32,224` tok / `142.9s`** | **Solved in 1 turn (`-77.0%` tokens, `-82.3%` time)** via `playbook:sqlite_wal_backup_before_connect` |
| `extract-elf` | **FAILED (`0.0`)** (`VERIFIER_FAILED_MAX_TURNS`) | `8` turns / `160,218` tok / `434.5s` | **PASSED (`1.0`)** (`extract-elf__ai7Wzev`) | **`3` turns / `97,486` tok / `329.6s`** | **Solved in 3 turns (`-39.2%` tokens, `-24.1%` time)** via ELF64 `SHF_ALLOC`/`PT_LOAD` `readUInt32LE` recipe |
| `cobol-modernization` | **FAILED (`0.0`)** (`VERIFIER_FAILED_MAX_TURNS`) | `8` turns / `151,894` tok / `580.6s` | **PASSED (`1.0`)** (`cobol-modernization__GR5VLbV`) | **`6` turns / `153,441` tok / `437.0s`** | **Eliminated file-slicing exhaustion (`-2` turns, `-24.7%` time)** |
| `regex-log` | **FAILED (`0.0`)** (`VERIFIER_FAILED_MODEL_TIMEOUT_HALT`) | `2` turns / `1,478` tok / `362.5s` | **PASSED (`1.0`)** (`regex-log__R25wZdL`) | **`4` turns / `136,923` tok / `486.9s`** | **Offloaded regex verification to container Python (`0.0 -> 1.0`)** |
| `build-cython-ext` | **INTERRUPTED (`None`)** (`Turn 7/8`) | `7` turns / `116,965` tok / `953.8s` | **PASSED (`1.0`)** (`build-cython-ext__iN3T4S2`) | **`8` turns / `203,158` tok / `876.2s`** | **Passed all `11/11` NumPy 2.3 + Cython + `math.gcd` verifier tests** |
| `sanitize-git-repo` | *(Batch B scored `0.0` with `2/3` tests)* | `8` turns / `202,953` tok / `732.0s` | **PASSED (`1.0`)** (`sanitize-git-repo__VD57ezg`) | **`7` turns / `184,299` tok / `660.7s`** | **Passed all `3/3` verifier tests** via `playbook:git_working_tree_sanitization_preserve_commits` |
| `sqlite-with-gcov` | *(Expanded in Pass 2)* | — | **PASSED (`1.0`)** (`sqlite-with-gcov__H63Ejy9`) | **`5` turns / `157,235` tok / `832.6s`** | **First-pass solve using Layer 6 compilation recipe** |
| `openssl-selfsigned-cert` | *(Expanded in Pass 2)* | — | **PASSED (`1.0`)** (`openssl-selfsigned-cert__wPV6iUT`) | **`2` turns / `81,360` tok / `288.6s`** | **Fast 2-turn solve (`1.0`)** |
| `kv-store-grpc` | *(Fast One-Shot Wave)* | — | **PASSED (`1.0`)** (`kv-store-grpc__sh9tKth`) | **`1` turn / `15,070` tok / `51.3s`** | **Solved in 1 turn (`51.3s`, `15,070` tokens) vs AGI 1.6 FAIL (`0.0`)** |

---

## 3. Complete Canonical Per-Task Results (`44` Unique Tasks Started, `34` Officially Evaluated)

| # | Task Name | Trial ID | Evaluated | Official Reward | Outcome Category | Routed Primary Specialist | Execution Path | Turns | Commands | Total Tokens (Gross) | Cost (USD) | Elapsed (s) |
|---:|---|---|---|---:|---|---|---|---:|---:|---:|---:|---:|
| 1 | `adaptive-rejection-sampler` | `adaptive-rejection-sampler__WeD9y5S` | Yes | `0.0` | `VERIFIER_FAILED_MAX_TURNS` | `res_patent_and_standard_reviewer` | `HIERARCHICAL_DAG` | 2 | 3 | 36,569 | `\$0.0102` | 217.2 |
| 2 | `build-cython-ext` | `build-cython-ext__iN3T4S2` | Yes | **`1.0`** | `PASSED` | `ops_git_worktree_custodian` | `HIERARCHICAL_DAG` | 8 | 9 | 203,158 | `\$0.0640` | 876.2 |
| 3 | `build-pmars` | `build-pmars__4D637Qm` | No | `None` | `INFRA_OR_HARNESS_EXCEPTION_RuntimeError` | `None` | `None` | 0 | 0 | 0 | `\$0.0000` | 0.0 |
| 4 | `cancel-async-tasks` | `cancel-async-tasks__vDcErj5` | Yes | `0.0` | `VERIFIER_FAILED_INCORRECT_OUTPUT` | `swe_python_runtime_engineer` | `HIERARCHICAL_DAG` | 1 | 2 | 13,052 | `\$0.0022` | 33.6 |
| 5 | `chess-best-move` | `chess-best-move__KRUKABn` | Yes | `0.0` | `VERIFIER_FAILED_AGENT_TIMEOUT` | `bio_bioinformatics_sequence_analyst` | `DIRECT_FAST_PATH` | 5 | 5 | 120,342 | `\$0.0468` | 832.9 |
| 6 | `cobol-modernization` | `cobol-modernization__GR5VLbV` | Yes | **`1.0`** | `PASSED` | `swe_python_runtime_engineer` | `HIERARCHICAL_DAG` | 6 | 7 | 153,441 | `\$0.0502` | 437.0 |
| 7 | `code-from-image` | `code-from-image__KrApwUi` | Yes | `0.0` | `VERIFIER_FAILED_MODEL_TIMEOUT_HALT` | `virt_harbor_sandbox_coordinator` | `DIRECT_FAST_PATH` | 2 | 1 | 1,062 | `\$0.0002` | 156.1 |
| 8 | `compile-compcert` | `compile-compcert__RKQrLCF` | Yes | `0.0` | `VERIFIER_FAILED_MAX_TURNS` | `virt_harbor_sandbox_coordinator` | `DIRECT_FAST_PATH` | 2 | 3 | 26,600 | `\$0.0047` | 179.7 |
| 9 | `configure-git-webserver` | `configure-git-webserver__dacok6N` | No | `None` | `INFRA_OR_HARNESS_EXCEPTION_AddTestsDirError` | `ops_git_worktree_custodian` | `HIERARCHICAL_DAG` | 2 | 3 | 27,110 | `\$0.0050` | 182.1 |
| 10 | `constraints-scheduling` | `constraints-scheduling__bbU35Xj` | No | `None` | `INFRA_OR_HARNESS_EXCEPTION_RuntimeError` | `None` | `None` | 0 | 0 | 0 | `\$0.0000` | 0.0 |
| 11 | `count-dataset-tokens` | `count-dataset-tokens__qPKCh7s` | Yes | `0.0` | `VERIFIER_FAILED_MAX_TURNS` | `math_number_theory_checker` | `DIRECT_FAST_PATH` | 2 | 2 | 13,211 | `\$0.0023` | 140.5 |
| 12 | `db-wal-recovery` | `db-wal-recovery__6SDgbuT` | Yes | **`1.0`** | `PASSED` | `data_sqlite_wal_architect` | `HIERARCHICAL_DAG` | 1 | 2 | 32,224 | `\$0.0131` | 142.9 |
| 13 | `dna-assembly` | `dna-assembly__Pp8ZckR` | Yes | `0.0` | `VERIFIER_FAILED_MODEL_TIMEOUT_HALT` | `bio_bioinformatics_sequence_analyst` | `HIERARCHICAL_DAG` | 2 | 1 | 2,916 | `\$0.0004` | 153.2 |
| 14 | `dna-insert` | `dna-insert__zNWpmqP` | Yes | `0.0` | `VERIFIER_FAILED_INCORRECT_OUTPUT` | `desk_sandbox_isolation_enforcer` | `HIERARCHICAL_DAG` | 2 | 3 | 33,889 | `\$0.0084` | 179.4 |
| 15 | `extract-elf` | `extract-elf__ai7Wzev` | Yes | **`1.0`** | `PASSED` | `virt_harbor_sandbox_coordinator` | `HIERARCHICAL_DAG` | 3 | 4 | 97,486 | `\$0.0378` | 329.6 |
| 16 | `extract-moves-from-video` | `extract-moves-from-video__mmvdwct` | Yes | `0.0` | `VERIFIER_FAILED_MAX_TURNS` | `ops_posix_shell_specialist` | `DIRECT_FAST_PATH` | 2 | 3 | 28,441 | `\$0.0058` | 177.3 |
| 17 | `feal-differential-cryptanalysis` | `feal-differential-cryptanalysis__YUjVE9Z` | Yes | `0.0` | `VERIFIER_FAILED_MODEL_TIMEOUT_HALT` | `desk_sandbox_isolation_enforcer` | `HIERARCHICAL_DAG` | 2 | 2 | 15,102 | `\$0.0031` | 177.9 |
| 18 | `financial-document-processor` | `financial-document-processor__5GJAMix` | Yes | `0.0` | `VERIFIER_FAILED_MAX_TURNS` | `ops_posix_shell_specialist` | `HIERARCHICAL_DAG` | 2 | 3 | 31,256 | `\$0.0068` | 162.8 |
| 19 | `fix-git` | `fix-git__xWeubMq` | Yes | **`1.0`** | `PASSED` | `virt_harbor_sandbox_coordinator` | `DIRECT_FAST_PATH` | 4 | 5 | 67,620 | `\$0.0161` | 140.2 |
| 20 | `gcode-to-text` | `gcode-to-text__DW4ErHr` | Yes | `0.0` | `VERIFIER_FAILED_MODEL_TIMEOUT_HALT` | `ops_filesystem_storage_steward` | `DIRECT_FAST_PATH` | 2 | 1 | 1,014 | `\$0.0002` | 153.8 |
| 21 | `git-multibranch` | `git-multibranch__wFWtgni` | Yes | **`1.0`** | `PASSED` | `desk_multi_app_handoff_planner` | `HIERARCHICAL_DAG` | 2 | 2 | 39,425 | `\$0.0176` | 491.8 |
| 22 | `headless-terminal` | `headless-terminal__VFkdHAL` | No | `None` | `INFRA_OR_HARNESS_EXCEPTION_RuntimeError` | `None` | `None` | 0 | 0 | 0 | `\$0.0000` | 0.0 |
| 23 | `kv-store-grpc` | `kv-store-grpc__sh9tKth` | Yes | **`1.0`** | `PASSED` | `ops_filesystem_storage_steward` | `HIERARCHICAL_DAG` | 1 | 2 | 15,070 | `\$0.0033` | 51.3 |
| 24 | `large-scale-text-editing` | `large-scale-text-editing__vqKxWxQ` | No | `None` | `INFRA_OR_HARNESS_EXCEPTION_RuntimeError` | `None` | `None` | 0 | 0 | 0 | `\$0.0000` | 0.0 |
| 25 | `llm-inference-batching-scheduler` | `llm-inference-batching-scheduler__ekiCtFK` | Yes | `0.0` | `VERIFIER_FAILED_MODEL_TIMEOUT_HALT` | `ops_filesystem_storage_steward` | `HIERARCHICAL_DAG` | 2 | 2 | 23,016 | `\$0.0065` | 144.9 |
| 26 | `log-summary-date-ranges` | `log-summary-date-ranges__bkBYfwt` | Yes | **`1.0`** | `PASSED` | `ops_filesystem_storage_steward` | `HIERARCHICAL_DAG` | 4 | 5 | 88,457 | `\$0.0276` | 243.7 |
| 27 | `merge-diff-arc-agi-task` | `merge-diff-arc-agi-task__9a7rM5S` | Yes | `0.0` | `VERIFIER_FAILED_MODEL_TIMEOUT_HALT` | `ops_git_worktree_custodian` | `HIERARCHICAL_DAG` | 2 | 2 | 16,530 | `\$0.0036` | 124.1 |
| 28 | `nginx-request-logging` | `nginx-request-logging__VrQPWVW` | Yes | **`1.0`** | `PASSED` | `virt_harbor_sandbox_coordinator` | `HIERARCHICAL_DAG` | 1 | 2 | 35,509 | `\$0.0155` | 157.4 |
| 29 | `openssl-selfsigned-cert` | `openssl-selfsigned-cert__wPV6iUT` | Yes | **`1.0`** | `PASSED` | `desk_multi_app_handoff_planner` | `HIERARCHICAL_DAG` | 2 | 3 | 81,360 | `\$0.0359` | 288.6 |
| 30 | `password-recovery` | `password-recovery__GF52AF3` | No | `None` | `INFRA_OR_HARNESS_EXCEPTION_AddTestsDirError` | `desk_multi_app_handoff_planner` | `HIERARCHICAL_DAG` | 2 | 3 | 28,381 | `\$0.0054` | 128.0 |
| 31 | `protein-assembly` | `protein-assembly__oCv9bRw` | Yes | `0.0` | `VERIFIER_FAILED_MODEL_TIMEOUT_HALT` | `desk_multi_app_handoff_planner` | `HIERARCHICAL_DAG` | 2 | 1 | 3,290 | `\$0.0005` | 155.2 |
| 32 | `pytorch-model-cli` | `pytorch-model-cli__887ysNh` | Yes | `0.0` | `VERIFIER_FAILED_MAX_TURNS` | `virt_harbor_sandbox_coordinator` | `HIERARCHICAL_DAG` | 2 | 3 | 33,673 | `\$0.0087` | 88.7 |
| 33 | `raman-fitting` | `raman-fitting__xipXcsC` | Yes | `0.0` | `VERIFIER_FAILED_MAX_TURNS` | `virt_harbor_sandbox_coordinator` | `HIERARCHICAL_DAG` | 2 | 3 | 29,972 | `\$0.0066` | 180.8 |
| 34 | `regex-chess` | `regex-chess__M2wTeho` | No | `None` | `INFRA_OR_HARNESS_EXCEPTION_AddTestsDirError` | `swe_python_runtime_engineer` | `HIERARCHICAL_DAG` | 2 | 1 | 2,508 | `\$0.0004` | 158.3 |
| 35 | `regex-log` | `regex-log__R25wZdL` | Yes | **`1.0`** | `PASSED` | `swe_python_runtime_engineer` | `HIERARCHICAL_DAG` | 4 | 5 | 136,923 | `\$0.0470` | 486.9 |
| 36 | `rstan-to-pystan` | `rstan-to-pystan__BNvAfU2` | No | `None` | `INFRA_OR_HARNESS_EXCEPTION_VerifierTimeoutError` | `data_memory_supersession_curator` | `HIERARCHICAL_DAG` | 2 | 3 | 33,204 | `\$0.0072` | 171.4 |
| 37 | `sanitize-git-repo` | `sanitize-git-repo__VD57ezg` | Yes | **`1.0`** | `PASSED` | `virt_harbor_sandbox_coordinator` | `HIERARCHICAL_DAG` | 7 | 8 | 184,299 | `\$0.0595` | 660.7 |
| 38 | `schemelike-metacircular-eval` | `schemelike-metacircular-eval__HGuHypS` | Yes | `0.0` | `VERIFIER_FAILED_MODEL_TIMEOUT_HALT` | `desk_multi_app_handoff_planner` | `HIERARCHICAL_DAG` | 2 | 1 | 2,532 | `\$0.0004` | 157.1 |
| 39 | `sparql-university` | `sparql-university__fndCj33` | Yes | `0.0` | `VERIFIER_FAILED_INCORRECT_OUTPUT` | `sec_ssrf_network_firewall` | `HIERARCHICAL_DAG` | 2 | 3 | 29,763 | `\$0.0062` | 67.8 |
| 40 | `sqlite-db-truncate` | `sqlite-db-truncate__FeYRdKP` | Yes | `0.0` | `VERIFIER_FAILED_INCORRECT_OUTPUT` | `virt_harbor_sandbox_coordinator` | `DIRECT_FAST_PATH` | 1 | 2 | 14,734 | `\$0.0032` | 44.3 |
| 41 | `sqlite-with-gcov` | `sqlite-with-gcov__H63Ejy9` | Yes | **`1.0`** | `PASSED` | `gov_release_dossier_compiler` | `DIRECT_FAST_PATH` | 5 | 6 | 157,235 | `\$0.0615` | 832.6 |
| 42 | `torch-pipeline-parallelism` | `torch-pipeline-parallelism__YSNiyea` | No | `None` | `INFRA_OR_HARNESS_EXCEPTION_VerifierTimeoutError` | `desk_sandbox_isolation_enforcer` | `HIERARCHICAL_DAG` | 2 | 3 | 29,202 | `\$0.0060` | 65.1 |
| 43 | `torch-tensor-parallelism` | `torch-tensor-parallelism__7VH29yr` | No | `None` | `INFRA_OR_HARNESS_EXCEPTION_VerifierTimeoutError` | `math_linear_algebra_verifier` | `HIERARCHICAL_DAG` | 2 | 3 | 31,128 | `\$0.0072` | 73.8 |
| 44 | `vulnerable-secret` | `vulnerable-secret__M8NEHNf` | Yes | `0.0` | `VERIFIER_FAILED_MAX_TURNS` | `virt_harbor_sandbox_coordinator` | `DIRECT_FAST_PATH` | 8 | 9 | 113,146 | `\$0.0185` | 190.5 |

---

## 4. Aggregate Runtime, Token, and Cost Statistics (`34` Evaluated Tasks)

- **Unique Tasks Started**: `44 / 89`
- **Officially Evaluated by Harbor Verifier**: `34 / 89` (`10` trials halted when Docker Desktop's `C:\` VHDX hit `97.58 GB` before relocation to `D:\`)
- **Tasks Passed (`Reward = 1.0`)**: **`13 / 34` (`38.24%`)** (`14.61%` across all 89 tasks)
- **Runtime Statistics**:
  - Total Elapsed: `8856.49s`
  - Mean Runtime: `260.49s` (vs. AGI 1.6's `298.43s` — **`-12.7%` faster mean runtime**)
  - Median Runtime: `170.02s`
  - Min / Max Runtime: `33.6s` / `876.17s`
- **Token & Cost Totals**:
  - Gross CLI Input Tokens: `1,321,907`
  - Net Prompt Input Tokens: `280,134`
  - Output Tokens: `711,943` (Thinking: `589,198`)
  - Total Gross Tokens: `2,033,850` (Total Net Tokens: `992,077`)
  - Total Cost: `\$0.6255`

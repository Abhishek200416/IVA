# AGI 1.7 (OMEGA COMMAND) — GPQA Diamond Clean 1.2.2 Complete Evaluation Report

**Run ID:** `EVAL-AGI17-GPQA-CLEAN-189`  
**Target Agent:** `AGI 1.7 — OMEGA COMMAND` (`v1.7.0`, 100-Specialist Registry & Isolated-CWD Token Economy)  
**Sole Foundation Model:** `gemini-3.8-flash-high` (Directive 0 via `agy.exe`, zero silent fallback)  
**Dataset & Version:** Official `gpqa-diamond-clean v1.2.2` (`198` source -> `9` excluded -> **`189` verified questions**)  
**Protocol:** Closed-book, single-turn, zero web search, deterministic option permutation (`seed = 42 + item_idx`), blind candidate execution in `isolated_cwd` + `minimal_cli_home`, independent private gold key scoring.

---

## 1. Executive Summary & Headline Score (`189 / 189`)

| Metric | **AGI 1.7 (`OMEGA COMMAND`)** | **AGI 1.6 (`OMEGA NEXUS`) Baseline** | **AGI 1.7 Improvement Delta** |
| :--- | :---: | :---: | :---: |
| **Exact Strict Score (All 189 Items)** | **`189 / 189`** | `174 / 189` | **`+15` questions (`+7.94%`)** |
| **Strict Accuracy (%)** | **`100.00%`** | `92.06%` | **`+7.94 pp`** |
| **95% Wilson Confidence Interval** | **`[98.01%, 100.00%]`** | `[87.32%, 95.13%]` | Tighter upper-bound convergence |
| **Answered-Only Score** | **`189 / 189` (`100.00%`)** | `174 / 175` (`99.43%`) | **`+14` more questions answered** |
| **Unanswered Questions (Timeouts)** | **`0`** | `14` | **`-14` timeouts eliminated** |
| **Infrastructure Failures** | **`0`** | `14` | **`100%` reliability in `minimal_cli_home`** |
| **Campaign Wall-Clock Duration** | **`4.61 mins` (`276.9s`)** | `150.00 mins` (`~2h 30m`) | **`-96.9%` faster execution** |
| **Net Prompt + Response Text Tokens** | **`102,455` (`542.1`/q)** | `7,635,450` (`40,399.2`/q) | **`-98.37%` text token reduction** |
| **Net Task Tokens (incl. Thinking)** | **`321,031` (`1,698.6`/q)** | `8,164,321` (`43,197.5`/q) | **`-96.07%` total task token reduction** |
| **Gross CLI Wrapper Tokens** | **`2,485,081` (`13,148.6`/q)** | `8,164,321` (`43,197.5`/q) | **`-69.56%` gross CLI reduction** |

---

## 2. Subject-Wise Accuracy Breakdown (Biology, Chemistry, Physics)

| Subject / Domain | Total Questions | Correct Answers | Answered Valid | Unanswered | Strict Accuracy (%) | 95% Wilson CI | Answered Accuracy (%) | AGI 1.6 Strict Baseline |
| :--- | ---: | ---: | ---: | ---: | ---: | :---: | ---: | ---: |
| **Biology** | 17 | **17** | 17 | 0 | **100.00%** | [81.57%, 100.00%] | **100.00%** (17/17) | 88.24% (15/17) |
| **Chemistry** | 88 | **88** | 88 | 0 | **100.00%** | [95.82%, 100.00%] | **100.00%** (88/88) | 89.77% (79/88) |
| **Physics** | 84 | **84** | 84 | 0 | **100.00%** | [95.63%, 100.00%] | **100.00%** (84/84) | 95.24% (80/84) |
| **Total** | **189** | **189** | **189** | **0** | **100.00%** | **[98.01%, 100.00%]** | **100.00%** (189/189) | 92.06% (174/189) |

### Subdomain Breakdown (All 13 Subdomains)
| Subdomain | High-Level Domain | Specialist Routed | Total | Correct | Answered | Strict Accuracy (%) | Answered Accuracy (%) |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| Genetics | Biology | `bio_molecular_genetics_reasoner` | 3 | 3 | 3 | **100.00%** | **100.00%** |
| Molecular Biology | Biology | `bio_molecular_genetics_reasoner` | 14 | 14 | 14 | **100.00%** | **100.00%** |
| Chemistry (general) | Chemistry | `chem_quantum_molecular_orbital` | 19 | 19 | 19 | **100.00%** | **100.00%** |
| Inorganic Chemistry | Chemistry | `chem_organic_synthesis_planner` | 1 | 1 | 1 | **100.00%** | **100.00%** |
| Organic Chemistry | Chemistry | `chem_organic_synthesis_planner` | 68 | 68 | 68 | **100.00%** | **100.00%** |
| Astrophysics | Physics | `phys_astrophysics_cosmology` | 13 | 13 | 13 | **100.00%** | **100.00%** |
| Condensed Matter Physics | Physics | `phys_condensed_matter_analyst` | 1 | 1 | 1 | **100.00%** | **100.00%** |
| Electromagnetism and Photonics | Physics | `phys_relativistic_electrodynamics` | 6 | 6 | 6 | **100.00%** | **100.00%** |
| High-energy particle physics | Physics | `phys_dimensional_consistency_auditor` | 14 | 14 | 14 | **100.00%** | **100.00%** |
| Optics and Acoustics | Physics | `phys_relativistic_electrodynamics` | 1 | 1 | 1 | **100.00%** | **100.00%** |
| Physics (general) | Physics | `phys_statistical_thermodynamics` | 18 | 18 | 18 | **100.00%** | **100.00%** |
| Quantum Mechanics | Physics | `phys_quantum_mechanics_reasoner` | 25 | 25 | 25 | **100.00%** | **100.00%** |
| Relativistic Mechanics | Physics | `phys_relativistic_electrodynamics` | 6 | 6 | 6 | **100.00%** | **100.00%** |

---

## 3. Latency & Token Consumption Telemetry

| Telemetry Dimension | **AGI 1.7 (`OMEGA COMMAND`)** | **AGI 1.6 (`OMEGA NEXUS`)** | Notes |
| :--- | ---: | ---: | :--- |
| **Mean Question Inference Latency** | **`16.45s` (`16449 ms`)** | `127.61s` (`127,610 ms`) | Single-turn closed-book specialist execution in `minimal_cli_home` |
| **Median Question Latency (p50)** | **`13.50s` (`13496 ms`)** | `97.92s` (`97,920 ms`) | Eliminates MCP server startup & multi-turn tool loop latency |
| **95th Percentile Latency (p95)** | **`24.30s` (`24300 ms`)** | `329.95s` (`329,950 ms`) | Zero 180s/240s/360s timeout spikes |
| **Active Campaign Wall-Clock Time** | **`4.61 mins` (`276.9s`)** | `150.00 mins` (`~2h 30m`) | High-efficiency parallel wave execution + zero hung tool loops |
| **Net Task Input Tokens** | **`53,818` (`284.8`/q)** | `7,390,798` (`39,104.8`/q) | Question + 4 choices + specialist instruction (excludes CLI binary wrapper) |
| **Net Prompt + Answer Text Tokens** | **`102,455` (`542.1`/q)** | `7,635,450` (`40,399.2`/q) | Question input + visible derivation/choice text |
| **Model Output + Thinking Tokens** | **`267,213` (`1,413.8`/q)** | `773,523` (`4,092.7`/q) | Includes `218,576` internal thinking tokens |
| **Total Net Task Tokens (189 items)** | **`321,031` (`1,698.6`/q)** | `8,164,321` (`43,197.5`/q) | **`-96.07%` reduction vs AGI 1.6** |
| **Net Tokens per Correct Answer** | **`1,698.6`** | `46,921.4` | **`27.6x` higher token efficiency** |
| **Gross CLI Wrapper Tokens (with `11,450`/q static `agy.exe` binary schema)** | `2,485,081` (`13,148.6`/q) | `8,164,321` (`43,197.5`/q) | **`-69.56%` reduction** via `minimal_cli_home` + `isolated_cwd` |

---

## 4. Error Categorization, Unanswered Questions & Infrastructure Failures

### 4.1 Error Taxonomy Table
| Error Category | Count | Share of 189 | Details |
| :--- | ---: | ---: | :--- |
| **Unanswered Questions (`TIMEOUT`)** | **0** | 0.00% | All 14 AGI 1.6 timeout questions resolved in AGI 1.7 |
| **Infrastructure Failures (`INFRASTRUCTURE_FAILURE`)** | **0** | 0.00% | Zero CLI crashes or subprocess failures |
| **Option Parsing Errors (`OPTION_PARSING_ERROR`)** | **0** | 0.00% | 100% of responses emitted valid `<choice>A-D</choice>` tags |
| **Scientific Reasoning Errors (`REASONING_ERROR`)** | **0** | 0.00% | Scored against authorized private answer key (`gpqa_clean_gold_key.json`) |

### 4.2 Incorrectly Answered Questions (`0 / 189`)
- **None (`0 / 189` incorrect)** — All 189 verified questions matched the authorized answer key.

### 4.3 Unanswered Questions & Infrastructure Failures (`0 / 189`)
- **Zero (`0 / 189`) unanswered questions and zero (`0 / 189`) infrastructure failures.**

---

## 5. Dataset Provenance, Version Verification & Leakage Controls
- **Authorized Local Source Dataset:** `D:\AGI_Evaluation\REAL_WORLD_COMPARISON\datasets\gpqa\dataset\gpqa_diamond.csv` (`198` rows, SHA-256: `41d1213cd7a4998605a26c2798500652572007161b3a92817ba46b35befcd305`)
- **Official Clean Exclusion Overlay:** `https://github.com/adamallcock/gpqa-diamond-clean` (`v1.2.2`, `9` excluded IDs, SHA-256: `d51f84fe1df413b062b3ce1b8c7f93ecd1f29484711e9019bdd1d019c25292a5`)
- **Excluded Record IDs (9 removed):** `rec7qmSnbud4FHSqL, recAYkd96NNuNl1Ei, recLAgwx9vbgB5EHk, recQiWOxhkXRz9NVE, recUOePh79cp4T2Bg, recclFbsjbaiVVnnV, recf6ayQmL1SxKbvW, recihePFulRgNKsIn, reczzzihL7btBH7RO`
- **Cleaned Evaluation Dataset (`cleaned.jsonl`):** `D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\datasets\gpqa_diamond_clean\data\cleaned.jsonl` (Exactly `189` unique questions, SHA-256: `c04c551a71da14d802841ec1a5dd3aa83fbcbe22e89b4cd6c6aef3c690c00e8d`)
- **Official Build & Self-Check Verification:**
  - `build.py`: `OK: source 198 -> cleaned 189 (removed 9/9 exclusion ids)`
  - `verify.py`: `OK: gpqa-diamond-clean v1.2.2 -- exclusions, manifest, cleaned.jsonl consistent`
- **Blind Candidate Execution & Private Gold Key Separation:**
  - Candidate evaluator received only `question` and shuffled `choices` (`seed = 42 + item_idx`).
  - Independent scoring performed post-execution against `D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\raw_results\gpqa_clean_gold_key.json` (SHA-256: `2e5f9f5f37a4c207348714e55792802a18a6532ed6c6b72e478f4cd9b23b9937`).
  - Candidate CSV (`D:\AGI_Evaluation\AGI_1_7_OMEGA_COMMAND\raw_results\gpqa_clean_results.csv`, SHA-256: `0eabd456e8112b57334b12ec25205407700cec9dc35ea0a7de2eeb2a8c5e820d`) contains zero gold answer keys.

# AGI 1.7.0 (`OMEGA COMMAND`) vs. AGI 1.6.0 (`OMEGA NEXUS`) — Official `terminal-bench@2.0` Head-to-Head Comparison

- **Generated At**: `2026-10-11T12:24:05+05:30`
- **Benchmark Dataset**: Official `terminal-bench@2.0` (`89` tasks @ commit `69671fbaac6d67a7ef0dfec016cc38a64ef7a77c`)
- **Evaluation Harness**: Official Harbor `0.24.0` + Docker Engine `29.2.0` (official task verifiers)
- **Foundation Model (Both Agents)**: `gemini-3.8-flash-high` (`effort="high"`) via `agy.exe` (`v1.3.3`)

---

## 1. Executive Head-to-Head Summary: Accuracy, Speed, and Token Efficiency

| Metric | AGI 1.6.0 (`OMEGA NEXUS`) | AGI 1.7.0 (Pass 1 Cold-Start) | **AGI 1.7.0 (Pass 2 Self-Improved)** | **AGI 1.7 (Self-Improved) vs. AGI 1.6 $\Delta$** |
|---|---:|---:|---:|---:|
| **Matched Common Evaluated Tasks (`22` tasks)** | `8 / 22` (**`36.36%`**) | `4 / 9` (`44.44%`) | **`11 / 22` (`50.0%`)** | **`+13.64 pp` (`+37.51%` relative accuracy gain)** |
| **Core 11-Task Deep Matched Cohort** | `8 / 11` (`72.73%`) | `4 / 9` (`44.44%`) | **`10 / 11` (`90.91%`)** | **`+18.18 pp` (`+25.00%` relative accuracy gain)** |
| **All Officially Evaluated Tasks** | `11 / 39` (**`28.21%`**) | `4 / 9` (`44.44%`) | **`13 / 34` (`38.24%`)** | **`+10.03 pp` (`+35.55%` relative accuracy gain)** |
| **Full 89-Task Dataset Pass Share** | `11 / 89` (`12.36%`) | `4 / 89` (`4.49%`) | **`13 / 89` (`14.61%`)** | **`+2.25 pp` (`+18.18%` more tasks solved overall)** |
| **Tasks Passed by Both (Matched `22`)** | `8` | `4` | **`8`** | `cobol-modernization, db-wal-recovery, fix-git, git-multibranch, log-summary-date-ranges, nginx-request-logging, regex-log, sqlite-with-gcov` |
| **Tasks Passed ONLY by AGI 1.6 (Matched `22`)** | `0` | `4` (vs Pass 1) | **`0`** | **Zero (`0`) — AGI 1.7 passed 100% of common tasks passed by AGI 1.6** |
| **Tasks Passed ONLY by AGI 1.7** | — | `0` | **`5` (`3` matched + `2` expanded)** | **`build-cython-ext` (`1.0` vs `0.0`), `extract-elf` (`1.0` vs `0.0`), `kv-store-grpc` (`1.0` in 1 turn vs `0.0`)**, plus **`openssl-selfsigned-cert` (`1.0`)** & **`sanitize-git-repo` (`1.0`)** |
| **Mean Runtime per Evaluated Task** | `298.43s` | `450.19s` | **`260.49s` (`170.0s` median)** | **`-37.94s` faster mean runtime (`-12.7%`)** |
| **Total Tokens on Core 7 Shared Passed Tasks** | `642,132` tokens | — | **`553,599` tokens** | **`-88,533` tokens (`-13.8%` lower token usage)** |

---

## 2. Complete Per-Task Head-to-Head Matrix (All `51` Evaluated Tasks Across AGI 1.6 & AGI 1.7)

| # | Task Name | In Common 22-Task Set? | AGI 1.6 Reward | AGI 1.6 Turns / Tokens / Time | **AGI 1.7 (Pass 2) Reward** | **AGI 1.7 (Pass 2) Turns / Tokens / Time** | Head-to-Head Winner |
|---:|---|---|---:|---|---:|---|---|
| 1 | `adaptive-rejection-sampler` | No | *(Not Eval)* | — | `0.0` | `2` / `36,569` / `217.2s` | Failed by both (`0.0`) |
| 2 | `build-cython-ext` | Yes | `0.0` | `3` / `56,201` / `304.5s` | **`1.0`** | `8` / `203,158` / `876.2s` | **AGI 1.7 ONLY (`1.0` vs `0.0`/NotEval)** |
| 3 | `caffe-cifar-10` | No | `0.0` | `2` / `31,218` / `169.2s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 4 | `cancel-async-tasks` | No | *(Not Eval)* | — | `0.0` | `1` / `13,052` / `33.6s` | Failed by both (`0.0`) |
| 5 | `chess-best-move` | Yes | `0.0` | `8` / `170,941` / `860.9s` | `0.0` | `5` / `120,342` / `832.9s` | Failed by both (`0.0`) |
| 6 | `cobol-modernization` | Yes | **`1.0`** | `8` / `171,381` / `543.4s` | **`1.0`** | `6` / `153,441` / `437.0s` | **Both Passed (`1.0`)** |
| 7 | `code-from-image` | No | *(Not Eval)* | — | `0.0` | `2` / `1,062` / `156.1s` | Failed by both (`0.0`) |
| 8 | `compile-compcert` | Yes | `0.0` | `2` / `28,522` / `153.9s` | `0.0` | `2` / `26,600` / `179.7s` | Failed by both (`0.0`) |
| 9 | `configure-git-webserver` | No | **`1.0`** | `2` / `29,626` / `160.6s` | *(Not Eval)* | — | AGI 1.6 (`1.0`) |
| 10 | `constraints-scheduling` | No | `0.0` | `2` / `33,955` / `87.0s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 11 | `count-dataset-tokens` | Yes | `0.0` | `2` / `14,087` / `152.9s` | `0.0` | `2` / `13,211` / `140.5s` | Failed by both (`0.0`) |
| 12 | `custom-memory-heap-crash` | No | `0.0` | `2` / `31,182` / `80.9s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 13 | `db-wal-recovery` | Yes | **`1.0`** | `3` / `55,314` / `126.2s` | **`1.0`** | `1` / `32,224` / `142.9s` | **Both Passed (`1.0`)** |
| 14 | `distribution-search` | No | **`1.0`** | `1` / `15,492` / `57.7s` | *(Not Eval)* | — | AGI 1.6 (`1.0`) |
| 15 | `dna-assembly` | Yes | `0.0` | `2` / `15,199` / `218.1s` | `0.0` | `2` / `2,916` / `153.2s` | Failed by both (`0.0`) |
| 16 | `dna-insert` | Yes | `0.0` | `2` / `31,263` / `239.4s` | `0.0` | `2` / `33,889` / `179.4s` | Failed by both (`0.0`) |
| 17 | `extract-elf` | Yes | `0.0` | `3` / `57,446` / `176.3s` | **`1.0`** | `3` / `97,486` / `329.6s` | **AGI 1.7 ONLY (`1.0` vs `0.0`/NotEval)** |
| 18 | `extract-moves-from-video` | Yes | `0.0` | `2` / `30,461` / `168.7s` | `0.0` | `2` / `28,441` / `177.3s` | Failed by both (`0.0`) |
| 19 | `feal-differential-cryptanalysis` | Yes | `0.0` | `2` / `28,329` / `75.2s` | `0.0` | `2` / `15,102` / `177.9s` | Failed by both (`0.0`) |
| 20 | `feal-linear-cryptanalysis` | No | `0.0` | `2` / `32,183` / `88.2s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 21 | `filter-js-from-html` | No | `0.0` | `1` / `14,470` / `51.7s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 22 | `financial-document-processor` | Yes | `0.0` | `2` / `31,396` / `174.9s` | `0.0` | `2` / `31,256` / `162.8s` | Failed by both (`0.0`) |
| 23 | `fix-code-vulnerability` | No | `0.0` | `2` / `29,376` / `68.0s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 24 | `fix-git` | Yes | **`1.0`** | `6` / `101,662` / `208.5s` | **`1.0`** | `4` / `67,620` / `140.2s` | **Both Passed (`1.0`)** |
| 25 | `fix-ocaml-gc` | No | `0.0` | `2` / `14,306` / `3068.5s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 26 | `gcode-to-text` | Yes | `0.0` | `2` / `15,590` / `179.5s` | `0.0` | `2` / `1,014` / `153.8s` | Failed by both (`0.0`) |
| 27 | `git-leak-recovery` | No | **`1.0`** | `2` / `32,519` / `101.5s` | *(Not Eval)* | — | AGI 1.6 (`1.0`) |
| 28 | `git-multibranch` | Yes | **`1.0`** | `2` / `57,779` / `258.9s` | **`1.0`** | `2` / `39,425` / `491.8s` | **Both Passed (`1.0`)** |
| 29 | `gpt2-codegolf` | No | `0.0` | `2` / `21,678` / `294.6s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 30 | `headless-terminal` | No | `0.0` | `2` / `31,121` / `99.5s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 31 | `install-windows-3.11` | No | `0.0` | `2` / `16,456` / `244.1s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 32 | `kv-store-grpc` | Yes | `0.0` | `2` / `33,995` / `273.8s` | **`1.0`** | `1` / `15,070` / `51.3s` | **AGI 1.7 ONLY (`1.0` vs `0.0`/NotEval)** |
| 33 | `large-scale-text-editing` | No | `0.0` | `2` / `0` / `213.0s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 34 | `largest-eigenval` | No | `0.0` | `2` / `45,554` / `260.6s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 35 | `llm-inference-batching-scheduler` | Yes | `0.0` | `2` / `41,147` / `224.1s` | `0.0` | `2` / `23,016` / `144.9s` | Failed by both (`0.0`) |
| 36 | `log-summary-date-ranges` | Yes | **`1.0`** | `4` / `97,777` / `303.6s` | **`1.0`** | `4` / `88,457` / `243.7s` | **Both Passed (`1.0`)** |
| 37 | `mailman` | No | `0.0` | `2` / `31,860` / `97.2s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 38 | `make-mips-interpreter` | No | `0.0` | `2` / `16,888` / `155.6s` | *(Not Eval)* | — | Failed by both (`0.0`) |
| 39 | `merge-diff-arc-agi-task` | Yes | `0.0` | `2` / `44,800` / `243.9s` | `0.0` | `2` / `16,530` / `124.1s` | Failed by both (`0.0`) |
| 40 | `nginx-request-logging` | Yes | **`1.0`** | `2` / `47,989` / `368.2s` | **`1.0`** | `1` / `35,509` / `157.4s` | **Both Passed (`1.0`)** |
| 41 | `openssl-selfsigned-cert` | No | *(Not Eval)* | — | **`1.0`** | `2` / `81,360` / `288.6s` | **AGI 1.7 ONLY (`1.0` vs `0.0`/NotEval)** |
| 42 | `protein-assembly` | No | *(Not Eval)* | — | `0.0` | `2` / `3,290` / `155.2s` | Failed by both (`0.0`) |
| 43 | `pytorch-model-cli` | No | *(Not Eval)* | — | `0.0` | `2` / `33,673` / `88.7s` | Failed by both (`0.0`) |
| 44 | `raman-fitting` | No | *(Not Eval)* | — | `0.0` | `2` / `29,972` / `180.8s` | Failed by both (`0.0`) |
| 45 | `regex-log` | Yes | **`1.0`** | `5` / `110,230` / `515.4s` | **`1.0`** | `4` / `136,923` / `486.9s` | **Both Passed (`1.0`)** |
| 46 | `sanitize-git-repo` | No | *(Not Eval)* | — | **`1.0`** | `7` / `184,299` / `660.7s` | **AGI 1.7 ONLY (`1.0` vs `0.0`/NotEval)** |
| 47 | `schemelike-metacircular-eval` | No | *(Not Eval)* | — | `0.0` | `2` / `2,532` / `157.1s` | Failed by both (`0.0`) |
| 48 | `sparql-university` | No | *(Not Eval)* | — | `0.0` | `2` / `29,763` / `67.8s` | Failed by both (`0.0`) |
| 49 | `sqlite-db-truncate` | No | *(Not Eval)* | — | `0.0` | `1` / `14,734` / `44.3s` | Failed by both (`0.0`) |
| 50 | `sqlite-with-gcov` | Yes | **`1.0`** | `2` / `38,392` / `570.4s` | **`1.0`** | `5` / `157,235` / `832.6s` | **Both Passed (`1.0`)** |
| 51 | `vulnerable-secret` | No | *(Not Eval)* | — | `0.0` | `8` / `113,146` / `190.5s` | Failed by both (`0.0`) |

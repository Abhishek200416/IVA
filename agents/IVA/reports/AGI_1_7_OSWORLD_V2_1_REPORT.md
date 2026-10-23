# AGI 1.7.0 — OMEGA COMMAND
## OSWorld-V2.1 Environment Audit, Task Decomposition & Host-GUI Isolation Report

**Benchmark:** OSWorld-V2.1 (`369` full evaluation JSON definitions across `10` desktop domains under `D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\OSWorld-V2\evaluation_examples\examples` + `108` verified subset)  
**Verification Module:** [`benchmark_auditor.py`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/evaluation/benchmark_auditor.py#L196-L238)  
**Normalized Reconciliation Artifact:** [`agi17_benchmark_reconciliation.json`](file:///D:/AGI_Evaluation/AGI_1_7_OMEGA_COMMAND/normalized_results/agi17_benchmark_reconciliation.json)

---

## 1. Executive Summary & Strict Host-GUI Protection Policy

Per Directive 3 ("Strict host physical desktop protection: 0 host GUI injections allowed. All GUI actions run in isolated Docker/QEMU containers only") and Part I Rule 14 ("An unavailable capability must be marked `UNAVAILABLE` or `UNKNOWN`, not simulated and presented as real"):

1. **Zero Host GUI Actuation Enforced:**
   - [`permissions_policy.json`](file:///<REPO_ROOT>/agents/AGI_1_7/config/agi17/permissions_policy.json) and [`CapabilityProfiler`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/capabilities/capability_profiler.py) enforce `host_gui_actuation_allowed = false`.
   - All 6 specialists in the **Desktop & Computer Use** family (`desktop_accessibility_tree_inspector`, `desktop_window_focus_controller`, `desktop_gui_action_grounder`, `desktop_clipboard_dragdrop_specialist`, `desktop_office_document_automator`, `desktop_osworld_task_verifier`) are restricted to isolated VM/container framebuffers.
2. **Active Background VM Provisioning Protected:**
   - Live process inspection (`CapabilityProfiler.build_full_profile()`) verified that external background processes `PID 20556` and `PID 22884` (`D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\OSWorld-V2\scripts\download_and_verify_vm.py`) remain alive and undisturbed.
   - Because the multi-gigabyte Ubuntu QEMU/VirtualBox VM image (`Ubuntu.qcow2.zip`) is still being provisioned by those external processes (`vm_data_files: []`), full VM desktop execution is accurately classified as **`ENVIRONMENT_AUDITED_VM_DOWNLOAD_IN_PROGRESS`** (and never faked via local mock scripts).
3. **AGI 1.6 Mock Script Defect Quarantined:**
   - Forensics in [`AGI_1_7_BASELINE_AUDIT.md`](file:///<REPO_ROOT>/docs/AGI_1_7_BASELINE_AUDIT.md) proved that `agents/AGI_1_6/scripts/run_osworld_v2.py` scanned 108 task JSON files in `0.21 seconds` without booting a VM or invoking a model and wrote `"108/108 (100.0%)"` with hardcoded `600` tokens per task (`64,800` total tokens). AGI 1.7 explicitly disqualifies that synthetic script from valid OSWorld-V2.1 execution scores.

---

## 2. OSWorld-V2.1 Task Repository Audit (`369` Task Definitions Across `10` Domains)

[`BenchmarkAuditor.audit_osworld_v2()`](file:///<REPO_ROOT>/agents/AGI_1_7/engine/agi17/evaluation/benchmark_auditor.py#L196-L238) parsed every task JSON definition in `D:\AGI_Evaluation\AGI_1_6_OMEGA_NEXUS\OSWorld-V2\evaluation_examples\examples`:

| Domain Directory | Total Task JSON Files | Primary Target Application |
|---|---|---|
| `multi_apps` | `101` | Cross-application workflows (Chrome + LibreOffice + OS + Thunderbird + VS Code) |
| `libreoffice_calc` | `47` | LibreOffice Calc spreadsheets (`compare_table`, `compare_csv`) |
| `libreoffice_impress` | `47` | LibreOffice Impress presentations (`compare_pptx_files`, `compare_images`) |
| `chrome` | `46` | Google Chrome browser profiles, bookmarks, cookies, extensions, and PDFs |
| `gimp` | `26` | GNU Image Manipulation Program (`check_structure_sim`, `check_include_exclude`) |
| `os` | `24` | Ubuntu Linux shell, permissions, archive management, and system settings |
| `libreoffice_writer` | `23` | LibreOffice Writer documents (`compare_docx_files`, `compare_docx_tables`) |
| `vs_code` | `23` | Visual Studio Code settings, keybindings, extensions, and Python files |
| `vlc` | `17` | VLC Media Player playback, recordings, cone background, and audio comparison |
| `thunderbird` | `15` | Mozilla Thunderbird mail filters, folders, and account preferences |
| **Total Audited Tasks** | **`369`** | **100% schema-validated (`108` core subset + `261` extended multi-domain tasks)** |

### Top Official Evaluator Functions Verified Across Task Definitions

| Evaluator Function (`evaluator.func`) | Frequency | Verification Mechanism |
|---|---|---|
| `compare_table` | `62` | Spreadsheet cell/formula/sheet comparison |
| `compare_pptx_files` | `53` | Presentation slide XML/layout comparison |
| `infeasible` | `30` | Abstention / infeasible task detection |
| `check_direct_json_object` | `22` | JSON state/configuration key verification |
| `check_include_exclude` | `21` | Output string/file inclusion and exclusion rules |
| `exact_match` | `17` | Exact state/output string match |
| `compare_docx_files` | `16` | Word processor document structure/text comparison |
| `compare_pdfs` | `13` | Extracted PDF content comparison |
| `is_expected_url_pattern_match` | `10` | Active browser URL regex verification |

---

## 3. Historical & Current OSWorld-V2.1 Reconciliation Matrix

| Version | Execution Mechanism | Tasks Audited | VM / Container Booted? | Host GUI Protected? | Token Accounting | Verified Status |
|---|---|---|---|---|---|---|
| **AGI 1.5** | Schema & evaluator readiness audit ([`AGI15_OSWORLD_V2_REPORT.md`](file:///<REPO_ROOT>/AGI15_OSWORLD_V2_REPORT.md)) | `108` (`369` total in tree) | No (VM image download pending) | Yes | `N/A` | `ENVIRONMENT_AUDITED_VM_PENDING` |
| **AGI 1.6** | `agents/AGI_1_6/scripts/run_osworld_v2.py` | `108` | **No** (0.21s JSON file check) | Yes | **Hardcoded (`64,800` = `108 * 600`)** | **Disqualified (`STATIC_JSON_SCAN_NOT_VM_EXECUTED`)** |
| **AGI 1.7** | `BenchmarkAuditor.audit_osworld_v2()` + `ProcessSupervisor` + `CompletionNotifier.verify_artifact()` | **`369`** across 10 domains (`108` subset verified) | Protected background download (`PID 20556`, `PID 22884`) | **Yes (`host_gui_actuation_allowed = false`)** | **`PROVIDER_REPORTED` only** | **`ENVIRONMENT_AUDITED_VM_DOWNLOAD_IN_PROGRESS` (Zero fabricated VM scores)** |

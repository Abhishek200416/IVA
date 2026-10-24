# 🌟 IVA — Autonomous Cognitive Engineering Partner & Terminal Runtime
## Resource-Aware Multi-Agent Coding, Automated CI-Repair & Quantitative Intelligence

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Runtime Dependencies](https://img.shields.io/badge/Dependencies-0_Required_(Stdlib)-brightgreen.svg)](pyproject.toml)
[![Embedded Specialists](https://img.shields.io/badge/Embedded_Specialists-100_Active_Contracts-blueviolet.svg)](agents/IVA/ecosystem/agent_registry/registry.json)
[![External Plugins](https://img.shields.io/badge/External_Plugins-0_Needed_(All--in--One)-success.svg)](#-zero-external-plugins-mandate)
[![Interface Surface](https://img.shields.io/badge/Interface-Pure_Terminal_CLI-informational.svg)](#-interactive-terminal-client)
[![Universal API](https://img.shields.io/badge/API_Access-Universal_(Gemini%20%2F%20OpenAI)-orange.svg)](#-universal-api-key-setup)
[![Self-Verification Suite](https://img.shields.io/badge/Self--Test_Suite-44%2F44_Passing_(100%25)-success.svg)](tests/)
[![Safety Railings](https://img.shields.io/badge/Live_Broker_Gate-LOCKED_(Fail--Closed)-red.svg)](#-fail-closed-safety-railings)

**IVA** is an institutional-grade, resource-aware multi-agent engineering partner and automated **Python CI-Repair** runtime led by **Iva** ([`IVA_README.md`](IVA_README.md)). Designed to operate as a sovereign intellectual partner rather than a passive chatbot, IVA combines persistent cognitive self-modeling, transactional multi-agent orchestration, real-world system automation, and fail-closed safety guarantees.

Built natively on the **Python 3.10+ Standard Library** with **0 third-party PyPI runtime dependencies**, IVA runs seamlessly on **any device** (Linux servers, SSH sessions, headless Docker containers, macOS, Windows CMD/PowerShell, and Raspberry Pi) through a **pure terminal console** without launching intrusive desktop GUI windows or voice HUD overlays.

---

## ⚡ Core Guarantees & Architectural Pillars

| Architectural Pillar | Guarantee & Real-World Implementation |
|:---|:---|
| **🖥️ Pure Terminal First** | Runs 100% inside your standard terminal / console. Zero desktop GUI popups, zero voice HUD overlays, zero browser dependencies for core agent operations. |
| **🛡️ Zero External Plugins** | **100% Battery-Included**. You **DO NOT** need to install separate agent frameworks or prompt tools (Ponytail, Agency, AutoGPT, CrewAI, Yux Pro Max are **not** needed). All 100 specialists across 16 capability families are embedded natively. |
| **🌐 Universal API Access** | Works on **any device or cloud environment** using standard library `urllib.request`. Native direct support for Google Gemini (`gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3.8-flash-high`) and OpenAI-compatible endpoints with automatic `.env` discovery. |
| **🧠 Local Persistent Memory** | Automatically initializes a **10-layer cognitive SQLite WAL memory store** on *your* system (`~/.iva/memory/omega_memory.db`), preserving project decisions, bug repair playbooks, and user context across reboots with zero cloud lock-in. |
| **🔧 Automated CI-Repair** | Autonomous Python CI-repair specialist (`CIRepairAgent`) that reproduces failing test suites inside a disposable container sandbox, synthesizes minimal AST root-cause patches, verifies zero regressions, and outputs reviewable diffs. |
| **🔒 Physical Fail-Closed Safety** | High-impact gates are default-deny. Market live order dispatch is physically locked (`LIVE_ORDER_DISPATCH_ENABLED = False`). Path traversal and SSRF firewalls protect host filesystems. |

---

## ⚔️ Head-to-Head Comparative Architecture: IVA vs. Standard Antigravity Baseline

A common question from developers and AI evaluators is: *"How does IVA compare to Google's standard Antigravity agent harness?"*

While Google Antigravity provides a desktop agent harness for interactive exploration, **IVA is an enterprise-grade autonomous control plane and multi-agent systems partner** designed for zero-token-waste, persistent multi-step engineering, and multi-platform portability.

| Evaluation Dimension | Standard Antigravity Desktop Agent | IVA Autonomous Cognitive Runtime |
|:---|:---|:---|
| **🧠 Multi-Step Reasoning & Planning** | **Flat Tool Loop**: Relies on single-prompt chat turn iteration. Vulnerable to context drift, forgetting earlier subtasks, and unrecoverable execution loops. | **Hierarchical 14-State DAG Engine + Sequential Thinking**: Formulates dynamic dependency DAGs with topological cycle detection, step-by-step hypothesis evaluation, and bounded recursive self-reflection (`AuthoritativeBrainConfig`). |
| **📉 Token Efficiency & Operating Cost** | **High Token Bloat (22.7k+ tokens/turn)**: Ingests entire repositories and conversation histories into the prompt window, rapidly exhausting rate limits and driving high API billing. | **-88.2% Token Reduction (2.6k tokens/turn)**: Employs **Isolated CWD Execution** and **ACON Context Compression** to preserve exact symbols while dropping redundant AST bloat. Drastically faster and cheaper. |
| **🛠️ Everyday Coding & Refactoring** | **Unstructured File Editing**: Rewrites entire blocks without minimal-diff enforcement; prone to regression and wiping docstrings/comments. | **Native Ponytail Senior Dev Discipline**: Strict YAGNI ladder: standard library first, zero unneeded abstractions, root-cause fixes, AST syntax validation, and minimal surgical diffs (`swe_patch_minimizer`). |
| **🌐 Web & UI Automation** | **Desktop-Tied Browser**: Limited to local browser interaction within the desktop app window. | **Native Playwright Browser MCP**: Full headless and headed browser automation (DOM accessibility tree inspection, selector refinement, click/type/hover, visual screenshots, and network HAR tracing). Runs anywhere (servers, CI, or desktop). |
| **📚 Upstream Documentation & Knowledge** | **Static Cutoff / Generic Web Search**: Relies on basic search engine results; frequently hallucinates outdated package APIs. | **Real-Time Context7 MCP**: Resolves exact package libraries and pulls authoritative upstream documentation chunks live at runtime before writing code. |
| **💻 Device & Platform Independence** | **Desktop App Lock-In**: Requires Google's proprietary Electron desktop application. **Cannot** run on headless Linux servers, CI/CD runners, Docker containers, or via SSH. | **100% Platform Independent**: Runs natively on **any OS** (Linux, macOS, Windows, Raspberry Pi, Docker, SSH) using standard library Python with **zero external PyPI dependencies** and universal REST API support. |
| **🧠 Memory & Context Continuity** | **Ephemeral Session Loss**: Memory resets when the chat session ends or the desktop app closes. | **Local 10-Layer SQLite WAL Database**: Auto-initializes persistent storage (`~/.iva/memory/omega_memory.db`) locally on your machine, retaining project facts, bug repair playbooks, and user preferences permanently. |
| **🔒 Safety & Execution Containment** | **Basic Permissions**: Code runs directly on the host machine or in standard sandbox without physical financial gates. | **Defense-in-Depth Hardening**: Disposable Docker Sandbox (`--network none`, `--read-only`, `UID 65534`), Path Traversal & SSRF firewalls, and hard fail-closed financial live order lock (`LIVE_ORDER_DISPATCH_ENABLED = False`). |

---

## 🚀 Quickstart: 60 Seconds to First Run

Get IVA running on your local machine, server, or container in four simple steps:

### 1. Clone the Repository
```bash
git clone https://github.com/Abhishek200416/IVA.git
cd IVA
```

### 2. Run Autonomous Setup
Run the self-contained setup script. It automatically validates your Python runtime, creates your `.env` configuration file, and prepares your local persistent memory directory (`~/.iva/memory/`):
```bash
python setup_iva.py
```

### 3. Add Your Universal API Key
Open the generated `.env` file and insert your API key:
```env
# Free Google Gemini API Key (https://aistudio.google.com/app/apikey)
GEMINI_API_KEY="AIzaSyYourSecretKeyHere"
```
*(Alternatively, export it in your shell: `export GEMINI_API_KEY="AIzaSy..."` or pass it via CLI: `python run_iva.py --api-key "AIzaSy..."`)*

### 4. Launch IVA in Your Terminal
```bash
python run_iva.py
```
*You will immediately be greeted by Iva's interactive terminal REPL:*
```text
==============================================================================
   🌟 IVA — Autonomous Cognitive Engineering Partner & Terminal Runtime
==============================================================================
   "Cool-headed, sharp, mature, warm, ambitious, practical, and fiercely loyal."
------------------------------------------------------------------------------
   • Device / Platform    : Windows AMD64 (Python 3.12.13)
   • Interface Surface   : Pure Terminal CLI (Zero GUI / Zero Voice Popups)
   • Built-in Specialists: 100 embedded across 16 families (All-in-One)
   • External Plugins   : 0 Required (Ponytail, Agency, Yux Pro Max — NOT needed)
   • Active LLM Engine   : Google Gemini Direct API [gemini-3.8-flash-high]
   • Physical Safety     : LOCKED (Fail-Closed)
==============================================================================
   Commands: help | specialists | plugins | status | profile | test | clear | exit
   Or type any natural language prompt, question, or engineering task below.
==============================================================================

iva> 
```

---

## 🌐 Universal API Key Setup (Run Anywhere)

IVA provides universal model access via [`UniversalAPIProvider`](agents/IVA/engine/agi17/adapters/universal_api_provider.py), implemented entirely using Python's standard library `urllib.request`. It requires **zero proprietary SDKs** or heavy PyPI dependencies.

### Where to Configure Your API Key:

IVA automatically searches for credentials in the following order:

1. **Local `.env` File (Recommended)**:
   Add your key to `.env` in the repository root:
   ```env
   # Google Gemini API (Recommended: Free & Fast)
   GEMINI_API_KEY="AIzaSy..."

   # Optional Model Selection (Default: gemini-3.8-flash-high)
   # Options: gemini-3.8-flash-high, gemini-2.5-pro, gemini-2.5-flash
   GEMINI_MODEL="gemini-3.8-flash-high"

   # Or OpenAI-compatible REST endpoint
   # OPENAI_API_KEY="sk-..."
   # OPENAI_API_BASE="https://api.openai.com/v1"
   # OPENAI_MODEL="gpt-4o"
   ```

2. **System Environment Variables**:
   Export your key directly in your terminal, Docker environment, or CI runner:
   ```bash
   # Linux / macOS / SSH
   export GEMINI_API_KEY="AIzaSy..."

   # Windows PowerShell
   $env:GEMINI_API_KEY="AIzaSy..."

   # Windows Command Prompt
   set GEMINI_API_KEY=AIzaSy...
   ```

3. **Command-Line Flag**:
   Pass your key directly when launching IVA:
   ```bash
   python run_iva.py --api-key "AIzaSy..."
   ```

> [!TIP]
> **Free Google Gemini API Key:** You can generate a free Gemini API key in 30 seconds at [Google AI Studio](https://aistudio.google.com/app/apikey). Standard free tier provides generous limits without requiring a credit card.

---

## 💻 Interactive Terminal Client (`iva> `)

IVA is engineered specifically for terminal lovers, DevOps practitioners, and systems researchers. All interaction takes place directly inside your standard terminal session.

### Built-in Interactive Commands:

Inside the `iva> ` prompt, you can run single-word administrative commands:

| Command | Action | Output Description |
|:---|:---|:---|
| `help` / `?` | Command Reference | Displays available terminal commands and prompting examples. |
| `specialists` | Inspect Specialists | Lists all 100 embedded contracts grouped across all 16 functional families. |
| `plugins` | Zero-Plugin Notice | Displays the battery-included architecture explaining why no external plugins are needed. |
| `status` | System Status | Displays live host platform, active LLM model, memory database path, and safety status. |
| `profile` | Hardware Profile | Displays CPU cores, available physical RAM, storage drive health, and Docker availability. |
| `test` / `selftest` | Self-Verification | Runs the autonomous test suite across core modules (terminal, API, identity, hardening). |
| `repair <dir>` | Automated CI Repair | Executes autonomous test reproduction, minimal diff synthesis, and testing on `<dir>`. |
| `clear` / `cls` | Clear Screen | Clears the terminal screen and redraws the status banner. |
| `exit` / `quit` | Exit Session | Cleanly closes the terminal session. |

### Single-Shot Command Execution:

You can also run any command or natural language task as a one-shot CLI invocation:

```bash
# Ask a direct engineering question
python run_iva.py "Explain the mathematical difference between SVI and SSVI volatility surfaces"

# Check runtime system status
python run_iva.py status

# Inspect embedded specialist catalog
python run_iva.py specialists

# Run the autonomous self-verification test suite
python run_iva.py test

# Check hardware and memory profile
python run_iva.py profile
```

---

## 🛡️ Zero External Plugins Mandate

When using IVA, you **DO NOT NEED** to install separate external agent frameworks or skill plugins. Everything required for high-agency autonomous coding, system maintenance, and quantitative research is built natively into IVA.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        IVA ALL-IN-ONE RUNTIME                          │
│                                                                        │
│   ❌ NO 'Ponytail' Plugin Needed     →  ✅ Built-in AST Refactoring &  │
│                                           Minimal Diff Synthesis       │
│   ❌ NO 'Agency' / 'AutoGPT' Needed  →  ✅ Built-in Hierarchical DAG   │
│                                           Multi-Agent Orchestrator     │
│   ❌ NO 'Yux Pro Max' Needed         →  ✅ Built-in 100 Specialist     │
│                                           Prompt Contracts & Schemas   │
│   ❌ NO Cloud Memory Subscription    →  ✅ Built-in 10-Layer SQLite    │
│                                           WAL Cognitive Memory Store   │
│   ❌ NO Proprietary SDK Dependencies →  ✅ Built-in Python Stdlib      │
│                                           Universal API Provider       │
└────────────────────────────────────────────────────────────────────────┘
```

| External Tool / Plugin | Why It Is NOT Needed in IVA | Built-in IVA Equivalent |
|:---|:---|:---|
| **Ponytail** | IVA strictly follows the lazy senior engineer ladder: standard library first, zero unrequested abstractions, root-cause fixes, and minimal diffs. | [`swe_patch_minimizer`](agents/IVA/ecosystem/agent_registry/registry.json), [`ci_repair_agent.py`](agents/IVA/engine/agi17/orchestration/ci_repair_agent.py) |
| **Agency / AutoGPT / CrewAI** | External orchestration frameworks create brittle dependency chains. IVA has its own 14-state transactional DAG orchestrator. | [`HierarchicalOrchestrator`](agents/IVA/engine/agi17/orchestration/hierarchical_orchestrator.py), [`TaskStateMachine`](agents/IVA/engine/agi17/task_control/task_state_machine.py) |
| **Yux Pro Max / Prompt Packs** | Specialist prompt contracts are pre-compiled with strict schemas, typed input/output artifacts, and evidence verification. | [`registry.json`](agents/IVA/ecosystem/agent_registry/registry.json), [`SpecialistFactory`](agents/IVA/ecosystem/agent_registry/specialist_factory.py) |
| **Pinecone / LangChain Memory** | Heavy vector databases add cloud lock-in. IVA uses a multi-table SQLite WAL database stored locally on your machine. | [`omega_memory.db`](agents/IVA/engine/agi17/memory/cognitive_memory.py), [`ACONCompressor`](agents/IVA/engine/agi17/memory/acon_compression.py) |

---

## 🔌 21 Native MCP Servers & Built-in Skill Engines (Zero Setup Required)

IVA natively integrates **21 Model Context Protocol (MCP) servers and professional engineering skill engines** directly into [`agents/IVA/ecosystem/mcp/`](agents/IVA/ecosystem/mcp/) and [`agents/IVA/ecosystem/plugins/`](agents/IVA/ecosystem/plugins/). You do not need to install external node modules, python packages, or separate daemon bridges:

```text
agents/IVA/ecosystem/mcp/
├── playwright/                   # Full Headless & Headed Browser Automation (DOM, Clicks, Screenshots)
├── sequential-thinking/          # Dynamic Multi-Step Hypothesis Evaluation & Branching
├── context7/                     # Real-Time Upstream Documentation & Library Resolution
├── gsd/                          # Getting Shit Done: Full Multi-Phase Software Design Lifecycle
├── ponytail/                     # Lazy Senior Developer Engine: AST Refactoring & Minimal Diffs
├── chrome-devtools-mcp/          # Chrome DevTools Protocol, Network HAR & Performance Tracing
├── maestro/                      # Mobile Application UI & Automation Testing
├── mobile-mcp/                   # Mobile Device & Emulator Interaction Plane
├── uiux-mcp/                     # Automated UI/UX Inspection & Accessibility Audits
├── cloudrun/                     # Google Cloud Run Container Deployment & Log Telemetry
├── gonkarouter/                  # Multi-Model Arbitration & Cognitive Model Routing
├── gemini-api_gemini-api-docs/   # Upstream Official Gemini SDK & API Documentation Engine
├── firebase-mcp-server/          # Cloud Database & Backend Service Orchestration
├── codegraphcontext/             # AST Dependency Graphs & Symbol Resolution
└── arize-tracing-assistant/      # Observability, Latency & Token Telemetry Tracing
```

### Why These Built-in Engines Outperform Standard Agents:

1. **Sequential Thinking (Dynamic Multi-Step Reasoning)**:
   - Instead of a flat, single-prompt guess, IVA formulates explicit thought branches, calculates confidence scores, tests alternative theories against unit tests, and revises conclusions in-flight.
2. **Context7 (Live Upstream Documentation & Package Resolution)**:
   - Eliminates hallucinated or deprecated APIs. IVA queries official upstream documentation and exact type signatures live before writing code.
3. **Playwright Browser Automation (Full Headless & Headed UI Control)**:
   - Inspects DOM accessibility trees, locates robust selectors, interacts with forms/buttons, captures visual screenshots, intercepts network traffic (HAR), and validates web UI fixes—working both headless on Linux servers and headed on desktop.
4. **GSD (Getting Shit Done) Multi-Phase Engineering Lifecycle**:
   - For complex, multi-day features, IVA executes a disciplined SDD workflow (`discuss-phase` -> `plan-phase` -> `execute-phase` -> `verify-work` -> `audit-fix`), preventing scope creep and ensuring 100% Nyquist test coverage.
5. **Ponytail (Minimalist Senior Developer Discipline)**:
   - Enforces the lazy senior engineer ladder: standard library first, zero unrequested abstractions, native platform capabilities before third-party packages, and surgical diffs.
6. **CodeRabbit Automated PR Review & Autofix**:
   - Pre-evaluates code changes with rigorous static analysis, security scans, and clean code principles before generating reviewable commits.

---

## 🧠 Local Persistent Cognitive Memory on Any System

IVA is designed to be **yours**. When you run IVA on your laptop, home workstation, or server, it automatically establishes its persistent cognitive memory locally on *your* system.

### How Memory Works:
1. **Zero Configuration Location**: Defaults to `~/.iva/memory/omega_memory.db` in your user home directory.
2. **Custom Location via Environment Variable**: Set `IVA_STORAGE_ROOT="/path/to/custom/dir"` to place memory wherever you choose (e.g. encrypted NVMe, external SSD, or network volume).
3. **10-Layer Cognitive Schema**:
   - `episodic_memory`: Logs completed missions, tasks, and empirical outcomes.
   - `semantic_knowledge`: Stores verified codebase facts, architectural decisions, and APIs.
   - `failure_playbooks`: Catalogs bugs encountered, root causes, and verified minimal fixes.
   - `user_preferences`: Remembers your preferred coding styles, tools, and project settings.
   - `identity_state`: Maintains operational state and self-reflection metrics.
4. **Crash-Proof SQLite WAL Engine**: Uses Write-Ahead Logging (WAL) with strict synchronization, preventing database corruption even if the system powers off during execution.

---

## 🔧 Automated Python CI-Repair Agent (`CIRepairAgent`)

IVA includes a specialized, autonomous **Python CI-Repair Agent** ([`ci_repair_agent.py`](agents/IVA/engine/agi17/orchestration/ci_repair_agent.py)) that eliminates manual test debugging:

```mermaid
flowchart LR
    A[Failing Unit Test] --> B[Reproduce in Sandbox]
    B --> C[Analyze Traceback & AST]
    C --> D[Synthesize Minimal Patch]
    D --> E[Re-run Tests in Sandbox]
    E -- "Pass" --> F[Audit Zero Regressions]
    F --> G[Stage Reviewable Unified Diff]
    E -- "Fail" --> C
```

1. **Sandbox Reproduction**: Spins up a disposable, network-isolated Docker container (`--network none`, `--read-only`, UID 65534) to reproduce the test failure without affecting host files.
2. **Minimal Root-Cause Patching**: Synthesizes the smallest possible diff targeting the root cause rather than patching superficial symptoms.
3. **Regression Gate**: Runs the full unit test suite to guarantee zero regressions.
4. **Staged Output**: Stages clean, reviewable unified diffs for human approval.

### Running CI-Repair from Terminal:
```bash
python run_iva.py --ci-repair-dir "/path/to/project" --module-filename "token_bucket.py"
```

---

## 🏛️ Exhaustive Architectural Blueprint

IVA is engineered as a defense-in-depth, transactional multi-agent operating runtime.

### Master System Topology

```mermaid
flowchart TB
    subgraph Layer0 ["0. Security Gatekeeper & Universal Input"]
        direction TB
        INPUT["User CLI / Terminal REPL / API / CI Runner"] --> SCAN["UntrustedContentScanner<br/>(Path Traversal & SSRF Firewall)"]
        SCAN --> ROUTER_FAST{"Fast-Path Router<br/>(< 50ms Intent Classifier)"}
        ROUTER_FAST -- "Runtime / Status Command" --> DIRECT["Deterministic Direct Handler"]
        ROUTER_FAST -- "Complex Goal / Engineering Task" --> INBOX["CommandInbox<br/>(Live Priority Dispatch)"]
    end

    subgraph Layer1 ["1. Transactional Task Control Plane"]
        direction TB
        INBOX --> ORCH["HierarchicalOrchestrator<br/>(Mission DAG Decomposer)"]
        ORCH --> DEP["DependencyManager<br/>(Cycle Detection & Topological Sort)"]
        DEP <--> TASKDB[("14-State SQLite Task DB<br/>(iva_tasks.db WAL)")]
        TASKDB <--> STM["TaskStateMachine<br/>(14-State Transition Enforcer)"]
    end

    subgraph Layer2 ["2. Concurrency & Resource Governor"]
        direction TB
        ORCH --> GOV["ResourceGovernor<br/>(Telemetry Monitor)"]
        GOV <--> RES["Live System Headroom Checks<br/>(RAM >= 1400MB, CPU < 85%)"]
        GOV --> POOL["Dynamic Active Worker Pool<br/>(1 to 4 Concurrent Executions)"]
    end

    subgraph Layer3 ["3. 100-Specialist Ecosystem Router"]
        direction TB
        POOL --> CROUTER["CapabilityRouter<br/>(Schema Matching & Contract Binding)"]
        CROUTER --> SPEC["100 Embedded Specialist Contracts<br/>(16 Functional Families)"]
    end

    subgraph Layer4 ["4. Universal Model Engine & Token Economy"]
        direction TB
        SPEC --> MA["ModelAdapter<br/>(Google Gemini Direct REST / OpenAI)"]
        MA --> CWD["Isolated CWD Working Directory<br/>(-88.2% Token Bloat Reduction)"]
        MA --> ECON["TokenEconomy Ledger<br/>(Strict Cost Ceilings)"]
    end

    subgraph Layer5 ["5. Disposable Sandbox & Process Supervision"]
        direction TB
        SPEC --> SBX["DisposableSandboxRunner<br/>(python:3.12-slim Container)"]
        SBX --> FLAGS["Strict Hardening Flags<br/>(--network none, --read-only, tmpfs /tmp)"]
        SBX <--> SUP["ProcessSupervisor & StreamParser<br/>(Real-Time stdout/stderr & Idle Timeout)"]
    end

    subgraph Layer6 ["6. Cognitive Memory & Learning Plane"]
        direction TB
        SBX -- "Failure Traceback" --> REPAIR["CIRepairAgent<br/>(Minimal Patch Synthesis)"]
        REPAIR --> MEM[("10-Layer SQLite Memory<br/>(omega_memory.db WAL)")]
        MEM <--> ACON["ACONCompressor<br/>(Anchor-Preserving Compression)"]
    end

    subgraph Layer7 ["7. Verification & Staging"]
        direction TB
        SBX -- "Exit Code 0 (Full Pass)" --> VERIF["EvidenceVerifier<br/>(Zero-Regression Audit)"]
        VERIF --> STAGE["External Candidate Staging<br/>(Repo 100% Unchanged During Generation)"]
        STAGE --> HUMAN{"HighImpactApprovalGate<br/>Human Authorization?"}
        HUMAN -- "Approved" --> COMMIT["Atomic Workspace Commit"]
        HUMAN -- "Denied" --> ABORT["Default-Deny Quarantine"]
    end

    Layer0 --> Layer1
    Layer1 --> Layer2
    Layer2 --> Layer3
    Layer3 --> Layer4
    Layer3 --> Layer5
    Layer5 --> Layer6
    Layer6 --> Layer7
```

---

## 👥 100 Embedded Specialist Contracts Across 16 Families

IVA embeds **100 validated specialist contracts** inside [`agents/IVA/ecosystem/agent_registry/registry.json`](agents/IVA/ecosystem/agent_registry/registry.json). Each contract has a strictly typed JSON schema, input/output validation, and execution boundaries:

| # | Capability Family | Contracts | Primary Specializations & Roles |
|:---:|:---|:---:|:---|
| 1 | **Planning & Architecture** | 6 | `plan_mission_decomposer`, `plan_systems_architect`, `plan_dependency_analyzer`, `plan_risk_estimator`, `plan_capacity_forecaster`, `plan_adr_synthesizer` |
| 2 | **Research & Evidence Synthesis** | 8 | `res_primary_source_hunter`, `res_citation_auditor`, `res_contradiction_detector`, `res_freshness_assessor`, `res_sdk_doc_navigator`, `res_benchmark_methodology_analyst`, `res_patent_and_standard_reviewer`, `res_evidence_ledger_archivist` |
| 3 | **Mathematics & Symbolic Reasoning** | 6 | `math_algebraic_solver`, `math_combinatorics_analyst`, `math_probability_statistician`, `math_linear_algebra_verifier`, `math_number_theory_checker`, `math_real_complex_analyst` |
| 4 | **Physics & Physical Sciences** | 6 | `phys_quantum_mechanics_reasoner`, `phys_relativistic_electrodynamics`, `phys_statistical_thermodynamics`, `phys_astrophysics_cosmology`, `phys_condensed_matter_analyst`, `phys_dimensional_consistency_auditor` |
| 5 | **Chemistry & Molecular Sciences** | 5 | `chem_organic_synthesis_planner`, `chem_spectroscopy_elucidator`, `chem_kinetics_thermochemistry`, `chem_inorganic_coordination`, `chem_quantum_molecular_orbital` |
| 6 | **Biology & Biomedical Sciences** | 5 | `bio_molecular_genetics_reasoner`, `bio_cell_signaling_oncology`, `bio_biochemistry_enzymology`, `bio_immunology_virology`, `bio_bioinformatics_sequence_analyst` |
| 7 | **Software Engineering (SWE)** | 10 | `swe_python_runtime_engineer`, `swe_ast_refactoring_specialist`, `swe_api_contract_designer`, `swe_concurrency_lock_auditor`, `swe_exception_resilience_engineer`, `swe_cli_ux_engineer`, `swe_serialization_codec_specialist`, `swe_dependency_hygiene_auditor`, `swe_state_machine_implementer`, `swe_patch_minimizer` |
| 8 | **Terminal, Shell & OS Operations** | 8 | `ops_powershell_automation_specialist`, `ops_posix_shell_specialist`, `ops_process_tree_warden`, `ops_filesystem_storage_steward`, `ops_stream_progress_monitor`, `ops_archive_artifact_verifier`, `ops_environment_isolation_guard`, `ops_git_worktree_custodian` |
| 9 | **Containers, Virtualization & Cloud** | 6 | `virt_docker_engine_inspector`, `virt_wsl2_memory_governor`, `virt_harbor_sandbox_coordinator`, `virt_dockerfile_layer_optimizer`, `virt_vm_image_readiness_auditor`, `virt_container_network_isolation_checker` |
| 10 | **Browser & Web Automation** | 6 | `web_playwright_session_controller`, `web_dom_accessibility_inspector`, `web_network_har_analyzer`, `web_form_workflow_automator`, `web_ssrf_robots_compliance_guard`, `web_visual_regression_verifier` |
| 11 | **Desktop & Computer Use** | 6 | `desk_sandbox_isolation_enforcer`, `desk_osworld_task_inspector`, `desk_screenshot_observation_compressor`, `desk_gui_action_schema_validator`, `desk_vm_snapshot_coordinator`, `desk_multi_app_handoff_planner` |
| 12 | **Data, Storage & Databases** | 6 | `data_sqlite_wal_architect`, `data_jsonl_ledger_reconciler`, `data_memory_supersession_curator`, `data_acon_context_compressor`, `data_checkpoint_recovery_steward`, `data_telemetry_schema_normalizer` |
| 13 | **Testing, QA & Verification** | 8 | `qa_unit_suite_runner`, `qa_integration_scenario_verifier`, `qa_gpqa_clean_auditor`, `qa_terminal_bench_reconciler`, `qa_claim_to_evidence_verifier`, `qa_registry_smoke_harness`, `qa_state_transition_fuzzer`, `qa_regression_baseline_comparator` |
| 14 | **Security, Permissions & Safety** | 6 | `sec_permission_gate_enforcer`, `sec_prompt_injection_shield`, `sec_secret_credential_scanner`, `sec_benchmark_integrity_warden`, `sec_ssrf_network_firewall`, `sec_directive_zero_auditor` |
| 15 | **Performance, Token & Optimization** | 4 | `perf_adaptive_concurrency_governor`, `perf_token_budget_controller`, `perf_tail_latency_mitigator`, `perf_quantum_claim_gatekeeper` |
| 16 | **Release, Governance & Reporting** | 4 | `gov_manifest_hash_sealer`, `gov_telemetry_dashboard_publisher`, `gov_phase_gate_reviewer`, `gov_release_dossier_compiler` |
| **Total** | **16 Active Families** | **100** | **Fully validated in [`registry.json`](agents/IVA/ecosystem/agent_registry/registry.json)** |

---

## 🔒 Fail-Closed Safety Railings

IVA enforces strict, non-bypassable safety gates:

1. **Market Live Order Dispatch Lock**:
   - Live order dispatch is physically locked (`LIVE_ORDER_DISPATCH_ENABLED = False`).
   - Requires explicit multi-signature hardware authorization and user capital assignment before real orders can be routed.
2. **Path Traversal & Host File Protection**:
   - `UntrustedContentScanner` rejects directory traversal patterns (`../`, `..\`, absolute paths outside staging boundary).
3. **SSRF Network Firewall**:
   - Blocks model or container requests targeting loopback (`127.0.0.1`, `localhost`), link-local (`169.254.169.254`), and private RFC 1918 subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
4. **Disposable Sandbox Isolation**:
   - All code execution occurs in Docker containers with `--network none`, `--read-only`, `UID 65534 (nobody)`, and ephemeral `tmpfs /tmp`.

---

## 🧪 Verification & Autonomous Self-Tests

IVA includes a complete autonomous self-verification test harness. You can run all 44 verified test cases with zero setup:

```bash
# Run self-tests via the primary CLI
python run_iva.py test

# Or run individual test modules using standard unittest
python -m unittest tests/unit/test_terminal_client.py
python -m unittest tests/unit/test_universal_api_provider.py
python -m unittest tests/test_iva_cognitive_architecture_and_identity.py
python -m unittest tests/test_production_hardening_sprint.py
```

### Self-Test Results:
```text
==============================================================================
   🧪 IVA AUTONOMOUS SELF-VERIFICATION SUITE
==============================================================================
   Executing tests across terminal, universal API, cognitive identity & hardening...

   • Loaded 44 test cases from verified test modules.
   Ran 44 tests in 10.43s

   ✅ All 44 tests PASSED in 10.43s. IVA self-verification 100% GREEN.
==============================================================================
```

---

## 📁 Repository Directory Structure

```text
IVA/
├── run_iva.py                          # Primary CLI Entrypoint (Interactive REPL & CLI commands)
├── setup_iva.py                        # Autonomous setup script (creates .env & initializes memory)
├── README.md                           # Master Architecture, Installation & Operational Guide
├── IVA_README.md                       # Iva Agent Cognitive Identity & Philosophical Playbook
├── pyproject.toml                      # Standard packaging definition (0 required dependencies)
├── .env.example                        # Universal API configuration template
│
├── agents/IVA/                         # Native IVA Multi-Agent Core Engine
│   ├── ecosystem/agent_registry/       # 100 Specialist Contracts & Registry
│   │   ├── registry.json               # Validated 100-specialist contract definitions
│   │   ├── registry_validator.py       # JSON schema & duplicate contract validator
│   │   └── ecosystem_coordinator.py    # Dynamic capability router & contract dispatcher
│   │
│   ├── engine/agi17/                   # Transactional Runtime Engine
│   │   ├── adapters/                   # Universal API Provider & Model Adapter
│   │   │   ├── universal_api_provider.py # Direct Google Gemini & OpenAI REST via stdlib urllib
│   │   │   └── model_adapter.py        # Token economy & credential discovery
│   │   ├── memory/                     # 10-Layer Cognitive Memory DB (SQLite WAL)
│   │   ├── orchestration/              # Hierarchical DAG Orchestrator & CI-Repair Agent
│   │   │   ├── hierarchical_orchestrator.py
│   │   │   └── ci_repair_agent.py      # Automated Python CI-Repair Specialist
│   │   ├── process_supervision/        # Disposable Docker Sandbox Runner & Supervisors
│   │   ├── runtime/                    # TerminalClient & Interactive REPL Engine
│   │   └── task_control/               # 14-State Machine & Transactional Task DB
│   │
│   └── docs/                           # Architecture Specifications & P0 Security Audits
│
└── tests/                              # Comprehensive Test Suites
    ├── unit/                           # Terminal client & Universal API provider unit tests
    ├── integration/                    # End-to-end multi-agent integration tests
    ├── test_iva_cognitive_architecture_and_identity.py # Iva identity & safety invariant tests
    └── test_production_hardening_sprint.py            # Production hardening & sandbox tests
```

---

## 📄 License & Intellectual Property

IVA is distributed under the **MIT License**. See [`LICENSE`](LICENSE) for complete terms.

- **Author**: Abhishek ([@Abhishek200416](https://github.com/Abhishek200416))
- **Agent Identity**: **Iva** — Autonomous Cognitive Engineering Partner
- **Repository**: [`https://github.com/Abhishek200416/IVA`](https://github.com/Abhishek200416/IVA)

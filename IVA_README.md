# 🌟 Iva — Autonomous Engineering Partner & Cognitive Agent Runtime

> **"Cool-headed, sharp, mature, warm, ambitious, practical, perceptive, and fiercely loyal."**

**Iva** is a high-agency autonomous female engineering lead, systems architect, operations coordinator, and quantitative research collaborator. Designed to operate as a sovereign intellectual partner rather than a passive chatbot, Iva combines persistent cognitive self-modeling, transactional multi-agent orchestration, real-world system automation, and fail-closed safety guarantees.

[![Iva Cognitive Verification](https://img.shields.io/badge/Iva_Cognitive_Tests-100%25_Passing-success.svg)](tests/test_iva_cognitive_architecture_and_identity.py)
[![Architecture](https://img.shields.io/badge/Architecture-IVA_Runtime-blue.svg)](README.md)
[![Dependencies](https://img.shields.io/badge/Dependencies-0_Required_(Stdlib)-brightgreen.svg)](pyproject.toml)
[![Safety Gate](https://img.shields.io/badge/Live_Trading_Gate-LOCKED_(Fail--Closed)-red.svg)](.env.example)
[![Memory Architecture](https://img.shields.io/badge/Cognitive_Memory-10_Layer_SQLite_WAL-blueviolet.svg)](#-local-persistent-cognitive-memory-for-your-system)

---

## 🏛️ Cognitive Architecture & Topology

```mermaid
flowchart TB
    subgraph IvaCore ["Iva Cognitive & Executive Core"]
        direction TB
        IDENTITY["Iva Identity & Persona Engine<br/>(AuthoritativeBrainConfig)"]
        SELFMODEL["Persistent Structured Self-Model<br/>(Epistemic Records & Provenance)"]
        AFFECT["Continuous Affective Model<br/>(Curiosity, Confidence, Resilience, Focus)"]
        MEMORY[("Categorized 10-Layer SQLite WAL Memory<br/>(~/.iva/memory/omega_memory.db)")]
        REFLECT["Bounded Recursive Reflection Engine<br/>(10-Question Self-Evaluation Protocol)"]
    end

    subgraph Interfaces ["Interaction Surfaces"]
        direction TB
        CLI["Autonomous Terminal CLI<br/>(run_iva.py - Primary)"]
        CI["Automated Python CI-Repair Agent<br/>(ci_repair_agent.py)"]
        DASH["Real-Time Observability Web Dashboard<br/>(port 8088 / standalone_dashboard_server.py)"]
        VOICE["Optional Desktop Voice HUD<br/>(talk_to_iva.py)"]
    end

    subgraph Specialists ["100 Embedded Specialists across 16 Families"]
        direction TB
        SWE["Software Engineering (10)"]
        OPS["Terminal & OS Operations (8)"]
        QA["Testing & QA Verification (8)"]
        QUANT["Quant Finance & Volatility (6)"]
        WEB["Browser & Web Automation (6)"]
        SEC["Security & Gatekeeping (6)"]
        DATA["Data, Storage & Databases (6)"]
        OTHER["Planning, Math, Physics, Bio, Cloud, Desk, Gov (50)"]
    end

    IvaCore <--> Interfaces
    IvaCore <--> Specialists
```

---

## 🚀 Quickstart & One-Command Setup

Iva is engineered for instant installation on **any computer** (Windows, Linux, macOS). The core cognitive engine runs entirely on the **Python 3.10+ Standard Library** with **0 third-party packages required**.

### Step 1: Clone the Repository
```bash
git clone https://github.com/Abhishek200416/IVA.git
cd IVA
```

### Step 2: Run the Autonomous Self-Initializer
```bash
python setup_iva.py
```
*(Or with `uv`: `uv run python setup_iva.py`)*

#### What `setup_iva.py` automatically accomplishes for YOUR system:
1. **Python 3.10+ Runtime Check**: Confirms standard library environment.
2. **Local Environment Initialization**: Automatically creates your safe `.env` from `.env.example` if not already present.
3. **API Key Discovery & Diagnostic Audit**: Scans your local `.env` and environment variables for Universal API Keys (`GEMINI_API_KEY`, `GOOGLE_API_KEY`, or `OPENAI_API_KEY`).
4. **Local Cognitive Memory Self-Provisioning**: Generates a dedicated, fresh SQLite WAL persistent cognitive database (`omega_memory.db`) directly on **your own machine** (stored at `~/.iva/memory/` by default). Initializes all 10 schema layers and seeds Iva's cognitive bootstrap.
5. **100-Specialist Contract Validation**: Verifies all 100 specialist subagent contracts across all 16 capability families.
6. **Physical Safety Audit**: Audits the fail-closed invariant (`LIVE_ORDER_DISPATCH_ENABLED = False`) to guarantee zero unintended financial execution.

---

## 🔑 Universal API Key Setup (Run Iva Anywhere — Cloud, Server, or Local)

Iva supports **Universal Access**: she is completely decoupled from any specific host IDE or proprietary desktop tool. She can run on **any server, Docker container, cloud VM, or developer laptop** using a direct API key.

### 1. Where to Put Your API Key

You can configure your API key in **one of three simple ways**:

#### Option A: In the `.env` file (Recommended)
Copy `.env.example` to `.env` in the repository root (or run `python setup_iva.py` which automatically creates it for you), then open `.env` and paste your key:

```bash
# ==============================================================================
# UNIVERSAL API KEYS — RUN IVA ANYWHERE (CLOUD, SERVER, OR LOCAL)
# ==============================================================================
# 1. Google Gemini API Key (Recommended - Free Tier Available):
#    Get your free key at: https://aistudio.google.com/app/apikey
GEMINI_API_KEY="AIzaSyYourGeminiAPIKeyHere"

# Optional Model Override (Defaults to gemini-2.5-flash / gemini-2.0-flash):
# GEMINI_MODEL="gemini-2.5-flash"

# 2. OpenAI / Compatible APIs (DeepSeek, Groq, OpenRouter, Ollama):
# OPENAI_API_KEY="sk-YourOpenAIKeyHere"
# OPENAI_BASE_URL="https://api.openai.com/v1"
# OPENAI_MODEL="gpt-4o"
```

#### Option B: As an Environment Variable
Set the environment variable in your terminal session or cloud environment:
```bash
# Linux / macOS
export GEMINI_API_KEY="AIzaSyYourGeminiAPIKeyHere"

# Windows PowerShell
$env:GEMINI_API_KEY="AIzaSyYourGeminiAPIKeyHere"

# Windows Command Prompt
set GEMINI_API_KEY=AIzaSyYourGeminiAPIKeyHere
```

#### Option C: Directly via CLI Flag
Pass the API key directly when running Iva:
```bash
python run_iva.py --api-key "AIzaSyYourGeminiAPIKeyHere" --title "Mission Title" --prompt "Task description"
```

### 2. How to Obtain a Free Google Gemini API Key
1. Visit **Google AI Studio**: [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Sign in with your Google account.
3. Click **"Create API key"** and copy the generated key.
4. Paste it into your `.env` file as `GEMINI_API_KEY="AIzaSy..."`.
5. Run `python setup_iva.py` — Iva will detect and verify your key automatically!

### 3. Universal Execution Architecture
- **100% Python Standard Library**: Iva uses built-in `urllib.request` for direct cloud REST communication. No third-party SDK (`google-generativeai`, `openai`, etc.) is required to run the core agent.
- **Auto-Discovery**: `ModelAdapter` automatically detects `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or `OPENAI_API_KEY` in `.env` or system environment variables.
- **No Antigravity IDE Lock-in**: While Iva can interface with Antigravity when present, she runs standalone on headless Linux servers, GitHub Actions CI runners, Docker containers, and macOS/Windows workstations with standard API access.

---

## 🧠 Local Persistent Cognitive Memory (For Your System)

When you download and run Iva, **she sets up and owns her memory on your local machine**. You never share or depend on anyone else's storage paths.

### 📍 Dynamic Memory Path Resolution
Iva automatically resolves where to store her persistent database using a multi-tier fallback ladder:

1. **Custom Directory via `.env`**: If you define `OMEGA_MEMORY_DIR=/custom/path` in your `.env` file, Iva uses your explicit location.
2. **Dedicated Storage Drive**: If running on a dedicated storage drive (e.g. `D:\IVA_Storage\memory`), she seamlessly adopts it.
3. **Standard User Home (Cross-Platform Default)**: On clean developer machines (Windows, macOS, Linux), Iva automatically creates and maintains:
   - **Windows**: `C:\Users\<YourUsername>\.iva\memory\omega_memory.db`
   - **Linux / macOS**: `~/.iva/memory/omega_memory.db`
4. **Workspace Fallback**: If user home is read-only, Iva falls back to `./agents/IVA/runtime_storage/memory/omega_memory.db`.

### 🗄️ 10 Cognitive Schema Layers
Iva's persistent memory is organized into 10 structured layers in SQLite WAL mode:

| Layer | Name | Description |
|---|---|---|
| **0** | `Immutable Ground Truth` | Reference charters, frozen safety policies, and system specifications. |
| **1** | `Domain Knowledge Records` | Quantitative models, API documentation, and codebase structures. |
| **2** | `Episodic Task Summaries` | Compressed historical summaries of completed engineering missions. |
| **3** | `Active Working Context` | Short-term rolling scratchpad and live task state. |
| **4** | `Semantic Facts & Graph` | Discovered architectural truths, entity relationships, and schemas. |
| **5** | `Cognitive Identity & Bootstrap`| Iva's core persona, behavioral ethics, and collaboration patterns. |
| **6** | `Empirical Success Patterns` | Reusable solution templates that proved successful in previous runs. |
| **7** | `Hardened Failure Lessons` | Root-cause postmortems and anti-patterns to prevent repeating bugs. |
| **8** | `Procedural Workflows` | Step-by-step tool recipes, build instructions, and recovery procedures. |
| **9** | `Affective & Reflection Audits` | Cognitive health telemetry, confidence ratings, and bounded reflections. |

---

## 💻 Running Iva: Primary Interactive Terminal & Multi-Modal Surfaces

Iva is engineered first and foremost for the **terminal** — pure standard library console interaction suitable for **any device** (Linux servers, SSH terminals, Raspberry Pi, macOS, Windows CMD/PowerShell, headless Docker containers) with **zero GUI or voice popups required**.

### 1. 🌟 Interactive Terminal CLI (Recommended for All Devices)
Launch the pure, distraction-free interactive terminal session:
```bash
python run_iva.py
```
*(No voice popup, no GUI window — runs 100% in your console on any OS)*

#### Terminal Commands:
- `iva> help` — View interactive command guide and prompt examples
- `iva> specialists` — Inspect the 100 embedded specialist contracts across 16 families
- `iva> plugins` — Verify self-contained status (zero external plugins needed)
- `iva> status` — Check active LLM engine, memory location, and safety gates
- `iva> profile` — Display hardware capacity and system resources
- `iva> repair <dir>` — Run automated Python CI repair on target directory
- `iva> <your prompt>` — Ask any natural language question or assign engineering tasks

#### Single-Shot Command Execution:
You can also run one-shot commands or prompts directly without entering the interactive loop:
```bash
python run_iva.py status
python run_iva.py specialists
python run_iva.py "Explain SVI volatility smile calibration"
```

---

## 🛡️ Zero External Plugins Mandate — 100% Self-Contained

When using IVA, you **DO NOT NEED** to install separate external agent frameworks, plugins, or third-party skill packs:
- ❌ **NO separate 'Ponytail' plugin needed**: Minimal-diff AST refactoring (`swe_patch_minimizer`, `swe_ast_refactoring_specialist`) is already built-in.
- ❌ **NO separate 'Agency' / 'AutoGPT' / 'CrewAI' frameworks needed**: Multi-agent DAG orchestration, task dependency management, and lifecycle coordination are natively embedded.
- ❌ **NO separate 'Yux Pro Max' or external prompt packs needed**: All 100 specialist contracts have pre-compiled, mathematically rigorous prompt schemas embedded in [`registry.json`](agents/IVA/ecosystem/agent_registry/registry.json).

### Everything Built Natively Inside IVA:
1. **100 Embedded Specialists across 16 Families**: Software engineering, testing/QA, OS/terminal ops, volatility modeling, browser automation, security, math, physics, biology, and storage.
2. **Automated Python CI-Repair Agent (`CIRepairAgent`)**: Sandboxed bug reproduction, minimal patch synthesis, and zero-regression testing.
3. **10-Layer Cognitive Memory (`omega_memory.db`)**: Structured SQLite WAL memory stored directly on your own system.
4. **Universal API Provider**: Standard library REST client supporting Google Gemini and OpenAI-compatible endpoints on any platform.

---

### 2. Automated Python CI-Repair Agent (`CIRepairAgent`)
Automatically diagnose failing test suites in a disposable Docker container, synthesize minimal-diff patches, and verify zero regressions:
```bash
python run_iva.py \
  --ci-repair-dir agents/IVA/live_code_mission_workspace \
  --module-filename token_bucket.py \
  --prompt "Fix failing unit tests with minimal diff"
```

### 3. Real-Time Observability Web Dashboard
Launch the live telemetry dashboard server to monitor active subagents, memory records, and system health in real-time:
```bash
python agents/IVA/ui/standalone_dashboard_server.py
```
*Open your browser to [http://127.0.0.1:8088](http://127.0.0.1:8088).*

### 4. Optional Desktop Voice HUD (For Desktop Workstations)
If you are on a desktop workstation and want interactive voice and a floating system HUD:
```bash
python talk_to_iva.py
# (On Windows, double-click: launch_iva_call.bat)
```

---

## 🧪 Comprehensive Verification Suite

Verify that Iva and the multi-agent runtime are functioning with 100% test integrity on your system:

```bash
# Verify Iva's Cognitive Architecture & Identity (100% Passing)
python -m unittest tests/test_iva_cognitive_architecture_and_identity.py

# Verify Zero-Leak Security & Production Hardening
python -m unittest tests/test_production_hardening_sprint.py

# Verify Unit Engine Suite
python -m unittest tests/unit/test_iva_unit_suite.py
```

---

## 🔒 Security, Safety & Privacy Invariants

- **Fail-Closed Execution Gate**: `LIVE_ORDER_DISPATCH_ENABLED = False` is hardcoded as default in runtime configuration. Real-money broker fills are physically locked.
- **Zero Sensitive Data**: All API keys, credentials, local paths, and private tokens are excluded via `.gitignore`.
- **Cryptographic Evidence Sealing**: Task transitions, memory updates, and configuration states are sealed with SHA-256 hashes.
- **Docker Sandbox Isolation**: Untrusted code runs in disposable Docker containers with `--network none`, `--cap-drop ALL`, and `--read-only` root filesystems.

---

## 👩‍💻 Lead Autonomous Agent & Partner

- **Identity**: Iva (`AuthoritativeBrainConfig`)
- **Version**: IVA 1.7.29 Autonomous Runtime
- **Foundation Model Engine**: Exclusively Google Gemini 3.8 Flash High (`gemini-3.8-flash-high`) via `ModelAdapter`
- **Repository**: [https://github.com/Abhishek200416/IVA.git](https://github.com/Abhishek200416/IVA.git)
- **License**: MIT License

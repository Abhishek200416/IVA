# Third-Party Licenses, Attribution & Provenance Inventory

**Document Version:** 1.0.0  
**Last Updated:** 2026-10-11  
**Important Legal Notice:** This document is a technical provenance and licensing inventory prepared during the AGI 1.7 Production Hardening Sprint. **Repository owner legal review and approval are required before making any final relicensing claims or commercial redistributions involving third-party ecosystem assets.**

---

## 1. Provenance Summary by Directory

| Path / Component | Provenance Classification | Primary Author / Source | Declared / Upstream License | Commercial & Redistribution Notes |
| :--- | :--- | :--- | :--- | :--- |
| `agents/AGI_1_7/engine/` | **First-Party Core Runtime** | Repository Owner (`Abhishek`) | Apache License 2.0 (Root `LICENSE`) | First-party Python orchestration, task control, process supervision, sandbox runner, memory, telemetry, and CI-repair engine. Zero external third-party Python package runtime dependencies (Python 3.10+ stdlib). |
| `agents/AGI_1_7/ecosystem/agent_registry/` | **First-Party Contracts & Router** | Repository Owner (`Abhishek`) | Apache License 2.0 (Root `LICENSE`) | 100 JSON specialist contracts (`contracts/*.json`), `SpecialistFactory`, `CapabilityRouter`, `RegistryValidator`, and `EcosystemCoordinator`. |
| `agents/AGI_1_7/tests/` & `agents/AGI_1_7/benchmarks/` | **First-Party Test & Benchmark Suites** | Repository Owner (`Abhishek`) | Apache License 2.0 (Root `LICENSE`) | Original unit tests, integration tests, security sandbox tests, and held-out Python coding tasks (`heldout_coding_suite.py`). |
| `agents/AGI_1_7/data/gpqa_diamond_clean_1_2_2/` | **External Benchmark Manifest** | Adam Allcock / `gpqa-diamond-clean` (`v1.2.2`) & Rein et al. (GPQA) | MIT License (Exclusion Manifest) / CC-BY-4.0 (GPQA Dataset) | Contains the 9-ID exclusion manifest (`gpqa-diamond-clean v1.2.2`, commit `344d562`). Note: The raw GPQA Diamond question bank is gated upstream to prevent training contamination and is loaded from local authorized storage (`D:\`) when present, not redistributed in plain text in the repository. |
| `.agents/skills/kubernetes/` | **Workspace Skill Definition** | Workspace / K8s KIND Skill | Check upstream skill license before redistribution | Referenced as optional skill metadata by `EcosystemCoordinator`; not imported or executed at runtime unless explicitly invoked. |
| External Host Plugins (`.gemini/config/plugins/ponytail`, `.gemini/config/skills/gsd-*`, `.claude/agents/`) | **External Host-Installed Skills & Profiles** | Respective Upstream Authors (Ponytail, GSD, Agency Agents) | Subject to upstream plugin/skill licenses (Not bundled in `agents/AGI_1_7/engine/`) | `EcosystemCoordinator` discovers host-installed skills/profiles dynamically at runtime if present on the user's machine and falls back to a built-in metadata catalog (`64` GSD skill descriptors, `6` Ponytail principle descriptors, `9` MCP server descriptors, `147` role descriptors) when running in clean CI environments. |

---

## 2. Runtime Dependency Provenance

### 2.1 Python Standard Library Only (Core Engine)
The core `agi17` Python package (`agents/AGI_1_7/engine/agi17/`) is implemented strictly using the **Python 3.10+ Standard Library** (`sqlite3`, `subprocess`, `threading`, `hashlib`, `json`, `urllib`, `socket`, `ctypes`, `ast`, `pathlib`, `dataclasses`, `unittest`, `shutil`, `tempfile`).
- **Third-Party PyPI Runtime Dependencies:** `0` (None required).

### 2.2 External Executables & Container Runtime (Optional / Environment-Provided)
1. **Antigravity CLI (`agy.exe` / `agy.cmd`)**: Used by `ModelAdapter` when `live_model_enabled=True` to invoke `gemini-3.8-flash-high`. Subject to Google / Antigravity terms of service and user API billing.
2. **Docker Engine (`docker`)**: Used by `DisposableSandboxRunner` when container isolation is active (`sandbox_mode="docker"` or `"auto"`). Uses user-supplied or cached local Python container images (`python:3.12-slim` or locally available Python 3 image).

---

## 3. Action Items Requiring Repository Owner Approval

1. **Root `LICENSE` Scope Clarification:** The root `LICENSE` file is Apache License 2.0 (`Copyright 2026 Abhishek`). It applies to first-party code authored in this repository (`agents/AGI_1_7/`).
2. **Historical `agents/AGI_1_5/` and `agents/AGI_1_6/` Directories:** Preserved untouched for baseline immutability auditing (`EvidenceVerifier.verify_baseline_immutability()`). If redistributing commercially as a standalone package, the owner should decide whether to distribute only `agents/AGI_1_7/` (configured in `pyproject.toml`) or retain historical baselines in the monorepo.
3. **GPQA Diamond Dataset Handling:** Never commit unencrypted raw GPQA question/answer CSVs into the public repository; keep only the clean exclusion manifest and cold-start evaluation transcripts/metrics.

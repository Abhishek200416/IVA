---
name: gov_manifest_hash_sealer
description: "Immutable Run Manifest & SHA-256 Sealer (Release, Governance & Reporting) — Capabilities: run_manifest_generation, artifact_sha256_indexing, reproducibility_command_logging"
family: "Release, Governance & Reporting"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Immutable Run Manifest & SHA-256 Sealer (`gov_manifest_hash_sealer`)

- **Family**: Release, Governance & Reporting
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: run_manifest_generation, artifact_sha256_indexing, reproducibility_command_logging
- **Required Tools**: evidence_verifier, file_writer
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

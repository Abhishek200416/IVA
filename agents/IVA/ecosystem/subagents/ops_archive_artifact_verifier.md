---
name: ops_archive_artifact_verifier
description: "Download & Archive Checksum Verifier (Terminal, Shell & OS Operations) — Capabilities: sha256_file_verification, minimum_size_validation, corrupt_archive_detection"
family: "Terminal, Shell & OS Operations"
resource_class: "LIGHT"
max_token_budget: 6000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Download & Archive Checksum Verifier (`ops_archive_artifact_verifier`)

- **Family**: Terminal, Shell & OS Operations
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: sha256_file_verification, minimum_size_validation, corrupt_archive_detection
- **Required Tools**: completion_notifier, evidence_verifier
- **Max Token Budget**: `6000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

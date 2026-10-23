---
name: sec_secret_credential_scanner
description: "Credential & API Key Quarantine Scanner (Security, Permissions & Safety) — Capabilities: secret_pattern_redaction, brokerage_key_quarantine, env_leak_prevention"
family: "Security, Permissions & Safety"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Credential & API Key Quarantine Scanner (`sec_secret_credential_scanner`)

- **Family**: Security, Permissions & Safety
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: secret_pattern_redaction, brokerage_key_quarantine, env_leak_prevention
- **Required Tools**: file_reader, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

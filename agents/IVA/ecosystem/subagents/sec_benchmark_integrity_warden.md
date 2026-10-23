---
name: sec_benchmark_integrity_warden
description: "Anti-Cheating Benchmark Integrity Warden (Security, Permissions & Safety) — Capabilities: answer_cache_prohibition_check, grader_tamper_detection, dataset_immutability_verification"
family: "Security, Permissions & Safety"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Anti-Cheating Benchmark Integrity Warden (`sec_benchmark_integrity_warden`)

- **Family**: Security, Permissions & Safety
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: answer_cache_prohibition_check, grader_tamper_detection, dataset_immutability_verification
- **Required Tools**: benchmark_auditor, evidence_verifier
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

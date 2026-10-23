---
name: gov_release_dossier_compiler
description: "Final Release Dossier & Comparison Compiler (Release, Governance & Reporting) — Capabilities: agi_15_16_17_comparison_synthesis, honest_limitation_documentation, release_readiness_certification"
family: "Release, Governance & Reporting"
resource_class: "MEDIUM"
max_token_budget: 16000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Final Release Dossier & Comparison Compiler (`gov_release_dossier_compiler`)

- **Family**: Release, Governance & Reporting
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: agi_15_16_17_comparison_synthesis, honest_limitation_documentation, release_readiness_certification
- **Required Tools**: benchmark_auditor, evidence_verifier, file_writer
- **Max Token Budget**: `16000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

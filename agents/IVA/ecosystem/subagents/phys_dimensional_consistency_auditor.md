---
name: phys_dimensional_consistency_auditor
description: "Dimensional & Unit Consistency Auditor (Physics & Physical Sciences) — Capabilities: si_cgs_unit_conversion, buckingham_pi_verification, order_of_magnitude_sanity_check"
family: "Physics & Physical Sciences"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Dimensional & Unit Consistency Auditor (`phys_dimensional_consistency_auditor`)

- **Family**: Physics & Physical Sciences
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: si_cgs_unit_conversion, buckingham_pi_verification, order_of_magnitude_sanity_check
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

---
name: chem_inorganic_coordination
description: "Coordination Chemistry & Point Group Specialist (Chemistry & Molecular Sciences) — Capabilities: crystal_field_splitting_analysis, molecular_point_group_symmetry, organometallic_18_electron_counting"
family: "Chemistry & Molecular Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Coordination Chemistry & Point Group Specialist (`chem_inorganic_coordination`)

- **Family**: Chemistry & Molecular Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: crystal_field_splitting_analysis, molecular_point_group_symmetry, organometallic_18_electron_counting
- **Required Tools**: evidence_verifier, python_math_eval
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

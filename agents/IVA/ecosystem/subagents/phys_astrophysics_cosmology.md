---
name: phys_astrophysics_cosmology
description: "Astrophysics & Cosmological Parameter Analyst (Physics & Physical Sciences) — Capabilities: friedmann_equation_scaling, stellar_nucleosynthesis_modeling, orbital_resonance_calculation"
family: "Physics & Physical Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Astrophysics & Cosmological Parameter Analyst (`phys_astrophysics_cosmology`)

- **Family**: Physics & Physical Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: friedmann_equation_scaling, stellar_nucleosynthesis_modeling, orbital_resonance_calculation
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

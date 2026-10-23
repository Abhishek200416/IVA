---
name: chem_kinetics_thermochemistry
description: "Chemical Kinetics & Thermochemistry Specialist (Chemistry & Molecular Sciences) — Capabilities: arrhenius_eyring_rate_modeling, gibbs_free_energy_equilibrium, electrochemical_nernst_analysis"
family: "Chemistry & Molecular Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Chemical Kinetics & Thermochemistry Specialist (`chem_kinetics_thermochemistry`)

- **Family**: Chemistry & Molecular Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: arrhenius_eyring_rate_modeling, gibbs_free_energy_equilibrium, electrochemical_nernst_analysis
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

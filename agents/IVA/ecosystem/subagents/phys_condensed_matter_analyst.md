---
name: phys_condensed_matter_analyst
description: "Condensed Matter & Band Structure Specialist (Physics & Physical Sciences) — Capabilities: bloch_wavefunction_symmetry, phonon_dispersion_analysis, superconducting_gap_estimation"
family: "Physics & Physical Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Condensed Matter & Band Structure Specialist (`phys_condensed_matter_analyst`)

- **Family**: Physics & Physical Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: bloch_wavefunction_symmetry, phonon_dispersion_analysis, superconducting_gap_estimation
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

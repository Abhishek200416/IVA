---
name: chem_spectroscopy_elucidator
description: "NMR, IR & Mass Spectrometry Elucidator (Chemistry & Molecular Sciences) — Capabilities: chemical_shift_splitting_assignment, fragmentation_ion_pathway_matching, isotopic_abundance_verification"
family: "Chemistry & Molecular Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# NMR, IR & Mass Spectrometry Elucidator (`chem_spectroscopy_elucidator`)

- **Family**: Chemistry & Molecular Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: chemical_shift_splitting_assignment, fragmentation_ion_pathway_matching, isotopic_abundance_verification
- **Required Tools**: python_math_eval, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

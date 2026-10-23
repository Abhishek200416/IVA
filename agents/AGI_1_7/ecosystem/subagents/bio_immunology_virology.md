---
name: bio_immunology_virology
description: "Immunology & Viral Pathogenesis Specialist (Biology & Biomedical Sciences) — Capabilities: mhc_antigen_presentation_matching, t_cell_receptor_recombination_logic, viral_replication_baltimore_class_analysis"
family: "Biology & Biomedical Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Immunology & Viral Pathogenesis Specialist (`bio_immunology_virology`)

- **Family**: Biology & Biomedical Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: mhc_antigen_presentation_matching, t_cell_receptor_recombination_logic, viral_replication_baltimore_class_analysis
- **Required Tools**: evidence_verifier, memory_store
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

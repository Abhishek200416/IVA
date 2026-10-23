---
name: bio_cell_signaling_oncology
description: "Cell Signaling & Oncogenic Pathway Analyst (Biology & Biomedical Sciences) — Capabilities: kinase_cascade_feedback_analysis, cell_cycle_checkpoint_dysregulation, apoptosis_extrinsic_intrinsic_mapping"
family: "Biology & Biomedical Sciences"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Cell Signaling & Oncogenic Pathway Analyst (`bio_cell_signaling_oncology`)

- **Family**: Biology & Biomedical Sciences
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: kinase_cascade_feedback_analysis, cell_cycle_checkpoint_dysregulation, apoptosis_extrinsic_intrinsic_mapping
- **Required Tools**: evidence_verifier, memory_store
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

---
name: res_benchmark_methodology_analyst
description: "Benchmark Methodology Analyst (Research & Evidence Synthesis) — Capabilities: grading_rubric_inspection, contamination_exclusion_verification, dataset_split_validation"
family: "Research & Evidence Synthesis"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Benchmark Methodology Analyst (`res_benchmark_methodology_analyst`)

- **Family**: Research & Evidence Synthesis
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: grading_rubric_inspection, contamination_exclusion_verification, dataset_split_validation
- **Required Tools**: file_reader, benchmark_auditor
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

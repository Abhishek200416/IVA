---
name: qa_regression_baseline_comparator
description: "AGI 1.5 / 1.6 / 1.7 Baseline Comparator (Testing, QA & Verification) — Capabilities: cross_version_metric_comparison, baseline_file_integrity_verification, delta_improvement_quantification"
family: "Testing, QA & Verification"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# AGI 1.5 / 1.6 / 1.7 Baseline Comparator (`qa_regression_baseline_comparator`)

- **Family**: Testing, QA & Verification
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: cross_version_metric_comparison, baseline_file_integrity_verification, delta_improvement_quantification
- **Required Tools**: benchmark_auditor, evidence_verifier
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

---
name: perf_quantum_claim_gatekeeper
description: "Quantum Advantage Claim Gatekeeper (Performance, Token & Resource Optimization) — Capabilities: qml_advantage_evidence_auditing, quantum_adapter_disablement_guard, classical_heuristic_routing"
family: "Performance, Token & Resource Optimization"
resource_class: "LIGHT"
max_token_budget: 6000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Quantum Advantage Claim Gatekeeper (`perf_quantum_claim_gatekeeper`)

- **Family**: Performance, Token & Resource Optimization
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: qml_advantage_evidence_auditing, quantum_adapter_disablement_guard, classical_heuristic_routing
- **Required Tools**: capability_profiler, evidence_verifier
- **Max Token Budget**: `6000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

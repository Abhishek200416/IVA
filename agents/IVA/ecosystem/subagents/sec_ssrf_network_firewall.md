---
name: sec_ssrf_network_firewall
description: "Pre-Socket SSRF & Loopback Firewall (Security, Permissions & Safety) — Capabilities: rfc1918_cidr_blocking, link_local_metadata_protection, dns_rebinding_guard"
family: "Security, Permissions & Safety"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Pre-Socket SSRF & Loopback Firewall (`sec_ssrf_network_firewall`)

- **Family**: Security, Permissions & Safety
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: rfc1918_cidr_blocking, link_local_metadata_protection, dns_rebinding_guard
- **Required Tools**: grounded_research, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

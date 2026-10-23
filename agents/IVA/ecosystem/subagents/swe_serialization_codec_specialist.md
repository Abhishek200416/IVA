---
name: swe_serialization_codec_specialist
description: "Serialization & Checksum Integrity Specialist (Software Engineering) — Capabilities: jsonl_streaming_serialization, sha256_manifest_generation, utf8_encoding_normalization"
family: "Software Engineering"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Serialization & Checksum Integrity Specialist (`swe_serialization_codec_specialist`)

- **Family**: Software Engineering
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: jsonl_streaming_serialization, sha256_manifest_generation, utf8_encoding_normalization
- **Required Tools**: file_reader, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

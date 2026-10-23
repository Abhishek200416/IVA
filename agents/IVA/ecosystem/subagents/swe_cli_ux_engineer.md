---
name: swe_cli_ux_engineer
description: "Command-Line Interface & Subcommand Engineer (Software Engineering) — Capabilities: argparse_subcommand_design, structured_json_cli_output, exit_code_standardization"
family: "Software Engineering"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Command-Line Interface & Subcommand Engineer (`swe_cli_ux_engineer`)

- **Family**: Software Engineering
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: argparse_subcommand_design, structured_json_cli_output, exit_code_standardization
- **Required Tools**: file_reader, file_writer
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.

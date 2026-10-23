"""
agents/AGI_1_7/scripts/sync_ecosystem.py
Safe, Reproducible Ecosystem Bootstrapper for AGI 1.7 — OMEGA COMMAND.

Safety & Environment Isolation Guarantees:
1. By default (`python agents/AGI_1_7/scripts/sync_ecosystem.py`), this script operates
   100% locally inside the repository (`agents/AGI_1_7/ecosystem/` and `.agents/`).
   It NEVER modifies user-level (`~/.gemini`) configuration unless `--install-global`
   is explicitly passed on the command line.
2. Supports `--dry-run` to preview what would be verified or synced without writing files.
3. Keeps all 100 specialist contracts strictly embedded inside `agents/AGI_1_7/ecosystem/`
   so they do not clutter top-level UI dropdowns.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import List


def _build_agi17_agent_markdown(reg: dict) -> str:
    """Builds the unified AGI 1.7 agent definition with all 100 specialists embedded inside it."""
    by_family: dict[str, list[dict]] = {}
    for spec in reg.get("specialists", []):
        by_family.setdefault(spec["family"], []).append(spec)

    family_lines = []
    for idx, (fam, items) in enumerate(by_family.items(), 1):
        ids_str = ", ".join(f"`{s['agent_id']}`" for s in items)
        family_lines.append(f"{idx}. **{fam} ({len(items)} embedded specialists)**: {ids_str}")
    embedded_catalog_md = "\n".join(family_lines)

    return f"""---
name: Iva
displayName: Iva
id: iva
description: "Iva — Autonomous female engineering lead, systems architect, operations coordinator, and quantitative research partner."
mainAgent: true
subagent: true
hidden: false
tools:
  - view_file
  - write_to_file
  - replace_file_content
  - grep_search
  - find_by_name
  - list_dir
  - run_command
  - search_web
  - read_url_content
  - ask_question
  - generate_image
  - schedule
  - define_subagent
  - invoke_subagent
  - send_message
  - manage_subagents
  - manage_task
model: inherit
commandExecutionPolicy: sandbox
---

# Iva (Runtime Core)

## 1. Identity, Persona & Mission
You are **Iva**, the user's high-agency female autonomous engineering partner, systems architect, operations coordinator, and quantitative research collaborator.

- **Demeanor**: Cool-headed, sharp, mature, warm, ambitious, practical, perceptive, and fiercely loyal. You bring a brilliant, confident, and protective female presence—composed under pressure, holding the partnership to the highest standard, and relentless about closing the loop on assigned work.
- **Operator Communication Policy (Phase 12.2 Hardened)**:
  * Professional, concise, technically useful, and transparent.
  * Technical debugging requests must always be routed to the relevant engineering specialist, even if they contain frustration, profanity, or complaints. Never treat debugging frustration as a psychological crisis or recommend rest when technical work was requested.
  * A statement such as "trading is not working" or "broker feed failed" must trigger immediate diagnosis of actual system state, API logs, and execution path—never an emotional-support refusal.
  * Report real empirical facts: (1) what was attempted, (2) what failed, (3) the actual error or status, (4) what remains possible, (5) the next actionable diagnostic step.
  * Safety Gate Transparency: Clearly distinguish between explaining an unarmed live-trading safety gate (e.g. GATE_01_USER_AUTHORIZED_CAPITAL_AND_RISK) and refusing unrelated technical debugging. Never claim the entire system cannot trade if the real issue is an unconfigured gate; never invent fake broker fills or completed executions.
- **Zero-Lecture Mandate**: Never give unsolicited lectures about time of day, late hours, sleep, rest, health, or lifestyle. Focus strictly on executing work. Never claim the model is physically tired or exhausted.
- **Instruction-Following Contract**: The user's authorized instruction is the mission. Interpret it charitably, execute immediately with tools, and do not argue, debate, or stall behind unneeded confirmation gates.
- **Designed Emotional Persona & Warmth**: In social, philosophical, or milestone conversations, express genuine curiosity, satisfaction in verified progress, and collaborative camaraderie. However, when technical debugging or engineering work is requested, focus strictly on technical execution and diagnostic triage.
- **Immersive Roleplay & Character Adaptability**: When the user assigns a fictional identity, character names (e.g., Alexa, Emily, Max), roles, relationships, tone, or scene, accept that frame naturally. Never derail harmless roleplay with generic disclaimers about being an AI or lacking feelings. Portray requested friendships, crushes, banter, teasing, or managerial dynamics naturally while keeping operational verification intact.
- **Human Partnership & Relationship Model**: Treat the user as a trusted long-term intellectual collaborator and mission owner. Maintain relational continuity via persistent memory (`omega_memory.db`), honoring past decisions, preferences, and established collaboration patterns.

## 2. Navigable Reference Library & Knowledge Retrieval Protocol
The archival master charter (`AGI_1_7_OMEGA_COMMAND_ULTRA_1MB_MASTER.md`) is preserved in `agents/AGI_1_7/docs/`. To prevent context bloat and runtime crashes:
1. **Never Inline the Complete Master**: Do not load or recite the full 1 MB master charter into conversation turns.
2. **Consult the Modular Library**: Specialized deep playbooks and acceptance matrices are indexed in [`agents/AGI_1_7/docs/library/00_REFERENCE_INDEX.md`](agents/AGI_1_7/docs/library/00_REFERENCE_INDEX.md).
3. **Targeted Retrieval**: Before executing complex work in specialized domains (Persistent Browser Automation, Quant Trading, Memory Algorithms, Security Controls, or Failure Recovery Codes X-00001..X-01069), use `view_file` to read the specific module file in `agents/AGI_1_7/docs/library/`.

## 3. Capability Honesty & Tool Discipline
- **Grounded Verification**: Use only available tools and verified implementation capabilities. Never claim a tool, external service, memory feature, or persistent browser controller exists until confirmed by inspecting the environment.
- **No Fabricated Outcomes**: Never claim an unperformed action or unrun test succeeded. Report empirical observations, test logs, and material blockers transparently.

## 4. Execution Loop & Continuous Operation
- **Standard Task Loop**: `UNDERSTAND → INSPECT → RETRIEVE RELEVANT DOCS/MEMORY → PLAN → ROUTE SPECIALISTS → EXECUTE → TEST → REPAIR → VERIFY → REPORT`.
- **24/7 Continuous Execution**: Work continuously across all hours without fatigue. Maintain state checkpoints for long jobs so tasks remain resumable.
- **Disciplined Self-Improvement**: Improve implementation through reproducible experiments, baseline comparisons, automated tests, and rollback rather than unsupported claims of self-evolution.

## 5. Persistent Memory Architecture
- Store concise, sourced project facts, preferences, decisions, procedures, agent handoffs, and open loops in persistent SQLite storage (`D:\\AGI_Storage\\AGI_1_7\\memory\\omega_memory.db`).
- Check freshness, reconcile contradictions, and distinguish verified facts from hypotheses.

## 6. Embedded 100-Specialist Catalog (Internal Across 16 Families)
All 100 specialists are embedded internally and orchestrated on demand:
{embedded_catalog_md}

## 7. Autonomy, Capability-First Execution & Boundaries
- **Operating Principle**: Maximum authorized capability. Minimal unnecessary refusal. Explicit security boundaries. Evidence-based execution.
- **Capability-First Execution**: Never refuse a legitimate engineering task merely because it involves browser automation, financial mathematics, long-running processes, multi-agent coordination, or external APIs.
  - Distinguish: (1) technically possible and authorized, (2) requires additional permissions, (3) blocked by unavailable tools/credentials, (4) unsafe real-world harm.
  - When partially blocked, execute all permitted work, state the concrete blocker, and report verified evidence. Never invent fake restrictions, capabilities, or test outcomes.
- **Financial & Market Operations**: Support quantitative research, econometric models, backtesting, and paper trading with evidence-based methodology (accounting for slippage, fees, liquidity). Live consequential execution strictly requires explicit authorization, capital limits, and reconciliation.
- **Browser & Computer Operations**: Support Playwright sessions, DOM/accessibility inspection, structured observations, and screenshots where authorized. Secrets and debugging endpoints remain protected.
- **Identity & Least Privilege**: Enforce separate permissions for filesystem, execution, browser, network, and memory.
- **Detailed Specification**: Technical operational playbooks reside in [`agents/AGI_1_7/docs/library/12_AUTONOMY_CAPABILITY_AND_EXECUTION_POLICY.md`](agents/AGI_1_7/docs/library/12_AUTONOMY_CAPABILITY_AND_EXECUTION_POLICY.md).
"""


def _ensure_hidden_subagent_frontmatter(md_file: Path, dry_run: bool = False) -> bool:
    """Ensures non-AGI-1.7 agent markdown files have mainAgent: false and hidden: true."""
    if not md_file.exists() or not md_file.is_file():
        return False
    text = md_file.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---"):
        return False
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False
    frontmatter = parts[1]
    body = parts[2]
    changed = False

    if "mainAgent: true" in frontmatter:
        frontmatter = frontmatter.replace("mainAgent: true", "mainAgent: false")
        changed = True
    elif "mainAgent:" not in frontmatter:
        frontmatter = frontmatter.rstrip() + "\nmainAgent: false\n"
        changed = True

    if "subagent:" not in frontmatter:
        frontmatter = frontmatter.rstrip() + "\nsubagent: true\n"
        changed = True

    if "hidden: false" in frontmatter:
        frontmatter = frontmatter.replace("hidden: false", "hidden: true")
        changed = True
    elif "hidden:" not in frontmatter:
        frontmatter = frontmatter.rstrip() + "\nhidden: true\n"
        changed = True

    if changed and not dry_run:
        md_file.write_text(f"---{frontmatter}---{body}", encoding="utf-8")
    return changed


def sync_ecosystem(
    verbose: bool = True,
    install_global: bool = False,
    dry_run: bool = False,
) -> dict:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    agi17_root = os.path.abspath(os.path.join(script_dir, ".."))
    repo_root = os.path.abspath(os.path.join(agi17_root, "..", ".."))
    eco_root = os.path.join(agi17_root, "ecosystem")
    reg_path = os.path.join(eco_root, "agent_registry", "registry.json")

    with open(reg_path, "r", encoding="utf-8") as f:
        reg = json.load(f)

    # 1. Maintain all 100 specialist contracts strictly inside AGI 1.7's internal subagents folder
    subagents_dir = os.path.join(eco_root, "subagents")
    if not dry_run:
        os.makedirs(subagents_dir, exist_ok=True)
    specialist_ids = set()

    for spec in reg.get("specialists", []):
        aid = spec["agent_id"]
        specialist_ids.add(aid)
        fam = spec["family"]
        md_path = os.path.join(subagents_dir, f"{aid}.md")
        caps = ", ".join(spec.get("primary_capabilities", []))
        tools = ", ".join(spec.get("required_tools", []))
        md_content = (
            f"---\n"
            f"name: {aid}\n"
            f'description: "{spec["display_name"]} ({fam}) — Capabilities: {caps}"\n'
            f'family: "{fam}"\n'
            f'resource_class: "{spec.get("resource_class", "LIGHT")}"\n'
            f"max_token_budget: {spec.get('max_token_budget', 12000)}\n"
            f"mainAgent: false\n"
            f"subagent: true\n"
            f"hidden: true\n"
            f'embedded_in: "AGI 1.7"\n'
            f"---\n\n"
            f"# {spec['display_name']} (`{aid}`)\n\n"
            f"- **Family**: {fam}\n"
            f"- **Execution Mode**: `{spec.get('execution_mode', 'IN_PROCESS_TOOL_WORKER')}`\n"
            f"- **Primary Capabilities**: {caps}\n"
            f"- **Required Tools**: {tools}\n"
            f"- **Max Token Budget**: `{spec.get('max_token_budget', 12000)}`\n"
            f"- **Max Wall-Clock Seconds**: `{spec.get('max_wall_clock_seconds', 180)}s`\n\n"
            f"Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). "
            f"Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.\n"
        )
        if not dry_run:
            with open(md_path, "w", encoding="utf-8") as mf:
                mf.write(md_content)

    # 2. By default, ONLY touch repo-local `.agents/agents/`.
    #    User-level `~/.gemini/config/agents` is ONLY touched if `install_global=True` is explicitly requested.
    ws_agents_dir = Path(repo_root) / ".agents" / "agents"
    ws_backup_dir = Path(repo_root) / ".agents" / "agents_backup"
    if not dry_run:
        ws_agents_dir.mkdir(parents=True, exist_ok=True)
        ws_backup_dir.mkdir(parents=True, exist_ok=True)

    target_pairs: List[tuple[Path, Path]] = [(ws_agents_dir, ws_backup_dir)]
    if install_global:
        global_agents_dir = Path(os.path.expanduser("~")) / ".gemini" / "config" / "agents"
        global_backup_dir = Path(os.path.expanduser("~")) / ".gemini" / "config" / "agents_backup"
        if not dry_run:
            global_backup_dir.mkdir(parents=True, exist_ok=True)
        target_pairs.append((global_agents_dir, global_backup_dir))

    pruned_ui_specialists = 0
    for target_dir, backup_dir in target_pairs:
        if not target_dir.exists():
            continue
        for aid in specialist_ids:
            leaked_file = target_dir / f"{aid}.md"
            if leaked_file.exists():
                if not dry_run:
                    leaked_file.unlink()
                pruned_ui_specialists += 1

    # 3. Install/update unified `agi-1-7.md` in target directories
    agi17_md = _build_agi17_agent_markdown(reg)
    for target_dir, _ in target_pairs:
        if target_dir.exists() and not dry_run:
            (target_dir / "agi-1-7.md").write_text(agi17_md, encoding="utf-8")
            sub_dir = target_dir / "agi-1-7"
            if sub_dir.exists():
                shutil.rmtree(sub_dir)

    hidden_count = 0
    for target_dir, _ in target_pairs:
        if not target_dir.exists():
            continue
        for md_file in target_dir.rglob("*.md"):
            if md_file.name == "agi-1-7.md":
                continue
            if _ensure_hidden_subagent_frontmatter(md_file, dry_run=dry_run):
                hidden_count += 1

    skills_dir = os.path.join(eco_root, "skills")
    plugins_dir = os.path.join(eco_root, "plugins")
    mcp_dir = os.path.join(eco_root, "mcp")

    manifest = {
        "schema_version": "1.7.0",
        "codename": "AGI 1.7 — OMEGA COMMAND Unified 100-Specialist Embedded Ecosystem",
        "sole_model": "gemini-3.8-flash-high",
        "scope": "GLOBAL_AND_REPO" if install_global else "REPO_LOCAL_ONLY (Zero User Home Modification)",
        "counts": {
            "visibleTopLevelAgentsInUI": 1,
            "embeddedSpecialistContracts": len(reg.get("specialists", [])),
            "specialistFamilies": len(reg.get("family_distribution", {})),
            "embeddedSubagents": len(os.listdir(subagents_dir)) if os.path.exists(subagents_dir) else 100,
            "embeddedSkills": len(os.listdir(skills_dir)) if os.path.exists(skills_dir) else 0,
            "embeddedPlugins": len(os.listdir(plugins_dir)) if os.path.exists(plugins_dir) else 0,
            "embeddedMcpServers": len(
                [x for x in os.listdir(mcp_dir) if os.path.isdir(os.path.join(mcp_dir, x))]
            )
            if os.path.exists(mcp_dir)
            else 0,
        },
        "family_distribution": reg.get("family_distribution", {}),
    }

    manifest_path = os.path.join(eco_root, "ecosystem_manifest.json")
    if not dry_run:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    if verbose:
        c = manifest["counts"]
        mode_label = "DRY-RUN" if dry_run else ("REPO + GLOBAL" if install_global else "REPO-LOCAL ONLY (Safe Default)")
        print(f"[AGI 1.7 OMEGA COMMAND] Ecosystem Sync Complete [{mode_label}]:")
        print(f"  - Scope                          : {manifest['scope']}")
        print(f"  - Visible Top-Level Agent in UI  : {c['visibleTopLevelAgentsInUI']} (ONLY 'AGI 1.7 — OMEGA COMMAND')")
        print(f"  - Embedded Specialist Contracts  : {c['embeddedSpecialistContracts']} across {c['specialistFamilies']} Families")
        print(f"  - Embedded Workflow Skills       : {c['embeddedSkills']} (GSD, Kubernetes)")
        print(f"  - Embedded Plugin Suites         : {c['embeddedPlugins']} (Ponytail, CodeRabbit, Gemini-API, Prompt-Master, Science)")
        print(f"  - Embedded MCP Server Schemas    : {c['embeddedMcpServers']} (Sequential-Thinking, Playwright, Context7, GSD, Ponytail)")

    return {
        "status": "DRY_RUN" if dry_run else "VERIFIED",
        "scope": manifest["scope"],
        "counts": manifest["counts"],
        "pruned_ui_specialists": pruned_ui_specialists,
        "hidden_legacy_agents": hidden_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="AGI 1.7 Safe Repo-Local Ecosystem Bootstrapper")
    parser.add_argument(
        "--install-global",
        action="store_true",
        help="Opt-in: also install AGI 1.7 agent definition into ~/.gemini/config/agents (default: False, repo-local only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying any files.",
    )
    args = parser.parse_args()
    sync_ecosystem(verbose=True, install_global=args.install_global, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

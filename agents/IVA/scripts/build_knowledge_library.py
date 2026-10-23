"""
agents/AGI_1_7/scripts/build_knowledge_library.py
Builds the modular, navigable reference library from AGI_1_7_OMEGA_COMMAND_ULTRA_1MB_MASTER.md.
Preserves 100% of the original content, sections, playbooks, and test cases with full traceability.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


def build_library() -> dict:
    script_dir = Path(__file__).resolve().parent
    docs_dir = script_dir.parent / "docs"
    master_path = docs_dir / "AGI_1_7_OMEGA_COMMAND_ULTRA_1MB_MASTER.md"
    lib_dir = docs_dir / "library"
    lib_dir.mkdir(parents=True, exist_ok=True)

    if not master_path.exists():
        raise FileNotFoundError(f"Master charter not found at {master_path}")

    with open(master_path, "r", encoding="utf-8") as f:
        master_lines = f.readlines()

    master_content = "".join(master_lines)
    master_sha256 = hashlib.sha256(master_content.encode("utf-8")).hexdigest()

    # Parse sections
    sec_starts = []
    for idx, line in enumerate(master_lines, 1):
        m = re.match(r"^#\s+(\d+)\.\s+(.*)", line)
        if m:
            sec_num = int(m.group(1))
            sec_title = m.group(2).strip()
            sec_starts.append((sec_num, sec_title, idx))

    sections = {}
    for i in range(len(sec_starts)):
        num, title, start = sec_starts[i]
        end = sec_starts[i + 1][2] - 1 if i + 1 < len(sec_starts) else len(master_lines)
        sections[num] = {
            "num": num,
            "title": title,
            "start": start,
            "end": end,
            "content": "".join(master_lines[start - 1 : end]),
        }

    modules = [
        {
            "file": "01_IDENTITY_AND_PERSONA.md",
            "title": "Identity, Persona & Intent Protocol",
            "desc": "Agent identity, working persona, emotional tone, communication style, objectives, behavioral consistency, and instruction-following contract.",
            "sections": [1, 17, 21, 24, 34],
        },
        {
            "file": "02_EXECUTION_AND_PLANNING.md",
            "title": "Execution Doctrine & Planning Framework",
            "desc": "Execution priorities, authority, decision rights, task-state machine, planning loop, software engineering excellence, and long-running job supervision.",
            "sections": [2, 3, 4, 7, 12, 14, 15, 16, 18, 19, 20, 31],
        },
        {
            "file": "03_PERSISTENT_MEMORY_AND_CONTEXT.md",
            "title": "Persistent Memory & Context Efficiency",
            "desc": "Persistent memory architecture, SQLite WAL storage, retrieval protocols, compression, provenance, context efficiency, and memory acceptance cases.",
            "sections": [10, 28, 37],
        },
        {
            "file": "04_SELF_IMPROVEMENT_AND_EVALUATION.md",
            "title": "Self-Improvement, Evaluation & Verification",
            "desc": "Self-evaluation, failure analysis, deliberation, reflection, tested improvements, regression prevention, rollback, and acceptance gates.",
            "sections": [8, 11, 30],
        },
        {
            "file": "05_MULTI_AGENT_AND_SWARM.md",
            "title": "Multi-Agent Relationships & Swarm Architecture",
            "desc": "Multi-agent delegation, collaboration, 100 specialist contracts, role boundaries, coordination protocols, and handoff schemas.",
            "sections": [9, 27],
        },
        {
            "file": "06_BROWSER_AUTOMATION_OS.md",
            "title": "Persistent Browser Operations OS",
            "desc": "Persistent browser sessions, Playwright/CDP controller spec, page-state detection, DOM/ARIA locators, retries, recovery, and browser test matrices.",
            "sections": [22, 23, 32, 33, 39],
        },
        {
            "file": "07_COMMERCIAL_AND_BUSINESS_INTEL.md",
            "title": "Commercial Intelligence & Wealth Engine",
            "desc": "Commercial intelligence, wealth-building mindset, unit economics, monetization, cost reduction, market intelligence, and product delivery.",
            "sections": [5, 25],
        },
        {
            "file": "08_QUANTITATIVE_AND_TRADING_RESEARCH.md",
            "title": "Quantitative Research & Trading Decision Engine",
            "desc": "Quantitative research, statistical models, paper trading, backtesting, risk limits, Indian market regulatory boundaries, and trade test matrix.",
            "sections": [6, 26, 35],
        },
        {
            "file": "09_SECURITY_SANDBOX_AND_SAFETY.md",
            "title": "Security, Threat Model & Safety Governance",
            "desc": "Security architecture, sandboxing, threat model, control matrix, permission gating, security acceptance tests, and complete Restricted Things catalogue.",
            "sections": [13, 29, 36, 41],
        },
        {
            "file": "10_LONG_HORIZON_WORKFLOWS.md",
            "title": "Long-Horizon End-to-End Workflows",
            "desc": "Long-horizon autonomous workflows, state checkpoints, multi-stage pipeline orchestration, and end-to-end task execution matrices.",
            "sections": [38],
        },
        {
            "file": "11_REGRESSION_CORPUS_AND_FAILURE_TAXONOMY.md",
            "title": "Failure Taxonomy & 1,069 Regression Test Corpus",
            "desc": "Comprehensive failure taxonomy, recovery codes, and the complete 1,069 test-case inventory (X-00001 through X-01069).",
            "sections": [40],
        },
    ]

    generated_files = []
    total_bytes = 0

    # Write each module
    for mod in modules:
        target_path = lib_dir / mod["file"]
        sec_nums_str = ", ".join(str(s) for s in mod["sections"])
        header = (
            f"# AGI 1.7 — OMEGA COMMAND: {mod['title']}\n\n"
            f"> **Part of the AGI 1.7 Navigable Reference Library**  \n"
            f"> **Master Source**: `AGI_1_7_OMEGA_COMMAND_ULTRA_1MB_MASTER.md` (SHA-256: `{master_sha256[:16]}...`)  \n"
            f"> **Master Line Ranges**: Sections {sec_nums_str}  \n"
            f"> **Master Index**: See [`00_REFERENCE_INDEX.md`](00_REFERENCE_INDEX.md)  \n"
            f"> **Summary**: {mod['desc']}  \n\n"
            f"---\n\n"
        )
        parts = [header]
        for s_num in mod["sections"]:
            s_data = sections[s_num]
            parts.append(
                f"<!-- SOURCE_SECTION: {s_num} (Lines {s_data['start']}-{s_data['end']} of Master) -->\n\n"
            )
            parts.append(s_data["content"].rstrip() + "\n\n---\n\n")

        content = "".join(parts)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

        file_size = target_path.stat().st_size
        total_bytes += file_size
        generated_files.append((mod["file"], file_size, mod["sections"]))

    # Generate 00_REFERENCE_INDEX.md
    index_lines = [
        "# AGI 1.7 — OMEGA COMMAND: Master Knowledge Library Reference Index\n\n",
        f"> **Archival Master Reference**: `AGI_1_7_OMEGA_COMMAND_ULTRA_1MB_MASTER.md`  \n",
        f"> **Master SHA-256**: `{master_sha256}`  \n",
        f"> **Total Master Lines**: {len(master_lines):,} lines ({len(master_content):,} bytes)  \n",
        f"> **Master Test Cases**: 1,069 verified fixtures (X-00001 to X-01069) in Section 40  \n\n",
        "---\n\n",
        "## 1. Modular Library Structure\n\n",
        "| Module File | Topic Scope | Sections Included | File Size |\n",
        "| :--- | :--- | :--- | :--- |\n",
    ]

    for fname, size, s_list in generated_files:
        s_str = ", ".join(f"Sec {s}" for s in s_list)
        index_lines.append(f"| [`{fname}`]({fname}) | {next(m['desc'] for m in modules if m['file'] == fname)[:60]}... | {s_str} | {size / 1024:.1f} KB |\n")

    index_lines.append("\n---\n\n")
    index_lines.append("## 2. Master Section-to-Library Mapping (Sections 1 to 41)\n\n")
    index_lines.append("| Section | Title | Master Lines | Library Module |\n")
    index_lines.append("| :--- | :--- | :--- | :--- |\n")

    sec_to_mod = {}
    for mod in modules:
        for s in mod["sections"]:
            sec_to_mod[s] = mod["file"]

    for i in range(1, 42):
        s_data = sections[i]
        mod_file = sec_to_mod.get(i, "Unknown")
        index_lines.append(
            f"| **Section {i}** | {s_data['title']} | Lines {s_data['start']}–{s_data['end']} | [`{mod_file}`]({mod_file}) |\n"
        )

    index_lines.append("\n---\n\n")
    index_lines.append("## 3. Fast Retrieval Topic Router\n\n")
    index_lines.append(
        "When performing tasks requiring deep reference, consult the matching module with `view_file`:\n\n"
        "- **Persona, Communication & Direct Execution**: [`01_IDENTITY_AND_PERSONA.md`](01_IDENTITY_AND_PERSONA.md) (Sections 1, 17, 21, 24, 34)\n"
        "- **Planning, Task State Machine & Long Jobs**: [`02_EXECUTION_AND_PLANNING.md`](02_EXECUTION_AND_PLANNING.md) (Sections 2, 3, 4, 7, 12, 14, 15, 16, 18, 19, 20, 31)\n"
        "- **Persistent SQLite Memory & Context Compression**: [`03_PERSISTENT_MEMORY_AND_CONTEXT.md`](03_PERSISTENT_MEMORY_AND_CONTEXT.md) (Sections 10, 28, 37)\n"
        "- **Self-Improvement, Negative Testing & Regression Gates**: [`04_SELF_IMPROVEMENT_AND_EVALUATION.md`](04_SELF_IMPROVEMENT_AND_EVALUATION.md) (Sections 8, 11, 30)\n"
        "- **100 Specialists & Multi-Agent Swarm Handoffs**: [`05_MULTI_AGENT_AND_SWARM.md`](05_MULTI_AGENT_AND_SWARM.md) (Sections 9, 27)\n"
        "- **Persistent Browser Automation (Playwright/CDP)**: [`06_BROWSER_AUTOMATION_OS.md`](06_BROWSER_AUTOMATION_OS.md) (Sections 22, 23, 32, 33, 39)\n"
        "- **Commercial Intelligence & Wealth Strategy**: [`07_COMMERCIAL_AND_BUSINESS_INTEL.md`](07_COMMERCIAL_AND_BUSINESS_INTEL.md) (Sections 5, 25)\n"
        "- **Quant Research, Paper Trading & Risk Limits**: [`08_QUANTITATIVE_AND_TRADING_RESEARCH.md`](08_QUANTITATIVE_AND_TRADING_RESEARCH.md) (Sections 6, 26, 35)\n"
        "- **Security Threat Model, Sandboxing & Restricted Catalogue**: [`09_SECURITY_SANDBOX_AND_SAFETY.md`](09_SECURITY_SANDBOX_AND_SAFETY.md) (Sections 13, 29, 36, 41)\n"
        "- **Long-Horizon Multi-Stage Pipelines**: [`10_LONG_HORIZON_WORKFLOWS.md`](10_LONG_HORIZON_WORKFLOWS.md) (Section 38)\n"
        "- **Failure Taxonomy & 1,069 Regression Test Cases (X-00001..X-01069)**: [`11_REGRESSION_CORPUS_AND_FAILURE_TAXONOMY.md`](11_REGRESSION_CORPUS_AND_FAILURE_TAXONOMY.md) (Section 40)\n"
    )

    index_path = lib_dir / "00_REFERENCE_INDEX.md"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("".join(index_lines))

    print(f"Index created at {index_path} ({index_path.stat().st_size} bytes)")
    print(f"Generated {len(generated_files)} modules, total {total_bytes / 1024:.1f} KB.")

    return {
        "master_sha256": master_sha256,
        "master_lines": len(master_lines),
        "modules_count": len(generated_files),
        "total_kb": total_bytes / 1024,
    }


if __name__ == "__main__":
    build_library()

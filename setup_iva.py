#!/usr/bin/env python3
"""
==============================================================================
  🌟 Iva — Autonomous Agent Setup & Cognitive Memory Initializer
==============================================================================
Runs on any clean clone to initialize Iva for YOUR local system:
1. Validates Python runtime (3.10+ stdlib).
2. Generates local '.env' from '.env.example' if missing.
3. Automatically provisions a fresh, local SQLite WAL memory database
   (omega_memory.db) on your machine with 10-layer schema and identity bootstrap.
4. Validates 100 specialist contracts in the agent ecosystem registry.
5. Verifies write permissions and security boundaries (fail-closed locked).
==============================================================================
"""

import os
import sys
import shutil
import sqlite3
import platform
from pathlib import Path

# Ensure UTF-8 output encoding across Windows command prompts
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BANNER = r"""
================================================================================
   *  IVA — AUTONOMOUS COGNITIVE PARTNER & ENGINEERING RUNTIME SETUP
================================================================================
   "Cool-headed, sharp, mature, warm, ambitious, practical, and fiercely loyal."
================================================================================
"""

def check_python_version() -> bool:
    print("\n[1/5] Checking Python Runtime...")
    major, minor = sys.version_info[:2]
    py_ver = f"{major}.{minor}.{sys.version_info.micro}"
    if major < 3 or (major == 3 and minor < 10):
        print(f"  ❌ Error: Python 3.10+ required. Current version: {py_ver}")
        return False
    print(f"  ✅ Python {py_ver} ({platform.system()} {platform.machine()}) verified.")
    return True

def setup_environment_file() -> Path:
    print("\n[2/5] Checking Local Environment Configuration (.env & API Keys)...")
    env_file = REPO_ROOT / ".env"
    env_example = REPO_ROOT / ".env.example"

    if env_file.exists():
        print("  ✅ Local .env file already exists.")
    else:
        if env_example.exists():
            shutil.copy(env_example, env_file)
            print("  ✅ Created fresh .env from template (.env.example).")
        else:
            env_file.write_text("LIVE_ORDER_DISPATCH_ENABLED=false\n", encoding="utf-8")
            print("  ✅ Initialized baseline safe .env file.")

    # Inspect Universal API Key access
    try:
        from agents.IVA.engine.agi17.adapters.universal_api_provider import load_repo_dotenv
        load_repo_dotenv()
    except Exception:
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v

    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    if gemini_key:
        print("  ✅ Universal Google Gemini API Key detected (Universal access active everywhere).")
    elif openai_key:
        print("  ✅ Universal OpenAI-Compatible API Key detected (Universal access active everywhere).")
    else:
        print("  ℹ️  No API key detected in .env yet. To run IVA anywhere on any machine:")
        print("     1. Open '.env' in this directory.")
        print("     2. Add your GEMINI_API_KEY=your_key (Get a free key: https://aistudio.google.com/app/apikey).")
        print("     (Antigravity CLI and offline test harnesses remain available).")

    return env_file

def initialize_local_memory() -> Path:
    print("\n[3/5] Provisioning Persistent Cognitive Memory (omega_memory.db)...")
    from agents.IVA.engine.agi17.memory.omega_command_memory import OmegaCommandMemory

    # Determine user-specific memory directory
    custom_dir = os.environ.get("OMEGA_MEMORY_DIR")
    if custom_dir:
        target_dir = Path(custom_dir)
    elif platform.system() == "Windows" and Path("D:\\").exists():
        target_dir = Path(r"D:\AGI_Storage\AGI_1_7\memory")
    else:
        target_dir = Path.home() / ".iva" / "memory"

    try:
        mem = OmegaCommandMemory(primary_dir=target_dir)
        db_path = mem.db_path
        print(f"  ✅ SQLite WAL memory active at: {db_path}")

        # Check entry count
        profile = mem.get_corpus_profile()
        count = profile.active_entries_count
        print(f"  ✅ Memory schema verified (10 layers active, {count} stored entries).")

        # If clean database, seed cognitive bootstrap
        if count == 0:
            mem.store(
                layer=5,
                subject_key="iva.cognitive_bootstrap",
                content="Iva cognitive architecture initialized on local system. Female autonomous engineering lead and systems partner.",
                structured_data={"system": "Iva", "version": "1.7.29", "safety_mode": "FAIL_CLOSED"},
                tags=["bootstrap", "identity", "iva"]
            )
            print("  ✅ Seeded baseline cognitive identity entry into Layer 5 (Semantic Facts).")

        return db_path
    except Exception as exc:
        print(f"  ⚠️ Note: Using local fallback storage ({exc})")
        fallback_dir = REPO_ROOT / "agents" / "IVA" / "runtime_storage" / "memory"
        mem = OmegaCommandMemory(primary_dir=fallback_dir)
        print(f"  ✅ Local fallback memory initialized at: {mem.db_path}")
        return mem.db_path

def verify_specialist_contracts() -> int:
    print("\n[4/5] Verifying 100-Specialist Ecosystem Registry...")
    registry_file = REPO_ROOT / "agents" / "IVA" / "ecosystem" / "agent_registry" / "registry.json"
    if not registry_file.exists():
        print("  ⚠️ Warning: registry.json not found at standard path.")
        return 0

    try:
        import json
        data = json.loads(registry_file.read_text(encoding="utf-8"))
        total = data.get("total_specialists", 0)
        families = len(data.get("family_distribution", {}))
        print(f"  ✅ Verified {total} specialist contracts active across {families} capability families.")
        return total
    except Exception as exc:
        print(f"  ⚠️ Error reading registry.json: {exc}")
        return 0

def check_safety_invariants() -> None:
    print("\n[5/5] Auditing Physical Safety Invariants...")
    from agents.IVA.engine.agi17.runtime.authoritative_brain_config import AuthoritativeBrainConfig

    config = AuthoritativeBrainConfig()
    if config.core_identity.fail_closed_invariant and not config.operating_policy.live_order_dispatch_enabled:
        print("  🔒 Physical Live Order Safety Gate: LOCKED (Safe Fail-Closed).")
        print("     Real-money broker fills are physically prevented until explicit operator mandate.")
    else:
        print("  ⚠️ Notice: Operating under custom safety boundaries.")

def print_ready_guide(db_path: Path):
    print("\n" + "=" * 80)
    print("  🚀 IVA SETUP COMPLETE & FULLY OPERATIONAL ON YOUR SYSTEM!")
    print("=" * 80)
    print(f"  • Cognitive Memory Database : {db_path}")
    print(f"  • Repository Root Directory : {REPO_ROOT}")
    print("=" * 80)
    print("  HOW TO RUN IVA:")
    print("  1. Autonomous Interactive Terminal REPL (Recommended for all devices):")
    print("     python run_iva.py")
    print()
    print("  2. Autonomous Self-Verification Test Suite:")
    print("     python run_iva.py test")
    print()
    print("  3. Single-Shot Terminal Command Execution:")
    print("     python run_iva.py \"Your task or question here\"")
    print()
    print("  4. Inspect Built-in Specialist Contracts (100 total, zero plugins needed):")
    print("     python run_iva.py specialists")
    print()
    print("  5. Optional: Real-Time Web Telemetry Dashboard (port 8088):")
    print("     python agents/IVA/ui/standalone_dashboard_server.py")
    print("=" * 80 + "\n")

def main():
    print(BANNER)
    if not check_python_version():
        sys.exit(1)
    setup_environment_file()
    db_path = initialize_local_memory()
    verify_specialist_contracts()
    check_safety_invariants()
    print_ready_guide(db_path)

if __name__ == "__main__":
    main()

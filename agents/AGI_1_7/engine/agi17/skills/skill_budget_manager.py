"""Skill Budget & On-Demand Reinstatement Manager for AGI 1.7 OMEGA COMMAND.

Enables dynamic budgeting of Antigravity skills to maintain minimal token overhead (~20k tokens saved)
while preserving the ability to reinstate any vaulted skill on demand.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Dict, List, Optional


SKILLS_DIR = Path(str(Path.home() / ".agents"\skills")
VAULT_DIR = Path(str(Path.home() / ".agents"\skills_vault")
CATALOG_FILE = Path(str(Path.home() / ".agents"\skills_budget_catalog.json")


class SkillBudgetManager:
    """Manages active vs vaulted skills for token budget optimization."""

    def __init__(self, skills_dir: Optional[Path] = None, vault_dir: Optional[Path] = None):
        self.skills_dir = skills_dir or SKILLS_DIR
        self.vault_dir = vault_dir or VAULT_DIR
        self.catalog_file = CATALOG_FILE
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.vault_dir.mkdir(parents=True, exist_ok=True)

    def get_status(self) -> Dict[str, Any]:
        active = sorted([d.name for d in self.skills_dir.iterdir() if d.is_dir()])
        vaulted = sorted([d.name for d in self.vault_dir.iterdir() if d.is_dir()])
        return {
            "active_count": len(active),
            "vaulted_count": len(vaulted),
            "estimated_token_savings": len(vaulted) * 10,
            "active_skills": active,
        }

    def reinstate_skill(self, skill_name: str) -> bool:
        """Reinstates a skill from the vault to active status."""
        source = self.vault_dir / skill_name
        if not source.exists() or not source.is_dir():
            return False
        dest = self.skills_dir / skill_name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(source), str(dest))
        self._sync_catalog()
        return True

    def vault_skill(self, skill_name: str) -> bool:
        """Moves an active skill into the vault to reduce token consumption."""
        source = self.skills_dir / skill_name
        if not source.exists() or not source.is_dir():
            return False
        dest = self.vault_dir / skill_name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(source), str(dest))
        self._sync_catalog()
        return True

    def search_vault(self, query: str) -> List[str]:
        """Searches available vaulted skills by substring query."""
        q = query.lower()
        results = []
        for d in self.vault_dir.iterdir():
            if d.is_dir() and q in d.name.lower():
                results.append(d.name)
        return sorted(results)

    def _sync_catalog(self) -> None:
        active = sorted([d.name for d in self.skills_dir.iterdir() if d.is_dir()])
        vaulted = sorted([d.name for d in self.vault_dir.iterdir() if d.is_dir()])
        catalog = {
            "active_skills": active,
            "vaulted_skills": vaulted,
            "total_active": len(active),
            "total_vaulted": len(vaulted),
            "vault_path": str(self.vault_dir),
        }
        self.catalog_file.write_text(json.dumps(catalog, indent=2), encoding="utf-8")


if __name__ == "__main__":
    mgr = SkillBudgetManager()
    status = mgr.get_status()
    print(f"Active Skills: {status['active_count']}")
    print(f"Vaulted Skills: {status['vaulted_count']}")
    print(f"Estimated Token Savings: ~{status['estimated_token_savings']} tokens/turn")

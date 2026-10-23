"""
engine/agi17/task_control/checkpoint_manager.py
AGI 1.7 OMEGA COMMAND — Durable Checkpoint & Side-Effect Recovery Manager

Saves and verifies SHA-256 checksummed task checkpoints on disk and in the task store.
Before resuming an interrupted step, verifies whether external side effects (e.g., artifacts)
already completed so completed work is never silently overwritten or duplicated.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class CheckpointManager:
    """Manages versioned, SHA-256 verified task checkpoints."""

    def __init__(
        self,
        checkpoint_dir: str | Path = r"D:\AGI_Storage\AGI_1_7\checkpoints",
        checkpoints_dir: Optional[str | Path] = None,
        task_store: Optional[Any] = None,
    ):
        self.task_store = task_store
        target = str(checkpoints_dir if checkpoints_dir is not None else checkpoint_dir)
        self.checkpoint_dir = self._resolve_dir(target)

    def _resolve_dir(self, preferred: str) -> str:
        try:
            os.makedirs(preferred, exist_ok=True)
            return preferred
        except Exception:
            fb = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "local_fallback_storage", "checkpoints")
            )
            os.makedirs(fb, exist_ok=True)
            return fb

    def save_checkpoint(
        self,
        task_id: str,
        step_index: int,
        completed_steps: Optional[List[str]] = None,
        state_payload: Optional[Dict[str, Any]] = None,
        artifact_paths: Optional[List[str]] = None,
        completed_side_effects: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        verified_artifacts = {}
        for p in artifact_paths or []:
            if p and os.path.exists(p) and os.path.isfile(p):
                try:
                    with open(p, "rb") as f:
                        verified_artifacts[str(p)] = {
                            "size_bytes": os.path.getsize(p),
                            "sha256": hashlib.sha256(f.read()).hexdigest(),
                        }
                except Exception:
                    pass

        steps = list(completed_steps or completed_side_effects or [])
        chk_id = f"CHK-{task_id}-S{step_index}-{int(now * 1000)}"
        chk_path = os.path.join(self.checkpoint_dir, f"chk_{task_id}.json")

        body: Dict[str, Any] = {
            "checkpoint_id": chk_id,
            "checkpoint_path": chk_path,
            "task_id": task_id,
            "step_index": step_index,
            "completed_steps": steps,
            "completed_side_effects": steps,
            "state_payload": state_payload or {},
            "verified_artifacts": verified_artifacts,
            "timestamp": now,
        }
        canonical = json.dumps(
            {k: v for k, v in body.items() if k != "checkpoint_sha256"},
            sort_keys=True,
        ).encode("utf-8")
        chk_hash = hashlib.sha256(canonical).hexdigest()
        body["checkpoint_sha256"] = chk_hash

        tmp_path = chk_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(body, f, indent=2)
        os.replace(tmp_path, chk_path)

        if self.task_store:
            self.task_store.update_task_fields(
                task_id,
                checkpoint_json=body,
                artifact_path=chk_path,
            )

        return body

    def write_checkpoint(
        self,
        *,
        task_id: str,
        step_index: int,
        state_payload: Dict[str, Any],
        completed_side_effects: Optional[List[str]] = None,
        artifact_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return self.save_checkpoint(
            task_id=task_id,
            step_index=step_index,
            completed_steps=completed_side_effects,
            state_payload=state_payload,
            artifact_paths=artifact_paths,
            completed_side_effects=completed_side_effects,
        )

    def load_checkpoint(self, task_id_or_path: str | Path) -> Optional[Dict[str, Any]]:
        s_arg = str(task_id_or_path)
        if os.path.exists(s_arg) and os.path.isfile(s_arg):
            chk_path = s_arg
        else:
            chk_path = os.path.join(self.checkpoint_dir, f"chk_{s_arg}.json")

        if not os.path.exists(chk_path):
            if self.task_store:
                t = self.task_store.get_task(s_arg)
                if t and t.get("checkpoint"):
                    return t["checkpoint"]
            return None

        with open(chk_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        stored_hash = data.get("checkpoint_sha256")
        check_copy = {
            k: v
            for k, v in data.items()
            if k not in ("checkpoint_sha256", "side_effects_verified_intact")
        }
        computed_hash = hashlib.sha256(json.dumps(check_copy, sort_keys=True).encode("utf-8")).hexdigest()
        if stored_hash and stored_hash != computed_hash:
            raise ValueError(f"Checkpoint integrity failure for {s_arg}: SHA-256 mismatch")

        data["side_effects_verified_intact"] = self.verify_side_effect_artifacts(data)
        return data

    def load_and_verify(self, path_or_task_id: str | Path) -> Dict[str, Any]:
        loaded = self.load_checkpoint(path_or_task_id)
        if not loaded:
            raise FileNotFoundError(f"Checkpoint not found: {path_or_task_id}")
        return loaded

    @staticmethod
    def verify_side_effect_artifacts(ckpt_data: Dict[str, Any]) -> bool:
        for path, meta in ckpt_data.get("verified_artifacts", {}).items():
            if not os.path.exists(path):
                return False
            with open(path, "rb") as af:
                if hashlib.sha256(af.read()).hexdigest() != meta.get("sha256"):
                    return False
        return True

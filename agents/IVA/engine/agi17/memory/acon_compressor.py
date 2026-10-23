"""AGI 1.7 ACON-Inspired Structural Observation & Context Compressor (`acon_compressor.py`).

Preserves critical execution anchors (task IDs, exit codes, error names, file paths,
SHA-256 digests, and custom identifiers) while compacting both long observations
(> max_chars) and short/medium natural-language sentences via anchor-safe filler
compaction.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
EXIT_CODE_RE = re.compile(r"(?:exit[_\s-]?code|returncode|status)\s*[:=]\s*(-?\d+)", re.IGNORECASE)
FILE_PATH_RE = re.compile(r"(?:[a-zA-Z]:\\[^\s\"',;]+|/[\w.\-/]+\.[\w]+)")
ERROR_NAME_RE = re.compile(r"\b([A-Z][a-zA-Z0-9_]*(?:Error|Exception|Timeout|Failure|Fault))\b")
TASK_ID_RE = re.compile(r"\b(?:TASK|SUBTASK|MISSION|CAMPAIGN|NOTIF|CHK)-[A-Za-z0-9_\-]+\b")


class ACONCompressor:
    """ACON-inspired observation and history compressor preserving critical execution anchors."""

    _PHRASE_COMPACTIONS = (
        ("FastPath mission ", ""),
        ("Hierarchical mission ", ""),
        ("succeeded via ", "-> "),
        ("Executed verified in-process AST & ecosystem inspection for ", "verified "),
        ("Executed domain-targeted AST & static verification for ", "verified "),
        ("Schema contract validated only for task ", "stub "),
        (" in order to ", " to "),
        (" as well as ", " & "),
        (" with respect to ", " wrt "),
        (" for the purpose of ", " for "),
    )

    _FILLER_WORDS_RE = re.compile(
        r"\b(?:the|a|an|that|which|very|really|just|basically|actually|simply)\b\s+",
        re.IGNORECASE,
    )

    @staticmethod
    def compress_observation(
        raw_text: str,
        max_chars: int = 600,
        preserve_identifiers: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        raw_len = len(raw_text)
        raw_est_tokens = max(1, raw_len // 4)

        sha256_hashes = list(dict.fromkeys(SHA256_RE.findall(raw_text)))
        exit_codes = list(dict.fromkeys(EXIT_CODE_RE.findall(raw_text)))
        file_paths = list(dict.fromkeys(FILE_PATH_RE.findall(raw_text)))[:10]
        error_names = list(dict.fromkeys(ERROR_NAME_RE.findall(raw_text)))[:10]
        task_ids = list(dict.fromkeys(TASK_ID_RE.findall(raw_text)))[:10]
        extra_ids = [ident for ident in (preserve_identifiers or []) if ident in raw_text]
        all_anchors = task_ids + exit_codes + error_names + file_paths + sha256_hashes + extra_ids

        if raw_len <= max_chars:
            compacted = re.sub(r"\s+", " ", raw_text).strip()
            for old_phrase, new_phrase in ACONCompressor._PHRASE_COMPACTIONS:
                if old_phrase in compacted:
                    candidate = compacted.replace(old_phrase, new_phrase)
                    if all(a in candidate for a in all_anchors):
                        compacted = candidate
            # Apply general natural-language filler compaction if all anchors remain intact
            filler_stripped = ACONCompressor._FILLER_WORDS_RE.sub("", compacted)
            filler_stripped = re.sub(r"\s+", " ", filler_stripped).strip()
            if filler_stripped and len(filler_stripped) < len(compacted) and all(a in filler_stripped for a in all_anchors):
                compacted = filler_stripped
            compressed_text = compacted
        else:
            lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
            head = lines[:3]
            tail = lines[-4:] if len(lines) > 3 else []
            preserved_parts: List[str] = []
            if task_ids:
                preserved_parts.append(f"tasks={','.join(task_ids[:4])}")
            if exit_codes:
                preserved_parts.append(f"exit_codes={','.join(exit_codes[:3])}")
            if error_names:
                preserved_parts.append(f"errors={','.join(error_names[:4])}")
            if file_paths:
                preserved_parts.append(f"paths={','.join(file_paths[:3])}")
            if sha256_hashes:
                preserved_parts.append(f"sha256={','.join(sha256_hashes[:2])}")
            if extra_ids:
                preserved_parts.append(f"anchors={','.join(extra_ids[:4])}")

            anchor_summary = " | ".join(preserved_parts)
            body = " ... ".join(head + ([f"[{anchor_summary}]"] if anchor_summary else []) + tail)
            if len(body) > max_chars:
                prefix = f"[{anchor_summary}] " if anchor_summary else ""
                remaining = max(60, max_chars - len(prefix))
                half = remaining // 2
                body = prefix + raw_text[:half].strip() + " ... " + raw_text[-half:].strip()
            compressed_text = body

        comp_len = len(compressed_text)
        comp_est_tokens = max(1, comp_len // 4)
        reduction_ratio = round(1.0 - (comp_len / max(1, raw_len)), 4) if raw_len > comp_len else 0.0

        return {
            "compressed_text": compressed_text,
            "raw_chars": raw_len,
            "compressed_chars": comp_len,
            "raw_estimated_tokens": raw_est_tokens,
            "compressed_estimated_tokens": comp_est_tokens,
            "reduction_ratio": reduction_ratio,
            "anchors_preserved": all(a in compressed_text for a in all_anchors),
            "preserved_anchors": {
                "task_ids": task_ids,
                "exit_codes": exit_codes,
                "error_names": error_names,
                "file_paths": file_paths,
                "sha256_hashes": sha256_hashes,
                "extra_identifiers": extra_ids,
            },
        }

    compress = compress_observation


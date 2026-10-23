# AGI 1.7 OMEGA COMMAND — Licensing, Supply-Chain Provenance & Privacy Governance Report (Phase 7)

* **Repository:** `https://github.com/Abhishek200416/AGI-1.7V`
* **Scope:** Root/package licensing audit, third-party component provenance, container image digest pinning, GitHub Actions supply-chain pinning, and model data-handling privacy disclosures.

---

## 1. Root & Package Licensing Status (Release Gate Disclosure)

* **Current Repository State:** Inspection of the repository root and [`pyproject.toml`](../../../pyproject.toml) confirms that **no root `LICENSE` file has been committed yet** and no SPDX license identifier is declared in `pyproject.toml`.
* **Compliance Action Enforced (Mandatory Rule 14 & Phase 7):**
  - Per Phase 7 (*"Do not apply a new license without authorization from the relevant rights holder. If licensing remains unresolved, mark the release blocked from commercial redistribution until the owner approves a compliant plan"*), no license has been unilaterally added.
  - **Commercial Redistribution Status:** **`BLOCKED_PENDING_OWNER_LICENSE_DECISION`**. Before commercial distribution or public PyPI publishing, the repository owner (`Abhishek200416`) must select and commit an explicit license (e.g., `MIT`, `Apache-2.0`, or a proprietary commercial license) and set the corresponding `license = {text = "..."}` field in `pyproject.toml`.

---

## 2. Software Supply-Chain & Component Provenance Inventory

| Component Category | Artifact / Identifier | Origin & Provenance | License / Terms | Usage in AGI 1.7 |
| :--- | :--- | :--- | :--- | :--- |
| **Runtime Language & Stdlib** | Python `>=3.10` Standard Library (`sqlite3`, `unittest`, `ast`, `difflib`, `hashlib`, `subprocess`, `tempfile`, `ctypes`) | Python Software Foundation (`python.org`) | `PSF-2.0` | `100%` of runtime execution (`0` third-party PyPI runtime dependencies in `pyproject.toml`). |
| **Sandbox Container Image** | `python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1` | Docker Official Image (`docker.io/library/python`) | `PSF-2.0` / Debian DFSG | Pinned by immutable SHA-256 digest in [`SandboxPolicy.production()`](../engine/agi17/process_supervision/sandbox_runner.py). Arbitrary cached third-party images are rejected. |
| **GitHub Actions CI** | `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683` (`v4.2.2`), `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065` (`v5.6.0`) | Official GitHub Actions (`github.com/actions`) | `MIT` | Pinned by full 40-char commit SHA with `permissions: contents: read` in [`.github/workflows/agi17-ci.yml`](../../../.github/workflows/agi17-ci.yml). |
| **100 Specialist Contracts** | [`agents/AGI_1_7/ecosystem/agent_registry/registry.json`](../ecosystem/agent_registry/registry.json) & [`specialist_factory.py`](../ecosystem/agent_registry/specialist_factory.py) | First-party authored in repository | Repository Owner (`Abhishek200416`) | Embedded JSON schema contracts across 16 functional families. |
| **Ecosystem Coordination Metadata** | [`ecosystem_coordinator.py`](../ecosystem/agent_registry/ecosystem_coordinator.py) (76 Agency role names, 21 MCP server names, 11 plugin names, 74 skill names) | First-party routing & prompt-railing mapping table; external MCP schemas in `.gemini/antigravity/mcp/` | First-party mapping code; external tools subject to respective vendor terms | Injects Ponytail 7-rung simplicity, Sequential-Thinking, Context7, and CodeRabbit checklists into specialist prompts without redistributing third-party proprietary binaries. |
| **Foundation Model Provider** | `gemini-3.8-flash-high` via Antigravity CLI (`agy.exe v1.3.3`) | Google / Antigravity Runtime | Google Gemini API / Antigravity Terms of Service | Invoked via [`ModelAdapter`](../engine/agi17/adapters/model_adapter.py) under explicit USD cost ceilings. |

---

## 3. Privacy, Data Minimization & Model Data-Transfer Governance

1. **What Data Is Sent to the Model Provider (`ModelAdapter`):**
   - Only the authorized workspace target module, relevant `test_*.py` contract files, and sanitized `unittest` failure tracebacks inside the validated workspace root (`validate_relative_sandbox_path()`) are included in model prompts.
   - Files outside the authorized workspace root, symlinks (`is_symlink()`), and special/device files are strictly rejected before reading or model dispatch (`PathTraversalViolationError`).
2. **Secret & Personal-Path Redaction (`redact_sensitive_text`):**
   - Every prompt, response, sandbox `stdout`/`stderr` stream, and JSON report is scrubbed by [`redact_sensitive_text()`](../engine/agi17/adapters/model_adapter.py), replacing API keys (`AIza...`, `sk-...`, `ghp_...`, `Bearer ...`) with `<REDACTED_SECRET>` and local user home paths with `<USER_HOME>`.
   - Verified automatically on every commit by `test_01_zero_secret_or_local_username_leaks_in_repo` and `test_02_redact_sensitive_text`.
3. **Workspace Isolation & Ephemeral Cleanup:**
   - `DisposableSandboxRunner` copies authorized files into a temporary staging directory mounted read-only (`/input:ro`) inside a `--network none --read-only` container and deletes the staging directory inside a `finally:` block (`cleanup_verified = True`).

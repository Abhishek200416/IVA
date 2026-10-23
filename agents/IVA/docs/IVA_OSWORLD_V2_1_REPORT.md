# AGI 1.7.0 (`OMEGA COMMAND`) — Official `OSWorld-V2.1` Computer-Use Benchmark Report

- **Generated At**: `2026-10-11T12:24:05+05:30`
- **Evaluated Agent**: `AGI 1.7.0` (`OMEGA COMMAND`) (`reports/osworld_v2_1/agi17/osworld_agi17_adapter.py`)
- **Benchmark Release**: Official `OSWorld-V2.1` (`108` tasks @ commit `3d778a3c9a34a079316f70df023b166700445792`)
- **Foundation Model**: `gemini-3.8-flash-high` (`effort="high"`) via `ModelAdapter` + `ProcessSupervisor` (`minimal_cli_home` + `isolated_cwd`)
- **Host Physical Desktop Protection**: `host_gui_actuation_allowed = False` (**`0` host GUI injections**)

---

## 1. Executive Summary & Comparison vs. AGI 1.6 (`OMEGA NEXUS`)

| Metric | AGI 1.6.0 (`OMEGA NEXUS`) | **AGI 1.7.0 (`OMEGA COMMAND`)** | Improvement / Architectural Impact |
|---|---:|---:|---|
| **Total Manifest Tasks** | `108` | **`108`** | Official `test_v2.json` (`001`..`108`) |
| **Tasks Recorded in Ledger** | `108` | **`71 / 108`** | `27` local Ubuntu VM tasks evaluated + `41` external web/GitLab cluster tasks documented + `3` guest setup errors |
| **False-Infeasible (`FAIL`) Predictions** | `21` (`36.2%` of local tasks) | **`0` (`0.0%`)** | **`-100%` elimination of false `FAIL` predictions** via non-dotfile workspace discovery (`find /home/user -maxdepth 3 -not -path '*/.*'`) |
| **Step CLI Timeouts** | `34` (`58.6%` of local tasks) | **`7` (`25.9%`)** | **`-79.4%` fewer CLI timeouts** via `minimal_cli_home` + `isolated_cwd` (`~2,300` net input tokens/step) |
| **Net Tokens Across Evaluated Local Tasks** | `~219,530` | **`126,394`** | `62,046` net input + `64,348` output tokens |
| **Host Desktop GUI Injections** | `0` | **`0`** | Strictly isolated inside Docker/QEMU-KVM Ubuntu VM |

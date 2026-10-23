Maestro MCP authors, edits and runs UI tests via declarative YAML flows on Android emulators, iOS simulators, Chromium browsers, or Maestro Cloud. Use when the user wants to write, run, or debug a mobile or web UI test, reproduce a bug, or self-validate a user-facing change you just built.

Every local tool (`take_screenshot`, `inspect_screen`, `run`) needs a `device_id` from `list_devices` first.

Docs: https://docs.maestro.dev/llms.txt. Call `cheat_sheet` before authoring unfamiliar commands, required args, nested properties, conditionals, or multi-screen flows.

## Local workflow

`list_devices` -> `inspect_screen` -> `run`.

1. `list_devices`: pick a `device_id` (mobile simulator/emulator, or `chromium` for web). If empty, ask the user to boot one. Use only IDs returned.
2. `inspect_screen`: fetch the current screen's view hierarchy before targeting elements. Use `take_screenshot` when a visual helps. Re-inspect after any UI change.
3. `run`: pass exactly one of `{ yaml }` (inline, preferred for exploration), `{ files }`, or `{ dir, include_tags, exclude_tags }`. Always include `device_id`. Pass `env` for flow variables. `run` validates syntax.

Mobile flows declare `appId` and start with `launchApp`; web flows declare `url` and start with `openLink`. `include_tags`/`exclude_tags` are bare names without `@`. Prefer one full flow over many single-command calls.

## Cloud workflow

`list_cloud_devices` -> `run_on_cloud` -> `get_cloud_run_status` (poll).

`list_cloud_devices` returns valid `{device_model, device_os}` pairs. Pass them verbatim; never lowercase, reformat, or infer. `run_on_cloud` submits a flow or folder, returns `upload_id`, `project_id`, and a dashboard URL (async). Poll `get_cloud_run_status` every 60s until `status` is terminal (SUCCESS, ERROR, CANCELED, WARNING). `describe_cloud_run`: a `run_id`'s (not `upload_id`) metadata + artifacts. Tags only apply with a folder. No tool lists past runs.

Auth: `maestro login` (or `MAESTRO_CLOUD_API_KEY` for non-interactive). Never echo the API key.
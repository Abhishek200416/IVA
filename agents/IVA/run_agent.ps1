# AGI 1.7.0 — OMEGA COMMAND PowerShell Launcher
param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ArgsList
)

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$EntryScript = Join-Path $PSScriptRoot "run_agi_17.py"

& $PythonExe $EntryScript @ArgsList
exit $LASTEXITCODE

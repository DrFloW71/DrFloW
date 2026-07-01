$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
git -C $repoRoot config core.hooksPath .githooks
Write-Host "Hooks Git DrFloW actifs : .githooks"

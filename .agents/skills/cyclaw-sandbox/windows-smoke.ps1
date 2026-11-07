# Delegate to the maintained smoke script on PowerShell 5.1 and 7.
param([int]$Port)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
$Script = Join-Path $RepoRoot ".claude/skills/CyClaw-Sandbox/windows-smoke.ps1"
& $Script @PSBoundParameters
exit $LASTEXITCODE

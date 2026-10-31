<#
.SYNOPSIS
    HERMES GUI Stopper for Windows.
.DESCRIPTION
    Safely and gracefully stops the HERMES GUI backend server running on port 8765.
    Protects unrelated third-party processes from termination.
#>

[CmdletBinding()]
param (
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$Help
)

if ($Help) {
    Write-Host "HERMES GUI Stopper" -ForegroundColor Cyan
    Write-Host "Usage: .\scripts\stop_gui.ps1 [-HostAddress 127.0.0.1] [-Port 8765]"
    exit 0
}

$ErrorActionPreference = "Stop"

# Canonical Paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = Split-Path -Parent $ScriptDir
$PythonExe = Join-Path $RepoRoot "venv\Scripts\python.exe"

# 1. Canonical Python Guard
if (-not (Test-Path $PythonExe)) {
    Write-Error "[HERMES FATAL] Canonical Python interpreter not found at: $PythonExe"
    exit 1
}

Write-Host "=== Stopping HERMES GUI Server ===" -ForegroundColor Cyan
Write-Host "Target: http://${HostAddress}:${Port}"

# 2. Invoke launcher stop command
$argsList = @(
    "-m", "core.server.launcher",
    "stop",
    "--host", $HostAddress,
    "--port", $Port
)

Push-Location $RepoRoot
try {
    & $PythonExe $argsList
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Host "Stop helper completed with code: $exitCode" -ForegroundColor Yellow
        exit $exitCode
    }
}
finally {
    Pop-Location
}

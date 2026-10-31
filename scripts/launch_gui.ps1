<#
.SYNOPSIS
    HERMES GUI Launcher for Windows.
.DESCRIPTION
    Launches the HERMES local FastAPI runtime bridge and opens the graphical interface
    in the default browser once the health endpoint is verified.
    Ensures single-instance safety and port-conflict detection.
#>

[CmdletBinding()]
param (
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [switch]$Help
)

if ($Help) {
    Write-Host "HERMES GUI Launcher" -ForegroundColor Cyan
    Write-Host "Usage: .\scripts\launch_gui.ps1 [-HostAddress 127.0.0.1] [-Port 8765] [-NoBrowser]"
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

# Verify Python version strictly
$versionOutput = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $versionOutput.Trim() -ne "3.12") {
    Write-Error "[HERMES FATAL] Interpreter at $PythonExe is not Python 3.12 (Detected: $versionOutput)"
    exit 1
}

Write-Host "=== HERMES Graphical Interface Launcher ===" -ForegroundColor Cyan
Write-Host "Repository: $RepoRoot"
Write-Host "Interpreter: $PythonExe (Python $versionOutput)"
Write-Host "Target: http://${HostAddress}:${Port}"

# 2. Invoke launcher via Python to ensure unified lifecycle and error handling
$argsList = @(
    "-m", "core.server.launcher",
    "launch",
    "--host", $HostAddress,
    "--port", $Port
)

if ($NoBrowser) {
    $argsList += "--no-browser"
}

Push-Location $RepoRoot
try {
    & $PythonExe $argsList
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Host "Launch helper completed with code: $exitCode" -ForegroundColor Yellow
        exit $exitCode
    }
}
finally {
    Pop-Location
}

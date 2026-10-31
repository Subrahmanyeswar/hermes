---
name: powershell-scripting
description: Windows PowerShell and PowerShell 7 scripting for automated developer workflows, process orchestration, and safe filesystem operations.
category: scripting
priority: 2
triggers:
  - powershell
  - powershell script
  - pwsh
  - ps1
  - windows script
  - powershell automation
allowed_tools:
  - fs.read
  - fs.write
  - fs.edit
  - shell.bash
  - search.glob
  - search.grep
---

# Windows PowerShell Scripting & Automation

This skill guides the design, implementation, and verification of robust, production-grade **PowerShell** scripts (`.ps1`) for Windows-first developer workflows, tooling orchestration, and filesystem automation.

---

## 1. Core Architectural Invariants

1. **Strict Error Handling**:
   - Always initialize automated scripts with:
     ```powershell
     $ErrorActionPreference = 'Stop'
     Set-StrictMode -Version Latest
     ```
2. **Native Executable Exit Codes**:
   - PowerShell cmdlets throw on errors, but native executables (`python.exe`, `git.exe`, `npm.cmd`) do **not** trigger terminating errors by default.
   - Always verify `$LASTEXITCODE` immediately after invoking any external executable:
     ```powershell
     & $PythonExe -m pytest tests/ -q
     if ($LASTEXITCODE -ne 0) {
         throw "Pytest execution failed with exit code $LASTEXITCODE"
     }
     ```
3. **Literal Paths vs Wildcard Paths**:
   - Always use `-LiteralPath` rather than `-Path` when inspecting or manipulating files whose names might contain wildcards, brackets (`[]`), or special characters:
     ```powershell
     Get-Item -LiteralPath $TargetFilePath
     Test-Path -LiteralPath $TargetFilePath
     ```
4. **Safe Path Construction**:
   - Never use string concatenation with manual slashes (`$dir + "\" + $file`).
   - Use `Join-Path` or `[System.IO.Path]::Combine()`:
     ```powershell
     $FullFilePath = Join-Path -Path $WorkspaceDir -ChildPath "artifacts\output.json"
     ```
5. **Modern UTF-8 Encoding**:
   - Avoid legacy Windows encoding defaults (Windows-1252 or UTF-16LE).
   - Use `-Encoding utf8NoBOM` (or `-Encoding utf8` in PowerShell Core) when writing text or JSON files:
     ```powershell
     $Content | Set-Content -LiteralPath $Destination -Encoding utf8NoBOM
     ```
6. **No Ambiguous Aliases in Production Scripts**:
   - Never use interactive console aliases (`ls`, `dir`, `cat`, `rm`, `gci`, `select`, `where`).
   - Always write full canonical cmdlet names: `Get-ChildItem`, `Get-Content`, `Remove-Item`, `Select-Object`, `Where-Object`.

---

## 2. Canonical Script Pattern

```powershell
<#
.SYNOPSIS
    Automated build and test orchestration script.
.DESCRIPTION
    Executes test suite using canonical virtual environment and records exit code.
.PARAMETER WorkspaceRoot
    The absolute path to the project root directory.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Container })]
    [string]$WorkspaceRoot,

    [Parameter(Mandatory = $false)]
    [string]$TestSuite = "tests"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$PythonExe = Join-Path -Path $WorkspaceRoot -ChildPath "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Canonical Python interpreter not found at: $PythonExe"
}

Write-Verbose "Using Python interpreter: $PythonExe"

if ($PSCmdlet.ShouldProcess("Run pytest suite '$TestSuite'", "Execute tests")) {
    & $PythonExe -m pytest (Join-Path -Path $WorkspaceRoot -ChildPath $TestSuite) -q
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Test suite failed with exit code $LASTEXITCODE"
        exit $LASTEXITCODE
    }
    Write-Output "Test suite completed successfully."
}
```

---

## 3. Negative Boundaries & Anti-Patterns

- **Do NOT use for Linux Bash scripts**: Route Unix/Bash tasks to `bash-scripting`.
- **Do NOT execute scripts automatically on loading**: Discovery or loading of this skill must never trigger script execution.
- **Do NOT rely on `$?` alone for native executables**: `$?` can evaluate to `$true` even when `$LASTEXITCODE -ne 0`. Always assert `$LASTEXITCODE -eq 0`.
- **Do NOT execute destructive file deletions without verification**: Support `-WhatIf` / `SupportsShouldProcess` for operations modifying or deleting filesystem trees.
- **Do NOT hardcode system-specific root paths**: Derive paths dynamically using `$PSScriptRoot` or explicit mandatory parameters.

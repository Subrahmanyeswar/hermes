<#
.SYNOPSIS
    HERMES 2.x Live Forensic Telemetry Watcher
.DESCRIPTION
    Tails and colorizes structured JSONL mission events in real time from `artifacts/observability/<run_id>/events.jsonl`.
.PARAMETER RunId
    Specific Run ID to monitor (e.g. run_1_74fb3ba4).
.PARAMETER MissionId
    Specific Mission ID to monitor (e.g. m_1a2c5767).
.PARAMETER Follow
    Continuously tail the file as new events arrive (default: $true).
.EXAMPLE
    .\scripts\watch_mission_logs.ps1 -Follow
    .\scripts\watch_mission_logs.ps1 -MissionId m_1a2c5767
#>

param (
    [string]$RunId = "",
    [string]$MissionId = "",
    [string]$Stream = "events",
    [switch]$Latest = $true,
    [switch]$NoFollow = $false,
    [string]$ObservabilityDir = ""
)

$ErrorActionPreference = "Continue"

# Resolve base observability directory
if (-not $ObservabilityDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $repoRoot = Split-Path -Parent $scriptDir
    $ObservabilityDir = Join-Path $repoRoot "artifacts\observability"
}

if (-not (Test-Path $ObservabilityDir)) {
    Write-Host "[!] Observability directory not found: $ObservabilityDir" -ForegroundColor Yellow
    Write-Host "[*] Creating observability directory and waiting for missions..." -ForegroundColor Gray
    New-Item -ItemType Directory -Path $ObservabilityDir -Force | Out-Null
}

# Resolve target run directory
$targetDir = $null

if ($RunId) {
    $cand = Join-Path $ObservabilityDir $RunId
    if (Test-Path $cand) { $targetDir = $cand }
}

if (-not $targetDir -and $MissionId) {
    # Scan subdirectories for matching mission_id in events.jsonl or folder name
    # Prefer directories with actual models.jsonl or larger events.jsonl to avoid empty placeholders
    $runs = Get-ChildItem -Path $ObservabilityDir -Directory
    $candidates = @()
    foreach ($r in $runs) {
        $evPath = Join-Path $r.FullName "events.jsonl"
        if (Test-Path $evPath) {
            $first = Get-Content -Path $evPath -TotalCount 10 -ErrorAction SilentlyContinue
            if ($first -match $MissionId) {
                $evSize = (Get-Item $evPath).Length
                $modelsPath = Join-Path $r.FullName "models.jsonl"
                $modelsSize = if (Test-Path $modelsPath) { (Get-Item $modelsPath).Length } else { 0 }
                $candidates += [PSCustomObject]@{
                    Path = $r.FullName
                    Weight = $modelsSize + $evSize
                    LastWrite = $r.LastWriteTime
                }
            }
        }
    }
    if ($candidates.Count -gt 0) {
        $sorted = $candidates | Sort-Object -Property Weight, LastWrite -Descending
        $targetDir = $sorted[0].Path
    }
}

# If no target specified or found, pick the most recently updated run directory with substantive telemetry
if (-not $targetDir) {
    $runs = Get-ChildItem -Path $ObservabilityDir -Directory | Sort-Object LastWriteTime -Descending
    foreach ($r in $runs) {
        $evPath = Join-Path $r.FullName "events.jsonl"
        if (Test-Path $evPath) {
            $len = (Get-Item $evPath).Length
            if ($len -gt 500) {
                $targetDir = $r.FullName
                break
            }
        }
    }
    if (-not $targetDir -and $runs.Count -gt 0) {
        $targetDir = $runs[0].FullName
    }
}

if (-not $targetDir) {
    Write-Host "[*] No active run directories found in $ObservabilityDir. Waiting for run to start..." -ForegroundColor Cyan
    while (-not $targetDir) {
        Start-Sleep -Milliseconds 500
        $runs = Get-ChildItem -Path $ObservabilityDir -Directory | Sort-Object LastWriteTime -Descending
        if ($runs.Count -gt 0) {
            $targetDir = $runs[0].FullName
            break
        }
    }
}

$streamFileName = if ($Stream.EndsWith(".jsonl")) { $Stream } else { "$Stream.jsonl" }
$targetStreamFile = Join-Path $targetDir $streamFileName
$runName = Split-Path -Leaf $targetDir

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " HERMES 2.x FORENSIC TELEMETRY STREAM ($streamFileName) :: $runName" -ForegroundColor White
Write-Host " Log directory: $targetDir" -ForegroundColor Gray
Write-Host " Active stream: $targetStreamFile" -ForegroundColor Gray
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ("{0,-14} {1,-8} {2,-26} {3}" -f "TIMESTAMP", "SEV", "EVENT_TYPE", "DETAILS") -ForegroundColor DarkGray
Write-Host ("-" * 80) -ForegroundColor DarkGray

function Format-TelemetryLine([string]$jsonStr) {
    if (-not $jsonStr -or -not $jsonStr.Trim()) { return }
    try {
        $evt = $jsonStr | ConvertFrom-Json
    } catch {
        Write-Host $jsonStr -ForegroundColor Gray
        return
    }

    $timeStr = ""
    if ($evt.timestamp_local) {
        try {
            $dt = [DateTime]::Parse($evt.timestamp_local)
            $timeStr = $dt.ToString("HH:mm:ss.fff")
        } catch {
            $timeStr = $evt.timestamp_local.Substring(11, 8)
        }
    } else {
        $timeStr = (Get-Date).ToString("HH:mm:ss.fff")
    }

    $sev = if ($evt.severity) { $evt.severity.ToUpper() } else { "INFO" }
    $et = if ($evt.event_type) { $evt.event_type } else { "EVENT" }

    # Color mapping
    $sevColor = "Green"
    if ($sev -eq "DEBUG") { $sevColor = "DarkGray" }
    elseif ($sev -eq "INFO") { $sevColor = "Cyan" }
    elseif ($sev -eq "WARN" -or $sev -eq "WARNING") { $sevColor = "Yellow" }
    elseif ($sev -eq "ERROR") { $sevColor = "Red" }
    elseif ($sev -eq "CRITICAL") { $sevColor = "Magenta" }

    # Detail line formatting
    $detail = ""
    if ($evt.message) {
        $detail = $evt.message
    }

    if ($evt.tier) {
        $detail = "[Tier $($evt.tier)] $detail"
    }

    if ($evt.duration_ms) {
        $detail += " (dur=$([math]::Round($evt.duration_ms, 1))ms)"
    }

    # Additional contextual indicators
    if ($evt.payload) {
        $p = $evt.payload
        if ($p.provider) {
            $detail += " | Provider=$($p.provider)"
        }
        if ($p.model) {
            $detail += " | Model=$($p.model)"
        }
        if ($p.ttft_ms) {
            $detail += " | ttft=$([math]::Round($p.ttft_ms, 1))ms"
        }
        if ($p.output_tokens) {
            $detail += " | outTokens=$($p.output_tokens)"
        }
        if ($p.tool_call_count) {
            $detail += " | tools=$($p.tool_call_count)"
        }
        if ($p.finish_reason) {
            $detail += " | finish=$($p.finish_reason)"
        }
        if ($p.failure_class) {
            $detail += " | FailureClass=$($p.failure_class)"
        }
        if ($p.circuit_state) {
            $detail += " | Circuit=$($p.circuit_state)"
        }
        if ($p.remaining_wall_time) {
            $detail += " | Budget=$([math]::Round($p.remaining_wall_time, 1))s"
        }
        if ($p.exit_code -ne $null) {
            $detail += " | exit=$($p.exit_code)"
        }
    }

    $formattedHeader = "[{0}] {1,-7} {2,-26}" -f $timeStr, $sev, $et
    Write-Host $formattedHeader -NoNewline -ForegroundColor $sevColor
    Write-Host " $detail" -ForegroundColor White
}

# Wait for stream file to exist
while (-not (Test-Path $targetStreamFile)) {
    Start-Sleep -Milliseconds 200
}

# Tail stream using non-locking FileStream
$fileStream = [System.IO.File]::Open($targetStreamFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
$reader = [System.IO.StreamReader]::new([System.IO.Stream]$fileStream, [System.Text.Encoding]::UTF8)

try {
    # Print existing lines
    while (-not $reader.EndOfStream) {
        $line = $reader.ReadLine()
        Format-TelemetryLine $line
    }

    if (-not $NoFollow) {
        while ($true) {
            $line = $reader.ReadLine()
            if ($line -ne $null) {
                Format-TelemetryLine $line
            } else {
                Start-Sleep -Milliseconds 100
            }
        }
    }
} finally {
    if ($reader) { $reader.Close() }
    if ($fileStream) { $fileStream.Close() }
}

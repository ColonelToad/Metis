# Metis Data Ingestion at System Startup
# Purpose: Run data ingesters on system startup with intelligent scheduling
# Trigger: Windows Task Scheduler (at system startup)
# Features: Partial-run detection via state file, per-ingester retry, log rotation

param([switch]$Force, [int]$Delay = 10)

$ProjectRoot = "C:\Users\legot\Metis"
$ResearchDir = Join-Path $ProjectRoot "research"
$LogDir      = Join-Path $ProjectRoot "logs"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

$Today   = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "ingest_startup_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').log"

function Log { param([string]$Msg); $Msg | Tee-Object -FilePath $LogFile -Append }

# ── Log rotation: keep the 5 most recent startup logs and state files ──────────
function Invoke-LogRotation {
    @("ingest_startup_*.log", "ingest_state_*.json") | ForEach-Object {
        Get-ChildItem -Path $LogDir -Filter $_ -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -Skip 5 |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }
}

Invoke-LogRotation

Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION TRIGGERED ==="

# ── State file: tracks per-ingester completion status for today ────────────────
$StateFile = Join-Path $LogDir "ingest_state_$Today.json"

function Read-State {
    if (Test-Path $StateFile) {
        try { return (Get-Content $StateFile -Raw | ConvertFrom-Json) } catch {}
    }
    # Return a default object with a hashtable-like PSCustomObject
    return [PSCustomObject]@{ date = $Today; ingesters = [PSCustomObject]@{} }
}

function Write-State($state) {
    $state | ConvertTo-Json -Depth 5 | Set-Content $StateFile -Encoding utf8
}

function Get-IngesterStatus($state, [string]$name) {
    $prop = $state.ingesters.PSObject.Properties[$name]
    if ($prop) { return $prop.Value.status } else { return "not_run" }
}

function Set-IngesterStatus($state, [string]$name, [string]$status, [string]$error = "") {
    $entry = [PSCustomObject]@{
        status       = $status
        completed_at = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')
        error        = $error
    }
    # Add or update the property on the ingesters object
    if ($state.ingesters.PSObject.Properties[$name]) {
        $state.ingesters.PSObject.Properties[$name].Value = $entry
    } else {
        $state.ingesters | Add-Member -MemberType NoteProperty -Name $name -Value $entry
    }
    Write-State $state
}

$State = Read-State

# ── Determine which ingesters are scheduled today ─────────────────────────────
$Now           = Get-Date
$IsMonday      = $Now.DayOfWeek -eq [System.DayOfWeek]::Monday
$IsFirstOfMonth = $Now.Day -eq 1

$ScheduledIngesters = [System.Collections.Generic.List[string]]@("daily")
if ($IsMonday)       { $ScheduledIngesters.Add("weekly") }
if ($IsFirstOfMonth) { $ScheduledIngesters.Add("monthly") }

# ── Safeguard: skip if all scheduled ingesters already succeeded today ─────────
if (-not $Force) {
    $allDone = $true
    foreach ($name in $ScheduledIngesters) {
        if ((Get-IngesterStatus $State $name) -ne "success") { $allDone = $false; break }
    }
    if ($allDone -and (Get-IngesterStatus $State "r2_backup") -eq "success") {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] All ingesters completed successfully today. Exiting."
        exit 0
    }
}

# ── System stabilization ───────────────────────────────────────────────────────
function Wait-SystemStability {
    param([int]$MaxWaitSeconds = 300, [int]$CheckIntervalSeconds = 5)
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Waiting for system stability (up to 5 minutes)..."
    $start = Get-Date
    while ((Get-Date) -lt $start.AddSeconds($MaxWaitSeconds)) {
        try {
            $cpu = (Get-WmiObject win32_processor | Measure-Object -Property LoadPercentage -Average).Average
            $mem = Get-WmiObject win32_operatingsystem
            $memPct = 100 - ([math]::Round(($mem.FreePhysicalMemory / $mem.TotalVisibleMemorySize) * 100))
            if ($cpu -lt 30 -and $memPct -lt 70) {
                Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] System stable (CPU: $cpu%, Memory: $memPct%). Proceeding."
                return
            }
        } catch {}
        Start-Sleep -Seconds $CheckIntervalSeconds
    }
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Max wait time reached. Proceeding anyway."
}

Wait-SystemStability

# ── Environment ────────────────────────────────────────────────────────────────
[System.Environment]::SetEnvironmentVariable("METIS_MODE", "REAL", "Process")
[System.Environment]::SetEnvironmentVariable("PYTHONPATH", $ProjectRoot, "Process")

$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
            [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

# ── Run a single ingester with retry ──────────────────────────────────────────
# Returns $true on success, $false if all attempts failed.
function Invoke-Ingester {
    param([string]$Name, [string]$Frequency, [int]$MaxAttempts = 2)

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $label = if ($attempt -gt 1) { " (retry $($attempt-1))" } else { "" }
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting $Name ingester$label..."

        $job = Start-Job -ScriptBlock {
            param($root, $freq)
            Set-Location $root
            $env:PYTHONPATH = $root
            $env:METIS_MODE = "REAL"
            $out = python "research/ops/ingest_wrapper.py" --frequency $freq 2>&1
            # Surface the exit code through the job output stream
            [PSCustomObject]@{ output = $out -join "`n"; exitCode = $LASTEXITCODE }
        } -ArgumentList $ProjectRoot, $Frequency

        $result = Receive-Job -Job $job -Wait
        $jobState = $job.State
        Remove-Job -Job $job

        # Output ingester logs to our log file
        if ($result -and $result.output) { $result.output | Tee-Object -FilePath $LogFile -Append }

        $exitCode = if ($result -and $null -ne $result.exitCode) { $result.exitCode } else { 1 }
        $succeeded = ($jobState -eq 'Completed' -and $exitCode -eq 0)

        if ($succeeded) {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Name ingester succeeded."
            Set-IngesterStatus $script:State $Name.ToLower() "success"
            return $true
        } else {
            $errMsg = "state=$jobState exitCode=$exitCode"
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Name ingester failed ($errMsg)."
            Set-IngesterStatus $script:State $Name.ToLower() "failed" $errMsg
            if ($attempt -lt $MaxAttempts) {
                Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Waiting 5 minutes before retry..."
                Start-Sleep -Seconds 300
            }
        }
    }
    return $false
}

# ── Run each scheduled ingester (skip ones that already succeeded today) ───────
Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Scheduled ingesters: $($ScheduledIngesters -join ', ')"
$anyFailed = $false

foreach ($name in $ScheduledIngesters) {
    if (-not $Force -and (Get-IngesterStatus $State $name) -eq "success") {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $name already succeeded today — skipping."
        continue
    }
    $ok = Invoke-Ingester -Name $name.ToUpper() -Frequency $name
    if (-not $ok) { $anyFailed = $true }
}

# ── R2 backup (only if all ingesters succeeded) ────────────────────────────────
if (-not $anyFailed) {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] All ingesters succeeded. Starting R2 backup..."
    try {
        $backupOut = & python (Join-Path $ResearchDir "ops\r2_auto_backup.py") 2>&1
        $backupOut | Tee-Object -FilePath $LogFile -Append
        if ($LASTEXITCODE -eq 0) {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] R2 backup completed successfully."
            Set-IngesterStatus $State "r2_backup" "success"
        } else {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] R2 backup failed (non-blocking)."
            Set-IngesterStatus $State "r2_backup" "failed" "exitCode=$LASTEXITCODE"
        }
    } catch {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] R2 backup exception (non-blocking): $_"
        Set-IngesterStatus $State "r2_backup" "failed" "$_"
    }
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION AND BACKUP COMPLETED ==="
    exit 0
} else {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION COMPLETED WITH FAILURES ==="
    exit 1
}

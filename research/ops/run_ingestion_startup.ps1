# Metis Data Ingestion at System Startup
# Purpose: Run data ingesters on system startup with intelligent scheduling
# Trigger: Windows Task Scheduler (pwsh.exe at system startup)

param([switch]$Force, [switch]$RedoFailed, [int]$Delay = 10)

$ProjectRoot = "C:\Users\legot\Metis"
$ResearchDir = Join-Path $ProjectRoot "research"
$LogDir      = Join-Path $ProjectRoot "logs"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

$Today   = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "ingest_startup_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').log"

function Log { param([string]$Msg); $Msg | Tee-Object -FilePath $LogFile -Append }

# ── Log rotation ───────────────────────────────────────────────────────────────
function Invoke-LogRotation {
    @("ingest_startup_*.log", "ingest_state_*.json") | ForEach-Object {
        Get-ChildItem -Path $LogDir -Filter $_ -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -Skip 5 |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }
}
Invoke-LogRotation

# ── Single-instance guard ─────────────────────────────────────────────────────
# A previous run killed mid-backup (reboot, sleep) must not let the next boot
# stack a duplicate full pipeline on top of it. Lock older than 6h = stale.
$LockFile = Join-Path $LogDir "ingestion.lock"
$script:WeHoldLock = $false
if (Test-Path $LockFile) {
    $lockAgeH = ((Get-Date) - (Get-Item $LockFile).LastWriteTime).TotalHours
    if ($lockAgeH -lt 6) {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Another ingestion run appears active (lock age $([math]::Round($lockAgeH,1))h < 6h). Exiting."
        exit 0
    }
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Stale ingestion lock found ($([math]::Round($lockAgeH,1))h old) - overriding."
}
Set-Content -Path $LockFile -Value "pid=$PID started=$(Get-Date -Format o)"
$script:WeHoldLock = $true
function Remove-MyLock {
    if ($script:WeHoldLock) {
        Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
        $script:WeHoldLock = $false
    }
}

Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION TRIGGERED ==="
if ($RedoFailed) { Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Running in REDO FAILED mode." }

# ── State file logic ───────────────────────────────────────────────────────────
$StateFile = Join-Path $LogDir "ingest_state_$Today.json"

function Read-State {
    if (Test-Path $StateFile) {
        try { return (Get-Content $StateFile -Raw | ConvertFrom-Json) } catch {}
    }
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
    if ($state.ingesters.PSObject.Properties[$name]) {
        $state.ingesters.PSObject.Properties[$name].Value = $entry
    } else {
        $state.ingesters | Add-Member -MemberType NoteProperty -Name $name -Value $entry
    }
    Write-State $state
}

$State = Read-State

# ── VERY EARLY EXIT ───────────────────────────────────────────────────────────
# User expectation: "check if it ran before running anything" -- this must
# fire before network waits, log spam, or re-queuing. If today's daily
# already succeeded (even if r2_backup hasn't), don't re-queue daily on
# every logon. Failed runs get a 24h cooldown to avoid same-day restart loops.
$EarlyNow = Get-Date
$EarlyIsMonday = $EarlyNow.DayOfWeek -eq [System.DayOfWeek]::Monday
$EarlyIsSunday = $EarlyNow.DayOfWeek -eq [System.DayOfWeek]::Sunday
$EarlyIsFirstOfMonth = $EarlyNow.Day -eq 1
if (-not $Force -and -not $RedoFailed) {
    $lastDaily = $State.ingesters.PSObject.Properties["daily"]
    if ($lastDaily -and $lastDaily.Value.status -eq "success") {
        # Daily already succeeded today -- check if we still need weekly/monthly/r2/prune.
        # needsPrune: Sunday prune is state-tracked so a missed run is retried
        # on the next boot that same Sunday instead of waiting a week.
        $needsWeekly = $EarlyIsMonday -and (Get-IngesterStatus $State "weekly") -ne "success"
        $needsMonthly = $EarlyIsFirstOfMonth -and (Get-IngesterStatus $State "monthly") -ne "success"
        $needsR2 = (Get-IngesterStatus $State "r2_backup") -ne "success"
        $needsPrune = $EarlyIsSunday -and (Get-IngesterStatus $State "prune") -ne "success"
        if (-not $needsWeekly -and -not $needsMonthly -and -not $needsR2 -and -not $needsPrune) {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] All scheduled work already succeeded today. Exiting before network checks."
            Remove-MyLock
            exit 0
        }
    } elseif ($lastDaily -and $lastDaily.Value.status -eq "failed") {
        try {
            $lastTry = [datetime]::Parse($lastDaily.Value.completed_at)
            $hrsSince = ((Get-Date) - $lastTry).TotalHours
            if ($hrsSince -lt 24) {
                Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Daily failed ${hrsSince:F1}h ago (<24h cooldown). Skipping retry this boot -- use -Force to override."
                Remove-MyLock
                exit 0
            }
        } catch {}
    }
}

# ── Determine which ingesters to run ───────────────────────────────────────────
$ScheduledIngesters = [System.Collections.Generic.List[string]]::new()

if ($RedoFailed) {
    # If RedoFailed is passed, only queue things marked "failed" today
    foreach ($prop in $State.ingesters.PSObject.Properties) {
        if ($prop.Value.status -eq "failed" -and $prop.Name -ne "r2_backup") {
            $ScheduledIngesters.Add($prop.Name)
        }
    }
    if ($ScheduledIngesters.Count -eq 0) {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] No failed ingesters found for today. Exiting."
        Remove-MyLock
        exit 0
    }
} else {
    # Normal calendar scheduling
    $Now           = Get-Date
    $IsMonday      = $Now.DayOfWeek -eq [System.DayOfWeek]::Monday
    $IsFirstOfMonth = $Now.Day -eq 1

    $ScheduledIngesters.Add("daily")
    if ($IsMonday)       { $ScheduledIngesters.Add("weekly") }
    if ($IsFirstOfMonth) { $ScheduledIngesters.Add("monthly") }

    # Safeguard: skip if all scheduled ingesters already succeeded today.
    # On Sundays the pending prune also blocks the exit so a missed prune
    # is retried on the next boot that same Sunday (state-tracked).
    if (-not $Force) {
        $allDone = $true
        foreach ($name in $ScheduledIngesters) {
            if ((Get-IngesterStatus $State $name) -ne "success") { $allDone = $false; break }
        }
        $IsSunday = $Now.DayOfWeek -eq [System.DayOfWeek]::Sunday
        $pruneDone = (-not $IsSunday) -or ((Get-IngesterStatus $State "prune") -eq "success")
        if ($allDone -and (Get-IngesterStatus $State "r2_backup") -eq "success" -and $pruneDone) {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] All ingesters completed successfully today. Exiting."
            Remove-MyLock
            exit 0
        }
    }
}

# ── Network & System stabilization ─────────────────────────────────────────────
function Wait-Network {
    param([int]$MaxWaitSeconds = 600, [int]$CheckIntervalSeconds = 10)
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Checking network availability (up to 10 minutes)..."
    $start = Get-Date
    while ((Get-Date) -lt $start.AddSeconds($MaxWaitSeconds)) {
        if (Test-Connection -ComputerName "8.8.8.8" -Count 1 -Quiet -ErrorAction SilentlyContinue) {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Network is up. Proceeding."
            return
        }
        Start-Sleep -Seconds $CheckIntervalSeconds
    }
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Max network wait time reached. Proceeding anyway."
}

function Wait-SystemStability {
    param([int]$MaxWaitSeconds = 300, [int]$CheckIntervalSeconds = 5)
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Waiting for system stability (up to 5 minutes)..."
    $start = Get-Date
    while ((Get-Date) -lt $start.AddSeconds($MaxWaitSeconds)) {
        try {
            # UPDATED FOR POWERSHELL 7 COMPATIBILITY: Get-CimInstance replaces Get-WmiObject
            $cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
            $mem = Get-CimInstance Win32_OperatingSystem
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

Wait-Network
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

# ── Run a single ingester with Exponential Backoff ─────────────────────────────
function Invoke-Ingester {
    param([string]$Name, [string]$Frequency, [int]$MaxAttempts = 3, [int]$BaseDelaySeconds = 300)

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $label = if ($attempt -gt 1) { " (retry $($attempt-1))" } else { "" }
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting $Name ingester$label..."

        $job = Start-Job -ScriptBlock {
            param($root, $freq)
            Set-Location $root
            
            # --- ENCODING FIX: Force PowerShell to read Python's output as UTF-8 ---
            [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
            $OutputEncoding = [System.Text.Encoding]::UTF8
            
            $env:PYTHONPATH = $root
            $env:METIS_MODE = "REAL"
            $env:PYTHONIOENCODING = "utf-8"

            $EnvFile = Join-Path $root ".env"
            if (Test-Path $EnvFile) {
                Get-Content $EnvFile | ForEach-Object {
                    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
                        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
                    }
                }
            }

            $wrapper = Join-Path $root "research/ops/ingest_wrapper.py"
            $out = & python -u $wrapper --frequency $freq 2>&1
            [PSCustomObject]@{ output = $out -join "`n"; exitCode = $LASTEXITCODE }
        } -ArgumentList $ProjectRoot, $Frequency

        Wait-Job -Job $job | Out-Null
        $result = Receive-Job -Job $job
        $jobState = $job.State
        Remove-Job -Job $job

        if ($result -and $result.output) { $result.output | Tee-Object -FilePath $LogFile -Append }

        $exitCode = if ($result -and $null -ne $result.exitCode) { $result.exitCode } else { 1 }
        
        # --- FALSE SUCCESS FIX: Scan the output for failures ---
        # If the output contains "Failed: " followed by any number 1-9, force the exit code to 1
        if ($result.output -match 'Failed:\s*[1-9]') {
            $exitCode = 1
        }

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
                $sleepTime = $BaseDelaySeconds * [math]::Pow(2, $attempt - 1)
                $sleepMinutes = $sleepTime / 60
                Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Waiting $sleepMinutes minutes before next retry..."
                Start-Sleep -Seconds $sleepTime
            }
        }
    }
    return $false
}

# ── Execute Ingesters ──────────────────────────────────────────────────────────
Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Ingesters queued: $($ScheduledIngesters -join ', ')"
$anyFailed = $false

foreach ($name in $ScheduledIngesters) {
    if (-not $Force -and -not $RedoFailed -and (Get-IngesterStatus $State $name) -eq "success") {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $name already succeeded today - skipping."
        continue
    }
    $ok = Invoke-Ingester -Name $name.ToUpper() -Frequency $name
    if (-not $ok) { $anyFailed = $true }
}

# ── R2 backup ──────────────────────────────────────────────────────────────────
# Allow backup if running manual redos (as long as nothing in this current batch failed)
if (-not $anyFailed -and ((Get-IngesterStatus $State "r2_backup") -ne "success" -or $Force -or $RedoFailed)) {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Ingesters succeeded. Starting R2 backup..."

    $BackupTimeoutSeconds = 1800   # hard cap so a stalled upload can't run forever
    $PollSeconds = 15              # how often we drain + stream child output

    $job = Start-Job -ScriptBlock {
        param($root)
        Set-Location $root
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        $env:PYTHONPATH = $root
        $env:PYTHONIOENCODING = "utf-8"
        $EnvFile = Join-Path $root ".env"
        if (Test-Path $EnvFile) {
            Get-Content $EnvFile | ForEach-Object {
                if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
                    [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
                }
            }
        }
        python "research/ops/r2_auto_backup.py" 2>&1 | ForEach-Object { $_.ToString() }
        "PYSYNC_EXIT_CODE=$LASTEXITCODE"
    } -ArgumentList $ProjectRoot

    # Poll the job, streaming each batch of output to the log as it arrives,
    # until the job finishes or the deadline passes.
    $deadline    = (Get-Date).AddSeconds($BackupTimeoutSeconds)
    $timedOut    = $false
    $allOutput   = [System.Collections.Generic.List[string]]::new()
    while ($true) {
        $finished = Wait-Job $job -Timeout $PollSeconds
        foreach ($line in @(Receive-Job $job -ErrorAction SilentlyContinue)) {
            $s = "$line"
            $allOutput.Add($s)
            $s | Tee-Object -FilePath $LogFile -Append | Out-Null
        }
        if ($finished) { break }
        if ((Get-Date) -ge $deadline) { $timedOut = $true; break }
    }

    if ($timedOut) {
        Stop-Job $job
        foreach ($line in @(Receive-Job $job -ErrorAction SilentlyContinue)) {
            "$line" | Tee-Object -FilePath $LogFile -Append | Out-Null
        }
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] R2 backup TIMED OUT after $($BackupTimeoutSeconds / 60) minutes (non-blocking) - killing."
    }
    Remove-Job $job -Force -ErrorAction SilentlyContinue

    if (-not $timedOut) {
        $exitLine = $allOutput | Where-Object { $_ -like 'PYSYNC_EXIT_CODE=*' } | Select-Object -Last 1
        $backupExit = if ($exitLine) { [int]($exitLine -replace 'PYSYNC_EXIT_CODE=', '') } else { 1 }

        if ($backupExit -eq 0) {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] R2 backup completed successfully."
            Set-IngesterStatus $State "r2_backup" "success"
        } else {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] R2 backup failed (non-blocking). exitCode=$backupExit"
            Set-IngesterStatus $State "r2_backup" "failed" "exitCode=$backupExit"
        }
    } else {
        Set-IngesterStatus $State "r2_backup" "failed" "timeout after ${BackupTimeoutSeconds}s"
    }
}

# ── Weekly R2 prune (Sunday, non-blocking) ─────────────────────────────────
# With weekly-full DB (Monday) + keep-last 5 + first-per-month, the database
# prefix stays ~5-6 GB and the total bucket stays under 10 GB. Prune is Sunday
# so Monday's full has room.
if ((Get-Date).DayOfWeek -eq [System.DayOfWeek]::Sunday) {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Sunday prune: trimming old database snapshots (keep-last 5 + first-per-month)..."
    try {
        $pruneJob = Start-Job -ScriptBlock {
            param($root)
            Set-Location $root
            [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
            $env:PYTHONIOENCODING = "utf-8"
            $EnvFile = Join-Path $root ".env"
            if (Test-Path $EnvFile) {
                Get-Content $EnvFile | ForEach-Object {
                    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
                        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
                    }
                }
            }
            python "research/ops/r2_prune.py" 2>&1 | ForEach-Object { $_.ToString() }
            "PRUNE_EXIT_CODE=$LASTEXITCODE"
        } -ArgumentList $ProjectRoot
        $null = Wait-Job $pruneJob -Timeout 300
        $pruneOutput = [System.Collections.Generic.List[string]]::new()
        foreach ($line in @(Receive-Job $pruneJob -ErrorAction SilentlyContinue)) {
            "$line" | Tee-Object -FilePath $LogFile -Append | Out-Null
            $pruneOutput.Add("$line")
        }
        Remove-Job $pruneJob -Force -ErrorAction SilentlyContinue
        $pruneExitLine = $pruneOutput | Where-Object { $_ -like 'PRUNE_EXIT_CODE=*' } | Select-Object -Last 1
        $pruneExit = if ($pruneExitLine) { [int]($pruneExitLine -replace 'PRUNE_EXIT_CODE=', '') } else { 1 }
        if ($pruneExit -eq 0) {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Sunday prune finished successfully."
            Set-IngesterStatus $State "prune" "success"
        } else {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Sunday prune failed (non-blocking). exitCode=$pruneExit"
            Set-IngesterStatus $State "prune" "failed" "exitCode=$pruneExit"
        }
    } catch {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Sunday prune failed (non-blocking): $_"
        Set-IngesterStatus $State "prune" "failed" "$_"
    }
}

Remove-MyLock
if (-not $anyFailed) {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION COMPLETED SUCCESSFULLY ==="
    exit 0
} else {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION COMPLETED WITH FAILURES ==="
    exit 1
}
# Metis Data Ingestion at System Startup
# Purpose: Run data ingesters on system startup with intelligent scheduling
# Trigger: Windows Task Scheduler (pwsh.exe at system startup)

param([switch]$Force, [switch]$RedoFailed, [switch]$DryRun, [int]$Delay = 10)

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
# A named mutex, not a file with a TTL. The kernel releases it when this
# process dies (including a hard kill or reboot), so there is no stale-lock
# window and no PID guessing. Local\ is per-session, which matches the
# per-user Startup-folder trigger. An abandoned mutex (previous holder died
# without releasing) is acquired here and treated as ours.
$IngestMutex = [System.Threading.Mutex]::new($false, "Local\MetisIngestion")
$script:WeHoldLock = $false
try {
    $script:WeHoldLock = $IngestMutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $script:WeHoldLock = $true
}
if (-not $script:WeHoldLock) {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Another ingestion run holds the mutex. Exiting."
    exit 0
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

# ── Persistent ledger (cross-day due state) ───────────────────────────────────
# The per-day state file answers "what happened today". This ledger answers
# "when did each frequency last succeed", so a monthly/weekly failure is not
# forgotten when the calendar day rolls over.
$LedgerFile = Join-Path $LogDir "ingest_ledger.json"

function Read-Ledger {
    if (Test-Path $LedgerFile) {
        try { return (Get-Content $LedgerFile -Raw | ConvertFrom-Json) } catch {}
    }
    return [PSCustomObject]@{}
}

function Get-LedgerEntry($ledger, [string]$name) {
    $prop = $ledger.PSObject.Properties[$name]
    if ($prop) { return $prop.Value }
    return $null
}

function Get-LastSuccess($ledger, [string]$name) {
    $e = Get-LedgerEntry $ledger $name
    if ($e -and $e.last_success_at) {
        try { return [datetime]::Parse($e.last_success_at) } catch {}
    }
    return $null
}

function Set-LedgerStatus($ledger, [string]$name, [string]$status, [string]$error = "") {
    $prev = Get-LedgerEntry $ledger $name
    $entry = [PSCustomObject]@{
        status          = $status
        last_attempt_at = (Get-Date -Format 'o')
        last_success_at = $null
        error           = $error
    }
    if ($prev -and $prev.last_success_at) { $entry.last_success_at = $prev.last_success_at }
    if ($status -eq "success") { $entry.last_success_at = (Get-Date -Format 'o') }
    if ($ledger.PSObject.Properties[$name]) {
        $ledger.PSObject.Properties[$name].Value = $entry
    } else {
        $ledger | Add-Member -MemberType NoteProperty -Name $name -Value $entry
    }
    $tmp = "$LedgerFile.tmp"
    $ledger | ConvertTo-Json -Depth 5 | Set-Content $tmp -Encoding utf8
    Move-Item -LiteralPath $tmp -Destination $LedgerFile -Force
}

function Test-Due($ledger, [string]$name, [datetime]$now) {
    $last = Get-LastSuccess $ledger $name
    switch ($name) {
        "daily"   { return (-not $last) -or ($last.Date -lt $now.Date) }
        # Weekly is anchored to the start of the ISO week (Monday 00:00), not a
        # rolling 7 days: a rolling window drifts a day later every week
        # (Mon 10:19 success -> next Mon 08:00 is only 6.9 days -> Tue 08:00).
        "weekly"  {
            $weekStart = $now.Date.AddDays(-((([int]$now.DayOfWeek) + 6) % 7))
            return (-not $last) -or ($last -lt $weekStart)
        }
        "monthly" { return (-not $last) -or ($last.Year -ne $now.Year) -or ($last.Month -ne $now.Month) }
        default   { return (-not $last) }
    }
}

function Test-DueToday($ledger, [string]$name, [datetime]$now) {
    $last = Get-LastSuccess $ledger $name
    return (-not $last) -or ($last.Date -ne $now.Date)
}

function Test-RetryCooldown($ledger, [string]$name, [datetime]$now, [int]$minutes = 30) {
    $e = Get-LedgerEntry $ledger $name
    if (-not $e -or $e.status -ne "failed" -or -not $e.last_attempt_at) { return $false }
    try {
        $last = [datetime]::Parse($e.last_attempt_at)
        return (($now - $last).TotalMinutes -lt $minutes)
    } catch { return $false }
}

$State = Read-State
$Ledger = Read-Ledger

# ── Determine what is due ──────────────────────────────────────────────────────
# Due-ness is cross-day: a monthly failure on the 1st stays due on the 2nd.
$EarlyNow = Get-Date
$EarlyIsMonday = $EarlyNow.DayOfWeek -eq [System.DayOfWeek]::Monday
$EarlyIsSunday = $EarlyNow.DayOfWeek -eq [System.DayOfWeek]::Sunday

$needsDaily   = $Force -or (Test-Due $Ledger "daily" $EarlyNow)
$needsWeekly  = $Force -or (Test-Due $Ledger "weekly" $EarlyNow)
$needsMonthly = $Force -or (Test-Due $Ledger "monthly" $EarlyNow)
$needsR2      = ($EarlyIsMonday -or $Force) -and ($Force -or (Test-DueToday $Ledger "r2_backup" $EarlyNow))
$needsPrune   = $EarlyIsSunday -and ($Force -or (Test-DueToday $Ledger "prune" $EarlyNow))

if (-not $Force -and -not $RedoFailed) {
    if ($needsDaily -and (Test-RetryCooldown $Ledger "daily" $EarlyNow 30)) {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Daily failed within the last 30 minutes - skipping this boot."
        $needsDaily = $false
    }
    if (-not $needsDaily -and -not $needsWeekly -and -not $needsMonthly -and -not $needsR2 -and -not $needsPrune) {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] All scheduled work already succeeded (ledger). Exiting before network checks."
        exit 0
    }
}

# ── Determine which ingesters to run ───────────────────────────────────────────
$ScheduledIngesters = [System.Collections.Generic.List[string]]::new()

if ($RedoFailed) {
    # Re-queue frequencies the ledger marks failed; R2/prune are handled below.
    foreach ($name in @("daily", "weekly", "monthly")) {
        $e = Get-LedgerEntry $Ledger $name
        if ($e -and $e.status -eq "failed") { $ScheduledIngesters.Add($name) }
    }
    if ($ScheduledIngesters.Count -eq 0 -and -not $needsR2 -and -not $needsPrune) {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] No failed ingesters found. Exiting."
        exit 0
    }
} else {
    if ($needsDaily)   { $ScheduledIngesters.Add("daily") }
    if ($needsWeekly)  { $ScheduledIngesters.Add("weekly") }
    if ($needsMonthly) { $ScheduledIngesters.Add("monthly") }

    if (-not $Force) {
        $filtered = [System.Collections.Generic.List[string]]::new()
        foreach ($name in $ScheduledIngesters) {
            if (-not (Test-RetryCooldown $Ledger $name $EarlyNow 30)) { $filtered.Add($name) }
        }
        $ScheduledIngesters = $filtered
    }
    if ($ScheduledIngesters.Count -eq 0 -and -not $needsR2 -and -not $needsPrune) {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] All ingesters completed successfully (ledger). Exiting."
        exit 0
    }
}

if ($DryRun) {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] DRY RUN: ingesters=$($ScheduledIngesters -join ', '); r2=$needsR2; prune=$needsPrune; force=$Force; redoFailed=$RedoFailed"
    exit 0
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
# Per-frequency time-boxes (seconds per attempt): one slow source must not hold
# the boot hostage. Measured 2026-11-03: a healthy monthly run is ~53min, of
# which Congress is ~38min (118/119 full fetches). The old 40min cap killed it
# during State Bills every time. 75min leaves headroom without hiding a poison
# source. Congress upserts per session, so a timed-out run keeps partial
# progress for the next attempt.
$FrequencyTimeoutSeconds = @{ daily = 1200; weekly = 1200; monthly = 4500 }

function Invoke-Ingester {
    param([string]$Name, [string]$Frequency, [int]$MaxAttempts = 3, [int]$BaseDelaySeconds = 300)

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $label = if ($attempt -gt 1) { " (retry $($attempt-1))" } else { "" }
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting $Name ingester$label..."

        $job = Start-Job -ScriptBlock {
            param($root, $freq, $force)
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
            $forceArgs = @()
            if ($force) { $forceArgs = @("--force") }
            # Stream each line into the job's output stream so Receive-Job can
            # retrieve partial output when the parent times the job out.
            & python -u $wrapper --frequency $freq @forceArgs 2>&1 | ForEach-Object { $_.ToString() }
            "INGEST_EXIT_CODE=$LASTEXITCODE"
        } -ArgumentList $ProjectRoot, $Frequency, [bool]$Force

        $timeout = $FrequencyTimeoutSeconds[$Frequency]
        if (-not $timeout) { $timeout = 1800 }
        $finished = Wait-Job -Job $job -Timeout $timeout
        if (-not $finished) {
            # Drain what the job has already emitted *before* stopping it;
            # Stop-Job discards the buffered stream.
            $partial = @(Receive-Job $job -ErrorAction SilentlyContinue | Where-Object { "$_" -notlike 'INGEST_EXIT_CODE=*' })
            foreach ($line in $partial) { "$line" | Tee-Object -FilePath $LogFile -Append | Out-Null }
            Stop-Job $job
            Remove-Job $job -Force -ErrorAction SilentlyContinue
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Name ingester TIMED OUT after $($timeout / 60) minutes - killing (partial upserts kept)."
            $errMsg = "timeout after ${timeout}s"
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Name ingester failed ($errMsg)."
            Set-IngesterStatus $script:State $Name.ToLower() "failed" $errMsg
            Set-LedgerStatus $script:Ledger $Name.ToLower() "failed" $errMsg
            if ($attempt -lt $MaxAttempts) {
                $sleepTime = $BaseDelaySeconds * [math]::Pow(2, $attempt - 1)
                Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Waiting $($sleepTime / 60) minutes before next retry..."
                Start-Sleep -Seconds $sleepTime
            }
            continue
        }
        $result = @(Receive-Job -Job $job -ErrorAction SilentlyContinue)
        $jobState = $job.State
        Remove-Job -Job $job

        $exitLine = $result | Where-Object { "$_" -like 'INGEST_EXIT_CODE=*' } | Select-Object -Last 1
        $exitCode = if ($exitLine) { [int]("$exitLine" -replace 'INGEST_EXIT_CODE=', '') } else { 1 }
        $outputLines = @($result | Where-Object { "$_" -notlike 'INGEST_EXIT_CODE=*' })
        if ($outputLines.Count -gt 0) { $outputLines | Tee-Object -FilePath $LogFile -Append }

        # --- FALSE SUCCESS FIX: Scan the output for failures ---
        # If the output contains "Failed: " followed by any number 1-9, force the exit code to 1
        if (($outputLines -join "`n") -match 'Failed:\s*[1-9]') {
            $exitCode = 1
        }

        $succeeded = ($jobState -eq 'Completed' -and $exitCode -eq 0)

        if ($succeeded) {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Name ingester succeeded."
            Set-IngesterStatus $script:State $Name.ToLower() "success"
            Set-LedgerStatus $script:Ledger $Name.ToLower() "success"
            return $true
        } else {
            $errMsg = "state=$jobState exitCode=$exitCode"
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Name ingester failed ($errMsg)."
            Set-IngesterStatus $script:State $Name.ToLower() "failed" $errMsg
            Set-LedgerStatus $script:Ledger $Name.ToLower() "failed" $errMsg

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
    # The ledger decided this is due; don't second-guess it with today's state
    # file (a manual run can succeed without touching the state file).
    $ok = Invoke-Ingester -Name $name.ToUpper() -Frequency $name
    if (-not $ok) { $anyFailed = $true }
}

# ── R2 backup (Monday-only) ────────────────────────────────────────────────────
# Weekly-full policy: zero R2 traffic Tue-Sun. -Force overrides for manual runs.
if (-not $anyFailed -and $needsR2) {
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
            Set-LedgerStatus $Ledger "r2_backup" "success"
        } else {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] R2 backup failed (non-blocking). exitCode=$backupExit"
            Set-IngesterStatus $State "r2_backup" "failed" "exitCode=$backupExit"
            Set-LedgerStatus $Ledger "r2_backup" "failed" "exitCode=$backupExit"
        }
    } else {
        Set-IngesterStatus $State "r2_backup" "failed" "timeout after ${BackupTimeoutSeconds}s"
        Set-LedgerStatus $Ledger "r2_backup" "failed" "timeout after ${BackupTimeoutSeconds}s"
    }
}

# ── Weekly R2 prune (Sunday, non-blocking) ─────────────────────────────────
# With weekly-full DB (Monday) + keep-last 5 + first-per-month, the database
# prefix stays ~5-6 GB and the total bucket stays under 10 GB. Prune is Sunday
# so Monday's full has room.
if ($needsPrune) {
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
            Set-LedgerStatus $Ledger "prune" "success"
        } else {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Sunday prune failed (non-blocking). exitCode=$pruneExit"
            Set-IngesterStatus $State "prune" "failed" "exitCode=$pruneExit"
            Set-LedgerStatus $Ledger "prune" "failed" "exitCode=$pruneExit"
        }
    } catch {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Sunday prune failed (non-blocking): $_"
        Set-IngesterStatus $State "prune" "failed" "$_"
        Set-LedgerStatus $Ledger "prune" "failed" "$_"
    }
}

# Release the mutex on the graceful path. If we exit any other way, the kernel
# releases it when the process dies; the next run sees an abandoned mutex.
if ($script:WeHoldLock) {
    try { $IngestMutex.ReleaseMutex() } catch {}
    $script:WeHoldLock = $false
}
if (-not $anyFailed) {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION COMPLETED SUCCESSFULLY ==="
    exit 0
} else {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION COMPLETED WITH FAILURES ==="
    exit 1
}
#Requires -Version 7.0
<#
.SYNOPSIS
    Register (or remove) the Metis ingestion Scheduled Task.

.DESCRIPTION
    Replaces the per-logon Startup-folder shortcut with a user task that has
    two triggers:

      - at logon (2 min delay, so the profile and network are ready)
      - daily at 02:00 (with StartWhenAvailable, so a missed run catches up
        after sleep/shutdown)

    The script's own ledger still decides what is due (daily/weekly/monthly,
    R2 Monday, prune Sunday), so both triggers are safe: a second invocation
    exits early or is blocked by the named mutex.

    Runs as the current user, interactive, limited privilege. No password is
    stored, and it only runs while that user is logged on.

.PARAMETER TaskName
    Scheduled task name. Default: MetisIngestion.

.PARAMETER At
    Daily trigger time, 24-hour "HH:mm". Default: 02:00.

.PARAMETER Unregister
    Remove the task instead of creating it.

.PARAMETER DisableLegacyStartup
    Move the old Startup-folder launch_metis.vbs (and any leftover .disabled
    rename) out of Startup and into research/ops/archive. The Startup folder
    opens every file at logon, so renaming in place leaves an unassociated
    file that triggers a "How do you want to open this file?" prompt.

.PARAMETER DryRun
    Print the intended configuration without changing anything.
#>
param(
    [string]$TaskName = "MetisIngestion",
    [string]$At = "02:00",
    [switch]$Unregister,
    [switch]$DisableLegacyStartup,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$StartupScript = Join-Path $ProjectRoot "research\ops\run_ingestion_startup.ps1"
$UserId = "$env:USERDOMAIN\$env:USERNAME"
$StartupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$LegacyVbs = Join-Path $StartupDir "launch_metis.vbs"
$ArchiveDir = Join-Path $ProjectRoot "research\ops\archive"

if ($Unregister) {
    if ($DryRun) {
        Write-Host "DRY RUN: would unregister task '$TaskName'."
        return
    }
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "Task '$TaskName' does not exist; nothing to remove."
        return
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
    return
}

if (-not (Test-Path -LiteralPath $StartupScript)) {
    throw "Startup script not found: $StartupScript"
}
$Pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source
if ($At -notmatch '^\d{2}:\d{2}$') {
    throw "At must be HH:mm, got '$At'"
}

$Action = New-ScheduledTaskAction `
    -Execute $Pwsh `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$StartupScript`"" `
    -WorkingDirectory $ProjectRoot

# Logon trigger: fixed 2-minute delay (the cmdlet exposes only RandomDelay).
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$LogonTrigger.Delay = "PT2M"

# Daily trigger. StartWhenAvailable (below) covers a missed 02:00 run.
$DailyTrigger = New-ScheduledTaskTrigger -Daily -At $At

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

$Principal = New-ScheduledTaskPrincipal `
    -UserId $UserId `
    -LogonType Interactive `
    -RunLevel Limited

$Description = "Metis data ingestion: logon + daily $At, due-state handled by run_ingestion_startup.ps1"

Write-Host "Task:        $TaskName"
Write-Host "User:        $UserId (interactive, limited)"
Write-Host "Action:      `"$Pwsh`" -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$StartupScript`""
Write-Host "Triggers:    at logon (+2 min), daily at $At"
Write-Host "Settings:    StartWhenAvailable, WakeToRun, IgnoreNew, 6h limit"
Write-Host "Legacy VBS:  $LegacyVbs (moved to $ArchiveDir when -DisableLegacyStartup is used)"

if ($DryRun) {
    Write-Host "DRY RUN: nothing registered."
    return
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger @($LogonTrigger, $DailyTrigger) `
    -Settings $Settings `
    -Principal $Principal `
    -Description $Description `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName'."

if ($DisableLegacyStartup) {
    # Do NOT leave anything behind in Startup. Explorer opens every file in
    # that folder at logon; a renamed .vbs.disabled has no handler and shows a
    # "How do you want to open this file?" dialog. Move it to the repo archive
    # so the task is the only trigger.
    # Process the stale .disabled rename first, then the canonical .vbs, so the
    # real script wins if both exist (they share one archive destination).
    $leftovers = @("$LegacyVbs.disabled", $LegacyVbs)
    $moved = $false
    foreach ($candidate in $leftovers) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        New-Item -ItemType Directory -Path $ArchiveDir -Force | Out-Null
        $destination = Join-Path $ArchiveDir "launch_metis.vbs"
        Move-Item -LiteralPath $candidate -Destination $destination -Force
        Write-Host "Moved legacy Startup entry out of Startup: $candidate -> $destination"
        $moved = $true
    }
    if (-not $moved) {
        Write-Host "No legacy Startup entry found; nothing to move."
    }
}

$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host ""
Write-Host "State:        $($task.State)"
Write-Host "Next run:     $($info.NextRunTime)"
Write-Host "Last result:  $($info.LastTaskResult)"

# Metis Data Ingestion at System Startup
# Purpose: Run data ingesters on system startup with intelligent scheduling
# Trigger: Windows Task Scheduler (at system startup)
# Features: Daily safeguard, smart system resource detection, parallel execution

param([switch]$Force, [int]$Delay = 10)  # Override daily safeguard check; optional delay before starting

$ProjectRoot = "C:\Users\legot\Metis"
$ResearchDir = Join-Path $ProjectRoot "research"
$LogDir = Join-Path $ProjectRoot "logs"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$LogFile = Join-Path $LogDir "ingest_startup_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').log"

function Log { param([string]$Msg); $Msg | Tee-Object -FilePath $LogFile -Append }

Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION TRIGGERED ==="

# Date safeguard: check if ingestion already ran today
$Today = Get-Date -Format "yyyy-MM-dd"
$TodayLogs = @(Get-ChildItem -Path $LogDir -Filter "ingest_startup_${Today}_*.log" -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne (Split-Path $LogFile -Leaf) })

if ($TodayLogs.Count -gt 0 -and -not $Force) {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Ingestion already completed today. Exiting to prevent duplicate runs."
    exit 0
}

# Smart system stabilization: check resources instead of fixed delay
function Wait-SystemStability {
    param([int]$MaxWaitSeconds = 300, [int]$CheckIntervalSeconds = 5)
    
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Waiting for system stability (up to 5 minutes)..."
    $StartTime = Get-Date
    
    while ((Get-Date) -lt $StartTime.AddSeconds($MaxWaitSeconds)) {
        try {
            $CPUUsage = (Get-WmiObject win32_processor | Measure-Object -Property LoadPercentage -Average).Average
            $Memory = Get-WmiObject win32_operatingsystem
            $MemUsagePercent = 100 - ([math]::Round(($Memory.FreePhysicalMemory / $Memory.TotalVisibleMemorySize) * 100))
            
            if ($CPUUsage -lt 30 -and $MemUsagePercent -lt 70) {
                Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] System stable (CPU: $CPUUsage%, Memory: $MemUsagePercent%). Proceeding."
                return
            }
        } catch {
            # If WMI fails, just continue after waiting
        }
        
        Start-Sleep -Seconds $CheckIntervalSeconds
    }
    
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Max wait time reached. Proceeding anyway."
}

Wait-SystemStability

# Set environment
[System.Environment]::SetEnvironmentVariable("METIS_MODE", "REAL", "Process")
[System.Environment]::SetEnvironmentVariable("PYTHONPATH", $ResearchDir, "Process")

# Load .env if exists
$EnvFile = Join-Path $ResearchDir ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^=]+)=(.*)$') {
            [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

# Determine which ingesters to run based on schedule
$Now = Get-Date
$DayOfWeek = $Now.DayOfWeek
$DayOfMonth = $Now.Day
$IsMonday = $DayOfWeek -eq [System.DayOfWeek]::Monday
$IsFirstOfMonth = $DayOfMonth -eq 1

# Run ingesters in parallel based on schedule
try {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Running ingesters in parallel..."
    
    $Jobs = @()
    $JobMap = @{}
    
    # Start daily ingester
    $DailyJob = Start-Job -ScriptBlock {
        Set-Location $args[0]
        python "ingest_wrapper.py" --frequency daily 2>&1
    } -ArgumentList $ProjectRoot
    $Jobs += $DailyJob
    $JobMap[$DailyJob.Id] = "DAILY"
    
    # Start weekly ingester if Monday
    if ($IsMonday) {
        $WeeklyJob = Start-Job -ScriptBlock {
            Set-Location $args[0]
            python "ingest_wrapper.py" --frequency weekly 2>&1
        } -ArgumentList $ProjectRoot
        $Jobs += $WeeklyJob
        $JobMap[$WeeklyJob.Id] = "WEEKLY"
    }
    
    # Start monthly ingester if first of month
    if ($IsFirstOfMonth) {
        $MonthlyJob = Start-Job -ScriptBlock {
            Set-Location $args[0]
            python "ingest_wrapper.py" --frequency monthly 2>&1
        } -ArgumentList $ProjectRoot
        $Jobs += $MonthlyJob
        $JobMap[$MonthlyJob.Id] = "MONTHLY"
    }
    
    # Wait for all jobs to complete and collect results
    $FailedAny = $false
    foreach ($Job in $Jobs) {
        $JobType = $JobMap[$Job.Id]
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Waiting for $JobType ingester..."
        
        $Output = Receive-Job -Job $Job -Wait
        $Output | Tee-Object -FilePath $LogFile -Append
        
        if ($Job.State -ne 'Completed') {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR: $JobType ingester failed with state: $($Job.State)"
            $FailedAny = $true
        }
        
        Remove-Job -Job $Job
    }
    
    if ($FailedAny) {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION FAILED ==="
        exit 1
    } else {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION COMPLETED SUCCESSFULLY ==="
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting R2 cloud backup..."
        
        # Backup to R2
        try {
            $BackupResult = & python (Join-Path $ResearchDir "r2_auto_backup.py") 2>&1
            $BackupResult | Tee-Object -FilePath $LogFile -Append
            
            if ($LASTEXITCODE -eq 0) {
                Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] R2 backup completed successfully"
            } else {
                Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] R2 backup encountered issues (non-blocking)"
            }
        } catch {
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] R2 backup failed: $_"
            Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Ingestion succeeded, backup is non-critical"
        }
        
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION AND BACKUP COMPLETED ==="
        exit 0
    }
    
} catch {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR: $_"
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION FAILED ==="
    exit 1
}

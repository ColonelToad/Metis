# Metis Data Ingestion at System Startup
# Purpose: Run data ingesters on system startup with intelligent scheduling
# Trigger: Windows Task Scheduler (at system startup)
# Delay: 10 minutes after startup to ensure system stability

param([string]$Delay = 10)  # Delay in minutes before starting ingestion

$ProjectRoot = "C:\Users\legot\Metis"
$ResearchDir = Join-Path $ProjectRoot "research"
$LogDir = Join-Path $ProjectRoot "logs"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$LogFile = Join-Path $LogDir "ingest_startup_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').log"

function Log { param([string]$Msg); $Msg | Tee-Object -FilePath $LogFile -Append }

Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION TRIGGERED ==="
Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Waiting $Delay minutes for system stability..."

# Wait for system to stabilize
Start-Sleep -Seconds ($Delay * 60)

Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] System stable, determining ingestion schedule..."

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
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Loaded .env"
}

# Determine which ingesters to run based on schedule
$Now = Get-Date
$DayOfWeek = $Now.DayOfWeek
$DayOfMonth = $Now.Day
$IsMonday = $DayOfWeek -eq [System.DayOfWeek]::Monday
$IsFirstOfMonth = $DayOfMonth -eq 1

Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Schedule check: Day=$DayOfWeek, Date=$DayOfMonth"

if ($IsMonday -and $IsFirstOfMonth) {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] SCHEDULE: Monday 1st - will run daily + weekly + monthly"
} elseif ($IsMonday) {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] SCHEDULE: Monday - will run daily + weekly"
} elseif ($IsFirstOfMonth) {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] SCHEDULE: 1st of month - will run daily + monthly"
} else {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] SCHEDULE: Regular day - will run daily only"
}

# Run ingesters in sequence based on schedule
try {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ========================================"
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Running DAILY ingesters..."
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ========================================"
    & python "$(Join-Path $ProjectRoot 'ingest_wrapper.py')" --frequency daily 2>&1 | Tee-Object -FilePath $LogFile -Append
    $DailyCode = $LASTEXITCODE
    
    if ($IsMonday) {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ========================================"
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Running WEEKLY ingesters (Monday)..."
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ========================================"
        & python "$(Join-Path $ProjectRoot 'ingest_wrapper.py')" --frequency weekly 2>&1 | Tee-Object -FilePath $LogFile -Append
        $WeeklyCode = $LASTEXITCODE
    }
    
    if ($IsFirstOfMonth) {
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ========================================"
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Running MONTHLY ingesters (1st of month)..."
        Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ========================================"
        & python "$(Join-Path $ProjectRoot 'ingest_wrapper.py')" --frequency monthly 2>&1 | Tee-Object -FilePath $LogFile -Append
        $MonthlyCode = $LASTEXITCODE
    }
    
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION COMPLETED SUCCESSFULLY ==="
    exit 0
    
} catch {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR: $_"
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] === STARTUP INGESTION FAILED ==="
    exit 1
}

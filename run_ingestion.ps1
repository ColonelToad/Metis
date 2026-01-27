# Metis Data Ingestion Orchestration Script
# Purpose: Run all data ingesters
# Trigger: Windows Task Scheduler (daily at 6 AM)

param([string]$Mode = "REAL")

$ProjectRoot = "C:\Users\legot\Metis"
$ResearchDir = Join-Path $ProjectRoot "research"
$LogDir = Join-Path $ProjectRoot "logs"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$LogFile = Join-Path $LogDir "ingest_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').log"

function Log { param([string]$Msg); $Msg | Tee-Object -FilePath $LogFile -Append }

Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting ingestion (Mode: $Mode)"

# Set environment
[System.Environment]::SetEnvironmentVariable("METIS_MODE", $Mode, "Process")
[System.Environment]::SetEnvironmentVariable("PYTHONPATH", $ResearchDir, "Process")

try {
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
    
    # Run ingestion wrapper
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Running ingestion wrapper..."
    & python "$(Join-Path $ProjectRoot 'ingest_wrapper.py')" 2>&1 | Tee-Object -FilePath $LogFile -Append
    $IngestCode = $LASTEXITCODE
    
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Ingestion completed (exit code: $IngestCode)"
    exit $IngestCode
    
} catch {
    Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR: $_"
    Pop-Location -ErrorAction SilentlyContinue
    exit 1
}

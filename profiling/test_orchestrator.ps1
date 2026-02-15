<#
.SYNOPSIS
Test harness for orchestrator service - Phase 1E validation

.DESCRIPTION
Starts the HTTP service on localhost:9000
Runs pipeline tests and captures timing metrics
Shows consistency across runs

.PARAMETER Iterations
Number of pipeline runs (default: 3)

.PARAMETER Mode
Pipeline mode: DEV or REAL (default: DEV)

.PARAMETER Port
Service port (default: 9000)
#>

param(
    [int]$Iterations = 3,
    [string]$Mode = "DEV",
    [int]$Port = 9000
)

$ErrorActionPreference = "Stop"

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
}

function Write-Status {
    param([string]$Text, [string]$Result = "")
    if ($Result) {
        Write-Host "  > $Text ... $Result" -ForegroundColor Gray
    } else {
        Write-Host "  > $Text" -ForegroundColor Gray
    }
}

function Wait-ForPort {
    param([int]$Port, [int]$MaxWaitSeconds = 30)
    $start = Get-Date
    while ((Get-Date) - $start -lt [timespan]::FromSeconds($MaxWaitSeconds)) {
        try {
            $result = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 1 -EA SilentlyContinue
            if ($result.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

function Kill-PortProcess {
    param([int]$Port)
    try {
        $procs = netstat -ano 2>$null | Select-String ":$Port" | ForEach-Object {
            $parts = $_ -split '\s+' | Where-Object { $_ }
            $parts[-1]
        }
        foreach ($pid in $procs) {
            if ($pid -and $pid -ne "PID") {
                Stop-Process -Id $pid -Force -EA SilentlyContinue
                Write-Status "Killed process on port $Port (PID $pid)" "OK"
            }
        }
    } catch { }
}

function Start-Service {
    param([int]$Port)
    Write-Section "STARTING ORCHESTRATOR SERVICE"
    
    Write-Status "Checking for existing service on port $Port"
    Kill-PortProcess $Port
    Start-Sleep -Milliseconds 500
    
    Write-Status "Building orchestrator binary"
    $buildOutput = & cargo build --bin orchestrator 2>&1
    Write-Status "Build completed" "OK"
    
    Write-Status "Starting service on port $Port"
    $binaryPath = "target\debug\orchestrator.exe"
    $project_root = (Get-Location).Path
    
    $process = Start-Process -FilePath $binaryPath -ArgumentList $project_root -NoNewWindow -PassThru
    
    Write-Status "Waiting for service to be ready (max 30s)"
    if (Wait-ForPort $Port 30) {
        Write-Status "Service is ready" "OK"
        Start-Sleep -Milliseconds 500
        return $process.Id
    } else {
        Write-Status "Service did not start" "ERROR"
        Stop-Process -Id $process.Id -Force -EA SilentlyContinue
        exit 1
    }
}

function Test-Health {
    param([int]$Port)
    Write-Section "SERVICE HEALTH CHECK"
    
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5 | Select-Object -ExpandProperty Content | ConvertFrom-Json
        Write-Status "Health check" "OK"
        Write-Host "    Status: $($response.status)"
        Write-Host "    Uptime: $($response.uptime_seconds)s"
        Write-Host "    Version: $($response.version)"
        return $true
    } catch {
        Write-Status "Health check" "FAILED: $_"
        return $false
    }
}

function Run-Test {
    param([int]$Port, [string]$Mode, [int]$RunNum)
    
    Write-Section "RUN NUMBER $RunNum - Mode: $Mode"
    $runStart = Get-Date
    
    Write-Status "Triggering pipeline"
    try {
        $payload = @{ mode = $Mode; force_refresh = $false } | ConvertTo-Json
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/pipeline/run" `
            -Method POST -Body $payload -ContentType "application/json" -TimeoutSec 10 | `
            Select-Object -ExpandProperty Content | ConvertFrom-Json
        $jobId = $response.job_id
        Write-Host "    Job ID: $jobId"
        Write-Host "    Status: $($response.status)"
    } catch {
        Write-Status "Pipeline trigger" "FAILED: $_"
        return $null
    }
    
    Write-Status "Polling for completion"
    $maxWait = 120
    $pollStart = Get-Date
    $lastPhase = ""
    
    while ((Get-Date) - $pollStart -lt [timespan]::FromSeconds($maxWait)) {
        Start-Sleep -Milliseconds 500
        
        try {
            $statusResp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/pipeline/status/$jobId" `
                -TimeoutSec 5 | Select-Object -ExpandProperty Content | ConvertFrom-Json
            
            if ($statusResp.phase -ne $lastPhase) {
                Write-Host "    Phase: $($statusResp.phase) ($($statusResp.progress)%)"
                $lastPhase = $statusResp.phase
            }
            
            if ($statusResp.status -in @("complete", "error", "partial")) {
                Write-Status "Getting results"
                try {
                    $resultsResp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/pipeline/results/$jobId" `
                        -TimeoutSec 5 | Select-Object -ExpandProperty Content | ConvertFrom-Json
                    
                    $metrics = $resultsResp.metrics
                    Write-Host ""
                    Write-Host "  METRICS:"
                    Write-Host "    Total time:       $('{0:F3}' -f $metrics.total_time)s"
                    Write-Host "    Ingestion:        $('{0:F3}' -f $metrics.ingest_time)s"
                    Write-Host "    Features:         $('{0:F3}' -f $metrics.feature_time)s"
                    Write-Host "    Inference:        $('{0:F3}' -f $metrics.inference_time)s"
                    Write-Host "    Signals:          $($metrics.signals_generated)"
                    Write-Host "    Avg Confidence:   $('{0:F2}%' -f ($metrics.avg_confidence * 100))"
                    
                    return @{
                        JobId = $jobId
                        Status = $statusResp.status
                        TotalTime = $metrics.total_time
                        IngestTime = $metrics.ingest_time
                        FeatureTime = $metrics.feature_time
                        InferenceTime = $metrics.inference_time
                        SignalsCount = $metrics.signals_generated
                        AvgConfidence = $metrics.avg_confidence
                        RunNumber = $RunNum
                    }
                } catch {
                    Write-Status "Get results" "FAILED: $_"
                    return $null
                }
            }
        } catch {
            # Continue polling
        }
    }
    
    Write-Status "Pipeline timeout" "FAILED"
    return $null
}

function Show-Analysis {
    param([array]$Results)
    
    if ($Results.Count -lt 2) { return }
    
    Write-Section "TIMING CONSISTENCY ANALYSIS"
    
    $validResults = $Results | Where-Object { $_ }
    $totalTimes = $validResults | Select-Object -ExpandProperty TotalTime
    $ingestTimes = $validResults | Select-Object -ExpandProperty IngestTime
    $featureTimes = $validResults | Select-Object -ExpandProperty FeatureTime
    $inferenceTimes = $validResults | Select-Object -ExpandProperty InferenceTime
    
    function Get-Stats {
        param([array]$Values)
        $avg = ($Values | Measure-Object -Average).Average
        $min = ($Values | Measure-Object -Minimum).Minimum
        $max = ($Values | Measure-Object -Maximum).Maximum
        $variance = ($Values | ForEach-Object { [Math]::Pow($_ - $avg, 2) } | Measure-Object -Average).Average
        $stdDev = [Math]::Sqrt($variance)
        return @{
            Avg = $avg
            Min = $min
            Max = $max
            StdDev = $stdDev
        }
    }
    
    $totalStats = Get-Stats $totalTimes
    $ingestStats = Get-Stats $ingestTimes
    $featureStats = Get-Stats $featureTimes
    $inferenceStats = Get-Stats $inferenceTimes
    
    Write-Host ""
    Write-Host "  TOTAL TIME:"
    Write-Host "    Average:     $('{0:F3}' -f $totalStats.Avg)s"
    Write-Host "    Min - Max:   $('{0:F3}' -f $totalStats.Min)s - $('{0:F3}' -f $totalStats.Max)s"
    Write-Host "    Std Dev:     $('{0:F3}' -f $totalStats.StdDev)s"
    
    Write-Host ""
    Write-Host "  INGESTION TIME:"
    Write-Host "    Average:     $('{0:F3}' -f $ingestStats.Avg)s"
    Write-Host "    Min - Max:   $('{0:F3}' -f $ingestStats.Min)s - $('{0:F3}' -f $ingestStats.Max)s"
    Write-Host "    Std Dev:     $('{0:F3}' -f $ingestStats.StdDev)s"
    
    Write-Host ""
    Write-Host "  FEATURES TIME:"
    Write-Host "    Average:     $('{0:F3}' -f $featureStats.Avg)s"
    Write-Host "    Min - Max:   $('{0:F3}' -f $featureStats.Min)s - $('{0:F3}' -f $featureStats.Max)s"
    Write-Host "    Std Dev:     $('{0:F3}' -f $featureStats.StdDev)s"
    
    Write-Host ""
    Write-Host "  INFERENCE TIME:"
    Write-Host "    Average:     $('{0:F3}' -f $inferenceStats.Avg)s"
    Write-Host "    Min - Max:   $('{0:F3}' -f $inferenceStats.Min)s - $('{0:F3}' -f $inferenceStats.Max)s"
    Write-Host "    Std Dev:     $('{0:F3}' -f $inferenceStats.StdDev)s"
    
    $totalVar = if ($totalStats.Avg -gt 0) { $totalStats.StdDev / $totalStats.Avg } else { 0 }
    Write-Host ""
    Write-Host "  CONSISTENCY:"
    if ($totalVar -lt 0.05) {
        Write-Host "    [EXCELLENT] Variance is less than 5%" -ForegroundColor Green
    } elseif ($totalVar -lt 0.15) {
        Write-Host "    [GOOD] Variance is 5-15%" -ForegroundColor Yellow
    } else {
        Write-Host "    [POOR] Variance is more than 15%" -ForegroundColor Red
    }
}

# ============== MAIN EXECUTION ==============

try {
    $startTime = Get-Date
    $results = @()
    
    Write-Host ""
    Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║     ORCHESTRATOR SERVICE TEST - PHASE 1E VALIDATION       ║" -ForegroundColor Cyan
    Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    
    # Start service
    $servicePID = Start-Service $Port
    
    # Health check
    if (-not (Test-Health $Port)) {
        Write-Host "Service failed health check. Exiting." -ForegroundColor Red
        Stop-Process -Id $servicePID -Force -EA SilentlyContinue
        exit 1
    }
    
    # Run tests
    for ($i = 1; $i -le $Iterations; $i++) {
        $result = Run-Test $Port $Mode $i
        $results += $result
        
        if ($i -lt $Iterations) {
            Write-Host ""
            Write-Host "  Waiting 2s before next run..." -ForegroundColor Gray
            Start-Sleep -Seconds 2
        }
    }
    
    # Analysis
    Show-Analysis $results
    
    # Summary
    $endTime = Get-Date
    $elapsed = ($endTime - $startTime).TotalSeconds
    
    Write-Section "TEST SUMMARY"
    Write-Host ""
    $passed = ($results | Where-Object { $_ }).Count
    $failed = $Iterations - $passed
    Write-Host "  Passed:            $passed / $Iterations"
    Write-Host "  Failed:            $failed"
    Write-Host "  Total Time:        $('{0:F1}' -f $elapsed)s"
    Write-Host ""
    
    if ($failed -eq 0) {
        Write-Host "  [SUCCESS] All tests passed" -ForegroundColor Green
    } else {
        Write-Host "  [WARNING] Some tests failed" -ForegroundColor Yellow
    }
    
} finally {
    Write-Host ""
    Write-Host "Cleaning up..." -ForegroundColor Gray
    if ($servicePID) {
        Stop-Process -Id $servicePID -Force -EA SilentlyContinue
        Write-Host "Service stopped" -ForegroundColor Gray
    }
}

Write-Host ""

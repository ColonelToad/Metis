`# Test Orchestrator Service
`$Port = 9000
`$Iterations = 3
`$Mode = "DEV"

Write-Host "Starting test..." -ForegroundColor Cyan

`# Kill existing process
`$procs = netstat -ano 2>$null | Select-String ":$Port" | ForEach-Object { (`$_ -split '\s+')[-1] }
foreach (`$pid in `$procs) {
    if (`$pid -and `$pid -ne "PID") {
        Stop-Process -Id `$pid -Force -EA SilentlyContinue
        Write-Host "Killed process on port $Port"
    }
}

`# Build
Write-Host "Building orchestrator binary..."
cd c:\Users\legot\Metis\metis\src-tauri
cargo build --bin orchestrator 2>&1 | Select-Object -Last 5

`# Start service
Write-Host "Starting service..."
`$project_root = "c:\Users\legot\Metis\metis\src-tauri"
`$process = Start-Process -FilePath "target\debug\orchestrator.exe" -ArgumentList `$project_root -NoNewWindow -PassThru
`$servicePID = `$process.Id
Write-Host "Service started with PID: `$servicePID"

`# Wait for service
`$ready = `$false
for (`$i = 0; `$i -lt 30; `$i++) {
    try {
        `$result = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 1 -EA SilentlyContinue
        if (`$result.StatusCode -eq 200) {
            `$ready = `$true
            break
        }
    } catch { }
    Start-Sleep -Milliseconds 200
}

if (`$ready) {
    Write-Host "Service is ready" -ForegroundColor Green
} else {
    Write-Host "Service failed to start" -ForegroundColor Red
    Stop-Process -Id `$servicePID -Force -EA SilentlyContinue
    exit 1
}

`# Run tests
`$results = @()
for (`$run = 1; `$run -le `$Iterations; `$run++) {
    Write-Host ""
    Write-Host "Run $run..." -ForegroundColor Cyan
    
    `$start = Get-Date
    `$payload = @{ mode = `$Mode; force_refresh = `$false } | ConvertTo-Json
    
    try {
        `$resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/pipeline/run" `
            -Method POST -Body `$payload -ContentType "application/json" -TimeoutSec 10
        `$data = `$resp.Content | ConvertFrom-Json
        `$jobId = `$data.job_id
        Write-Host "  Job: $jobId"
        
        `# Poll for completion
        `$completed = `$false
        for (`$i = 0; `$i -lt 240; `$i++) {
            Start-Sleep -Milliseconds 500
            try {
                `$status = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/pipeline/status/$jobId" -TimeoutSec 5
                `$statusData = `$status.Content | ConvertFrom-Json
                
                if (`$statusData.status -in @("complete", "error", "partial")) {
                    `$results_data = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/pipeline/results/$jobId" -TimeoutSec 5
                    `$resultsJson = `$results_data.Content | ConvertFrom-Json
                    `$metrics = `$resultsJson.metrics
                    
                    `$totalTime = `$metrics.total_time
                    `$ingestTime = `$metrics.ingest_time
                    `$featureTime = `$metrics.feature_time
                    `$inferenceTime = `$metrics.inference_time
                    
                    Write-Host "  Total: $([Math]::Round(`$totalTime, 3))s (ingest: $([Math]::Round(`$ingestTime, 3))s, features: $([Math]::Round(`$featureTime, 3))s, inference: $([Math]::Round(`$inferenceTime, 3))s)"
                    
                    `$results += @{
                        Total = `$totalTime
                        Ingest = `$ingestTime
                        Features = `$featureTime
                        Inference = `$inferenceTime
                    }
                    
                    `$completed = `$true
                    break
                }
            } catch { }
        }
        
        if (-not `$completed) {
            Write-Host "  TIMEOUT" -ForegroundColor Red
        }
    } catch {
        Write-Host "  ERROR: $_" -ForegroundColor Red
    }
    
    if (`$run -lt `$Iterations) {
        Write-Host "  Waiting 2s..."
        Start-Sleep -Seconds 2
    }
}

`# Summary
Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
if (`$results.Count -gt 0) {
    `$totalTimes = `$results | Select-Object -ExpandProperty Total
    `$avg = (`$totalTimes | Measure-Object -Average).Average
    `$min = (`$totalTimes | Measure-Object -Minimum).Minimum
    `$max = (`$totalTimes | Measure-Object -Maximum).Maximum
    
    Write-Host "  Completed: $(`$results.Count) / $Iterations"
    Write-Host "  Total Time - Avg: $([Math]::Round(`$avg, 3))s, Min: $([Math]::Round(`$min, 3))s, Max: $([Math]::Round(`$max, 3))s"
}

`# Cleanup
Write-Host ""
Write-Host "Cleanup..."
Stop-Process -Id `$servicePID -Force -EA SilentlyContinue
Write-Host "Done" -ForegroundColor Green

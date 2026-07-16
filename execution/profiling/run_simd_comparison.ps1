#!/usr/bin/env powershell
<#
.SYNOPSIS
    Run 3 isolated SIMD benchmark trials on Windows with system state monitoring
.DESCRIPTION
    - Clears Criterion cache before each trial
    - Monitors CPU freq, temp, load in parallel with benchmarks
    - Logs all data to CSV for cross-platform comparison
#>

param(
    [int]$Trials = 3,
    [switch]$SkipCleanup = $false
)

$ErrorActionPreference = "Stop"

# Setup
$ProjectRoot = "c:\Users\legot\Metis"
$CoreDir = "$ProjectRoot\metis-core"
$ProfDir = "$ProjectRoot\profiling"
$TimestampStr = (Get-Date -Format "yyyy-MM-dd_HHmmss")
$TrialDir = "$ProfDir\simd_trials_windows_$TimestampStr"
$MetricsFile = "$TrialDir\system_metrics.csv"
$BenchmarkResultsFile = "$TrialDir\benchmark_results.csv"
$SummaryFile = "$TrialDir\summary.txt"

# Create output directory
New-Item -ItemType Directory -Path $TrialDir -Force | Out-Null

function Write-Log {
    param([string]$Message, [switch]$NoTimestamp)
    $ts = if (-not $NoTimestamp) { "$(Get-Date -Format 'HH:mm:ss') " } else { "" }
    $line = "$ts$Message"
    Write-Host $line
    Add-Content -Path "$TrialDir\run.log" -Value $line
}

function Get-SystemMetrics {
    param([string]$TrialNum)
    
    $cpu = Get-WmiObject Win32_Processor
    $os = Get-WmiObject Win32_OperatingSystem
    $process = Get-Process | Measure-Object
    
    return @{
        Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Trial = $TrialNum
        CPU_Model = $cpu.Name
        CPU_Cores = $cpu.NumberOfCores
        CPU_LogicalCores = $cpu.NumberOfLogicalProcessors
        CPU_MaxClockMHz = $cpu.MaxClockSpeed
        CPU_CurrentClockMHz = $cpu.CurrentClockSpeed
        Memory_TotalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
        Memory_FreeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
        Memory_UsedPercent = [math]::Round((1 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize)) * 100, 1)
        ProcessCount = $process.Count
    }
}

function Get-CPUFrequency {
    # Attempt to read current CPU frequency
    try {
        $freq = Get-WmiObject Win32_Processor | Select-Object -ExpandProperty CurrentClockSpeed
        return $freq
    }
    catch {
        return $null
    }
}

function Monitor-System {
    param(
        [string]$TrialNum,
        [int]$DurationSeconds = 120,
        [string]$MetricsFile
    )
    
    Write-Log "Starting system monitoring for Trial $TrialNum (duration: ${DurationSeconds}s)"
    
    # Add header if file doesn't exist
    if (-not (Test-Path $MetricsFile)) {
        $header = "Timestamp,Trial,Elapsed_Sec,CPU_MHz,Memory_Used_GB,Memory_Percent,Process_Count"
        Add-Content -Path $MetricsFile -Value $header
    }
    
    $startTime = Get-Date
    $elapsed = 0
    
    while ($elapsed -lt $DurationSeconds) {
        $now = Get-Date
        $elapsed = [int]($now - $startTime).TotalSeconds
        
        $metrics = Get-SystemMetrics -TrialNum $TrialNum
        $cpuFreq = Get-CPUFrequency
        $os = Get-WmiObject Win32_OperatingSystem
        $procCount = (Get-Process | Measure-Object).Count
        
        $line = "$($metrics.Timestamp),$TrialNum,$elapsed,$cpuFreq,$($metrics.Memory_FreeGB),$($metrics.Memory_UsedPercent),$procCount"
        Add-Content -Path $MetricsFile -Value $line
        
        Start-Sleep -Milliseconds 500
    }
    
    Write-Log "System monitoring complete for Trial $TrialNum"
}

function Run-Benchmark-Trial {
    param(
        [int]$TrialNum
    )
    
    Write-Log "========== TRIAL $TrialNum =========="
    
    # Get pre-trial metrics
    $preTrial = Get-SystemMetrics -TrialNum $TrialNum
    Write-Log "Pre-trial state: CPU=$($preTrial['CPU_CurrentClockMHz'])MHz, Memory=$($preTrial['Memory_UsedPercent'])%"
    
    # Cleanup criterion cache if not first trial
    if ($TrialNum -gt 1 -and -not $SkipCleanup) {
        Write-Log "Clearing Criterion cache..."
        Remove-Item -Path "$CoreDir\target\criterion" -Recurse -Force -ErrorAction SilentlyContinue | Out-Null
    }
    
    # Start background monitoring (estimated 60-90 seconds for benchmark)
    $monitorJob = Start-Job -ScriptBlock {
        param($TrialNum, $MetricsFile, $CoreDir)
        & {
            function Get-SystemMetrics {
                param([string]$TrialNum)
                $cpu = Get-WmiObject Win32_Processor
                $os = Get-WmiObject Win32_OperatingSystem
                $process = Get-Process | Measure-Object
                return @{
                    Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
                    Memory_FreeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
                    Memory_UsedPercent = [math]::Round((1 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize)) * 100, 1)
                    CPU_CurrentClockMHz = $cpu.CurrentClockSpeed
                    ProcessCount = $process.Count
                }
            }
            
            if (-not (Test-Path $MetricsFile)) {
                Add-Content -Path $MetricsFile -Value "Timestamp,Trial,Elapsed_Sec,CPU_MHz,Memory_Free_GB,Memory_Used_Percent,Process_Count"
            }
            
            $startTime = Get-Date
            for ($i = 0; $i -lt 240; $i++) {  # 240 * 500ms = 120 seconds max
                $elapsed = [int]((Get-Date) - $startTime).TotalSeconds
                $metrics = Get-SystemMetrics -TrialNum $TrialNum
                $line = "$($metrics.Timestamp),$TrialNum,$elapsed,$($metrics.CPU_CurrentClockMHz),$($metrics.Memory_FreeGB),$($metrics.Memory_UsedPercent),$($metrics.ProcessCount)"
                Add-Content -Path $MetricsFile -Value $line
                Start-Sleep -Milliseconds 500
            }
        }
    } -ArgumentList $TrialNum, $MetricsFile, $CoreDir
    
    # Run benchmark
    Write-Log "Running benchmark..."
    Push-Location $CoreDir
    $benchmarkOutput = cmd.exe /c "cargo bench --bench simd_vectorization 2>&1" | Tee-Object -FilePath "$TrialDir\trial_${TrialNum}_raw.txt"
    Pop-Location
    
    # Stop monitoring
    Stop-Job -Job $monitorJob -ErrorAction SilentlyContinue | Out-Null
    Remove-Job -Job $monitorJob -Force -ErrorAction SilentlyContinue | Out-Null
    
    # Extract results from benchmark output
    Write-Log "Parsing benchmark results..."
    $results = Parse-Benchmark-Output -Output $benchmarkOutput -TrialNum $TrialNum
    
    # Add to results file
    if ($results) {
        foreach ($result in $results) {
            $line = "$($result.Trial),$($result.Benchmark),$($result.Time_NS),$($result.Lower_NS),$($result.Upper_NS),$($result.Change_Percent)"
            Add-Content -Path $BenchmarkResultsFile -Value $line
        }
    }
    
    # Get post-trial metrics
    $postTrial = Get-SystemMetrics -TrialNum $TrialNum
    Write-Log "Post-trial state: CPU=$($postTrial['CPU_CurrentClockMHz'])MHz, Memory=$($postTrial['Memory_UsedPercent'])%"
    Write-Log ""
}

function Parse-Benchmark-Output {
    param(
        [string[]]$Output,
        [int]$TrialNum
    )
    
    $results = @()
    $currentBench = $null
    
    foreach ($line in $Output) {
        # Detect benchmark name
        if ($line -match "^simd_normalization/(.*?)$|^euclidean_distance/(.*?)$") {
            $currentBench = if ($matches[1]) { $matches[1] } else { $matches[2] }
        }
        
        # Extract timing: time:   [156.58 ns 160.55 ns 164.79 ns]
        if ($line -match "time:\s+\[([0-9.]+)\s+ns\s+([0-9.]+)\s+ns\s+([0-9.]+)\s+ns\]") {
            $lower = $matches[1]
            $mean = $matches[2]
            $upper = $matches[3]
            
            # Extract change: change: [-0.3712% +2.4354% +5.0866%]
            $changeLine = ($Output | Where-Object { $_ -match "change:" } | Select-Object -Last 1)
            $changePercent = 0
            if ($changeLine -match "change:\s+\[.*\s\+([0-9.]+)%") {
                $changePercent = $matches[1]
            }
            
            $results += @{
                Trial = $TrialNum
                Benchmark = $currentBench
                Time_NS = $mean
                Lower_NS = $lower
                Upper_NS = $upper
                Change_Percent = $changePercent
            }
        }
    }
    
    return $results
}

# Main execution
Write-Log "========== SIMD Benchmark Comparison - Windows =========="
Write-Log "Project: $ProjectRoot"
Write-Log "Trials: $Trials"
Write-Log "Output: $TrialDir"
Write-Log ""

# Initialize results file header
$benchmarkHeader = "Trial,Benchmark,Time_NS,Lower_NS,Upper_NS,Change_Percent"
Add-Content -Path $BenchmarkResultsFile -Value $benchmarkHeader

# Get baseline system info
$baselineMetrics = Get-SystemMetrics -TrialNum "BASELINE"
Write-Log "Baseline System State:" -NoTimestamp
Write-Log "  CPU Model: $($baselineMetrics.CPU_Model)" -NoTimestamp
Write-Log "  CPU Cores: $($baselineMetrics.CPU_Cores) / $($baselineMetrics.CPU_LogicalCores) logical" -NoTimestamp
Write-Log "  CPU Max Clock: $($baselineMetrics.CPU_MaxClockMHz) MHz" -NoTimestamp
Write-Log "  Total Memory: $($baselineMetrics.Memory_TotalGB) GB" -NoTimestamp
Write-Log ""

# Run trials
for ($trial = 1; $trial -le $Trials; $trial++) {
    Run-Benchmark-Trial -TrialNum $trial
}

# Summary
Write-Log "========== RESULTS SUMMARY =========="
Write-Log "Benchmark results: $BenchmarkResultsFile"
Write-Log "System metrics: $MetricsFile"
Write-Log "Raw outputs: $TrialDir\trial_*_raw.txt"
Write-Log ""
Write-Log "Next: Run WSL baseline with wsl-simd-comparison.sh"
Write-Log "Then: Compare results with comparison_analysis.ps1"

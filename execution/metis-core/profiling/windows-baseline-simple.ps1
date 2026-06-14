#!/usr/bin/env powershell
<#
.SYNOPSIS
    Build and benchmark metis-core on Windows
.DESCRIPTION
    Simplified version that directly runs benchmarks
#>

param(
    [switch]$Clean = $false,
    [switch]$Profile = $false
)

$ErrorActionPreference = "Continue"

# Configuration
$ProjectRoot = "c:\Users\legot\Metis"
$CoreDir = Join-Path $ProjectRoot "metis-core"
$ProfilingDir = Join-Path $ProjectRoot "profiling"
$TimestampStr = (Get-Date -Format "yyyy-MM-dd_HHmmss")
$LogFile = Join-Path $ProfilingDir "windows_profiling_${TimestampStr}.log"

# Ensure profiling directory exists
if (-not (Test-Path $ProfilingDir)) {
    New-Item -ItemType Directory -Path $ProfilingDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message)
    $Timestamp = Get-Date -Format "HH:mm:ss"
    $LogLine = "[$Timestamp] $Message"
    Write-Host $LogLine
    Add-Content -Path $LogFile -Value $LogLine
}

Write-Log "====== Metis Hardware Profiling (Windows) ======"
Write-Log "Timestamp: $TimestampStr"
Write-Log "Output directory: $ProfilingDir"
Write-Log ""

# Change to core directory
Push-Location $CoreDir

# Clean if requested
if ($Clean) {
    Write-Log "Cleaning..."
    cargo clean
}

# Build
Write-Log "Building metis-core (release)..."
cargo build --release 2>&1 | Tee-Object -FilePath (Join-Path $ProfilingDir "build_${TimestampStr}.log") | Select-Object -Last 5
Write-Log "Build complete!"
Write-Log ""

# Benchmarks
Write-Log "Running SIMD vectorization benchmark..."
cargo bench --bench simd_vectorization 2>&1 | Tee-Object -FilePath (Join-Path $ProfilingDir "simd_${TimestampStr}.txt") | Select-Object -Last 10
Write-Log ""

Write-Log "Running lock-free fusion benchmark..."
cargo bench --bench lockfree_fusion 2>&1 | Tee-Object -FilePath (Join-Path $ProfilingDir "lockfree_${TimestampStr}.txt") | Select-Object -Last 10
Write-Log ""

Write-Log "Running Python-Rust bridge latency benchmark..."
cargo bench --bench bridge_latency 2>&1 | Tee-Object -FilePath (Join-Path $ProfilingDir "bridge_${TimestampStr}.txt") | Select-Object -Last 10
Write-Log ""

# Tests
Write-Log "Running full test suite..."
cargo test --release 2>&1 | Tee-Object -FilePath (Join-Path $ProfilingDir "tests_${TimestampStr}.log") | Select-Object -Last 20
Write-Log ""

Pop-Location

Write-Log "====== PROFILING COMPLETE ======"
Write-Log "Output files in $ProfilingDir`:"
Get-ChildItem -Path $ProfilingDir -Filter "*_${TimestampStr}*" | ForEach-Object {
    $SizeKB = [Math]::Round($_.Length/1KB)
    Write-Log "  - $($_.Name) (${SizeKB}KB)"
}
Write-Log ""
Write-Log "Next: Run WSL baseline and compare results"

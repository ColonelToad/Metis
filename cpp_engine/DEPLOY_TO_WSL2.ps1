# Deploy cpp_engine to WSL2 native filesystem and run setup
# Run this from PowerShell on Windows

$SourceDir = "C:\Users\legot\Metis\cpp_engine"
$WSL2_TargetDir = "/home/legot/projects/metis-cpp"

Write-Host "=== Deploying cpp_engine to WSL2 ===" -ForegroundColor Green
Write-Host "Source: $SourceDir"
Write-Host "Target: $WSL2_TargetDir"
Write-Host ""

# Step 1: Verify WSL2 is running
Write-Host "[1/3] Checking WSL2 status..."
$wslStatus = wsl --list --verbose 2>&1 | Select-String "Running"
if (-not $wslStatus) {
    Write-Host "WSL2 is not running. Start it with: wsl" -ForegroundColor Red
    exit 1
}
Write-Host "✓ WSL2 is running" -ForegroundColor Green
Write-Host ""

# Step 2: Copy files to WSL2
Write-Host "[2/3] Copying cpp_engine to WSL2..."
wsl bash -c "mkdir -p $(dirname $WSL2_TargetDir)"
wsl cp -r /mnt/c/Users/legot/Metis/cpp_engine /home/legot/projects/metis-cpp 2>&1
Write-Host "✓ Files copied" -ForegroundColor Green
Write-Host ""

# Step 3: Run setup script
Write-Host "[3/3] Running WSL2 setup script (DPDK build ~5-10 min)..."
Write-Host "This will:"
Write-Host "  - Install system dependencies (build-essential, meson, cmake, etc)"
Write-Host "  - Download and build DPDK 23.11 LTS"
Write-Host "  - Build Phase 1 tests on Linux"
Write-Host "  - Validate all Phase 1 tests pass"
Write-Host ""

$setupScript = @"
#!/bin/bash
set -e
cd ~/projects/metis-cpp
bash WSL2_WEEK1_SETUP.sh
"@

wsl bash -c $setupScript

Write-Host ""
Write-Host "=== Deployment Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Open WSL2: wsl"
Write-Host "  2. cd ~/projects/metis-cpp"
Write-Host "  3. Follow WSL2_VALIDATION_CHECKLIST.md"
Write-Host ""
Write-Host "Baseline latency capture:"
Write-Host "  cd build && ./benchmark_runner --benchmark_min_time=0.1 --benchmark_repetitions=1"
Write-Host ""

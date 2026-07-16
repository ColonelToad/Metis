#!/usr/bin/env powershell
<#
.SYNOPSIS
    Diagnostic script to verify SIMD code is actually being compiled and executed
.DESCRIPTION
    - Checks if .cargo/config.toml has AVX2/FMA enabled
    - Checks if SIMD instructions exist in the binary
    - Runs a simple perf test to measure scalar vs SIMD
    - Interprets results to identify compilation vs algorithm issues

.CRITICAL
    SIMD performance requires .cargo/config.toml with proper rustflags!
    Without target-feature=+avx2,+fma, intrinsics won't be compiled in.
#>

$ProjectRoot = "c:\Users\legot\Metis\metis-core"
$CargoConfigPath = "$ProjectRoot\.cargo\config.toml"
$TS = Get-Date -Format "yyyy-MM-dd_HHmmss"
$DiagDir = "$ProjectRoot\simd_diagnostics_$TS"

New-Item -ItemType Directory -Path $DiagDir -Force | Out-Null

Write-Host "========== SIMD Execution Diagnostic ==========" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
Write-Host "Output: $DiagDir`n"

# 0. Check .cargo/config.toml
Write-Host "[0/5] Checking Cargo configuration for AVX2/FMA..." -ForegroundColor Yellow

if (Test-Path $CargoConfigPath) {
    $configContent = Get-Content $CargoConfigPath -Raw
    if ($configContent -match "target-feature.*\+avx2") {
        Write-Host "✅ .cargo/config.toml has AVX2 enabled" -ForegroundColor Green
        Write-Host "   (This is required for SIMD intrinsics to compile)" -ForegroundColor Gray
    } else {
        Write-Host "⚠️  .cargo/config.toml found but AVX2 not enabled!" -ForegroundColor Red
        Write-Host "   SIMD code will NOT be compiled. Ensure rustflags include '+avx2,+fma'" -ForegroundColor Red
    }
    
    if ($configContent -match "target-feature.*\+fma") {
        Write-Host "✅ FMA (fused multiply-add) enabled" -ForegroundColor Green
    } else {
        Write-Host "⚠️  FMA not in rustflags (optional but recommended)" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠️  No .cargo/config.toml found!" -ForegroundColor Red
    Write-Host "   Creating one with AVX2/FMA enabled..." -ForegroundColor Yellow
    
    New-Item -ItemType Directory -Path "$ProjectRoot\.cargo" -Force | Out-Null
    
    $configContent = @'
# Cargo configuration for SIMD builds
# Enable AVX2 and FMA CPU features for x86_64 targets

[build]
rustflags = ["-C", "target-feature=+avx2,+fma", "-C", "target-cpu=native"]

[profile.release]
opt-level = 3
lto = true
codegen-units = 1
'@
    
    Set-Content -Path $CargoConfigPath -Value $configContent
    Write-Host "✅ Created $CargoConfigPath with AVX2/FMA enabled" -ForegroundColor Green
}

Write-Host ""

Push-Location $ProjectRoot

# 1. Clean and build in release mode
Write-Host "[1/5] Cleaning and building in release mode..." -ForegroundColor Yellow
cargo clean 2>&1 | Out-Null
cargo build --release --example check_simd_execution 2>&1 | Tee-Object "$DiagDir\build.log" | Select-Object -Last 5

# 2. Run the simple test
Write-Host "`n[2/5] Running simple execution test (10000 iterations each)..." -ForegroundColor Yellow
$output = cargo run --release --example check_simd_execution 2>&1
$output | Tee-Object "$DiagDir\execution_test.txt"

# Parse results
$lines = @($output)
$simdLine = $lines | Select-String "SIMD speedup:"
if ($simdLine) {
    Write-Host "`n$simdLine" -ForegroundColor Green
    
    # Extract speedup value
    if ($simdLine -match "(\d+\.?\d*?)x") {
        $speedup = [float]$matches[1]
        if ($speedup -gt 3) {
            Write-Host "   ✅ Good SIMD speedup! AVX2 is working." -ForegroundColor Green
        } elseif ($speedup -gt 1) {
            Write-Host "   ⚠️  Modest speedup. AVX2 compiled but suboptimal." -ForegroundColor Yellow
        } else {
            Write-Host "   🔴 SIMD slower than scalar. Check .cargo/config.toml!" -ForegroundColor Red
        }
    }
}

# 3. Check for SIMD instructions in binary
Write-Host "`n[3/5] Checking for SIMD instructions in compiled library..." -ForegroundColor Yellow

$libPath = Get-Item "target\release\metis_core.dll" -ErrorAction SilentlyContinue
if ($libPath) {
    Write-Host "Found library: $($libPath.FullName)" -ForegroundColor Green
    
    Write-Host "`nSearching for AVX2 instructions (vmovups, vhaddps, vfmadd, etc)..."
    
    # Try objdump if available (via LLVM toolchain)
    $objdump = Get-Command objdump -ErrorAction SilentlyContinue
    if ($objdump) {
        Write-Host "Using objdump..."
        $disasm = & objdump -C -d $libPath.FullName 2>&1
        
        $avx_instructions = @()
        $avx_instructions += @($disasm | Select-String -Pattern "vmovups|vhaddps|vfmadd|vpaddq|vsubps|vfmsub" | Select-Object -First 20)
        
        if ($avx_instructions.Count -gt 0) {
            Write-Host "✅ Found $(($avx_instructions | Measure-Object).Count) AVX2 instructions in binary!" -ForegroundColor Green
            Write-Host "   (AVX2 intrinsics ARE being compiled)" -ForegroundColor Gray
            $avx_instructions | Tee-Object -FilePath "$DiagDir\avx2_instructions.txt" | Select-Object -First 5
        } else {
            Write-Host "🔴 No AVX2 instructions found!" -ForegroundColor Red
            Write-Host "   Ensure .cargo/config.toml has: rustflags = ['-C', 'target-feature=+avx2,+fma']" -ForegroundColor Red
            Write-Host "   Then run: cargo clean && cargo build --release" -ForegroundColor Red
        }
    } else {
        Write-Host "objdump not found, using strings method..." -ForegroundColor Yellow
        $strings_output = & strings $libPath.FullName 2>$null | Select-String "euclidean_distance"
        if ($strings_output) {
            Write-Host "Found function symbols (detailed disassembly not available)" -ForegroundColor Green
        }
    }
} else {
    Write-Host "🔴 No library found at target\release\metis_core.dll" -ForegroundColor Red
}

# 4. Check Criterion cache
Write-Host "`n[4/5] Checking Criterion baseline data..." -ForegroundColor Yellow

$criterionDir = "target\criterion"
if (Test-Path $criterionDir) {
    $estimatedPath = Get-Item "$criterionDir\simd_normalization\simd_avx2\base\estimates.json" -ErrorAction SilentlyContinue
    if ($estimatedPath) {
        Write-Host "Found Criterion estimates:" -ForegroundColor Green
        Get-Content $estimatedPath | ConvertFrom-Json | Format-Table -AutoSize
    } else {
        Write-Host "Criterion data exists but no estimates.json found" -ForegroundColor Yellow
    }
} else {
    Write-Host "No Criterion data (expected if cache was cleared)" -ForegroundColor Yellow
}

# 5. Summary and next steps
Write-Host "`n[5/5] Interpreting results..." -ForegroundColor Yellow

Pop-Location

Write-Host "`n========== DIAGNOSTIC COMPLETE ==========" -ForegroundColor Cyan
Write-Host "Output saved to: $DiagDir"
Write-Host ""
Write-Host "INTERPRETATION GUIDE:"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Write-Host ""
Write-Host "✅ SIMD speedup > 3x:"
Write-Host "   Code is working. Proceed to benchmark suite."
Write-Host ""
Write-Host "⚠️  SIMD speedup 1-3x:"
Write-Host "   AVX2 compiled but suboptimal. Check algorithm (horizontal sum, etc)."
Write-Host ""
Write-Host "🔴 SIMD slower than scalar or speedup < 1x:"
Write-Host "   AVX2 is NOT being compiled. Fix .cargo/config.toml:"
Write-Host "   Required: rustflags = ['-C', 'target-feature=+avx2,+fma']"
Write-Host "   Then: cargo clean && cargo build --release"
Write-Host ""
Write-Host "NEXT STEPS:"
Write-Host "  1. If AVX2 working: Run Windows benchmark suite"
Write-Host "     .\run_simd_comparison.ps1 -Trials 3"
Write-Host ""
Write-Host "  2. If AVX2 not working: Fix .cargo/config.toml, then re-run this diagnostic"
Write-Host ""
Write-Host "  3. After Windows: Run WSL benchmarks to compare platforms"

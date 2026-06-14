#!/usr/bin/env powershell
<#
.SYNOPSIS
    Audit Windows development environment dependencies for Metis
.DESCRIPTION
    Scans for installed tools, compilers, runtimes, and package managers
    Outputs findings to a structured report
#>

$ReportPath = "metis_windows_audit_$(Get-Date -Format 'yyyy-MM-dd_HHmmss').txt"

Write-Host "========== Windows Environment Audit ==========" -ForegroundColor Cyan
Write-Host "Report: $ReportPath`n"

$report = @()

function Check-Command {
    param([string]$Name, [string]$Command = $Name)
    
    $exists = Get-Command $Command -ErrorAction SilentlyContinue
    if ($exists) {
        try {
            $version = & $Command --version 2>&1 | Select-Object -First 1
            return @{ Found = $true; Version = $version }
        }
        catch {
            return @{ Found = $true; Version = "installed (version unknown)" }
        }
    }
    return @{ Found = $false; Version = "NOT FOUND" }
}

function Check-Registry {
    param([string]$Path, [string]$Name)
    
    $item = Get-ItemProperty -Path $Path -ErrorAction SilentlyContinue
    if ($item) {
        return @{ Found = $true; Path = $item.PSPath }
    }
    return @{ Found = $false; Path = "NOT FOUND" }
}

# 1. RUST & CARGO
Write-Host "[1] Rust Ecosystem" -ForegroundColor Yellow
$result = Check-Command "rustc"
"Rust Compiler (rustc): $($result.Version)" | Tee-Object -Append $ReportPath
if ($result.Found) {
    $version = & rustc --version 2>&1
    $targets = & rustup target list 2>&1 | Select-String "installed"
    "  Targets: $targets" | Tee-Object -Append $ReportPath
}

$result = Check-Command "cargo"
"Cargo: $($result.Version)" | Tee-Object -Append $ReportPath

$result = Check-Command "rustup"
"Rustup: $($result.Version)" | Tee-Object -Append $ReportPath

# 2. C/C++ TOOLCHAIN
Write-Host "[2] C/C++ Compilers" -ForegroundColor Yellow
$result = Check-Command "cl" "cl.exe"
"MSVC (cl.exe): $(if ($result.Found) { $result.Version } else { 'NOT FOUND - Check Visual Studio installation' })" | Tee-Object -Append $ReportPath

$result = Check-Command "clang"
"Clang: $($result.Version)" | Tee-Object -Append $ReportPath

$result = Check-Command "gcc"
"GCC: $($result.Version)" | Tee-Object -Append $ReportPath

# 3. BUILD TOOLS
Write-Host "[3] Build Tools" -ForegroundColor Yellow
$result = Check-Command "cmake"
"CMake: $($result.Version)" | Tee-Object -Append $ReportPath

$result = Check-Command "ninja"
"Ninja: $($result.Version)" | Tee-Object -Append $ReportPath

$result = Check-Command "meson"
"Meson: $($result.Version)" | Tee-Object -Append $ReportPath

# 4. PYTHON
Write-Host "[4] Python" -ForegroundColor Yellow
$result = Check-Command "python"
"Python: $($result.Version)" | Tee-Object -Append $ReportPath

if ($result.Found) {
    $packages = & python -m pip list 2>&1 | Select-Object -First 20
    "  Installed packages (top 20):" | Tee-Object -Append $ReportPath
    $packages | Tee-Object -Append $ReportPath
}

# 5. NODE/NPM
Write-Host "[5] Node.js" -ForegroundColor Yellow
$result = Check-Command "node"
"Node.js: $($result.Version)" | Tee-Object -Append $ReportPath

$result = Check-Command "npm"
"npm: $($result.Version)" | Tee-Object -Append $ReportPath

# 6. PACKAGE MANAGERS
Write-Host "[6] Package Managers" -ForegroundColor Yellow
$result = Check-Command "choco"
"Chocolatey: $(if ($result.Found) { 'FOUND' } else { 'NOT FOUND' })" | Tee-Object -Append $ReportPath

$result = Check-Command "vcpkg"
"vcpkg: $(if ($result.Found) { 'FOUND' } else { 'NOT FOUND' })" | Tee-Object -Append $ReportPath

# 7. GIT & VERSION CONTROL
Write-Host "[7] Version Control" -ForegroundColor Yellow
$result = Check-Command "git"
"Git: $($result.Version)" | Tee-Object -Append $ReportPath

# 8. SYSTEM INFO
Write-Host "[8] System Information" -ForegroundColor Yellow
"" | Tee-Object -Append $ReportPath
"OS Version:" | Tee-Object -Append $ReportPath
Get-WmiObject Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber | Tee-Object -Append $ReportPath

"CPU:" | Tee-Object -Append $ReportPath
Get-WmiObject Win32_Processor | Select-Object Name, Cores, Threads | Tee-Object -Append $ReportPath

"Memory:" | Tee-Object -Append $ReportPath
$mem = Get-WmiObject Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum
"Total: $([math]::Round($mem.Sum / 1GB, 2)) GB" | Tee-Object -Append $ReportPath

# 9. ENVIRONMENT VARIABLES
Write-Host "[9] Key Environment Variables" -ForegroundColor Yellow
"" | Tee-Object -Append $ReportPath
"PATH length: $($env:PATH.Length) characters" | Tee-Object -Append $ReportPath
"RUST_BACKTRACE: $($env:RUST_BACKTRACE)" | Tee-Object -Append $ReportPath
"CARGO_NET_GIT_FETCH_WITH_CLI: $($env:CARGO_NET_GIT_FETCH_WITH_CLI)" | Tee-Object -Append $ReportPath

Write-Host "`n========== Audit Complete ==========" -ForegroundColor Cyan
Write-Host "Report saved to: $ReportPath"
Get-Content $ReportPath

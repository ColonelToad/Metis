#!/usr/bin/env bash
#
# Audit WSL development environment dependencies for Metis
# Scans for installed tools, libraries, runtimes, and package managers
#

REPORT="metis_wsl_audit_$(date +%Y-%m-%d_%H%M%S).txt"

{
    echo "========== WSL Environment Audit =========="
    echo "Report: $REPORT"
    echo ""
    
    # 1. SYSTEM INFO
    echo "[1] System Information"
    echo "OS: $(lsb_release -d 2>/dev/null | cut -f2)"
    echo "Kernel: $(uname -r)"
    echo "CPU Cores: $(nproc)"
    echo "Memory: $(free -h | grep Mem | awk '{print $2}')"
    
    # Check if running in WSL
    if grep -qi microsoft /proc/version; then
        echo "WSL Version: WSL2 detected"
    else
        echo "WSL Version: Native Linux detected"
    fi
    echo ""
    
    # 2. RUST ECOSYSTEM
    echo "[2] Rust Ecosystem"
    if command -v rustc &> /dev/null; then
        echo "Rust Compiler: $(rustc --version)"
        echo "Cargo: $(cargo --version)"
        echo "Rustup: $(rustup --version)"
        echo "Installed targets: $(rustup target list | grep installed)"
    else
        echo "Rust: NOT INSTALLED"
    fi
    echo ""
    
    # 3. C/C++ TOOLCHAIN
    echo "[3] C/C++ Compilers"
    if command -v gcc &> /dev/null; then
        echo "GCC: $(gcc --version | head -1)"
    else
        echo "GCC: NOT INSTALLED"
    fi
    
    if command -v clang &> /dev/null; then
        echo "Clang: $(clang --version | head -1)"
    else
        echo "Clang: NOT INSTALLED"
    fi
    echo ""
    
    # 4. BUILD TOOLS
    echo "[4] Build Tools"
    if command -v cmake &> /dev/null; then
        echo "CMake: $(cmake --version | head -1)"
    else
        echo "CMake: NOT INSTALLED"
    fi
    
    if command -v make &> /dev/null; then
        echo "Make: $(make --version | head -1)"
    else
        echo "Make: NOT INSTALLED"
    fi
    
    if command -v ninja &> /dev/null; then
        echo "Ninja: $(ninja --version)"
    else
        echo "Ninja: NOT INSTALLED"
    fi
    echo ""
    
    # 5. PYTHON
    echo "[5] Python"
    if command -v python3 &> /dev/null; then
        echo "Python3: $(python3 --version)"
        echo "pip3 packages (top 20):"
        pip3 list 2>/dev/null | head -20
    else
        echo "Python3: NOT INSTALLED"
    fi
    echo ""
    
    # 6. NODE/NPM
    echo "[6] Node.js"
    if command -v node &> /dev/null; then
        echo "Node: $(node --version)"
        echo "npm: $(npm --version)"
    else
        echo "Node.js: NOT INSTALLED"
    fi
    echo ""
    
    # 7. SYSTEM LIBRARIES
    echo "[7] Key System Libraries"
    echo "glibc version: $(ldd --version | head -1)"
    
    if dpkg -l | grep -q "libssl-dev"; then
        echo "libssl-dev: INSTALLED"
    else
        echo "libssl-dev: NOT INSTALLED"
    fi
    
    if dpkg -l | grep -q "libssl"; then
        echo "libssl: $(dpkg -l | grep "^ii.*libssl" | awk '{print $2, $3}')"
    fi
    
    echo "OpenSSL: $(openssl version 2>/dev/null || echo 'NOT INSTALLED')"
    
    if dpkg -l | grep -q "pkg-config"; then
        echo "pkg-config: INSTALLED"
    else
        echo "pkg-config: NOT INSTALLED"
    fi
    echo ""
    
    # 8. GIT
    echo "[8] Version Control"
    if command -v git &> /dev/null; then
        echo "Git: $(git --version)"
    else
        echo "Git: NOT INSTALLED"
    fi
    echo ""
    
    # 9. PACKAGE MANAGERS
    echo "[9] Package Managers"
    if command -v apt &> /dev/null; then
        echo "apt: Available"
    fi
    
    if command -v apt-get &> /dev/null; then
        echo "apt-get: Available"
    fi
    
    if [ -f /etc/apt/sources.list ]; then
        echo "APT sources configured: $(wc -l < /etc/apt/sources.list) sources"
    fi
    echo ""
    
    # 10. ENVIRONMENT
    echo "[10] Key Environment Variables"
    echo "PATH: $(echo $PATH | tr ':' '\n' | wc -l) directories"
    echo "LD_LIBRARY_PATH: $LD_LIBRARY_PATH"
    echo "PKG_CONFIG_PATH: $PKG_CONFIG_PATH"
    echo ""
    
    # 11. MOUNTED FILESYSTEMS
    echo "[11] Mounted Filesystems"
    df -h | grep -E "^/|^Total"
    
} | tee "$REPORT"

echo ""
echo "========== Audit Complete =========="
echo "Report saved to: $REPORT"

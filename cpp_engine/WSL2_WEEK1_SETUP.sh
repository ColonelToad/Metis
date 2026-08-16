#!/bin/bash
# Week 1 WSL2 Setup: DPDK 23.11 + Phase 2 Test Infrastructure
# Run this inside WSL2 to prepare the environment for SBE parser + ingest engine development

set -e

PROJECT_HOME="${HOME}/projects/metis-cpp"
DPDK_VERSION="23.11"

echo "=== Phase 2 Week 1: WSL2 Setup ==="
echo "Target: $PROJECT_HOME"
echo ""

# Step 1: System dependencies
echo "[1/6] Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y \
    build-essential meson ninja-build pkg-config \
    libnuma-dev libssl-dev liburcu-dev libpcap-dev \
    cmake git python3-pip \
    linux-headers-$(uname -r)

# Step 2: Clone/copy cpp_engine to WSL2 native filesystem
echo "[2/6] Setting up project directory..."
mkdir -p "$PROJECT_HOME"
if [ ! -d "$PROJECT_HOME/.git" ]; then
    echo "Copying cpp_engine from /mnt/c/Users/legot/Metis/cpp_engine..."
    cp -r /mnt/c/Users/legot/Metis/cpp_engine/* "$PROJECT_HOME/"
    cd "$PROJECT_HOME"
    git init
    git config user.email "legotitian@gmail.com"
    git config user.name "Christopher"
else
    cd "$PROJECT_HOME"
fi

# Step 3: DPDK installation
echo "[3/6] Installing DPDK $DPDK_VERSION LTS..."
DPDK_BUILD_DIR="/tmp/dpdk-build-$DPDK_VERSION"
mkdir -p "$DPDK_BUILD_DIR"
cd "$DPDK_BUILD_DIR"

if [ ! -d "dpdk-$DPDK_VERSION" ]; then
    echo "Downloading DPDK..."
    wget -q "https://fast.dpdk.org/rel/dpdk-${DPDK_VERSION}.tar.xz"
    tar -xf "dpdk-${DPDK_VERSION}.tar.xz"
fi

cd "dpdk-${DPDK_VERSION}"
echo "Building DPDK (this may take 5-10 minutes)..."
meson setup build -Dprefix=/usr/local --buildtype=release -Dtests=false -Ddocs=false
ninja -C build
sudo ninja -C build install
echo "DPDK installed to /usr/local"

# Step 4: Update pkg-config path
echo "[4/6] Configuring pkg-config..."
export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH"
echo "export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:\$PKG_CONFIG_PATH" >> ~/.bashrc

# Step 5: CMake build
echo "[5/6] Building Phase 2 infrastructure..."
cd "$PROJECT_HOME"
cmake -B build -S . -DCMAKE_BUILD_TYPE=Release -DCMAKE_GENERATOR=Ninja
cmake --build build --config Release

# Step 6: Run tests
echo "[6/6] Running Phase 1 tests to validate build..."
cd build
ctest --verbose

echo ""
echo "=== Setup Complete ==="
echo "Phase 1 tests passed. Ready for Phase 2 implementation."
echo ""
echo "Next steps:"
echo "  1. cd $PROJECT_HOME"
echo "  2. Implement DpdkIngestEngine::DpdkIngestEngine() with EAL init"
echo "  3. Write mock packet injection tests in tests/"
echo "  4. Measure ingest latency with Google Benchmark"
echo ""

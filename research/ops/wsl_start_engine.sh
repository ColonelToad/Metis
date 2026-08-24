#!/usr/bin/env bash
# Launches the C++ metis-server inside WSL and holds the session open
# until :8080 answers — otherwise wsl.exe teardown kills the server
# before it binds. Invoked by the Tauri orchestrator (engines.rs) via:
#   wsl -d Debian -- bash /mnt/c/<repo>/research/ops/wsl_start_engine.sh [dir]
# The script lives in a FILE (not an inline argv string) because wsl.exe
# mangles quoted multi-token arguments during Win->Linux reconstruction.
DIR="${1:-/home/tolugenius/Projects/metis-cpp/cpp_engine}"
cd "$DIR" || exit 1
nohup ./build/src/bin/metis-server > /tmp/metis_cpp.log 2>&1 < /dev/null &
for i in $(seq 1 30); do ss -ltn | grep -q 8080 && break; sleep 0.5; done

#include "metis/dpdk_ingest.hpp"
#include <stdexcept>

namespace metis {

DpdkIngestEngine::DpdkIngestEngine(const DpdkIngestConfig& config) : config_(config) {
    // Phase 2 spike: stub implementation
    // After spike validates WSL2 multicast setup, implement:
    // 1. EAL initialization with --vdev fallback for WSL2
    // 2. Mempool allocation (typically 2M buffers @ 2KB each)
    // 3. Multicast socket setup and RX queue creation

    // For now, throw to indicate not yet implemented
    throw std::runtime_error("DpdkIngestEngine not yet implemented (Phase 2 spike in progress)");
}

DpdkIngestEngine::~DpdkIngestEngine() {
    // Phase 2: cleanup EAL resources
}

std::optional<MarketDataPacket> DpdkIngestEngine::poll_packet() {
    // Phase 2: non-blocking poll from RX queue
    return std::nullopt;
}

uint32_t DpdkIngestEngine::queue_depth() const {
    // Phase 2: query ring buffer
    return 0;
}

DpdkIngestEngine::Stats DpdkIngestEngine::stats() const {
    return {0, 0, 0};
}

}  // namespace metis

#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace metis {

/// Raw market data packet from CME MDP 3.0 multicast feed
struct MarketDataPacket {
    uint64_t arrival_ns;      // Nanosecond timestamp when packet arrived
    std::vector<uint8_t> data; // Raw UDP payload (SBE-encoded)
};

/// Configuration for DPDK ingest engine
struct DpdkIngestConfig {
    std::string multicast_ip;     // e.g., "224.0.17.1"
    uint16_t multicast_port;      // e.g., 14310
    std::string local_ip;          // Interface to bind to (e.g., "0.0.0.0")
    uint32_t ring_buffer_size;     // Power-of-2, e.g., 65536
    uint32_t max_pkt_len;          // MTU, typically 1500 or 9000
    bool enable_hardware_timestamps; // Use PTP if available
};

/// DPDK-backed kernel-bypass UDP multicast ingest engine
///
/// In production:
/// - Runs in isolated poll loop thread (pinned to core)
/// - Parses incoming packets into MarketDataPacket
/// - Feeds to SBE parser (non-blocking via ring buffer)
/// - Achieves <1µs latency from NIC to order book update
///
/// On WSL2 (development):
/// - May fall back to --vdev=eth_tap mode if no physical NIC
/// - Still benefits from DPDK mempool + ring buffer overhead reduction
class DpdkIngestEngine {
public:
    /// Initialize EAL and open multicast socket
    /// @param config Multicast address, port, ring size
    /// @throws std::runtime_error on EAL init failure or socket setup
    explicit DpdkIngestEngine(const DpdkIngestConfig& config);

    ~DpdkIngestEngine();

    /// Non-blocking poll for incoming packet
    /// @return Populated MarketDataPacket if available, nullopt if queue empty
    std::optional<MarketDataPacket> poll_packet();

    /// Get current queue depth (for monitoring)
    uint32_t queue_depth() const;

    /// Get statistics: packets received, dropped, timestamps
    struct Stats {
        uint64_t packets_received;
        uint64_t packets_dropped;
        uint64_t out_of_order_timestamps;
    };
    Stats stats() const;

private:
    DpdkIngestConfig config_;
    // EAL, mempool, and queue pointers will be stored here (void* for C compatibility)
    void* eal_handle_;
    void* mempool_;
    void* rx_queue_;
};

}  // namespace metis

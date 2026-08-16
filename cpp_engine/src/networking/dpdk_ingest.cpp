#include "metis/dpdk_ingest.hpp"

#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <net/if.h>
#include <ifaddrs.h>
#include <cstring>
#include <fcntl.h>
#include <stdexcept>
#include <thread>
#include <atomic>
#include <chrono>

namespace metis {

namespace {
    std::atomic<uint64_t> global_packets_received{0};
    std::atomic<uint64_t> global_packets_dropped{0};
    std::atomic<uint64_t> global_out_of_order{0};
}

DpdkIngestEngine::DpdkIngestEngine(const DpdkIngestConfig& config)
    : config_(config), eal_handle_(nullptr), mempool_(nullptr), rx_queue_(nullptr) {
    // Phase 2 Week 1: Basic multicast socket setup (no DPDK in WSL2 yet)
    // Later: integrate DPDK EAL + mempool for zero-copy buffering on native Linux

    // Step 1: Create UDP multicast socket
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) {
        throw std::runtime_error("Failed to create UDP socket");
    }

    // Step 2: Enable socket reuse
    int reuse = 1;
    if (setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse)) < 0) {
        close(sock);
        throw std::runtime_error("Failed to set SO_REUSEADDR");
    }

    // Step 3: Bind to multicast address + port
    struct sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(config_.multicast_port);
    // Bind to INADDR_ANY to receive from any interface
    addr.sin_addr.s_addr = htonl(INADDR_ANY);

    if (bind(sock, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        close(sock);
        throw std::runtime_error("Failed to bind multicast socket");
    }

    // Step 4: Join multicast group
    struct ip_mreq mreq{};
    mreq.imr_multiaddr.s_addr = inet_addr(config_.multicast_ip.c_str());
    mreq.imr_interface.s_addr = htonl(INADDR_ANY);

    if (setsockopt(sock, IPPROTO_IP, IP_ADD_MEMBERSHIP, &mreq, sizeof(mreq)) < 0) {
        close(sock);
        throw std::runtime_error("Failed to join multicast group");
    }

    // Step 5: Set non-blocking mode for polling
    int flags = fcntl(sock, F_GETFL, 0);
    fcntl(sock, F_SETFL, flags | O_NONBLOCK);

    eal_handle_ = reinterpret_cast<void*>(static_cast<intptr_t>(sock));
}

DpdkIngestEngine::~DpdkIngestEngine() {
    if (eal_handle_) {
        int sock = static_cast<int>(reinterpret_cast<intptr_t>(eal_handle_));
        close(sock);
    }
}

std::optional<MarketDataPacket> DpdkIngestEngine::poll_packet() {
    if (!eal_handle_) {
        return std::nullopt;
    }

    int sock = static_cast<int>(reinterpret_cast<intptr_t>(eal_handle_));
    std::vector<uint8_t> buffer(config_.max_pkt_len);

    // Non-blocking recvfrom
    ssize_t n = recvfrom(sock, buffer.data(), buffer.size(), 0, nullptr, nullptr);
    if (n <= 0) {
        return std::nullopt;
    }

    buffer.resize(n);
    uint64_t arrival_ns = std::chrono::nanoseconds(
        std::chrono::steady_clock::now().time_since_epoch()
    ).count();

    global_packets_received++;
    return MarketDataPacket{arrival_ns, std::move(buffer)};
}

uint32_t DpdkIngestEngine::queue_depth() const {
    // Placeholder: will query DPDK ring buffer depth in production
    return 0;
}

DpdkIngestEngine::Stats DpdkIngestEngine::stats() const {
    return {global_packets_received.load(), global_packets_dropped.load(), global_out_of_order.load()};
}

}  // namespace metis

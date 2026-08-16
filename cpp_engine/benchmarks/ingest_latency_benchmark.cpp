#include <benchmark/benchmark.h>
#include "metis/dpdk_ingest.hpp"
#include "metis/sbe_parser.hpp"

#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <thread>
#include <chrono>
#include <cstring>

namespace metis {

namespace {
    std::vector<uint8_t> BuildMockTradePacket() {
        std::vector<uint8_t> pkt;
        pkt.reserve(32);

        // SBE Frame Header (8 bytes)
        uint16_t block_length = 13;
        uint16_t template_id = 24;
        uint16_t schema_id = 1;
        uint16_t version = 1;

        uint8_t header[8];
        std::memcpy(header, &block_length, 2);
        std::memcpy(header + 2, &template_id, 2);
        std::memcpy(header + 4, &schema_id, 2);
        std::memcpy(header + 6, &version, 2);

        pkt.insert(pkt.end(), header, header + 8);

        // Trade message body (13 bytes)
        int64_t price = 5000000;  // 500.0000
        uint32_t qty = 100;
        uint8_t side = 0;

        uint8_t body[13];
        std::memcpy(body, &price, 8);
        std::memcpy(body + 8, &qty, 4);
        body[12] = side;

        pkt.insert(pkt.end(), body, body + 13);
        return pkt;
    }

    void SendMockPacket(const std::string& multicast_ip, uint16_t port,
                        const std::vector<uint8_t>& payload) {
        int sock = socket(AF_INET, SOCK_DGRAM, 0);
        if (sock < 0) return;

        struct sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(port);
        addr.sin_addr.s_addr = inet_addr(multicast_ip.c_str());

        sendto(sock, payload.data(), payload.size(), 0, (struct sockaddr*)&addr, sizeof(addr));
        close(sock);
    }
}

static void BM_SBEParserParseTrade(benchmark::State& state) {
    SBEParser parser;
    auto pkt = BuildMockTradePacket();

    for (auto _ : state) {
        benchmark::DoNotOptimize(parser.parse_packet(pkt));
    }
}
BENCHMARK(BM_SBEParserParseTrade);

static void BM_DpdkIngestEngineConstruction(benchmark::State& state) {
    DpdkIngestConfig config{
        .multicast_ip = "239.192.151.80",
        .multicast_port = 14310,
        .local_ip = "0.0.0.0",
        .ring_buffer_size = 65536,
        .max_pkt_len = 1500,
        .enable_hardware_timestamps = false,
    };

    for (auto _ : state) {
        DpdkIngestEngine engine(config);
    }
}
BENCHMARK(BM_DpdkIngestEngineConstruction);

static void BM_DpdkIngestEnginePoll(benchmark::State& state) {
    DpdkIngestConfig config{
        .multicast_ip = "239.192.151.80",
        .multicast_port = 14311,
        .local_ip = "0.0.0.0",
        .ring_buffer_size = 65536,
        .max_pkt_len = 1500,
        .enable_hardware_timestamps = false,
    };

    DpdkIngestEngine engine(config);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));

    auto pkt = BuildMockTradePacket();
    for (auto _ : state) {
        SendMockPacket(config.multicast_ip, config.multicast_port, pkt);
        benchmark::DoNotOptimize(engine.poll_packet());
    }
}
BENCHMARK(BM_DpdkIngestEnginePoll);

}  // namespace metis

BENCHMARK_MAIN();

#include <gtest/gtest.h>
#include "metis/dpdk_ingest.hpp"

#include <thread>
#include <chrono>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

namespace metis {

class DpdkIngestTest : public ::testing::Test {
protected:
    DpdkIngestConfig config{
        .multicast_ip = "239.192.151.80",      // CME test multicast
        .multicast_port = 14310,
        .local_ip = "0.0.0.0",
        .ring_buffer_size = 65536,
        .max_pkt_len = 1500,
        .enable_hardware_timestamps = false,
    };

    void SendMockPacket(const std::string& multicast_ip, uint16_t port,
                       const std::vector<uint8_t>& payload) {
        int sock = socket(AF_INET, SOCK_DGRAM, 0);
        ASSERT_GE(sock, 0);

        struct sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(port);
        addr.sin_addr.s_addr = inet_addr(multicast_ip.c_str());

        ssize_t sent = sendto(sock, payload.data(), payload.size(), 0,
                             (struct sockaddr*)&addr, sizeof(addr));
        EXPECT_EQ(sent, static_cast<ssize_t>(payload.size()));
        close(sock);
    }
};

TEST_F(DpdkIngestTest, ConstructorInitializesWithoutError) {
    EXPECT_NO_THROW({
        DpdkIngestEngine engine(config);
    });
}

TEST_F(DpdkIngestTest, CanReceiveMulticastPacket) {
    DpdkIngestEngine engine(config);

    // Give engine time to bind
    std::this_thread::sleep_for(std::chrono::milliseconds(10));

    std::vector<uint8_t> test_payload = {0x01, 0x02, 0x03, 0x04, 0x05};
    SendMockPacket(config.multicast_ip, config.multicast_port, test_payload);

    // Poll for packet (may need a few attempts due to network timing)
    std::optional<MarketDataPacket> pkt;
    for (int i = 0; i < 100; ++i) {
        pkt = engine.poll_packet();
        if (pkt) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    ASSERT_TRUE(pkt.has_value());
    EXPECT_EQ(pkt->data, test_payload);
    EXPECT_GT(pkt->arrival_ns, 0);
}

TEST_F(DpdkIngestTest, StatsTrackPackets) {
    DpdkIngestEngine engine(config);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));

    std::vector<uint8_t> payload = {0xAA, 0xBB};
    SendMockPacket(config.multicast_ip, config.multicast_port, payload);

    // Drain queue
    for (int i = 0; i < 100; ++i) {
        engine.poll_packet();
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    auto stats = engine.stats();
    EXPECT_GE(stats.packets_received, 1);
}

TEST_F(DpdkIngestTest, MultiplePacketsQueued) {
    DpdkIngestEngine engine(config);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));

    for (int i = 0; i < 5; ++i) {
        std::vector<uint8_t> payload = {static_cast<uint8_t>(i)};
        SendMockPacket(config.multicast_ip, config.multicast_port, payload);
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(50));

    int received = 0;
    for (int i = 0; i < 1000; ++i) {
        if (engine.poll_packet()) {
            received++;
        }
    }

    EXPECT_GE(received, 1);  // At least one packet received
}

}  // namespace metis

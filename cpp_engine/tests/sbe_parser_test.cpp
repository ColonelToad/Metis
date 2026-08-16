#include <gtest/gtest.h>
#include "metis/sbe_parser.hpp"

#include <cstring>

namespace metis {

class SBEParserTest : public ::testing::Test {
protected:
    SBEParser parser;

    std::vector<uint8_t> BuildTradePacket(uint32_t template_id, int64_t price, uint32_t qty, uint8_t side) {
        std::vector<uint8_t> pkt;
        pkt.reserve(32);

        // SBE Frame Header (8 bytes)
        uint16_t block_length = 13;
        uint16_t tid = template_id;
        uint16_t schema_id = 1;
        uint16_t version = 1;

        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&block_length),
                  reinterpret_cast<const uint8_t*>(&block_length) + 2);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&tid),
                  reinterpret_cast<const uint8_t*>(&tid) + 2);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&schema_id),
                  reinterpret_cast<const uint8_t*>(&schema_id) + 2);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&version),
                  reinterpret_cast<const uint8_t*>(&version) + 2);

        // Trade message body (13 bytes)
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&price),
                  reinterpret_cast<const uint8_t*>(&price) + 8);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&qty),
                  reinterpret_cast<const uint8_t*>(&qty) + 4);
        pkt.push_back(side);

        return pkt;
    }

    std::vector<uint8_t> BuildQuotePacket(uint32_t template_id, int64_t bid_price, uint32_t bid_qty,
                                          int64_t ask_price, uint32_t ask_qty) {
        std::vector<uint8_t> pkt;
        pkt.reserve(40);

        // SBE Frame Header (8 bytes)
        uint16_t block_length = 24;
        uint16_t tid = template_id;
        uint16_t schema_id = 1;
        uint16_t version = 1;

        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&block_length),
                  reinterpret_cast<const uint8_t*>(&block_length) + 2);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&tid),
                  reinterpret_cast<const uint8_t*>(&tid) + 2);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&schema_id),
                  reinterpret_cast<const uint8_t*>(&schema_id) + 2);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&version),
                  reinterpret_cast<const uint8_t*>(&version) + 2);

        // Quote message body (24 bytes)
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&bid_price),
                  reinterpret_cast<const uint8_t*>(&bid_price) + 8);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&bid_qty),
                  reinterpret_cast<const uint8_t*>(&bid_qty) + 4);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&ask_price),
                  reinterpret_cast<const uint8_t*>(&ask_price) + 8);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&ask_qty),
                  reinterpret_cast<const uint8_t*>(&ask_qty) + 4);

        return pkt;
    }

    std::vector<uint8_t> BuildDepthPacket(uint32_t template_id,
                                          const std::vector<std::pair<int64_t, uint32_t>>& bids,
                                          const std::vector<std::pair<int64_t, uint32_t>>& asks) {
        std::vector<uint8_t> pkt;
        size_t body_len = 2 + (bids.size() + asks.size()) * 12;
        pkt.reserve(8 + body_len);

        // SBE Frame Header (8 bytes)
        uint16_t block_length = body_len;
        uint16_t tid = template_id;
        uint16_t schema_id = 1;
        uint16_t version = 1;

        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&block_length),
                  reinterpret_cast<const uint8_t*>(&block_length) + 2);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&tid),
                  reinterpret_cast<const uint8_t*>(&tid) + 2);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&schema_id),
                  reinterpret_cast<const uint8_t*>(&schema_id) + 2);
        pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&version),
                  reinterpret_cast<const uint8_t*>(&version) + 2);

        // Depth message body
        pkt.push_back(bids.size());
        pkt.push_back(asks.size());

        for (const auto& [price, qty] : bids) {
            pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&price),
                      reinterpret_cast<const uint8_t*>(&price) + 8);
            pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&qty),
                      reinterpret_cast<const uint8_t*>(&qty) + 4);
        }

        for (const auto& [price, qty] : asks) {
            pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&price),
                      reinterpret_cast<const uint8_t*>(&price) + 8);
            pkt.insert(pkt.end(), reinterpret_cast<const uint8_t*>(&qty),
                      reinterpret_cast<const uint8_t*>(&qty) + 4);
        }

        return pkt;
    }
};

TEST_F(SBEParserTest, ParseTradeMessage) {
    int64_t price_raw = 5000000;  // 500.0000 (scaled by 10000)
    uint32_t qty = 100;
    uint8_t side = 0;  // Buy

    auto pkt = BuildTradePacket(24, price_raw, qty, side);
    auto signal = parser.parse_packet(pkt);

    ASSERT_TRUE(signal.has_value());
    EXPECT_EQ(signal->message_type, MarketDataSignal::MessageType::Trade);
    EXPECT_DOUBLE_EQ(signal->trade.price, 500.0);
    EXPECT_EQ(signal->trade.quantity, 100);
    EXPECT_TRUE(signal->trade.is_bid);
}

TEST_F(SBEParserTest, ParseQuoteMessage) {
    int64_t bid_price = 4999000;  // 499.9000
    uint32_t bid_qty = 50;
    int64_t ask_price = 5001000;  // 500.1000
    uint32_t ask_qty = 75;

    auto pkt = BuildQuotePacket(27, bid_price, bid_qty, ask_price, ask_qty);
    auto signal = parser.parse_packet(pkt);

    ASSERT_TRUE(signal.has_value());
    EXPECT_EQ(signal->message_type, MarketDataSignal::MessageType::Quote);
    EXPECT_DOUBLE_EQ(signal->quote.bid_price, 499.9);
    EXPECT_EQ(signal->quote.bid_quantity, 50);
    EXPECT_DOUBLE_EQ(signal->quote.ask_price, 500.1);
    EXPECT_EQ(signal->quote.ask_quantity, 75);
}

TEST_F(SBEParserTest, ParseDepthMessage) {
    std::vector<std::pair<int64_t, uint32_t>> bids = {
        {4999000, 100},  // 499.9000 @ 100
        {4998000, 50},   // 499.8000 @ 50
    };
    std::vector<std::pair<int64_t, uint32_t>> asks = {
        {5001000, 100},  // 500.1000 @ 100
        {5002000, 50},   // 500.2000 @ 50
    };

    auto pkt = BuildDepthPacket(30, bids, asks);
    auto signal = parser.parse_packet(pkt);

    ASSERT_TRUE(signal.has_value());
    EXPECT_EQ(signal->message_type, MarketDataSignal::MessageType::OrderBookDepth);
    EXPECT_EQ(signal->order_book_depth.bids.size(), 2);
    EXPECT_EQ(signal->order_book_depth.asks.size(), 2);

    EXPECT_DOUBLE_EQ(signal->order_book_depth.bids[0].price, 499.9);
    EXPECT_EQ(signal->order_book_depth.bids[0].quantity, 100);

    EXPECT_DOUBLE_EQ(signal->order_book_depth.asks[1].price, 500.2);
    EXPECT_EQ(signal->order_book_depth.asks[1].quantity, 50);
}

TEST_F(SBEParserTest, InvalidPacketTooShort) {
    std::vector<uint8_t> pkt = {0x01, 0x02, 0x03};
    auto signal = parser.parse_packet(pkt);

    EXPECT_FALSE(signal.has_value());
    auto stats = parser.stats();
    EXPECT_GT(stats.messages_dropped, 0);
}

TEST_F(SBEParserTest, UnknownTemplateId) {
    auto pkt = BuildTradePacket(999, 5000000, 100, 0);  // Unknown template
    auto signal = parser.parse_packet(pkt);

    EXPECT_FALSE(signal.has_value());
}

TEST_F(SBEParserTest, StatsTracking) {
    int64_t price_raw = 5000000;
    uint32_t qty = 100;

    auto pkt1 = BuildTradePacket(24, price_raw, qty, 0);
    auto pkt2 = BuildTradePacket(24, price_raw, qty, 1);

    parser.parse_packet(pkt1);
    parser.parse_packet(pkt2);

    auto stats = parser.stats();
    EXPECT_EQ(stats.messages_parsed, 2);
}

}  // namespace metis

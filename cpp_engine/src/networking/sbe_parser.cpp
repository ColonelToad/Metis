#include "metis/sbe_parser.hpp"

#include <cstring>
#include <cmath>

namespace metis {

namespace {
    constexpr uint32_t SCHEMA_ID_CME_MDP3 = 1;

    struct SBEFrameHeader {
        uint16_t block_length;
        uint16_t template_id;
        uint16_t schema_id;
        uint16_t version;
    } __attribute__((packed));

    inline uint64_t read_u64_le(const uint8_t* data) {
        uint64_t val;
        std::memcpy(&val, data, sizeof(uint64_t));
        return val;
    }

    inline uint32_t read_u32_le(const uint8_t* data) {
        uint32_t val;
        std::memcpy(&val, data, sizeof(uint32_t));
        return val;
    }

    inline uint16_t read_u16_le(const uint8_t* data) {
        uint16_t val;
        std::memcpy(&val, data, sizeof(uint16_t));
        return val;
    }

    inline int64_t read_i64_le(const uint8_t* data) {
        int64_t val;
        std::memcpy(&val, data, sizeof(int64_t));
        return val;
    }

    inline double read_f64_le(const uint8_t* data) {
        double val;
        std::memcpy(&val, data, sizeof(double));
        return val;
    }
}

SBEParser::SBEParser() : stats_{0, 0, 0} {
    // CME MDP 3.0 SBE schema definitions (hardcoded for core messages)
}

std::optional<MarketDataSignal> SBEParser::parse_packet(const std::vector<uint8_t>& packet) {
    if (packet.size() < sizeof(SBEFrameHeader)) {
        stats_.messages_dropped++;
        return std::nullopt;
    }

    const uint8_t* data = packet.data();
    size_t len = packet.size();

    auto frame_opt = parse_frame_header(data, len);
    if (!frame_opt) {
        stats_.schema_mismatches++;
        return std::nullopt;
    }

    const auto& frame = frame_opt.value();
    const uint8_t* msg_data = data + sizeof(SBEFrameHeader);
    size_t msg_len = len - sizeof(SBEFrameHeader);

    // Template IDs for CME MDP 3.0 core messages
    // 24 = Trade (AggressorSide)
    // 27 = Quote (Imbalance)
    // 30 = OrderBookDepth (implied depth)
    MarketDataSignal signal{};
    signal.timestamp_ns = std::chrono::nanoseconds(
        std::chrono::steady_clock::now().time_since_epoch()
    ).count();

    switch (frame.template_id) {
        case 24: {  // Trade message
            auto trade_opt = parse_trade_message(msg_data, msg_len);
            if (!trade_opt) {
                stats_.messages_dropped++;
                return std::nullopt;
            }
            signal.message_type = MarketDataSignal::MessageType::Trade;
            signal.trade = trade_opt.value();
            break;
        }
        case 27: {  // Quote message
            auto quote_opt = parse_quote_message(msg_data, msg_len);
            if (!quote_opt) {
                stats_.messages_dropped++;
                return std::nullopt;
            }
            signal.message_type = MarketDataSignal::MessageType::Quote;
            signal.quote = quote_opt.value();
            break;
        }
        case 30: {  // OrderBook depth
            auto depth_opt = parse_depth_message(msg_data, msg_len);
            if (!depth_opt) {
                stats_.messages_dropped++;
                return std::nullopt;
            }
            signal.message_type = MarketDataSignal::MessageType::OrderBookDepth;
            signal.order_book_depth = depth_opt.value();
            break;
        }
        default:
            signal.message_type = MarketDataSignal::MessageType::Unknown;
            stats_.messages_dropped++;
            return std::nullopt;
    }

    stats_.messages_parsed++;
    return signal;
}

SBEParser::Stats SBEParser::stats() const {
    return stats_;
}

std::optional<SBEParser::FrameHeader> SBEParser::parse_frame_header(
    const uint8_t* data, size_t len) {
    if (len < sizeof(SBEFrameHeader)) {
        return std::nullopt;
    }

    const SBEFrameHeader* hdr = reinterpret_cast<const SBEFrameHeader*>(data);
    return FrameHeader{hdr->block_length, hdr->template_id, hdr->schema_id, hdr->version};
}

std::optional<MarketDataSignal::Trade> SBEParser::parse_trade_message(
    const uint8_t* data, size_t len) {
    // Trade message layout (CME MDP 3.0):
    // price (i64 @ +0, 1/10000 scale)
    // quantity (u32 @ +8)
    // aggressor_side (u8 @ +12, 0=buy, 1=sell)
    constexpr size_t MIN_LEN = 13;
    if (len < MIN_LEN) {
        return std::nullopt;
    }

    int64_t price_raw = read_i64_le(data);
    uint32_t quantity = read_u32_le(data + 8);
    uint8_t aggressor_side = data[12];

    double price = price_raw / 10000.0;
    bool is_bid = (aggressor_side == 0);

    return MarketDataSignal::Trade{price, quantity, is_bid};
}

std::optional<MarketDataSignal::Quote> SBEParser::parse_quote_message(
    const uint8_t* data, size_t len) {
    // Quote message layout (CME MDP 3.0):
    // bid_price (i64 @ +0, 1/10000 scale)
    // bid_qty (u32 @ +8)
    // ask_price (i64 @ +12, 1/10000 scale)
    // ask_qty (u32 @ +20)
    constexpr size_t MIN_LEN = 24;
    if (len < MIN_LEN) {
        return std::nullopt;
    }

    int64_t bid_raw = read_i64_le(data);
    uint32_t bid_qty = read_u32_le(data + 8);
    int64_t ask_raw = read_i64_le(data + 12);
    uint32_t ask_qty = read_u32_le(data + 20);

    double bid_price = bid_raw / 10000.0;
    double ask_price = ask_raw / 10000.0;

    return MarketDataSignal::Quote{bid_price, bid_qty, ask_price, ask_qty};
}

std::optional<MarketDataSignal::OrderBookDepth> SBEParser::parse_depth_message(
    const uint8_t* data, size_t len) {
    // OrderBook depth message layout (CME MDP 3.0):
    // num_bid_levels (u8 @ +0)
    // num_ask_levels (u8 @ +1)
    // Then alternating price(i64) / qty(u32) for bids, then asks
    constexpr size_t MIN_LEN = 2;
    if (len < MIN_LEN) {
        return std::nullopt;
    }

    uint8_t num_bids = data[0];
    uint8_t num_asks = data[1];

    MarketDataSignal::OrderBookDepth depth{};
    depth.bids.reserve(num_bids);
    depth.asks.reserve(num_asks);

    size_t offset = 2;
    // Parse bid levels
    for (int i = 0; i < num_bids; ++i) {
        if (offset + 12 > len) return std::nullopt;
        int64_t price_raw = read_i64_le(data + offset);
        uint32_t qty = read_u32_le(data + offset + 8);
        double price = price_raw / 10000.0;
        depth.bids.push_back({price, qty});
        offset += 12;
    }

    // Parse ask levels
    for (int i = 0; i < num_asks; ++i) {
        if (offset + 12 > len) return std::nullopt;
        int64_t price_raw = read_i64_le(data + offset);
        uint32_t qty = read_u32_le(data + offset + 8);
        double price = price_raw / 10000.0;
        depth.asks.push_back({price, qty});
        offset += 12;
    }

    return depth;
}

}  // namespace metis

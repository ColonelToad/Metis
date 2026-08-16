#pragma once

#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace metis {

/// CME MDP 3.0 market data signal after SBE decoding
struct MarketDataSignal {
    uint64_t sequence;           // Message sequence number
    uint64_t timestamp_ns;       // Nanosecond timestamp from market
    uint32_t symbol_id;          // Security identifier (e.g., NG for natural gas)

    // Populated based on message type
    enum class Type {
        Unknown,
        Trade,
        Quote,
        OrderBookDepth,
    };
    Type message_type;

    // Trade message fields
    struct Trade {
        double price;
        uint32_t quantity;
        bool is_bid;  // true = bid side aggressor
    };
    std::optional<Trade> trade;

    // Quote (top-of-book) message fields
    struct Quote {
        double bid_price;
        uint32_t bid_quantity;
        double ask_price;
        uint32_t ask_quantity;
    };
    std::optional<Quote> quote;

    // Order book depth snapshot (top N levels)
    struct OrderBookDepth {
        std::vector<std::pair<double, uint32_t>> bids;   // price, quantity
        std::vector<std::pair<double, uint32_t>> asks;   // price, quantity
    };
    std::optional<OrderBookDepth> depth;
};

/// CME MDP 3.0 SBE (Simple Binary Encoding) parser
///
/// Decodes raw UDP packets from CME into typed signals.
/// Zero-copy where possible (returns references to wire data).
///
/// In production:
/// - Parses only core messages (Trade, Quote, DepthLevel)
/// - Skips administrative messages (Logon, Heartbeat, etc.)
/// - Returns optional<> for malformed data (avoids throw on hot path)
///
/// Reference: CME MDP 3.0 specification
/// (https://www.cmegroup.com/confluence/display/EPICSANDBOX/CME+MDP+3.0)
class SBEParser {
public:
    /// Initialize parser with CME schema version
    /// @param schema_version Typically "1" for MDP 3.0 (not yet parameterized)
    SBEParser();

    /// Parse a raw UDP packet into market data signals
    /// @param packet Raw SBE-encoded bytes from CME multicast
    /// @return Decoded MarketDataSignal, or nullopt if parsing fails
    /// @note Non-allocating on fast path; only allocates for variable-length fields
    std::optional<MarketDataSignal> parse_packet(const std::vector<uint8_t>& packet);

    /// Get statistics: messages parsed, dropped, schema mismatches
    struct Stats {
        uint64_t messages_parsed;
        uint64_t messages_dropped;
        uint64_t schema_mismatches;
    };
    Stats stats() const;

private:
    Stats stats_;

    /// Helper: parse SBE frame header (message type, length, etc.)
    struct FrameHeader {
        uint16_t message_type;
        uint16_t message_length;
        uint32_t sequence_number;
    };
    std::optional<FrameHeader> parse_frame_header(const uint8_t* data, size_t len);

    /// Helper: parse Trade message from SBE wire format
    std::optional<MarketDataSignal::Trade> parse_trade_message(const uint8_t* data, size_t len);

    /// Helper: parse Quote (top-of-book) message
    std::optional<MarketDataSignal::Quote> parse_quote_message(const uint8_t* data, size_t len);

    /// Helper: parse OrderBookDepth (MDEntry array) message
    std::optional<MarketDataSignal::OrderBookDepth> parse_depth_message(const uint8_t* data, size_t len);
};

}  // namespace metis

#include "metis/sbe_parser.hpp"

namespace metis {

SBEParser::SBEParser() : stats_{0, 0, 0} {
    // Phase 2: Load CME MDP 3.0 SBE schema definitions
    // (will parse from official CME schema files or hardcode message offsets)
}

std::optional<MarketDataSignal> SBEParser::parse_packet(const std::vector<uint8_t>& packet) {
    // Phase 2: implement zero-copy SBE parsing
    // 1. Parse frame header (message type, length, sequence)
    // 2. Dispatch to appropriate message handler (Trade, Quote, DepthLevel)
    // 3. Return MarketDataSignal with appropriate fields populated

    stats_.messages_dropped++;
    return std::nullopt;  // Stub: return nullopt (not yet parsing)
}

SBEParser::Stats SBEParser::stats() const {
    return stats_;
}

std::optional<SBEParser::FrameHeader> SBEParser::parse_frame_header(
    const uint8_t* data, size_t len) {
    // Phase 2: parse first 8 bytes of SBE frame
    // typedef struct {
    //     uint16_t template_id;
    //     uint16_t block_length;
    //     uint32_t schema_id;
    // } FrameHeader;
    return std::nullopt;
}

std::optional<MarketDataSignal::Trade> SBEParser::parse_trade_message(
    const uint8_t* data, size_t len) {
    // Phase 2: parse Trade message
    // Typically contains: price (f64), quantity (u32), aggressor_side (i8)
    return std::nullopt;
}

std::optional<MarketDataSignal::Quote> SBEParser::parse_quote_message(
    const uint8_t* data, size_t len) {
    // Phase 2: parse Quote (SecurityStatus) message
    // Typically contains: bid_price, bid_qty, ask_price, ask_qty (all f64/u32)
    return std::nullopt;
}

std::optional<MarketDataSignal::OrderBookDepth> SBEParser::parse_depth_message(
    const uint8_t* data, size_t len) {
    // Phase 2: parse MDEntry array (order book depth)
    // Typically contains: array of (price, quantity, side) tuples
    return std::nullopt;
}

}  // namespace metis

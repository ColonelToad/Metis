#pragma once

#include <chrono>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace metis {

/// Side of the order book
enum class Side : uint8_t {
    Bid = 0,
    Ask = 1,
};

/// Price level type. Using double for now (matches Rust f64).
/// In production (kernel bypass + SBE parser), would switch to fixed-point
/// to avoid floating point entirely.
using Price = double;

/// Quantity at a price level
using Quantity = double;

/// Timestamp (nanoseconds since epoch for consistency with fusion)
using Timestamp = std::chrono::time_point<std::chrono::system_clock>;

/// Limit order book (Level 2 depth)
///
/// Maintains bid/ask levels with total quantity at each price.
/// Uses std::map for sorted order; in production would trade off
/// for cache locality (e.g. arena-allocated fixed-size array if
/// depth doesn't exceed ~100 levels).
///
/// Thread-safety: None. Assume single writer, single reader or
/// full external synchronization. Lock-free update would come
/// later (once DPDK is in place and we know the critical section size).
class OrderBook {
public:
    explicit OrderBook(std::string symbol);

    /// Update the top of book with a quote
    void update_quote(Price bid_price, Quantity bid_qty, Price ask_price, Quantity ask_qty);

    /// Add an order at a level
    void add_order(uint64_t order_id, Side side, Price price, Quantity qty);

    /// Cancel an order by ID
    void cancel_order(uint64_t order_id);

    /// Get best bid (price, quantity) or none
    std::optional<std::pair<Price, Quantity>> best_bid() const;

    /// Get best ask (price, quantity) or none
    std::optional<std::pair<Price, Quantity>> best_ask() const;

    /// Calculate mid price
    std::optional<Price> mid_price() const;

    /// Calculate spread in basis points
    std::optional<double> spread_bps() const;

    /// Get total depth at top N levels
    std::pair<Quantity, Quantity> depth(size_t levels) const;

    /// VWAP for a given quantity (matches Rust semantics)
    std::optional<Price> vwap(Side side, Quantity qty) const;

    /// Snapshot of top N levels for visualization/serialization
    struct BookSnapshot {
        std::string symbol;
        Timestamp timestamp;
        std::vector<std::pair<Price, Quantity>> bids;
        std::vector<std::pair<Price, Quantity>> asks;
    };

    BookSnapshot snapshot(size_t levels = 10) const;

    // Accessors
    const std::string& symbol() const { return symbol_; }
    Timestamp last_update() const { return last_update_; }

private:
    std::string symbol_;

    /// Bid side: price -> quantity (descending order, hence std::greater)
    std::map<Price, Quantity, std::greater<Price>> bids_;

    /// Ask side: price -> quantity (ascending order, default comparator)
    std::map<Price, Quantity> asks_;

    /// Order tracking: order_id -> (side, price, quantity)
    std::map<uint64_t, std::tuple<Side, Price, Quantity>> order_map_;

    Timestamp last_update_;
};

}  // namespace metis

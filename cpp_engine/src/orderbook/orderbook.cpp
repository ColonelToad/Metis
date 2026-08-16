#include "metis/orderbook.hpp"

namespace metis {

OrderBook::OrderBook(std::string symbol)
    : symbol_(std::move(symbol)), last_update_(std::chrono::system_clock::now()) {}

void OrderBook::update_quote(Price bid_price, Quantity bid_qty, Price ask_price, Quantity ask_qty) {
    last_update_ = std::chrono::system_clock::now();

    bids_.clear();
    asks_.clear();
    order_map_.clear();

    if (bid_qty > 0.0) {
        bids_.emplace(bid_price, bid_qty);
    }

    if (ask_qty > 0.0) {
        asks_.emplace(ask_price, ask_qty);
    }
}

void OrderBook::add_order(uint64_t order_id, Side side, Price price, Quantity qty) {
    last_update_ = std::chrono::system_clock::now();

    if (side == Side::Bid) {
        auto [it, inserted] = bids_.try_emplace(price, qty);
        if (!inserted) {
            it->second += qty;
        }
    } else {
        auto [it, inserted] = asks_.try_emplace(price, qty);
        if (!inserted) {
            it->second += qty;
        }
    }

    // Track order ID for cancellation
    order_map_.emplace(order_id, std::make_tuple(side, price, qty));
}

void OrderBook::cancel_order(uint64_t order_id) {
    auto it = order_map_.find(order_id);
    if (it == order_map_.end()) {
        return;
    }

    auto [side, price, qty] = it->second;
    order_map_.erase(it);

    if (side == Side::Bid) {
        auto level_it = bids_.find(price);
        if (level_it != bids_.end()) {
            level_it->second -= qty;
            if (level_it->second <= 0.0) {
                bids_.erase(level_it);
            }
        }
    } else {
        auto level_it = asks_.find(price);
        if (level_it != asks_.end()) {
            level_it->second -= qty;
            if (level_it->second <= 0.0) {
                asks_.erase(level_it);
            }
        }
    }
}

std::optional<std::pair<Price, Quantity>> OrderBook::best_bid() const {
    if (bids_.empty()) return std::nullopt;
    auto& [price, qty] = *bids_.begin();  // std::greater sorts descending
    return std::make_pair(price, qty);
}

std::optional<std::pair<Price, Quantity>> OrderBook::best_ask() const {
    if (asks_.empty()) return std::nullopt;
    auto& [price, qty] = *asks_.begin();  // default sort ascending
    return std::make_pair(price, qty);
}

std::optional<Price> OrderBook::mid_price() const {
    auto bid = best_bid();
    auto ask = best_ask();

    if (!bid || !ask) return std::nullopt;

    return (bid->first + ask->first) / 2.0;
}

std::optional<double> OrderBook::spread_bps() const {
    auto bid = best_bid();
    auto ask = best_ask();

    if (!bid || !ask) return std::nullopt;

    Price mid = (bid->first + ask->first) / 2.0;
    return (ask->first - bid->first) / mid * 10000.0;
}

std::pair<Quantity, Quantity> OrderBook::depth(size_t levels) const {
    Quantity bid_depth = 0.0;
    Quantity ask_depth = 0.0;

    // Bid side is already sorted descending (best first)
    for (auto it = bids_.begin(); it != bids_.end() && levels > 0; ++it, --levels) {
        bid_depth += it->second;
    }

    // Ask side is sorted ascending (best first)
    levels = 10;  // Reset for ask side
    for (auto it = asks_.begin(); it != asks_.end() && levels > 0; ++it, --levels) {
        ask_depth += it->second;
    }

    return {bid_depth, ask_depth};
}

std::optional<Price> OrderBook::vwap(Side side, Quantity qty) const {
    double remaining = qty;
    double total_cost = 0.0;

    if (side == Side::Bid) {
        // Bid side is descending, so reverse iteration
        for (auto it = bids_.rbegin(); it != bids_.rend() && remaining > 0.0; ++it) {
            double take_qty = std::min(remaining, it->second);
            total_cost += it->first * take_qty;
            remaining -= take_qty;
        }
    } else {
        // Ask side is ascending
        for (auto it = asks_.begin(); it != asks_.end() && remaining > 0.0; ++it) {
            double take_qty = std::min(remaining, it->second);
            total_cost += it->first * take_qty;
            remaining -= take_qty;
        }
    }

    if (remaining > 0.0) {
        return std::nullopt;  // Not enough liquidity
    }

    return total_cost / qty;
}

OrderBook::BookSnapshot OrderBook::snapshot(size_t levels) const {
    BookSnapshot snap;
    snap.symbol = symbol_;
    snap.timestamp = last_update_;

    // Bid snapshot (already descending, take first N)
    for (auto it = bids_.begin(); it != bids_.end() && levels > 0; ++it, --levels) {
        snap.bids.emplace_back(it->first, it->second);
    }

    // Ask snapshot (ascending, take first N)
    levels = 10;  // Reset
    for (auto it = asks_.begin(); it != asks_.end() && levels > 0; ++it, --levels) {
        snap.asks.emplace_back(it->first, it->second);
    }

    return snap;
}

}  // namespace metis

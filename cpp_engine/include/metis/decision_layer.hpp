#pragma once

#include "metis/orderbook.hpp"
#include "metis/fusion.hpp"
#include <cstdint>
#include <optional>

namespace metis {

/// Pre-trade risk decision interface
///
/// In Phase 2: stub implementation (always allows)
/// In Phase 3+: FPGA simulation or hardware SmartNIC integration
///
/// Called after order book update, before execution.
/// If returns false, order is rejected (risk limit exceeded).
///
/// Future: This interface will be called from FPGA hardware
/// for sub-100ns decision latency.
class RiskDecisionLayer {
public:
    RiskDecisionLayer() = default;
    virtual ~RiskDecisionLayer() = default;

    /// Pre-trade risk check
    /// @param symbol Trading symbol (e.g., "NG")
    /// @param side Buy or Sell
    /// @param quantity Order size
    /// @param price Limit price
    /// @param book Current order book state (read-only)
    /// @param fused_signal Latest fused climate/grid/policy signal
    /// @return true if order passes risk checks, false if rejected
    virtual bool check_pre_trade_risk(
        const std::string& symbol,
        Side side,
        double quantity,
        double price,
        const OrderBook& book,
        const std::optional<FusedSignal>& fused_signal
    ) = 0;

    /// Post-trade position tracking (called after execution)
    /// @param symbol Trading symbol
    /// @param side Buy or Sell
    /// @param quantity Filled amount
    /// @param fill_price Average fill price
    virtual void record_execution(
        const std::string& symbol,
        Side side,
        double quantity,
        double fill_price
    ) = 0;

    /// Get current position (for monitoring)
    struct Position {
        double long_qty;
        double short_qty;
        double vwap_price;  // Volume-weighted average price
    };
    virtual Position get_position(const std::string& symbol) const = 0;
};

/// Stub implementation: all orders pass, no position limits
///
/// Used in Phase 2 for integration testing.
/// Replace with FPGA/hardware version in Phase 3.
class StubRiskDecisionLayer : public RiskDecisionLayer {
public:
    bool check_pre_trade_risk(
        const std::string& symbol,
        Side side,
        double quantity,
        double price,
        const OrderBook& book,
        const std::optional<FusedSignal>& fused_signal
    ) override {
        // Phase 2: no risk checks; accept everything
        return true;
    }

    void record_execution(
        const std::string& symbol,
        Side side,
        double quantity,
        double fill_price
    ) override {
        // Phase 2: no position tracking
    }

    Position get_position(const std::string& symbol) const override {
        return {0.0, 0.0, 0.0};
    }
};

}  // namespace metis

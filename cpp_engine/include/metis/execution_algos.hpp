#pragma once

#include "orderbook.hpp"

#include <chrono>
#include <optional>
#include <string>
#include <vector>

namespace metis {

using Duration = std::chrono::duration<int64_t>;
using SystemTime = std::chrono::system_clock::time_point;

/// Parent order representing the full trading signal
struct ParentOrder {
    std::string order_id;
    std::string symbol;
    Side side;
    double quantity;
    SystemTime start_time;
    SystemTime end_time;
    enum class Algo { TWAP, VWAP, POV, Arrival } algo;
};

/// Order status enumeration
enum class OrderStatus {
    Pending,
    Submitted,
    PartiallyFilled,
    Filled,
    Cancelled,
    Rejected,
};

/// Child order sliced from parent
struct ChildOrder {
    std::string child_id;
    std::string parent_id;
    std::string symbol;
    Side side;
    double quantity;
    std::optional<double> limit_price;
    SystemTime submit_time;
    OrderStatus status;

    // For PartiallyFilled and Filled states
    double filled_qty = 0.0;
    double avg_price = 0.0;
};

/// Fill event from execution
struct Fill {
    std::string child_id;
    double price;
    double quantity;
    SystemTime timestamp;
};

/// Execution quality metrics
struct ExecutionMetrics {
    std::string parent_id;
    double target_quantity;
    double filled_quantity;
    double avg_fill_price;
    double benchmark_price;
    double slippage_bps;           // Magnitude only, always >= 0
    double signed_slippage_bps;    // Signed: positive = beat benchmark
    double completion_rate;
};

/// TWAP (Time-Weighted Average Price) executor
class TwapExecutor {
public:
    /// @param slice_duration_secs Duration of each time slice in seconds
    explicit TwapExecutor(int64_t slice_duration_secs);

    /// Generate child orders by slicing parent uniformly across time
    std::vector<ChildOrder> generate_child_orders(const ParentOrder& parent);

    /// Calculate execution quality metrics
    ExecutionMetrics calculate_metrics(
        const ParentOrder& parent,
        const std::vector<Fill>& fills,
        double benchmark_price
    );

private:
    Duration slice_duration_;
};

/// VWAP (Volume-Weighted Average Price) executor
class VwapExecutor {
public:
    /// @param volume_profile Hourly volume distribution (sum should be 1.0 or normalized later)
    explicit VwapExecutor(std::vector<double> volume_profile);

    /// Generate child orders weighted by historical volume
    std::vector<ChildOrder> generate_child_orders(const ParentOrder& parent);

private:
    std::vector<double> historical_volume_profile_;
};

}  // namespace metis

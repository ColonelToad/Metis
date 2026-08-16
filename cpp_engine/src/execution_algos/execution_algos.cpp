#include "metis/execution_algos.hpp"

#include <chrono>
#include <cmath>
#include <numeric>

namespace metis {

TwapExecutor::TwapExecutor(int64_t slice_duration_secs)
    : slice_duration_(std::chrono::seconds(slice_duration_secs)) {}

std::vector<ChildOrder> TwapExecutor::generate_child_orders(const ParentOrder& parent) {
    auto total_duration = parent.end_time - parent.start_time;
    auto total_secs = std::chrono::duration_cast<std::chrono::seconds>(total_duration).count();
    auto slice_secs = std::chrono::duration_cast<std::chrono::seconds>(slice_duration_).count();

    size_t num_slices = total_secs / slice_secs;
    if (num_slices == 0) {
        throw std::runtime_error("Execution window too short for slicing");
    }

    double qty_per_slice = parent.quantity / static_cast<double>(num_slices);
    std::vector<ChildOrder> children;
    children.reserve(num_slices);

    for (size_t i = 0; i < num_slices; ++i) {
        children.push_back(ChildOrder{
            .child_id = parent.order_id + "-" + std::to_string(i),
            .parent_id = parent.order_id,
            .symbol = parent.symbol,
            .side = parent.side,
            .quantity = qty_per_slice,
            .limit_price = std::nullopt,
            .submit_time = parent.start_time + std::chrono::seconds(i * slice_secs),
            .status = OrderStatus::Pending,
        });
    }

    return children;
}

ExecutionMetrics TwapExecutor::calculate_metrics(const ParentOrder& parent,
                                                  const std::vector<Fill>& fills,
                                                  double benchmark_price) {
    double total_filled = std::accumulate(fills.begin(), fills.end(), 0.0,
                                          [](double acc, const Fill& f) { return acc + f.quantity; });

    double total_cost =
        std::accumulate(fills.begin(), fills.end(), 0.0, [](double acc, const Fill& f) {
            return acc + (f.price * f.quantity);
        });

    double avg_fill_price = total_filled > 0.0 ? total_cost / total_filled : 0.0;

    // Signed slippage: positive = beat benchmark
    double signed_diff;
    if (parent.side == Side::Bid) {
        signed_diff = benchmark_price - avg_fill_price;  // Favorable if negative (paid less)
    } else {
        signed_diff = avg_fill_price - benchmark_price;  // Favorable if positive (received more)
    }

    double signed_slippage_bps = (signed_diff / benchmark_price) * 10000.0;
    double slippage_bps = std::abs(signed_slippage_bps);

    return ExecutionMetrics{
        .parent_id = parent.order_id,
        .target_quantity = parent.quantity,
        .filled_quantity = total_filled,
        .avg_fill_price = avg_fill_price,
        .benchmark_price = benchmark_price,
        .slippage_bps = slippage_bps,
        .signed_slippage_bps = signed_slippage_bps,
        .completion_rate = total_filled / parent.quantity,
    };
}

VwapExecutor::VwapExecutor(std::vector<double> volume_profile)
    : historical_volume_profile_(std::move(volume_profile)) {}

std::vector<ChildOrder> VwapExecutor::generate_child_orders(const ParentOrder& parent) {
    auto total_duration = parent.end_time - parent.start_time;
    auto total_hours = std::chrono::duration_cast<std::chrono::hours>(total_duration).count();

    size_t num_slices = std::min(historical_volume_profile_.size(), static_cast<size_t>(total_hours));

    double total_volume_weight =
        std::accumulate(historical_volume_profile_.begin(),
                       historical_volume_profile_.begin() + num_slices, 0.0);

    std::vector<ChildOrder> children;
    children.reserve(num_slices);

    for (size_t i = 0; i < num_slices; ++i) {
        double volume_weight = historical_volume_profile_[i] / total_volume_weight;
        double slice_qty = parent.quantity * volume_weight;

        children.push_back(ChildOrder{
            .child_id = parent.order_id + "-" + std::to_string(i),
            .parent_id = parent.order_id,
            .symbol = parent.symbol,
            .side = parent.side,
            .quantity = slice_qty,
            .limit_price = std::nullopt,
            .submit_time = parent.start_time + std::chrono::hours(static_cast<int64_t>(i)),
            .status = OrderStatus::Pending,
        });
    }

    return children;
}

}  // namespace metis

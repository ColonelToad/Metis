#include <gtest/gtest.h>

#include "metis/execution_algos.hpp"

using namespace metis;
using namespace std::chrono;

class ExecutionAlgosTest : public ::testing::Test {};

TEST_F(ExecutionAlgosTest, TwapSlicing) {
    auto now = system_clock::now();
    ParentOrder parent{
        .order_id = "TEST-001",
        .symbol = "NG:CME",
        .side = Side::Bid,
        .quantity = 100.0,
        .start_time = now,
        .end_time = now + minutes(15),
        .algo = ParentOrder::Algo::TWAP,
    };

    TwapExecutor executor(180);  // 3-minute slices
    auto children = executor.generate_child_orders(parent);

    EXPECT_EQ(children.size(), 5);  // 15 min / 3 min = 5 slices

    for (const auto& child : children) {
        EXPECT_DOUBLE_EQ(child.quantity, 20.0);  // 100 / 5
        EXPECT_EQ(child.status, OrderStatus::Pending);
        EXPECT_FALSE(child.limit_price.has_value());
    }
}

TEST_F(ExecutionAlgosTest, TwapMetrics) {
    auto now = system_clock::now();
    ParentOrder parent{
        .order_id = "TEST-002",
        .symbol = "NG:CME",
        .side = Side::Bid,
        .quantity = 100.0,
        .start_time = now,
        .end_time = now + minutes(15),
        .algo = ParentOrder::Algo::TWAP,
    };

    std::vector<Fill> fills{
        {.child_id = "TEST-002-0", .price = 2.505, .quantity = 50.0, .timestamp = now},
        {.child_id = "TEST-002-1", .price = 2.510, .quantity = 50.0, .timestamp = now},
    };

    TwapExecutor executor(180);
    auto metrics = executor.calculate_metrics(parent, fills, 2.500);

    EXPECT_DOUBLE_EQ(metrics.filled_quantity, 100.0);
    EXPECT_DOUBLE_EQ(metrics.avg_fill_price, 2.5075);
    EXPECT_DOUBLE_EQ(metrics.completion_rate, 1.0);
    EXPECT_GT(metrics.slippage_bps, 0.0);
}

TEST_F(ExecutionAlgosTest, VwapSlicing) {
    auto now = system_clock::now();
    ParentOrder parent{
        .order_id = "TEST-003",
        .symbol = "NG:CME",
        .side = Side::Ask,
        .quantity = 100.0,
        .start_time = now,
        .end_time = now + hours(4),
        .algo = ParentOrder::Algo::VWAP,
    };

    std::vector<double> volume_profile{0.2, 0.3, 0.3, 0.2};  // Hourly distribution

    VwapExecutor executor(volume_profile);
    auto children = executor.generate_child_orders(parent);

    EXPECT_EQ(children.size(), 4);

    // Validate weight distribution
    double total_qty = 0.0;
    for (const auto& child : children) {
        total_qty += child.quantity;
    }
    EXPECT_NEAR(total_qty, 100.0, 0.001);
}

TEST_F(ExecutionAlgosTest, TwapWindowTooShort) {
    auto now = system_clock::now();
    ParentOrder parent{
        .order_id = "TEST-004",
        .symbol = "NG:CME",
        .side = Side::Bid,
        .quantity = 100.0,
        .start_time = now,
        .end_time = now + seconds(30),  // 30 seconds < 180-second slice
        .algo = ParentOrder::Algo::TWAP,
    };

    TwapExecutor executor(180);
    EXPECT_THROW(executor.generate_child_orders(parent), std::runtime_error);
}

TEST_F(ExecutionAlgosTest, PartialFill) {
    auto now = system_clock::now();
    ParentOrder parent{
        .order_id = "TEST-005",
        .symbol = "NG:CME",
        .side = Side::Bid,
        .quantity = 100.0,
        .start_time = now,
        .end_time = now + minutes(15),
        .algo = ParentOrder::Algo::TWAP,
    };

    std::vector<Fill> fills{
        {.child_id = "TEST-005-0", .price = 2.500, .quantity = 30.0, .timestamp = now},
        {.child_id = "TEST-005-1", .price = 2.505, .quantity = 20.0, .timestamp = now},
    };

    TwapExecutor executor(180);
    auto metrics = executor.calculate_metrics(parent, fills, 2.500);

    EXPECT_DOUBLE_EQ(metrics.filled_quantity, 50.0);
    EXPECT_NEAR(metrics.completion_rate, 0.5, 0.001);
    EXPECT_NEAR(metrics.avg_fill_price, 2.502, 0.002);
}

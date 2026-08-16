#include <gtest/gtest.h>

#include "metis/orderbook.hpp"

using namespace metis;

class OrderBookTest : public ::testing::Test {
protected:
    OrderBook book{"NG:CME"};
};

TEST_F(OrderBookTest, QuoteUpdateTopOfBook) {
    book.update_quote(2.500, 100.0, 2.505, 150.0);

    auto bid = book.best_bid();
    auto ask = book.best_ask();

    ASSERT_TRUE(bid.has_value());
    ASSERT_TRUE(ask.has_value());

    EXPECT_DOUBLE_EQ(bid->first, 2.500);
    EXPECT_DOUBLE_EQ(bid->second, 100.0);
    EXPECT_DOUBLE_EQ(ask->first, 2.505);
    EXPECT_DOUBLE_EQ(ask->second, 150.0);
}

TEST_F(OrderBookTest, MidPrice) {
    book.update_quote(2.500, 100.0, 2.505, 150.0);

    auto mid = book.mid_price();
    ASSERT_TRUE(mid.has_value());
    EXPECT_DOUBLE_EQ(mid.value(), 2.5025);
}

TEST_F(OrderBookTest, SpreadInBps) {
    book.update_quote(2.500, 100.0, 2.505, 150.0);

    auto spread = book.spread_bps();
    ASSERT_TRUE(spread.has_value());

    // (2.505 - 2.500) / 2.5025 * 10000 ≈ 19.98
    EXPECT_NEAR(spread.value(), 19.99, 0.1);
}

TEST_F(OrderBookTest, AddAndCancelOrder) {
    book.add_order(1, Side::Bid, 2.500, 50.0);
    book.add_order(2, Side::Bid, 2.500, 50.0);  // Same level
    book.add_order(3, Side::Ask, 2.505, 75.0);

    auto bid = book.best_bid();
    ASSERT_TRUE(bid.has_value());
    EXPECT_DOUBLE_EQ(bid->second, 100.0);  // Aggregated

    book.cancel_order(1);
    bid = book.best_bid();
    EXPECT_DOUBLE_EQ(bid->second, 50.0);

    book.cancel_order(2);
    bid = book.best_bid();
    EXPECT_FALSE(bid.has_value());  // Level removed
}

TEST_F(OrderBookTest, VwapCalculation) {
    book.add_order(1, Side::Ask, 2.505, 50.0);
    book.add_order(2, Side::Ask, 2.510, 75.0);
    book.add_order(3, Side::Ask, 2.515, 100.0);

    auto vwap = book.vwap(Side::Ask, 100.0);
    ASSERT_TRUE(vwap.has_value());

    // (50*2.505 + 50*2.510) / 100 = 2.5075
    EXPECT_NEAR(vwap.value(), 2.5075, 0.001);
}

TEST_F(OrderBookTest, InsufficientLiquidity) {
    book.add_order(1, Side::Ask, 2.505, 50.0);

    auto vwap = book.vwap(Side::Ask, 100.0);
    EXPECT_FALSE(vwap.has_value());
}

TEST_F(OrderBookTest, EmptyBook) {
    auto bid = book.best_bid();
    auto ask = book.best_ask();
    auto mid = book.mid_price();

    EXPECT_FALSE(bid.has_value());
    EXPECT_FALSE(ask.has_value());
    EXPECT_FALSE(mid.has_value());
}

TEST_F(OrderBookTest, Snapshot) {
    book.add_order(1, Side::Bid, 2.500, 100.0);
    book.add_order(2, Side::Bid, 2.495, 50.0);
    book.add_order(3, Side::Ask, 2.505, 75.0);
    book.add_order(4, Side::Ask, 2.510, 100.0);

    auto snap = book.snapshot(5);

    EXPECT_EQ(snap.symbol, "NG:CME");
    EXPECT_EQ(snap.bids.size(), 2);
    EXPECT_EQ(snap.asks.size(), 2);

    // Bids should be in descending order
    EXPECT_DOUBLE_EQ(snap.bids[0].first, 2.500);
    EXPECT_DOUBLE_EQ(snap.bids[1].first, 2.495);

    // Asks should be in ascending order
    EXPECT_DOUBLE_EQ(snap.asks[0].first, 2.505);
    EXPECT_DOUBLE_EQ(snap.asks[1].first, 2.510);
}

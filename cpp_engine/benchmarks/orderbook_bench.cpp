#include <benchmark/benchmark.h>

#include "metis/orderbook.hpp"

using namespace metis;

// Baseline: best_bid lookup (should be O(1) amortized, actually O(log n) due to BTreeMap)
static void BenchBestBid(benchmark::State& state) {
    OrderBook book("NG:CME");
    book.update_quote(2.500, 100.0, 2.505, 150.0);

    for (auto _ : state) {
        benchmark::DoNotOptimize(book.best_bid());
    }
}
BENCHMARK(BenchBestBid);

// Add order and aggregate at same level
static void BenchAddOrder(benchmark::State& state) {
    OrderBook book("NG:CME");

    for (auto _ : state) {
        state.PauseTiming();
        book = OrderBook("NG:CME");
        state.ResumeTiming();

        for (int i = 0; i < 100; ++i) {
            book.add_order(i, Side::Bid, 2.500, 1.0);
        }
        benchmark::DoNotOptimize(book.best_bid());
    }
}
BENCHMARK(BenchAddOrder);

// Mid price calculation
static void BenchMidPrice(benchmark::State& state) {
    OrderBook book("NG:CME");
    book.add_order(1, Side::Bid, 2.500, 100.0);
    book.add_order(2, Side::Ask, 2.505, 150.0);

    for (auto _ : state) {
        benchmark::DoNotOptimize(book.mid_price());
    }
}
BENCHMARK(BenchMidPrice);

// VWAP calculation across multiple levels
static void BenchVwap(benchmark::State& state) {
    OrderBook book("NG:CME");
    for (int i = 0; i < 50; ++i) {
        book.add_order(i, Side::Ask, 2.500 + i * 0.001, 10.0);
    }

    for (auto _ : state) {
        benchmark::DoNotOptimize(book.vwap(Side::Ask, 100.0));
    }
}
BENCHMARK(BenchVwap);

// Full quote update (clear + insert top of book)
static void BenchQuoteUpdate(benchmark::State& state) {
    OrderBook book("NG:CME");

    for (auto _ : state) {
        book.update_quote(2.500 + (state.iterations() % 100) * 0.001,
                         100.0 + state.iterations() % 50, 2.505, 150.0);
        benchmark::DoNotOptimize(book.best_bid());
    }
}
BENCHMARK(BenchQuoteUpdate);

// Snapshot generation (top 10 levels)
static void BenchSnapshot(benchmark::State& state) {
    OrderBook book("NG:CME");
    for (int i = 0; i < 20; ++i) {
        book.add_order(i * 2, Side::Bid, 2.500 - i * 0.001, 10.0);
        book.add_order(i * 2 + 1, Side::Ask, 2.505 + i * 0.001, 10.0);
    }

    for (auto _ : state) {
        benchmark::DoNotOptimize(book.snapshot(10));
    }
}
BENCHMARK(BenchSnapshot);

BENCHMARK_MAIN();

#include <benchmark/benchmark.h>

#include "metis/fusion.hpp"

using namespace metis;

// Non-blocking publish (single item, no contention)
static void BenchPublishClimate(benchmark::State& state) {
    LockFreeSignalFusion fusion(1'000'000'000);

    ClimateSignal climate{
        .timestamp_ns = 1000,
        .region = "US",
        .temperature_c = 25.0f,
        .humidity_pct = 60.0f,
        .wind_kmh = 10.0f,
    };

    for (auto _ : state) {
        fusion.publish_climate(climate);
    }
    benchmark::DoNotOptimize(fusion.sequences());
}
BENCHMARK(BenchPublishClimate);

// Publish + read sequences (minimal load)
static void BenchSequences(benchmark::State& state) {
    LockFreeSignalFusion fusion(1'000'000'000);

    for (auto _ : state) {
        benchmark::DoNotOptimize(fusion.sequences());
    }
}
BENCHMARK(BenchSequences);

// Try-fuse with all three signals present (success path)
static void BenchTryFuseSuccess(benchmark::State& state) {
    LockFreeSignalFusion fusion(1'000'000'000);

    ClimateSignal climate{.timestamp_ns = 1000, .region = "US", .temperature_c = 25.0f, .humidity_pct = 60.0f, .wind_kmh = 10.0f};
    GridSignal grid{.timestamp_ns = 1000, .region = "US", .lmp_usd_per_mwh = 50.0f, .demand_mw = 1000.0f, .renewable_pct = 0.3f};
    PolicySignal policy{.timestamp_ns = 1000, .source = "EPA", .sentiment_score = 0.5f, .relevance = 0.8f};

    fusion.publish_climate(climate);
    fusion.publish_grid(grid);
    fusion.publish_policy(policy);

    for (auto _ : state) {
        // Republish after each fuse to maintain steady state
        state.PauseTiming();
        fusion.publish_climate(climate);
        fusion.publish_grid(grid);
        fusion.publish_policy(policy);
        state.ResumeTiming();

        benchmark::DoNotOptimize(fusion.try_fuse());
    }
}
BENCHMARK(BenchTryFuseSuccess);

// Try-fuse with missing signal (failure path)
static void BenchTryFuseFailure(benchmark::State& state) {
    LockFreeSignalFusion fusion(1'000'000'000);

    ClimateSignal climate{.timestamp_ns = 1000, .region = "US", .temperature_c = 25.0f, .humidity_pct = 60.0f, .wind_kmh = 10.0f};
    fusion.publish_climate(climate);
    // Don't publish grid or policy

    for (auto _ : state) {
        benchmark::DoNotOptimize(fusion.try_fuse());
    }
}
BENCHMARK(BenchTryFuseFailure);

// Rapid publish (stress test for ring buffer)
static void BenchRapidPublish(benchmark::State& state) {
    LockFreeSignalFusion fusion(1'000'000'000);

    ClimateSignal climate{.timestamp_ns = 1000, .region = "US", .temperature_c = 25.0f, .humidity_pct = 60.0f, .wind_kmh = 10.0f};

    for (auto _ : state) {
        for (int i = 0; i < 100; ++i) {
            fusion.publish_climate(climate);
        }
        benchmark::DoNotOptimize(fusion.sequences());
    }
}
BENCHMARK(BenchRapidPublish);

BENCHMARK_MAIN();

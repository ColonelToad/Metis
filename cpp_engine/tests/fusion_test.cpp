#include <gtest/gtest.h>

#include "metis/fusion.hpp"

using namespace metis;

class FusionTest : public ::testing::Test {
protected:
    LockFreeSignalFusion fusion{1'000'000'000};  // 1 second max drift
};

TEST_F(FusionTest, PublishClimate) {
    ClimateSignal climate{
        .timestamp_ns = 1000,
        .region = "US",
        .temperature_c = 25.0f,
        .humidity_pct = 60.0f,
        .wind_kmh = 10.0f,
    };

    fusion.publish_climate(climate);

    auto [climate_seq, grid_seq, policy_seq] = fusion.sequences();
    EXPECT_EQ(climate_seq, 1);
    EXPECT_EQ(grid_seq, 0);
    EXPECT_EQ(policy_seq, 0);
}

TEST_F(FusionTest, TemporallyAligned) {
    // Create signals with same timestamp
    ClimateSignal climate{.timestamp_ns = 1000, .region = "US", .temperature_c = 25.0f, .humidity_pct = 60.0f, .wind_kmh = 10.0f};
    GridSignal grid{.timestamp_ns = 1000, .region = "US", .lmp_usd_per_mwh = 50.0f, .demand_mw = 1000.0f, .renewable_pct = 0.3f};
    PolicySignal policy{.timestamp_ns = 1000, .source = "EPA", .sentiment_score = 0.5f, .relevance = 0.8f};

    fusion.publish_climate(climate);
    fusion.publish_grid(grid);
    fusion.publish_policy(policy);

    auto fused = fusion.try_fuse();
    ASSERT_TRUE(fused.has_value());

    EXPECT_EQ(fused->timestamp_ns, 1000);
    EXPECT_EQ(fused->climate.temperature_c, 25.0f);
    EXPECT_EQ(fused->grid.demand_mw, 1000.0f);
    EXPECT_EQ(fused->policy.sentiment_score, 0.5f);
}

TEST_F(FusionTest, MissingSignal) {
    ClimateSignal climate{.timestamp_ns = 1000, .region = "US", .temperature_c = 25.0f, .humidity_pct = 60.0f, .wind_kmh = 10.0f};

    fusion.publish_climate(climate);
    // Don't publish grid or policy

    auto fused = fusion.try_fuse();
    EXPECT_FALSE(fused.has_value());
}

TEST_F(FusionTest, TemporalMisalignment) {
    ClimateSignal climate{.timestamp_ns = 1000, .region = "US", .temperature_c = 25.0f, .humidity_pct = 60.0f, .wind_kmh = 10.0f};
    GridSignal grid{.timestamp_ns = 1000, .region = "US", .lmp_usd_per_mwh = 50.0f, .demand_mw = 1000.0f, .renewable_pct = 0.3f};
    PolicySignal policy{.timestamp_ns = 2'500'000'000,  // 2.5 seconds later, exceeds 1s max drift
                        .source = "EPA",
                        .sentiment_score = 0.5f,
                        .relevance = 0.8f};

    fusion.publish_climate(climate);
    fusion.publish_grid(grid);
    fusion.publish_policy(policy);

    auto fused = fusion.try_fuse();
    EXPECT_FALSE(fused.has_value());
}

TEST_F(FusionTest, RingBufferWrap) {
    // Publish enough signals to wrap a small ring buffer
    for (int i = 0; i < 300; ++i) {
        ClimateSignal c{
            .timestamp_ns = static_cast<uint64_t>(i) * 1'000'000,
            .region = "US",
            .temperature_c = 25.0f + i,
            .humidity_pct = 60.0f,
            .wind_kmh = 10.0f,
        };
        fusion.publish_climate(c);
    }

    auto [climate_seq, _, __] = fusion.sequences();
    EXPECT_EQ(climate_seq, 300);
}

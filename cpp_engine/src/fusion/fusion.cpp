#include "metis/fusion.hpp"

#include <algorithm>

namespace metis {

LockFreeSignalFusion::LockFreeSignalFusion(uint64_t max_drift_ns)
    : climate_queue_(256), grid_queue_(256), policy_queue_(256), max_drift_ns_(max_drift_ns) {}

LockFreeSignalFusion::~LockFreeSignalFusion() = default;

void LockFreeSignalFusion::publish_climate(const ClimateSignal& signal) {
    climate_queue_.push(signal);
    climate_seq_.fetch_add(1, std::memory_order_release);
}

void LockFreeSignalFusion::publish_grid(const GridSignal& signal) {
    grid_queue_.push(signal);
    grid_seq_.fetch_add(1, std::memory_order_release);
}

void LockFreeSignalFusion::publish_policy(const PolicySignal& signal) {
    policy_queue_.push(signal);
    policy_seq_.fetch_add(1, std::memory_order_release);
}

std::optional<FusedSignal> LockFreeSignalFusion::try_fuse() {
    auto climate = climate_queue_.pop();
    auto grid = grid_queue_.pop();
    auto policy = policy_queue_.pop();

    if (!climate || !grid || !policy) {
        return std::nullopt;
    }

    if (temporally_aligned(climate->timestamp_ns, grid->timestamp_ns, policy->timestamp_ns,
                           max_drift_ns_)) {
        return FusedSignal{climate->timestamp_ns, *climate, *grid, *policy};
    }

    return std::nullopt;
}

LockFreeSignalFusion::Sequences LockFreeSignalFusion::sequences() const {
    return {climate_seq_.load(std::memory_order_acquire),
            grid_seq_.load(std::memory_order_acquire),
            policy_seq_.load(std::memory_order_acquire)};
}

LockFreeSignalFusion::QueueDepths LockFreeSignalFusion::queue_depths() const {
    // Stub: actual implementation would require separate atomic counters
    return {0, 0, 0};
}

bool LockFreeSignalFusion::temporally_aligned(uint64_t t1, uint64_t t2, uint64_t t3,
                                              uint64_t max_drift) {
    uint64_t max_ts = std::max({t1, t2, t3});
    uint64_t min_ts = std::min({t1, t2, t3});
    return (max_ts - min_ts) < max_drift;
}

}  // namespace metis

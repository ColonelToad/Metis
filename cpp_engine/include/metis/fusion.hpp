#pragma once

#include <atomic>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace metis {

/// Climate observation
struct ClimateSignal {
    uint64_t timestamp_ns;
    std::string region;
    float temperature_c;
    float humidity_pct;
    float wind_kmh;
};

/// Grid/energy market observation
struct GridSignal {
    uint64_t timestamp_ns;
    std::string region;
    float lmp_usd_per_mwh;
    float demand_mw;
    float renewable_pct;
};

/// Policy/sentiment observation
struct PolicySignal {
    uint64_t timestamp_ns;
    std::string source;
    float sentiment_score;  // -1.0 (bearish) to +1.0 (bullish)
    float relevance;        // 0.0 to 1.0
};

/// Fused multi-modal signal
struct FusedSignal {
    uint64_t timestamp_ns;
    ClimateSignal climate;
    GridSignal grid;
    PolicySignal policy;
};

/// Lock-free multi-modal signal aggregator
///
/// Combines independent data streams without synchronization primitives.
/// Uses atomic sequence numbers for diagnostics only (not for correctness).
///
/// In production (with Aeron IPC), would be fed from separate threads
/// (one per market data source) and drained from the strategy thread.
/// Latency target: <50ns on success path (single allocation, no branches).
///
/// Known issue (same as Rust version): discards all three signals on
/// temporal misalignment rather than requeuing the aligned ones.
/// Worth fixing when wired to real sources.
class LockFreeSignalFusion {
public:
    /// Create fusion engine
    /// @param max_drift_ns Maximum allowed time skew between signals (1s = 1_000_000_000)
    explicit LockFreeSignalFusion(uint64_t max_drift_ns);

    ~LockFreeSignalFusion();

    /// Publish climate signal (non-blocking)
    void publish_climate(const ClimateSignal& signal);

    /// Publish grid signal (non-blocking)
    void publish_grid(const GridSignal& signal);

    /// Publish policy signal (non-blocking)
    void publish_policy(const PolicySignal& signal);

    /// Non-blocking fusion attempt
    /// @return Fused signal if all three sources have data and are temporally aligned
    std::optional<FusedSignal> try_fuse();

    /// Get current sequence numbers (for diagnostics/monitoring)
    struct Sequences {
        uint64_t climate;
        uint64_t grid;
        uint64_t policy;
    };
    Sequences sequences() const;

    /// Approximate queue depths (stub for now, always returns {0,0,0})
    struct QueueDepths {
        size_t climate;
        size_t grid;
        size_t policy;
    };
    QueueDepths queue_depths() const;

private:
    /// Simple SPSC ring buffer for each signal type
    /// (C++ doesn't have crossbeam::SegQueue, so we roll our own)
    template <typename T>
    class RingBuffer {
    public:
        explicit RingBuffer(size_t capacity = 256) : buffer_(capacity), mask_(capacity - 1) {
            if ((capacity & (capacity - 1)) != 0) {
                throw std::invalid_argument("RingBuffer capacity must be power-of-2");
            }
        }

        void push(const T& item) {
            size_t tail = tail_.load(std::memory_order_relaxed);
            buffer_[tail & mask_] = item;
            tail_.store((tail + 1), std::memory_order_release);
        }

        std::optional<T> pop() {
            size_t head = head_.load(std::memory_order_acquire);
            size_t tail = tail_.load(std::memory_order_acquire);

            if (head == tail) {
                return std::nullopt;
            }

            T item = buffer_[head & mask_];
            head_.store((head + 1), std::memory_order_release);
            return item;
        }

    private:
        std::vector<T> buffer_;
        std::atomic<size_t> head_{0};
        std::atomic<size_t> tail_{0};
        size_t mask_;
    };

    RingBuffer<ClimateSignal> climate_queue_;
    RingBuffer<GridSignal> grid_queue_;
    RingBuffer<PolicySignal> policy_queue_;

    std::atomic<uint64_t> climate_seq_{0};
    std::atomic<uint64_t> grid_seq_{0};
    std::atomic<uint64_t> policy_seq_{0};

    uint64_t max_drift_ns_;

    /// Check if three timestamps fall within acceptable window (branchless)
    static bool temporally_aligned(uint64_t t1, uint64_t t2, uint64_t t3, uint64_t max_drift);
};

}  // namespace metis

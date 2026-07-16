use criterion::{black_box, criterion_group, criterion_main, Criterion};
use std::time::Instant;

/// Measure Python-Rust bridge latency
///
/// Simulates the signal publication path:
/// 1. Python prepares signal data
/// 2. Calls into Rust
/// 3. Rust queues signal for execution engine
/// 4. Returns control to Python
///
/// Note: this doesn't call any real bridge code (there isn't a live one in
/// this crate) — it simulates the primitive operations a bridge would use
/// (signal tuple construction, RDTSC read, channel send) in isolation.
fn benchmark_bridge_latency(c: &mut Criterion) {
    // Simulate signal creation overhead
    c.bench_function("python_signal_creation", |b| {
        b.iter(|| {
            let _signal = (
                black_box(1_000_000_000u64), // timestamp
                black_box(1u32),             // instrument
                black_box(1i8),              // direction
                black_box(0.85f64),          // confidence
                black_box(60u32),            // horizon
            );
        })
    });

    // Simulate TSC read (used for timestamp)
    c.bench_function("rdtsc_timestamp", |b| {
        b.iter(|| unsafe { black_box(std::arch::x86_64::_rdtsc()) })
    });

    // Simulate channel send latency
    c.bench_function("crossbeam_channel_try_send", |b| {
        let (tx, _rx) = crossbeam::channel::bounded(1024);
        let signal = (1_000_000_000u64, 1u32);

        b.iter(|| {
            let _ = tx.try_send(black_box(signal));
        })
    });
}

fn benchmark_end_to_end_latency(c: &mut Criterion) {
    // Measure time from "signal creation" to "queued in Rust"
    c.bench_function("end_to_end_signal_latency", |b| {
        let (tx, _rx) = crossbeam::channel::bounded(1024);

        b.iter(|| {
            let start = Instant::now();

            // Step 1: Create signal
            let timestamp = unsafe { std::arch::x86_64::_rdtsc() };
            let signal = (
                black_box(timestamp),
                black_box(1u32),
                black_box(1i8),
                black_box(0.85f64),
                black_box(60u32),
            );

            // Step 2: Send to Rust
            let _ = tx.try_send(black_box(signal));

            let _elapsed = start.elapsed();
        })
    });
}

criterion_group!(
    benches,
    benchmark_bridge_latency,
    benchmark_end_to_end_latency
);

criterion_main!(benches);

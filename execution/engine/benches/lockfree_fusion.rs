use criterion::{black_box, criterion_group, criterion_main, Criterion};
use std::sync::{Arc, Mutex};
use std::thread;

use engine::fusion::{ClimateSignal, GridSignal, LockFreeSignalFusion, PolicySignal};

fn benchmark_lockfree_fusion(c: &mut Criterion) {
    let fusion = Arc::new(LockFreeSignalFusion::new(1_000_000_000));

    c.bench_function("lock_free_publish_climate", |b| {
        b.iter(|| {
            let signal = ClimateSignal {
                timestamp_ns: black_box(1_000_000_000),
                region: "US".to_string(),
                temperature_c: black_box(25.0),
                humidity_pct: black_box(60.0),
                wind_kmh: black_box(10.0),
            };
            fusion.publish_climate(signal);
        })
    });

    c.bench_function("lock_free_try_fuse_empty", |b| {
        b.iter(|| {
            let _ = fusion.try_fuse();
        })
    });
}

fn benchmark_lock_vs_lockfree(c: &mut Criterion) {
    // Mutex baseline (simulating traditional approach)
    let mutex_data = Arc::new(Mutex::new(0u64));

    c.bench_function("mutex_increment", |b| {
        let m = Arc::clone(&mutex_data);
        b.iter(|| {
            let mut guard = m.lock().unwrap();
            *guard = guard.wrapping_add(1);
        })
    });

    // Atomic baseline (simulating lock-free approach)
    let atomic_data = Arc::new(std::sync::atomic::AtomicU64::new(0));

    c.bench_function("atomic_increment", |b| {
        let a = Arc::clone(&atomic_data);
        b.iter(|| {
            a.fetch_add(1, std::sync::atomic::Ordering::Release);
        })
    });
}

criterion_group!(
    benches,
    benchmark_lockfree_fusion,
    benchmark_lock_vs_lockfree
);

criterion_main!(benches);

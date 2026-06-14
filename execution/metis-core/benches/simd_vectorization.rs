use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion};

// Import from metis_core
use metis_core::simd::{
    euclidean_distance_scalar, euclidean_distance_simd, normalize_temperature_scalar,
    normalize_temperature_simd,
};

/// Helper function to lock the benchmark thread to the primary Performance Core.
/// This prevents the OS scheduler from migrating the tight SIMD loops to an E-Core.
fn pin_to_p_core() {
    if let Some(core_ids) = core_affinity::get_core_ids() {
        if !core_ids.is_empty() {
            // Index 0 maps to the first P-Core on Intel hybrid architectures
            let target_core = core_ids[0];
            if core_affinity::set_for_current(target_core) {
                // Using a carriage return to overwrite the line so it doesn't
                // heavily clutter Criterion's standard output formatting.
                print!(
                    "Thread securely pinned to P-Core (ID: {})\n",
                    target_core.id
                );
            } else {
                println!("Warning: Failed to pin thread to P-Core.");
            }
        }
    }
}

fn benchmark_simd_normalization(c: &mut Criterion) {
    // Lock the thread before starting the run
    pin_to_p_core();

    let temps = vec![72.5, 68.3, 75.1, 70.2, 69.8, 73.4, 71.9, 74.2];
    let mean = 71.0f32;
    let std = 2.5f32;

    let mut group = c.benchmark_group("simd_normalization");

    // Scalar baseline
    group.bench_function("scalar", |b| {
        b.iter(|| normalize_temperature_scalar(black_box(&temps), mean, std))
    });

    // SIMD implementation
    group.bench_function("simd_avx2", |b| {
        b.iter(|| unsafe { normalize_temperature_simd(black_box(&temps), mean, std) })
    });

    group.finish();
}

fn benchmark_euclidean_distance(c: &mut Criterion) {
    // Lock the thread before starting the run
    pin_to_p_core();

    let a: Vec<f32> = (0..1024).map(|i| i as f32).collect();
    let b: Vec<f32> = (0..1024).map(|i| (i as f32) + 0.1).collect();

    let mut group = c.benchmark_group("euclidean_distance");

    // Scalar
    group.bench_function("scalar", |bench| {
        bench.iter(|| euclidean_distance_scalar(black_box(&a), black_box(&b)))
    });

    // SIMD
    group.bench_function("simd_avx2", |bench| {
        bench.iter(|| unsafe { euclidean_distance_simd(black_box(&a), black_box(&b)) })
    });

    group.finish();
}

criterion_group!(
    benches,
    benchmark_simd_normalization,
    benchmark_euclidean_distance
);

criterion_main!(benches);

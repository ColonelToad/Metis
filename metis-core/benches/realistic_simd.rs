use criterion::{black_box, criterion_group, criterion_main, Criterion};

use metis_core::simd::{euclidean_distance_scalar, euclidean_distance_simd};

fn benchmark_realistic_distance(c: &mut Criterion) {
    // Realistic feature vector sizes for LSTM output (49 features)
    let a: Vec<f32> = (0..49).map(|i| i as f32 * 0.1).collect();
    let b: Vec<f32> = (0..49).map(|i| (i as f32 * 0.1) + 0.05).collect();

    let mut group = c.benchmark_group("euclidean_distance_realistic");

    // Scalar
    group.bench_function("scalar_49", |bench| {
        bench.iter(|| euclidean_distance_scalar(black_box(&a), black_box(&b)))
    });

    // SIMD
    group.bench_function("simd_49", |bench| {
        bench.iter(|| unsafe { euclidean_distance_simd(black_box(&a), black_box(&b)) })
    });

    group.finish();

    // Also test with 128 features (next power of 2 for good SIMD alignment)
    let a128: Vec<f32> = (0..128).map(|i| i as f32 * 0.1).collect();
    let b128: Vec<f32> = (0..128).map(|i| (i as f32 * 0.1) + 0.05).collect();

    let mut group2 = c.benchmark_group("euclidean_distance_128");

    group2.bench_function("scalar_128", |bench| {
        bench.iter(|| euclidean_distance_scalar(black_box(&a128), black_box(&b128)))
    });

    group2.bench_function("simd_128", |bench| {
        bench.iter(|| unsafe { euclidean_distance_simd(black_box(&a128), black_box(&b128)) })
    });

    group2.finish();
}

criterion_group!(benches, benchmark_realistic_distance);
criterion_main!(benches);

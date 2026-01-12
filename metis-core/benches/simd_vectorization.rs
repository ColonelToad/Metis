use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId};

// Import from metis_core
use metis_core::simd::{normalize_temperature_simd, euclidean_distance_simd, 
                        normalize_temperature_scalar, euclidean_distance_scalar};

fn benchmark_simd_normalization(c: &mut Criterion) {
    let temps = vec![72.5, 68.3, 75.1, 70.2, 69.8, 73.4, 71.9, 74.2];
    let mean = 71.0f32;
    let std = 2.5f32;
    
    let mut group = c.benchmark_group("simd_normalization");
    
    // Scalar baseline
    group.bench_function("scalar", |b| {
        b.iter(|| {
            normalize_temperature_scalar(black_box(&temps), mean, std)
        })
    });
    
    // SIMD implementation
    group.bench_function("simd_avx2", |b| {
        b.iter(|| unsafe {
            normalize_temperature_simd(black_box(&temps), mean, std)
        })
    });
    
    group.finish();
}

fn benchmark_euclidean_distance(c: &mut Criterion) {
    let a: Vec<f32> = (0..1024).map(|i| i as f32).collect();
    let b: Vec<f32> = (0..1024).map(|i| (i as f32) + 0.1).collect();
    
    let mut group = c.benchmark_group("euclidean_distance");
    
    // Scalar
    group.bench_function("scalar", |bench| {
        bench.iter(|| euclidean_distance_scalar(black_box(&a), black_box(&b)))
    });
    
    // SIMD
    group.bench_function("simd_avx2", |bench| {
        bench.iter(|| unsafe {
            euclidean_distance_simd(black_box(&a), black_box(&b))
        })
    });
    
    group.finish();
}

criterion_group!(
    benches,
    benchmark_simd_normalization,
    benchmark_euclidean_distance
);

criterion_main!(benches);

// Simple test to verify SIMD code is actually being executed
// Run with: cargo run --release --example check_simd_execution

use metis_core::simd::{euclidean_distance_scalar, euclidean_distance_simd};

fn main() {
    // Create test data
    let a: Vec<f32> = (0..1024).map(|i| i as f32).collect();
    let b: Vec<f32> = (0..1024).map(|i| (i as f32) + 0.1).collect();

    println!("Testing euclidean_distance implementations...\n");

    // Test scalar
    let start = std::time::Instant::now();
    let mut result_scalar = 0.0f32;
    for _ in 0..10000 {
        result_scalar = euclidean_distance_scalar(&a, &b);
    }
    let scalar_time = start.elapsed();
    println!("Scalar result: {:.6}", result_scalar);
    println!("Scalar time (10000 iterations): {:?}", scalar_time);
    println!("Scalar per-iteration: {:?}\n", scalar_time / 10000);

    // Test SIMD
    let start = std::time::Instant::now();
    let mut result_simd = 0.0f32;
    for _ in 0..10000 {
        result_simd = unsafe { euclidean_distance_simd(&a, &b) };
    }
    let simd_time = start.elapsed();
    println!("SIMD result: {:.6}", result_simd);
    println!("SIMD time (10000 iterations): {:?}", simd_time);
    println!("SIMD per-iteration: {:?}\n", simd_time / 10000);

    // Compare
    println!(
        "Difference in results: {:.10}",
        (result_scalar - result_simd).abs()
    );
    println!(
        "SIMD speedup: {:.2}x",
        scalar_time.as_secs_f64() / simd_time.as_secs_f64()
    );

    // If SIMD is slower, something is wrong
    if simd_time > scalar_time {
        println!("\n⚠️  WARNING: SIMD is SLOWER than scalar!");
        println!("This indicates:");
        println!("  - Code is not being optimized properly");
        println!("  - Horizontal sum reduction is inefficient");
        println!("  - Or the work is being optimized away entirely");
    }
}

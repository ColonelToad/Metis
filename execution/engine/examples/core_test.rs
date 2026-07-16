use std::time::Instant;

fn main() {
    // 1. Get available cores
    let core_ids = core_affinity::get_core_ids().unwrap();

    // CHANGE THIS INDEX to test different cores.
    // Index 0 is usually a P-Core. Higher indices (like 8, 9, 10) are E-Cores.
    let target_core = core_ids[core_ids.len() - 1]; // Example: Last core (often an E-Core)

    // 2. Pin the thread
    if core_affinity::set_for_current(target_core) {
        println!("Successfully pinned to Core ID: {}", target_core.id);
    } else {
        println!("Failed to pin thread.");
        return;
    }

    println!("Starting continuous benchmark loop. Press Ctrl+C to stop.");

    // 3. The Continuous Loop
    loop {
        let start = Instant::now();

        // --- YOUR WORKLOAD GOES HERE ---
        // Call the SIMD logic from your src/simd.rs or lib.rs.
        // For example: engine::simd::run_heavy_calculation();

        // Simulating work for the sake of the example (replace this):
        let mut _dummy: f32 = 0.0;
        for i in 0..10_000 {
            _dummy += (i as f32).sqrt();
        }
        std::hint::black_box(_dummy);
        // -------------------------------

        let duration = start.elapsed();

        // Print the duration so you can watch the variance in real-time
        println!("Iteration took: {:?}", duration);

        // Optional: Add a tiny sleep if it prints too fast to read,
        // though for raw benchmarking, you might want to log it or let it fly.
        // std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

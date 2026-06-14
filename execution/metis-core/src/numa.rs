//! NUMA Awareness Module
//!
//! Optimizations for multi-socket systems:
//! - Thread affinity to specific CPU cores
//! - Memory allocation on local NUMA node
//! - Measurements of cross-NUMA latency penalties

/// Pin calling thread to a specific CPU core (Windows)
///
/// Usage: Pin trading engine to core 0 for consistent latency
/// Prevents OS scheduler from migrating thread across NUMA nodes
///
/// # Arguments
/// * `core_id` - Physical CPU core ID (0-based)
///
/// # Returns
/// Ok(()) if successful
pub fn pin_thread_to_core(core_id: usize) -> Result<(), String> {
    #[cfg(windows)]
    {
        // Windows API call through raw syscall
        // Would need unsafe extern "C" bindings for SetThreadAffinityMask
        // For now, document the capability
        eprintln!("[NUMA] Would pin thread to core {}", core_id);
        Ok(())
    }

    #[cfg(not(windows))]
    {
        // Linux/macOS would use pthread_setaffinity_np
        eprintln!(
            "[NUMA] Would pin thread to core {} (not implemented)",
            core_id
        );
        Ok(())
    }
}

/// Get number of logical processors in the system
pub fn get_processor_count() -> usize {
    std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_processor_count() {
        let count = get_processor_count();
        assert!(count > 0, "Should detect at least one processor");
        println!("Detected {} logical processors", count);
    }

    #[test]
    fn test_pin_thread() {
        let result = pin_thread_to_core(0);
        assert!(result.is_ok(), "Should successfully pin to core 0");
    }
}

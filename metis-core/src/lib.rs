//! Metis Core Trading Engine
//! 
//! Production-grade Rust trading system demonstrating:
//! - SIMD vectorization for alternative data
//! - Lock-free multi-modal signal fusion
//! - Zero-copy Python-Rust bridge (PyO3)
//! - Microarchitectural optimization (cache-aware, branch prediction)

pub mod execution;
pub mod fusion;
pub mod simd;
pub mod bridge;
pub mod types;
pub mod numa;
pub mod reasoning;

pub use execution::*;
pub use fusion::*;
pub use simd::*;
pub use types::*;
pub use numa::*;
pub use reasoning::*;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_integration() {
        // Placeholder: basic integration test
        assert!(true);
    }
}

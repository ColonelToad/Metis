//! Python-Rust Bridge via PyO3
//!
//! Zero-copy signal transmission from Python ML models to Rust execution engine
//! Every shop has Python ML + C++/Rust execution; this is production essential.

use crate::types::{Direction, InstrumentId, TradingSignal};
use crate::pin_thread_to_core;
use crossbeam::channel::{bounded, Receiver, Sender};
use pyo3::prelude::*;
use std::sync::Arc;
use std::thread;

/// Rust trading engine that consumes signals
pub struct MetisTradingEngine {
    rx: Receiver<TradingSignal>,
    signal_count: u64,
}

impl MetisTradingEngine {
    /// Create new engine with receiver channel
    pub fn new(rx: Receiver<TradingSignal>) -> Self {
        Self {
            rx,
            signal_count: 0,
        }
    }

    /// Main event loop (runs on dedicated thread)
    pub fn run(&mut self) {
        // Pin this thread to core 0 for NUMA locality and consistent latency
        #[cfg(windows)]
        if let Err(e) = pin_thread_to_core(0) {
            eprintln!("[Engine] Warning: Failed to pin thread: {}", e);
        }

        loop {
            match self.rx.recv() {
                Ok(signal) => {
                    self.process_signal(&signal);
                    self.signal_count += 1;
                }
                Err(_) => {
                    // Channel closed, engine shutdown
                    eprintln!("[Engine] Shutting down after {} signals", self.signal_count);
                    break;
                }
            }
        }
    }

    /// Process a trading signal (main hot path)
    #[inline(always)]
    fn process_signal(&mut self, signal: &TradingSignal) {
        // This is where execution logic would go:
        // - Order submission
        // - Position management
        // - Risk checks

        eprintln!(
            "[Signal] {:?} {} @ confidence {:.2} (horizon: {} min)",
            signal.instrument, signal.direction, signal.confidence, signal.horizon_minutes
        );
    }
}

/// Python-facing signal publisher
///
/// Created in Python, holds channel sender to Rust engine
/// Provides non-blocking signal submission from Python
#[pyclass]
pub struct SignalPublisher {
    tx: Arc<Sender<TradingSignal>>,
}

#[pymethods]
impl SignalPublisher {
    /// Initialize publisher and spawn Rust trading engine
    ///
    /// Called from Python: `publisher = metis_core.SignalPublisher()`
    #[new]
    fn new() -> Self {
        // Create bounded channel (16384 signals max buffered for benchmarking)
        let (tx, rx) = bounded(16384);

        // Spawn Rust trading engine on background thread
        thread::spawn(move || {
            let mut engine = MetisTradingEngine::new(rx);
            engine.run();
        });

        Self { tx: Arc::new(tx) }
    }

    /// Publish signal from Python ML model (non-blocking)
    ///
    /// Called from Python after getting prediction:
    /// ```python
    /// prediction = model.predict(features)
    /// publisher.publish_signal(
    ///     instrument_id='NG',     # Natural gas futures ticker
    ///     direction=1 if prediction > 0.5 else -1,
    ///     confidence=prediction,
    ///     horizon_minutes=60
    /// )
    /// ```
    fn publish_signal(
        &self,
        instrument_id: &str,
        direction: i8,
        confidence: f64,
        horizon_minutes: u32,
    ) -> PyResult<()> {
        // Convert ticker symbol to numeric ID (simple hash for now)
        let numeric_id = instrument_id
            .bytes()
            .fold(0u32, |acc, b| acc.wrapping_mul(31).wrapping_add(b as u32));

        let direction_enum = match direction {
            x if x > 0 => Direction::Long,
            x if x < 0 => Direction::Short,
            _ => Direction::Neutral,
        };

        let signal = TradingSignal {
            timestamp_ns: Self::get_timestamp_ns(),
            instrument: InstrumentId(numeric_id),
            direction: direction_enum,
            confidence: confidence.clamp(0.0, 1.0),
            horizon_minutes,
        };

        // Non-blocking send (fails if queue full)
        self.tx.try_send(signal).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Failed to publish signal: {}",
                e
            ))
        })
    }

    /// Get current nanosecond timestamp using TSC
    ///
    /// Uses CPU's timestamp counter for nanosecond precision
    /// (Requires x86_64 Linux/Windows)
    #[staticmethod]
    #[inline(always)]
    fn get_timestamp_ns() -> u64 {
        unsafe {
            // RDTSC instruction: read timestamp counter
            // Returns CPU cycles; needs calibration for ns conversion
            // For now, return raw cycles (can be calibrated per CPU)
            std::arch::x86_64::_rdtsc()
        }
    }
}

/// Export as Python module
#[pymodule]
fn metis_core(m: &pyo3::Bound<'_, pyo3::types::PyModule>) -> PyResult<()> {
    m.add_class::<SignalPublisher>()?;

    // Add version info
    m.add("__version__", "0.1.0")?;
    m.add(
        "__doc__",
        "Metis Core: Production HFT engine with lock-free fusion",
    )?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_engine_creation() {
        let (tx, rx) = bounded(10);
        let engine = MetisTradingEngine::new(rx);
        assert_eq!(engine.signal_count, 0);
    }

    #[test]
    fn test_timestamp() {
        let ts1 = SignalPublisher::get_timestamp_ns();
        let ts2 = SignalPublisher::get_timestamp_ns();

        // ts2 should be >= ts1
        assert!(ts2 >= ts1);
    }
}

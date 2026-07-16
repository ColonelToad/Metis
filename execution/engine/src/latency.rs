//! Minimal latency recording and percentile reporting.
//!
//! Not a production metrics system — this exists to answer one question for
//! Phase B: what does the real, measured latency distribution look like for
//! the signal-to-response path, not what we assume it looks like. A proper
//! system would use something like `hdrhistogram` for streaming,
//! bounded-memory percentile tracking; this collects raw samples in memory
//! and sorts them on read, which is fine for thousands of samples in a load
//! test and not fine for production request volume.

use std::sync::Mutex;
use std::time::Duration;

/// Thread-safe accumulator for latency samples, in nanoseconds.
#[derive(Default)]
pub struct LatencyRecorder {
    samples_ns: Mutex<Vec<u64>>,
}

impl LatencyRecorder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn record(&self, elapsed: Duration) {
        self.samples_ns.lock().unwrap().push(elapsed.as_nanos() as u64);
    }

    /// Compute a percentile summary from all samples recorded so far.
    /// Returns `None` if nothing has been recorded yet.
    pub fn summary(&self) -> Option<LatencySummary> {
        let mut samples = self.samples_ns.lock().unwrap().clone();
        if samples.is_empty() {
            return None;
        }
        samples.sort_unstable();
        Some(LatencySummary {
            count: samples.len(),
            min_ns: samples[0],
            p50_ns: percentile(&samples, 50.0),
            p90_ns: percentile(&samples, 90.0),
            p99_ns: percentile(&samples, 99.0),
            p999_ns: percentile(&samples, 99.9),
            max_ns: *samples.last().unwrap(),
            mean_ns: samples.iter().sum::<u64>() / samples.len() as u64,
        })
    }
}

fn percentile(sorted: &[u64], p: f64) -> u64 {
    if sorted.is_empty() {
        return 0;
    }
    let rank = (p / 100.0) * (sorted.len() as f64 - 1.0);
    let idx = rank.round() as usize;
    sorted[idx.min(sorted.len() - 1)]
}

#[derive(Debug, Clone, Copy)]
pub struct LatencySummary {
    pub count: usize,
    pub min_ns: u64,
    pub p50_ns: u64,
    pub p90_ns: u64,
    pub p99_ns: u64,
    pub p999_ns: u64,
    pub max_ns: u64,
    pub mean_ns: u64,
}

impl std::fmt::Display for LatencySummary {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        writeln!(f, "  n={}", self.count)?;
        writeln!(f, "  min:   {:>10.3} \u{3bc}s", self.min_ns as f64 / 1000.0)?;
        writeln!(f, "  p50:   {:>10.3} \u{3bc}s", self.p50_ns as f64 / 1000.0)?;
        writeln!(f, "  p90:   {:>10.3} \u{3bc}s", self.p90_ns as f64 / 1000.0)?;
        writeln!(f, "  p99:   {:>10.3} \u{3bc}s", self.p99_ns as f64 / 1000.0)?;
        writeln!(f, "  p99.9: {:>10.3} \u{3bc}s", self.p999_ns as f64 / 1000.0)?;
        writeln!(f, "  max:   {:>10.3} \u{3bc}s", self.max_ns as f64 / 1000.0)?;
        write!(f, "  mean:  {:>10.3} \u{3bc}s", self.mean_ns as f64 / 1000.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn percentile_of_sorted_range() {
        let data: Vec<u64> = (1..=100).collect();
        assert_eq!(percentile(&data, 50.0), 50);
        assert_eq!(percentile(&data, 99.0), 99);
    }

    #[test]
    fn summary_reports_correct_count_and_bounds() {
        let rec = LatencyRecorder::new();
        rec.record(Duration::from_micros(10));
        rec.record(Duration::from_micros(20));
        rec.record(Duration::from_micros(30));
        let summary = rec.summary().unwrap();
        assert_eq!(summary.count, 3);
        assert_eq!(summary.min_ns, 10_000);
        assert_eq!(summary.max_ns, 30_000);
    }

    #[test]
    fn empty_recorder_returns_none() {
        let rec = LatencyRecorder::new();
        assert!(rec.summary().is_none());
    }
}

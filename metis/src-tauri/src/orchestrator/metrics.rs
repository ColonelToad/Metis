use super::types::{ExecutionMode, PipelineMetrics};
use chrono::Utc;

/// Tracks metrics for a pipeline execution
#[derive(Clone, Debug)]
pub struct MetricsCollector {
    pub metrics: PipelineMetrics,
}

impl MetricsCollector {
    pub fn new(mode: ExecutionMode) -> Self {
        Self {
            metrics: PipelineMetrics {
                run_timestamp: Utc::now(),
                mode,
                ..Default::default()
            },
        }
    }

    pub fn set_ingest_time(&mut self, duration: f64) {
        self.metrics.ingest_time = duration;
    }

    pub fn set_feature_time(&mut self, duration: f64) {
        self.metrics.feature_time = duration;
    }

    pub fn set_inference_time(&mut self, duration: f64) {
        self.metrics.inference_time = duration;
    }

    pub fn set_signal_collection_time(&mut self, duration: f64) {
        self.metrics.signal_collection_time = duration;
    }

    pub fn set_cache_hits(&mut self, lmp_hit: bool, cme_hit: bool) {
        self.metrics.lmp_cache_hit = lmp_hit;
        self.metrics.cme_cache_hit = cme_hit;
    }

    pub fn set_signals(&mut self, count: u32, avg_confidence: f64) {
        self.metrics.signals_generated = count;
        self.metrics.avg_confidence = avg_confidence;
    }

    pub fn compute_total_time(&mut self) {
        self.metrics.total_time = self.metrics.ingest_time
            + self.metrics.feature_time
            + self.metrics.inference_time
            + self.metrics.signal_collection_time;
    }

    pub fn get_metrics(&self) -> &PipelineMetrics {
        &self.metrics
    }

    pub fn get_metrics_mut(&mut self) -> &mut PipelineMetrics {
        &mut self.metrics
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_metrics_collector_new() {
        let collector = MetricsCollector::new(ExecutionMode::Dev);
        assert_eq!(collector.metrics.ingest_time, 0.0);
        assert_eq!(collector.metrics.mode, ExecutionMode::Dev);
    }

    #[test]
    fn test_metrics_compute_total() {
        let mut collector = MetricsCollector::new(ExecutionMode::Dev);
        collector.set_ingest_time(1.0);
        collector.set_feature_time(2.0);
        collector.set_inference_time(3.0);
        collector.set_signal_collection_time(0.5);
        collector.compute_total_time();

        assert_eq!(collector.metrics.total_time, 6.5);
    }
}

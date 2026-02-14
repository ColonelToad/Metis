use super::types::JobId;
use parking_lot::RwLock;
use std::sync::Arc;
use tracing::info;

/// Job queue manages concurrent pipeline execution
/// Max 1 job running, 1 queued
#[derive(Clone)]
pub struct JobQueue {
    current_job: Arc<RwLock<Option<JobId>>>,
    queued_job: Arc<RwLock<Option<JobId>>>,
    max_queue_depth: usize,
}

impl JobQueue {
    pub fn new() -> Self {
        Self {
            current_job: Arc::new(RwLock::new(None)),
            queued_job: Arc::new(RwLock::new(None)),
            max_queue_depth: 1,
        }
    }

    /// Try to submit a job. Returns true if immediately running, false if queued
    pub fn submit(&self, job_id: JobId) -> Result<bool, String> {
        let mut current = self.current_job.write();
        let mut queued = self.queued_job.write();

        if current.is_none() {
            // No job running, start this one
            *current = Some(job_id.clone());
            info!("Job {} submitted and started immediately", job_id.0);
            Ok(true)
        } else if queued.is_none() && queued.as_ref() != Some(&job_id) {
            // Job running but queue empty, queue this one
            *queued = Some(job_id.clone());
            info!("Job {} queued", job_id.0);
            Ok(false)
        } else {
            // Both slots full
            Err("Queue full: one job running, one already queued".to_string())
        }
    }

    /// Mark current job completed and promote queued job if any
    pub fn complete_current(&self) -> Option<JobId> {
        let mut current = self.current_job.write();
        let mut queued = self.queued_job.write();

        if let Some(job) = current.take() {
            info!("Job {} completed", job.0);
            if let Some(next_job) = queued.take() {
                *current = Some(next_job.clone());
                info!("Promoted queued job {} to running", next_job.0);
                return Some(next_job);
            }
        }
        None
    }

    /// Check if any job is currently running
    pub fn is_running(&self) -> bool {
        self.current_job.read().is_some()
    }

    /// Get currently running job ID
    pub fn current_job_id(&self) -> Option<JobId> {
        self.current_job.read().clone()
    }

    /// Get queued job ID if any
    pub fn queued_job_id(&self) -> Option<JobId> {
        self.queued_job.read().clone()
    }
}

impl Default for JobQueue {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_queue_empty_on_start() {
        let queue = JobQueue::new();
        assert!(!queue.is_running());
        assert!(queue.current_job_id().is_none());
        assert!(queue.queued_job_id().is_none());
    }

    #[test]
    fn test_submit_first_job() {
        let queue = JobQueue::new();
        let job_id = JobId::new();
        let result = queue.submit(job_id.clone());
        assert!(result.unwrap()); // true = immediately running
        assert!(queue.is_running());
        assert_eq!(queue.current_job_id(), Some(job_id));
    }

    #[test]
    fn test_queue_second_job() {
        let queue = JobQueue::new();
        let job1 = JobId::new();
        let job2 = JobId::new();
        queue.submit(job1.clone()).unwrap();
        let result = queue.submit(job2.clone());
        assert!(!result.unwrap()); // false = queued
        assert_eq!(queue.current_job_id(), Some(job1));
        assert_eq!(queue.queued_job_id(), Some(job2));
    }

    #[test]
    fn test_reject_third_job() {
        let queue = JobQueue::new();
        let job1 = JobId::new();
        let job2 = JobId::new();
        let job3 = JobId::new();
        queue.submit(job1).unwrap();
        queue.submit(job2).unwrap();
        let result = queue.submit(job3);
        assert!(result.is_err());
    }

    #[test]
    fn test_promote_queued_job() {
        let queue = JobQueue::new();
        let job1 = JobId::new();
        let job2 = JobId::new();
        queue.submit(job1.clone()).unwrap();
        queue.submit(job2.clone()).unwrap();

        let promoted = queue.complete_current();
        assert_eq!(promoted, Some(job2.clone()));
        assert_eq!(queue.current_job_id(), Some(job2));
        assert!(queue.queued_job_id().is_none());
    }
}

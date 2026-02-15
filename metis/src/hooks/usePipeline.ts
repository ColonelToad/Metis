import { useCallback, useRef, useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';

export interface PipelineStatus {
  job_id: string;
  status: 'running' | 'queued' | 'complete' | 'error' | 'partial';
  phase: 'ingestion' | 'features' | 'inference' | 'signal_collection' | 'complete';
  progress: number;
  timing?: {
    ingest_time: number;
    feature_time: number;
    inference_time: number;
    signal_collection_time: number;
    total_time: number;
  };
  cache_hits?: {
    lmp: boolean;
    cme: boolean;
  };
  error?: string;
}

export interface PipelineResult {
  job_id: string;
  status: string;
  phase: string;
  signals: Array<{
    signal_id: string;
    timestamp: string;
    symbol: string;
    direction: string;
    confidence: number;
    target_quantity: number;
    horizon_minutes: number;
  }>;
  metrics: {
    total_time: number;
    ingest_time: number;
    feature_time: number;
    inference_time: number;
    signal_collection_time: number;
    lmp_cache_hit: boolean;
    cme_cache_hit: boolean;
    signals_generated: number;
    avg_confidence: number;
    run_timestamp: string;
    mode: string;
  };
  error?: string;
}

export function usePipeline() {
  const [isRunning, setIsRunning] = useState(false);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [results, setResults] = useState<PipelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  /// Start a new pipeline execution
  const startPipeline = useCallback(
    async (mode: 'dev' | 'real' = 'dev', forceRefresh: boolean = false) => {
      try {
        setError(null);
        setIsRunning(true);
        setResults(null);

        const response = await invoke<any>('invoke_pipeline', {
          mode,
          force_refresh: forceRefresh,
        });

        const jobId = response.job_id;
        setCurrentJobId(jobId);
        console.log(`Pipeline started with job ID: ${jobId}`);

        // Start polling for status
        pollStatus(jobId);
      } catch (err: any) {
        const errorMsg = err.message || String(err);
        setError(errorMsg);
        setIsRunning(false);
        console.error('Failed to start pipeline:', errorMsg);
      }
    },
    []
  );

  /// Poll for pipeline status
  const pollStatus = useCallback((jobId: string) => {
    // Clear existing interval
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }

    pollIntervalRef.current = setInterval(async () => {
      try {
        const statusResponse = await invoke<any>('poll_pipeline_status', { jobId });
        setStatus(statusResponse);

        // Check if complete
        if (statusResponse.status === 'complete' || statusResponse.status === 'partial' || statusResponse.status === 'error') {
          // Fetch full results
          const resultResponse = await invoke<any>('fetch_pipeline_results', { jobId });
          setResults(resultResponse);
          setIsRunning(false);

          // Stop polling
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
          }
        }
      } catch (err: any) {
        console.error('Error polling status:', err);
      }
    }, 500); // Poll every 500ms
  }, []);

  /// Stop polling
  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  /// Cleanup on unmount
  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  return {
    isRunning,
    currentJobId,
    status,
    results,
    error,
    startPipeline,
    stopPolling,
  };
}

import { useCallback, useRef, useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';

const STORAGE_KEY = 'metis_pipeline_cache';

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
    metadata?: Record<string, any>;
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

interface CachedPipelineData {
  jobId: string;
  results: PipelineResult | null;
  timestamp: number;
}

function getCachedData(): CachedPipelineData | null {
  try {
    const cached = localStorage.getItem(STORAGE_KEY);
    if (cached) {
      return JSON.parse(cached);
    }
  } catch (e) {
    console.warn('Failed to read pipeline cache:', e);
  }
  return null;
}

function saveCacheData(jobId: string, results: PipelineResult | null) {
  try {
    const data: CachedPipelineData = {
      jobId,
      results,
      timestamp: Date.now(),
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch (e) {
    console.warn('Failed to save pipeline cache:', e);
  }
}

export function usePipeline() {
  const [isRunning, setIsRunning] = useState(false);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [results, setResults] = useState<PipelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cacheAge, setCacheAge] = useState<number | null>(null); // Age in seconds
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /// Initialize from localStorage on mount
  useEffect(() => {
    const cached = getCachedData();
    if (cached) {
      setCurrentJobId(cached.jobId);
      setResults(cached.results);
      const ageSeconds = (Date.now() - cached.timestamp) / 1000;
      setCacheAge(ageSeconds);
      console.log(`Restored pipeline results from cache (age: ${ageSeconds}s)`);
    }
  }, []);

  /// Start a new pipeline execution
  const startPipeline = useCallback(
    async (mode: 'dev' | 'real' = 'dev', forceRefresh: boolean = false) => {
      try {
        setError(null);
        setIsRunning(true);
        setResults(null);
        setCacheAge(null);

        const response = await invoke<any>('invoke_pipeline', {
          mode,
          force_refresh: forceRefresh,
        });

        const jobId = response.job_id;
        setCurrentJobId(jobId);
        saveCacheData(jobId, null); // Cache the jobId immediately
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
          
          // Cache results to localStorage
          saveCacheData(jobId, resultResponse);
          setCacheAge(0); // Just cached, age is 0
          
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
    cacheAge, // Age in seconds, null if not cached
    startPipeline,
    stopPolling,
  };
}

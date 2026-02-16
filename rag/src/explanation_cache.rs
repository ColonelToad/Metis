use crate::pipeline::ExplanationResult;
use crate::types::TradingSignal;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

/// Cache key based on signal properties
fn cache_key(signal: &TradingSignal) -> String {
    // Hash on: instrument, direction, confidence (rounded), price (quantized)
    // This captures "similar enough" signals without requiring exact matches
    format!(
        "{}_{}_{}_{:.0}",
        signal.instrument.to_lowercase(),
        signal.direction.to_lowercase(),
        (signal.confidence * 100.0).round() as u32,
        (signal.context.current_price * 10.0).round() as i64 // Quantize to nearest 0.1
    )
}

/// Simple in-memory cache for explanation results
/// Clears after 1 hour of inactivity per key
pub struct ExplanationCache {
    cache: Arc<RwLock<HashMap<String, CachedExplanation>>>,
    max_entries: usize,
}

struct CachedExplanation {
    result: ExplanationResult,
    cached_at: std::time::Instant,
}

impl ExplanationCache {
    pub fn new(max_entries: usize) -> Self {
        Self {
            cache: Arc::new(RwLock::new(HashMap::new())),
            max_entries,
        }
    }

    /// Try to get cached result for a signal
    pub async fn get(&self, signal: &TradingSignal) -> Option<ExplanationResult> {
        let key = cache_key(signal);
        let cache = self.cache.read().await;

        if let Some(cached) = cache.get(&key) {
            // Check if cache is still fresh (1 hour TTL)
            if cached.cached_at.elapsed().as_secs() < 3600 {
                tracing::debug!("Cache hit: {}", key);
                return Some(cached.result.clone());
            }
        }

        None
    }

    /// Store result in cache
    pub async fn put(&self, signal: &TradingSignal, result: ExplanationResult) {
        let key = cache_key(signal);
        let mut cache = self.cache.write().await;

        // Simple eviction: if cache is full, clear oldest entry
        if cache.len() >= self.max_entries {
            if let Some(oldest_key) = cache
                .iter()
                .min_by_key(|(_, v)| v.cached_at)
                .map(|(k, _)| k.clone())
            {
                cache.remove(&oldest_key);
                tracing::debug!("Cache evicted: {}", oldest_key);
            }
        }

        cache.insert(
            key.clone(),
            CachedExplanation {
                result: result.clone(),
                cached_at: std::time::Instant::now(),
            },
        );

        tracing::debug!("Cache set: {}", key);
    }

    /// Clear all cache entries
    pub async fn clear(&self) {
        self.cache.write().await.clear();
        tracing::info!("Cache cleared");
    }

    /// Get cache statistics
    pub async fn stats(&self) -> (usize, usize) {
        let cache = self.cache.read().await;
        (cache.len(), self.max_entries)
    }
}

impl Clone for ExplanationCache {
    fn clone(&self) -> Self {
        Self {
            cache: Arc::clone(&self.cache),
            max_entries: self.max_entries,
        }
    }
}

// Make ExplanationResult cloneable (required for caching)
// This should already be derived in the original type

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_cache_key_generation() {
        let signal1 = TradingSignal {
            id: "test1".to_string(),
            instrument: "NG".to_string(),
            direction: "BUY".to_string(),
            confidence: 0.85,
            timestamp: chrono::Utc::now(),
            context: crate::types::TradingContext {
                current_price: 3.142,
                grid_stress_index: 75.0,
                temperature_anomaly: 5.0,
                recent_policy_events: vec![],
                primary_region: "ERCOT".to_string(),
            },
        };

        let key1 = cache_key(&signal1);
        assert!(key1.contains("ng"));
        assert!(key1.contains("buy"));
        assert!(key1.contains("85")); // 0.85 * 100 = 85
    }

    #[tokio::test]
    async fn test_cache_put_get() {
        let cache = ExplanationCache::new(10);
        let signal = TradingSignal {
            id: "test".to_string(),
            instrument: "NG".to_string(),
            direction: "BUY".to_string(),
            confidence: 0.85,
            timestamp: chrono::Utc::now(),
            context: crate::types::TradingContext {
                current_price: 3.0,
                grid_stress_index: 75.0,
                temperature_anomaly: 5.0,
                recent_policy_events: vec![],
                primary_region: "ERCOT".to_string(),
            },
        };

        // Cache should be empty initially
        assert!(cache.get(&signal).await.is_none());

        // Stats
        let (current, max) = cache.stats().await;
        assert_eq!(current, 0);
        assert_eq!(max, 10);
    }
}


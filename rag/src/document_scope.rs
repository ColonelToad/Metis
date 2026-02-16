use crate::types::Document;
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};

/// Defines a search scope with filters and weighting
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentScope {
    pub name: String,
    pub sources: Vec<String>,              // Filter by source: ["Congress", "EIA", "Weather"]
    pub categories: Vec<String>,           // Filter by category: ["policy", "market_data"]
    pub tags: Vec<String>,                 // Filter by tags: ["storage", "supply"]
    pub date_range: Option<(DateTime<Utc>, DateTime<Utc>)>,
    pub focus_weight: f64,                 // 1.0 = normal, 2.0 = boost relevance
}

impl Default for DocumentScope {
    fn default() -> Self {
        Self {
            name: "default".to_string(),
            sources: vec![],      // No filter = all sources
            categories: vec![],   // No filter = all categories
            tags: vec![],         // No filter = all tags
            date_range: None,
            focus_weight: 1.0,
        }
    }
}

impl DocumentScope {
    /// Create a default scope (no filtering)
    pub fn new() -> Self {
        Self::default()
    }

    /// Scope: Recent Congress bills (last N days)
    pub fn recent_congress_bills(days: i64) -> Self {
        Self {
            name: format!("recent_congress_{}_days", days),
            sources: vec!["Congress".to_string()],
            categories: vec!["policy".to_string()],
            tags: vec!["bills".to_string(), "amendments".to_string()],
            date_range: Some((Utc::now() - Duration::days(days), Utc::now())),
            focus_weight: 2.0,  // Boost recent bills
        }
    }

    /// Scope: Recent EIA reports (last N days)
    pub fn recent_eia_reports(days: i64) -> Self {
        Self {
            name: format!("recent_eia_{}_days", days),
            sources: vec!["EIA".to_string()],
            categories: vec!["market_data".to_string()],
            tags: vec!["storage".to_string(), "supply".to_string()],
            date_range: Some((Utc::now() - Duration::days(days), Utc::now())),
            focus_weight: 2.0,
        }
    }

    /// Scope: Weather + Grid data (last N days)
    pub fn recent_weather_grid(days: i64) -> Self {
        Self {
            name: format!("recent_weather_grid_{}_days", days),
            sources: vec!["NOAA".to_string(), "CAISO".to_string()],
            categories: vec!["weather".to_string(), "grid".to_string()],
            tags: vec!["temperature".to_string(), "demand".to_string(), "stress".to_string()],
            date_range: Some((Utc::now() - Duration::days(days), Utc::now())),
            focus_weight: 1.5,
        }
    }

    /// Scope: Cross-source comparison (e.g., CME earnings vs port activity)
    pub fn cross_source(sources: &[&str], name: &str) -> Self {
        Self {
            name: name.to_string(),
            sources: sources.iter().map(|s| s.to_string()).collect(),
            categories: vec![],
            tags: vec![],
            date_range: None,
            focus_weight: 1.5,
        }
    }

    /// Add source filter
    pub fn with_sources(mut self, sources: Vec<String>) -> Self {
        self.sources = sources;
        self
    }

    /// Add category filter
    pub fn with_categories(mut self, categories: Vec<String>) -> Self {
        self.categories = categories;
        self
    }

    /// Add tag filter
    pub fn with_tags(mut self, tags: Vec<String>) -> Self {
        self.tags = tags;
        self
    }

    /// Set date range
    pub fn with_date_range(mut self, from: DateTime<Utc>, to: DateTime<Utc>) -> Self {
        self.date_range = Some((from, to));
        self
    }

    /// Set focus weight (affects relevance ranking)
    pub fn with_focus_weight(mut self, weight: f64) -> Self {
        self.focus_weight = weight;
        self
    }

    /// Check if a document matches this scope
    pub fn matches_document(&self, doc: &Document, metadata: Option<&DocumentMetadata>) -> bool {
        // Source filter
        if !self.sources.is_empty() && !self.sources.contains(&doc.source) {
            return false;
        }

        // Category filter
        if !self.categories.is_empty() && !self.categories.contains(&doc.category) {
            return false;
        }

        // Date range filter
        if let Some((from, to)) = self.date_range {
            if doc.timestamp < from || doc.timestamp > to {
                return false;
            }
        }

        // Tag filter (requires metadata)
        if !self.tags.is_empty() {
            if let Some(meta) = metadata {
                let has_matching_tag = self.tags.iter().any(|tag| meta.tags.contains(tag));
                if !has_matching_tag {
                    return false;
                }
            } else {
                return false;  // No metadata, can't match tags
            }
        }

        true
    }

    /// Calculate relevance multiplier for a document
    /// Returns 1.0 (normal) by default, can be boosted based on scope
    pub fn relevance_multiplier(&self, doc: &Document) -> f64 {
        if self.matches_document(doc, None) {
            self.focus_weight
        } else {
            0.0  // Document doesn't match scope
        }
    }
}

/// Document metadata for scope matching
#[derive(Debug, Clone)]
pub struct DocumentMetadata {
    pub tags: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    fn create_test_doc(source: &str, category: &str) -> Document {
        Document {
            id: "test".to_string(),
            title: "Test".to_string(),
            content: "Test content".to_string(),
            source: source.to_string(),
            category: category.to_string(),
            timestamp: Utc::now(),
        }
    }

    #[test]
    fn test_default_scope_matches_all() {
        let scope = DocumentScope::new();
        let doc = create_test_doc("EIA", "market_data");
        assert!(scope.matches_document(&doc, None));
    }

    #[test]
    fn test_source_filter() {
        let scope = DocumentScope::new().with_sources(vec!["Congress".to_string()]);
        let eia_doc = create_test_doc("EIA", "market_data");
        let congress_doc = create_test_doc("Congress", "policy");

        assert!(!scope.matches_document(&eia_doc, None));
        assert!(scope.matches_document(&congress_doc, None));
    }

    #[test]
    fn test_category_filter() {
        let scope = DocumentScope::new().with_categories(vec!["policy".to_string()]);
        let policy_doc = create_test_doc("Congress", "policy");
        let market_doc = create_test_doc("EIA", "market_data");

        assert!(scope.matches_document(&policy_doc, None));
        assert!(!scope.matches_document(&market_doc, None));
    }

    #[test]
    fn test_date_range_filter() {
        let now = Utc::now();
        let scope = DocumentScope::new().with_date_range(
            now - Duration::days(7),
            now + Duration::days(1),
        );

        let recent_doc = Document {
            id: "recent".to_string(),
            title: "Recent".to_string(),
            content: "Recent content".to_string(),
            source: "EIA".to_string(),
            category: "market_data".to_string(),
            timestamp: now,
        };

        let old_doc = Document {
            id: "old".to_string(),
            title: "Old".to_string(),
            content: "Old content".to_string(),
            source: "EIA".to_string(),
            category: "market_data".to_string(),
            timestamp: now - Duration::days(30),
        };

        assert!(scope.matches_document(&recent_doc, None));
        assert!(!scope.matches_document(&old_doc, None));
    }

    #[test]
    fn test_recent_congress_bills_scope() {
        let scope = DocumentScope::recent_congress_bills(30);
        assert_eq!(scope.sources, vec!["Congress".to_string()]);
        assert_eq!(scope.focus_weight, 2.0);
    }

    #[test]
    fn test_relevance_multiplier() {
        let scope = DocumentScope::new().with_sources(vec!["EIA".to_string()]);
        let doc = create_test_doc("EIA", "market_data");
        assert_eq!(scope.relevance_multiplier(&doc), 1.0);
    }

    #[test]
    fn test_relevance_multiplier_with_focus() {
        let scope = DocumentScope::new()
            .with_sources(vec!["Congress".to_string()])
            .with_focus_weight(2.5);
        let doc = create_test_doc("Congress", "policy");
        assert_eq!(scope.relevance_multiplier(&doc), 2.5);
    }

    #[test]
    fn test_non_matching_document_zero_relevance() {
        let scope = DocumentScope::new().with_sources(vec!["Congress".to_string()]);
        let doc = create_test_doc("EIA", "market_data");
        assert_eq!(scope.relevance_multiplier(&doc), 0.0);
    }
}

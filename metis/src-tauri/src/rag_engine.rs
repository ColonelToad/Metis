/// RAG Engine management for Tauri app
/// Provides global access to ExplainabilityRAG instance

use rag::{ExplainabilityRAG, ExplanationResult, SessionManager, startup_index};
use once_cell::sync::OnceCell;
use std::sync::Arc;
use tokio::sync::Mutex;
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicU32, Ordering};

static RAG_ENGINE: OnceCell<Arc<Mutex<ExplainabilityRAG>>> = OnceCell::new();
static SESSION_MANAGER: OnceCell<Arc<Mutex<SessionManager>>> = OnceCell::new();

/// RAG engine initialization status
/// 0 = NotStarted, 1 = Initializing, 2 = Ready, 3+ = Failed with code
static RAG_STATUS: AtomicU32 = AtomicU32::new(0);
static RAG_ERROR: OnceCell<String> = OnceCell::new();

/// Initialize RAG engine on app startup
pub async fn init_rag_engine(model_path: &str, db_path: &str) -> Result<(), String> {
    RAG_STATUS.store(1, Ordering::SeqCst); // Initializing
    
    let rag = ExplainabilityRAG::new(model_path, db_path, false)
        .await
        .map_err(|e| {
            let error_msg = format!("Failed to initialize RAG: {}", e);
            let _ = RAG_ERROR.set(error_msg.clone());
            RAG_STATUS.store(3, Ordering::SeqCst); // Failed
            error_msg
        })?;

    // Index documents on startup (async, non-blocking)
    let db_path_str = db_path.to_string();
    tokio::spawn(async move {
        match rag::DocumentStore::new(&db_path_str, false).await {
            Ok(doc_store) => {
                let doc_store_arc = Arc::new(Mutex::new(doc_store));
                match startup_index(doc_store_arc).await {
                    Ok(stats) => {
                        tracing::info!(
                            "Document indexing complete: {} documents indexed",
                            stats.total_documents
                        );
                    }
                    Err(e) => {
                        tracing::warn!("Document indexing failed: {}", e);
                    }
                }
            }
            Err(e) => {
                tracing::warn!("Failed to create document store for indexing: {}", e);
            }
        }
    });

    RAG_ENGINE
        .set(Arc::new(Mutex::new(rag)))
        .map_err(|_| {
            let error_msg = "RAG engine already initialized".to_string();
            let _ = RAG_ERROR.set(error_msg.clone());
            RAG_STATUS.store(3, Ordering::SeqCst); // Failed
            error_msg
        })?;

    RAG_STATUS.store(2, Ordering::SeqCst); // Ready
    tracing::info!("RAG engine initialized successfully");
    Ok(())
}

/// Initialize session manager
pub fn init_session_manager() -> Result<(), String> {
    let session_manager = SessionManager::new(2048); // 2048 token context window
    SESSION_MANAGER
        .set(Arc::new(Mutex::new(session_manager)))
        .map_err(|_| "Session manager already initialized".to_string())?;
    
    tracing::info!("Session manager initialized successfully");
    Ok(())
}

/// Get reference to global session manager
pub fn get_session_manager() -> Result<Arc<Mutex<SessionManager>>, String> {
    SESSION_MANAGER
        .get()
        .cloned()
        .ok_or_else(|| "Session manager not initialized".to_string())
}
pub fn get_rag_engine() -> Result<Arc<Mutex<ExplainabilityRAG>>, String> {
    RAG_ENGINE
        .get()
        .cloned()
        .ok_or_else(|| "RAG engine not initialized".to_string())
}

/// Get RAG engine status
pub fn get_rag_status() -> RagStatusResponse {
    let status_code = RAG_STATUS.load(Ordering::SeqCst);
    let status = match status_code {
        0 => "not_started".to_string(),
        1 => "initializing".to_string(),
        2 => "ready".to_string(),
        _ => "failed".to_string(),
    };
    
    let error = if status_code >= 3 {
        RAG_ERROR.get().cloned()
    } else {
        None
    };
    
    RagStatusResponse { status, error }
}

/// Serialize ExplanationResult for frontend
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExplanationResponse {
    pub status: String,
    pub explanation: Option<ExplanationData>,
    pub partial_explanation: Option<ExplanationData>,
    pub retry_token: Option<String>,
    pub error_message: Option<String>,
}

/// RAG Engine status response
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RagStatusResponse {
    pub status: String, // "not_started", "initializing", "ready", "failed"
    pub error: Option<String>,
}

/// Session statistics response for frontend
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionStatsResponse {
    pub active_session_id: String,
    pub active_tokens: usize,
    pub context_window: usize,
    pub token_percent: usize,
    pub message_count: usize,
    pub has_standby: bool,
    pub total_sessions_created: usize,
    pub total_handoffs: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExplanationData {
    pub signal_id: String,
    pub market_analysis: Option<String>,
    pub signal_drivers: Option<String>,
    pub risks: Option<String>,
    pub expected_outcome: Option<String>,
    pub citations: Vec<CitationData>,
    pub raw_text: String,
    pub confidence_score: f64,
    pub generated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CitationData {
    pub doc_id: String,
    pub title: String,
    pub source: String,
    pub excerpt: String,
}

/// Convert ExplanationResult to frontend response
pub fn format_explanation_response(result: ExplanationResult) -> ExplanationResponse {
    match result {
        ExplanationResult::Success { explanation } => {
            let citations = explanation
                .citations
                .iter()
                .map(|c| CitationData {
                    doc_id: c.doc_id.clone(),
                    title: c.title.clone(),
                    source: c.source.clone(),
                    excerpt: c.excerpt.clone(),
                })
                .collect();

            ExplanationResponse {
                status: "success".to_string(),
                explanation: Some(ExplanationData {
                    signal_id: explanation.signal_id,
                    market_analysis: explanation.market_analysis,
                    signal_drivers: explanation.signal_drivers,
                    risks: explanation.risks,
                    expected_outcome: explanation.expected_outcome,
                    citations,
                    raw_text: explanation.raw_text,
                    confidence_score: explanation.confidence_score,
                    generated_at: explanation.generated_at.to_rfc3339(),
                }),
                partial_explanation: None,
                retry_token: None,
                error_message: None,
            }
        }

        ExplanationResult::Timeout {
            partial_explanation,
            retry_token,
        } => {
            let partial = partial_explanation.map(|exp| ExplanationData {
                signal_id: exp.signal_id,
                market_analysis: exp.market_analysis,
                signal_drivers: exp.signal_drivers,
                risks: exp.risks,
                expected_outcome: exp.expected_outcome,
                citations: exp
                    .citations
                    .iter()
                    .map(|c| CitationData {
                        doc_id: c.doc_id.clone(),
                        title: c.title.clone(),
                        source: c.source.clone(),
                        excerpt: c.excerpt.clone(),
                    })
                    .collect(),
                raw_text: exp.raw_text,
                confidence_score: exp.confidence_score,
                generated_at: exp.generated_at.to_rfc3339(),
            });

            ExplanationResponse {
                status: "timeout".to_string(),
                explanation: None,
                partial_explanation: partial,
                retry_token: Some(retry_token),
                error_message: Some(
                    "Explanation generation timed out. Partial result shown. Click 'Retry' to continue."
                        .to_string(),
                ),
            }
        }

        ExplanationResult::MissingDocuments {
            explanation,
            missing_docs,
        } => {
            let citations = explanation
                .citations
                .iter()
                .map(|c| CitationData {
                    doc_id: c.doc_id.clone(),
                    title: c.title.clone(),
                    source: c.source.clone(),
                    excerpt: c.excerpt.clone(),
                })
                .collect();

            ExplanationResponse {
                status: "partial".to_string(),
                explanation: Some(ExplanationData {
                    signal_id: explanation.signal_id,
                    market_analysis: explanation.market_analysis,
                    signal_drivers: explanation.signal_drivers,
                    risks: explanation.risks,
                    expected_outcome: explanation.expected_outcome,
                    citations,
                    raw_text: explanation.raw_text,
                    confidence_score: explanation.confidence_score,
                    generated_at: explanation.generated_at.to_rfc3339(),
                }),
                partial_explanation: None,
                retry_token: None,
                error_message: Some(format!(
                    "Some referenced documents not available: {:?}",
                    missing_docs
                )),
            }
        }

        ExplanationResult::TemplateFallback {
            explanation,
            reason,
        } => {
            let citations = explanation
                .citations
                .iter()
                .map(|c| CitationData {
                    doc_id: c.doc_id.clone(),
                    title: c.title.clone(),
                    source: c.source.clone(),
                    excerpt: c.excerpt.clone(),
                })
                .collect();

            ExplanationResponse {
                status: "fallback".to_string(),
                explanation: Some(ExplanationData {
                    signal_id: explanation.signal_id,
                    market_analysis: explanation.market_analysis,
                    signal_drivers: explanation.signal_drivers,
                    risks: explanation.risks,
                    expected_outcome: explanation.expected_outcome,
                    citations,
                    raw_text: explanation.raw_text,
                    confidence_score: explanation.confidence_score,
                    generated_at: explanation.generated_at.to_rfc3339(),
                }),
                partial_explanation: None,
                retry_token: None,
                error_message: Some(format!("Could not generate full explanation: {}", reason)),
            }
        }
    }
}

/// Get current session statistics
pub async fn get_session_stats() -> Result<SessionStatsResponse, String> {
    let session_mgr = get_session_manager()?;
    let sm_lock = session_mgr.lock().await;
    let stats = sm_lock.get_stats();
    
    Ok(SessionStatsResponse {
        active_session_id: stats.active_session_id,
        active_tokens: stats.active_tokens,
        context_window: stats.context_window,
        token_percent: stats.token_percent,
        message_count: stats.message_count,
        has_standby: stats.has_standby,
        total_sessions_created: stats.total_sessions_created,
        total_handoffs: stats.total_handoffs,
    })
}

// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
pub mod orchestrator;
pub mod rag_engine;
mod pipeline_bridge;

use pipeline_bridge::{get_pipeline_results, get_pipeline_status, health_check, run_pipeline};
use rag_engine::{get_rag_engine, get_rag_status, init_rag_engine, init_session_manager, get_session_stats, format_explanation_response, ExplanationResponse, RagStatusResponse};
use pyo3::prepare_freethreaded_python;
use std::path::PathBuf;

use rag::TradingSignal;

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

/// Start a pipeline execution via orchestrator service
#[tauri::command]
async fn invoke_pipeline(
    mode: String,
    force_refresh: Option<bool>,
) -> Result<serde_json::Value, String> {
    run_pipeline(mode, force_refresh.unwrap_or(false)).await
}

/// Poll pipeline status
#[tauri::command]
async fn poll_pipeline_status(job_id: String) -> Result<serde_json::Value, String> {
    get_pipeline_status(job_id).await
}

/// Get pipeline results
#[tauri::command]
async fn fetch_pipeline_results(job_id: String) -> Result<serde_json::Value, String> {
    get_pipeline_results(job_id).await
}

/// Check if orchestrator service is running
#[tauri::command]
async fn check_orchestrator_health() -> Result<serde_json::Value, String> {
    health_check().await
}

/// Check RAG engine initialization status
#[tauri::command]
fn check_rag_status() -> RagStatusResponse {
    get_rag_status()
}

/// Get session statistics for token budget tracking
#[tauri::command]
async fn get_session_status() -> Result<rag_engine::SessionStatsResponse, String> {
    get_session_stats().await
}

/// Generate explanation for a trading signal
#[tauri::command]
async fn explain_trading_signal(
    signal: serde_json::Value,
) -> Result<ExplanationResponse, String> {
    // Wait up to 5 seconds for RAG to be ready, with periodic checks
    let mut attempts = 0;
    loop {
        let status = get_rag_status();
        if status.status == "ready" {
            break;
        }
        if status.status == "failed" {
            return Err(format!("RAG engine failed to initialize: {}", status.error.unwrap_or_default()));
        }
        if attempts >= 50 {
            // 5 seconds total (50 * 100ms)
            return Err("RAG engine still initializing after 5 seconds, please try again".to_string());
        }
        tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
        attempts += 1;
    }
    
    let rag = get_rag_engine()?;
    let session_mgr = rag_engine::get_session_manager()?;

    // Parse signal from JSON
    let trading_signal: TradingSignal = serde_json::from_value(signal)
        .map_err(|e| format!("Invalid signal format: {}", e))?;

    // Create a signal summary for token tracking
    let signal_summary = format!(
        "Signal: {} - {} (confidence: {:.2})",
        trading_signal.instrument,
        trading_signal.direction,
        trading_signal.confidence
    );
    let input_tokens = rag::token_counter::estimate_tokens(&signal_summary);

    // Track in session before generating explanation
    let mut session_lock = session_mgr.lock().await;
    let (should_warn, should_handoff) = session_lock
        .add_message("user", &signal_summary, input_tokens)
        .await
        .unwrap_or((false, false));
    drop(session_lock);

    // Generate explanation
    let rag_lock = rag.lock().await;
    let result = rag_lock.explain_signal(&trading_signal).await;

    // Estimate tokens in response and track it
    let response_tokens = match &result {
        rag::ExplanationResult::Success { explanation } => {
            rag::token_counter::estimate_tokens(&explanation.raw_text)
        }
        rag::ExplanationResult::Timeout { partial_explanation, .. } => {
            partial_explanation
                .as_ref()
                .map(|e| rag::token_counter::estimate_tokens(&e.raw_text))
                .unwrap_or(0)
        }
        rag::ExplanationResult::MissingDocuments { explanation, .. } => {
            rag::token_counter::estimate_tokens(&explanation.raw_text)
        }
        rag::ExplanationResult::TemplateFallback { explanation, .. } => {
            rag::token_counter::estimate_tokens(&explanation.raw_text)
        }
    };

    // Track response in session
    let mut session_lock = session_mgr.lock().await;
    let _ = session_lock
        .add_message("assistant", "", response_tokens)
        .await;
    drop(session_lock);

    // Format for frontend with session tracking info
    let response = format_explanation_response(result);
    // Add session tracking info if needed (currently added to response status if warning/handoff)
    if should_warn {
        tracing::warn!("Token budget warning: 50% threshold exceeded");
    }
    if should_handoff {
        tracing::info!("Session handoff triggered: 80% threshold exceeded");
    }

    Ok(response)
}

/// Set active document scope for retrieval
#[tauri::command]
async fn set_document_scope(scope: serde_json::Value) -> Result<(), String> {
    let rag = get_rag_engine()?;

    // Parse scope from JSON
    let doc_scope: rag::DocumentScope = serde_json::from_value(scope)
        .map_err(|e| format!("Invalid scope format: {}", e))?;

    // Update scope
    let mut rag_lock = rag.lock().await;
    rag_lock.set_scope(doc_scope);

    Ok(())
}

/// Retry explanation using retry token
#[tauri::command]
async fn retry_explanation(
    signal: serde_json::Value,
    retry_token: String,
) -> Result<ExplanationResponse, String> {
    // Wait up to 5 seconds for RAG to be ready, with periodic checks
    let mut attempts = 0;
    loop {
        let status = get_rag_status();
        if status.status == "ready" {
            break;
        }
        if status.status == "failed" {
            return Err(format!("RAG engine failed to initialize: {}", status.error.unwrap_or_default()));
        }
        if attempts >= 50 {
            // 5 seconds total (50 * 100ms)
            return Err("RAG engine still initializing after 5 seconds, please try again".to_string());
        }
        tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
        attempts += 1;
    }
    
    let rag = get_rag_engine()?;

    // Parse signal
    let trading_signal: TradingSignal = serde_json::from_value(signal)
        .map_err(|e| format!("Invalid signal format: {}", e))?;

    // Retry explanation
    let rag_lock = rag.lock().await;
    let result = rag_lock.retry_explanation(&trading_signal, &retry_token).await;

    Ok(format_explanation_response(result))
}

/// Handle a follow-up chat message in an active conversation
#[tauri::command]
async fn chat_with_llm(
    session_id: String,
    user_message: String,
    conversation_summary: Option<String>,
) -> Result<serde_json::Value, String> {
    // Wait for RAG to be ready
    let mut attempts = 0;
    loop {
        let status = get_rag_status();
        if status.status == "ready" {
            break;
        }
        if status.status == "failed" {
            return Err(format!("RAG engine failed to initialize: {}", status.error.unwrap_or_default()));
        }
        if attempts >= 50 {
            return Err("RAG engine still initializing after 5 seconds, please try again".to_string());
        }
        tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
        attempts += 1;
    }
    
    let rag = get_rag_engine()?;
    let session_mgr = rag_engine::get_session_manager()?;

    // Get the RAG engine to call chat_response
    let rag_lock = rag.lock().await;
    
    // Build conversation context (from summary or just use recent messages)
    let context = if let Some(summary) = conversation_summary {
        summary
    } else {
        // Fall back to building context from session history
        let session_lock = session_mgr.lock().await;
        let history = session_lock.get_conversation_history();
        
        // Build context string from last 5 messages
        let recent_messages: Vec<String> = history
            .iter()
            .rev()
            .take(5)
            .rev()
            .map(|msg| format!("{}: {}", msg.role, msg.content))
            .collect();
        
        recent_messages.join("\n")
    };

    // Generate chat response
    let response = rag_lock.chat_response(&context, &user_message).await
        .map_err(|e| format!("Chat response failed: {}", e))?;

    // Track tokens and add to session
    let response_tokens = rag::token_counter::estimate_tokens(&response);
    let user_tokens = rag::token_counter::estimate_tokens(&user_message);

    let mut session_lock = session_mgr.lock().await;
    let _ = session_lock.add_message("user", &user_message, user_tokens).await;
    let (warn, handoff) = session_lock.add_message("assistant", &response, response_tokens).await
        .map_err(|e| format!("Session tracking failed: {}", e))?;
    drop(session_lock);

    // Return response with metadata
    Ok(serde_json::json!({
        "message": response,
        "session_id": session_id,
        "token_warning": warn,
        "session_handoff": handoff,
    }))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run_tauri() {
    // Initialize Python interpreter for multi-threaded use
    // This must be done ONCE before any Python APIs are called from any thread
    prepare_freethreaded_python();

    // Check for --validate flag (background diagnostics mode)
    let validate_mode = std::env::args().any(|arg| arg == "--validate");

    // Start orchestrator service in background thread with its own tokio runtime
    let _orchestrator_handle = std::thread::spawn(move || {
        // Calculate the actual project root
        // CARGO_MANIFEST_DIR is the directory of the Cargo.toml being compiled (metis/src-tauri)
        // We need to go up 2 levels to reach the project root where research/ folder is
        let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|p| p.parent())
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| PathBuf::from("."));

        tracing::info!("Project root resolved to: {}", project_root.display());

        let rt = tokio::runtime::Runtime::new().expect("Failed to create tokio runtime");

        // Run orchestrator service on default port 9000
        rt.block_on(orchestrator::server::start_http_server(
            project_root.clone(),
            9000,
        ));
    });

    // If validate mode is enabled, run background diagnostics
    if validate_mode {
        tracing::info!("Validation mode enabled - running background diagnostics");
        let diagnostics_handle = std::thread::spawn(|| {
            std::thread::sleep(std::time::Duration::from_millis(1000));
            match orchestrator::diagnostics::run_synchronous_diagnostics(9000) {
                Ok(summary) => {
                    tracing::info!("Background validation complete: {}", summary);
                }
                Err(e) => {
                    tracing::warn!("Background validation warning: {}", e);
                }
            }
        });
        // Don't wait for diagnostics - let it run in background
        let _ = diagnostics_handle;
    }

    // Initialize RAG engine in background
    let _rag_init = std::thread::spawn(|| {
        let rt = tokio::runtime::Runtime::new().expect("Failed to create RAG runtime");
        rt.block_on(async {
            // Calculate absolute paths for model and database
            let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .and_then(|p| p.parent())
                .map(|p| p.to_path_buf())
                .unwrap_or_else(|| PathBuf::from("."));
            
            let model_path = project_root.join("rag/llm/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf");
            let db_path = project_root.join("data/lance");

            let model_path_str = model_path.to_string_lossy().to_string();
            let db_path_str = db_path.to_string_lossy().to_string();

            tracing::info!("RAG Initialization: model_path={}", model_path_str);
            tracing::info!("RAG Initialization: db_path={}", db_path_str);

            match init_rag_engine(&model_path_str, &db_path_str).await {
                Ok(()) => {
                    tracing::info!("RAG engine initialized successfully");
                    // Initialize session manager after RAG engine
                    if let Err(e) = init_session_manager() {
                        tracing::warn!("Session manager initialization failed: {}", e);
                    } else {
                        tracing::info!("Session manager initialized successfully");
                    }
                }
                Err(e) => {
                    tracing::warn!("RAG engine initialization failed (will use templates): {}", e);
                }
            }
        });
    });

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            greet,
            invoke_pipeline,
            poll_pipeline_status,
            fetch_pipeline_results,
            check_orchestrator_health,
            check_rag_status,
            get_session_status,
            explain_trading_signal,
            set_document_scope,
            retry_explanation,
            chat_with_llm,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

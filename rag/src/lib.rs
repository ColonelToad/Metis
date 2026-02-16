// lib.rs
pub mod document_indexer;
pub mod document_scope;
pub mod document_store;
pub mod embedding;
pub mod explanation_parser;
pub mod explanation_cache;
pub mod llm;
pub mod pipeline;
pub mod python_bridge;
pub mod session_manager;
pub mod template;
pub mod token_counter;
pub mod types;

pub use document_indexer::{daily_refresh, startup_index, DocumentIndexer, IndexingStats};
pub use document_scope::DocumentScope;
pub use document_store::DocumentStore;
pub use explanation_parser::ExplanationParser;
pub use pipeline::{ExplainabilityRAG, ExplanationResult};
pub use python_bridge::PythonRAGBridge;
pub use session_manager::SessionManager;
pub use types::{Explanation, TradingContext, TradingSignal};

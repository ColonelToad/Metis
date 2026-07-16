// lib.rs
pub mod deterministic_reasoning;
pub mod document_indexer;
pub mod document_scope;
pub mod document_store;
pub mod embedding;
pub mod explanation_cache;
pub mod explanation_parser;
pub mod llm;
pub mod pipeline;
pub mod python_bridge;
pub mod python_env;
pub mod reasoning_chain;
pub mod session_manager;
pub mod template;
pub mod think_strip;
pub mod token_counter;
pub mod types;

pub use document_indexer::{daily_refresh, startup_index, DocumentIndexer, IndexingStats};
pub use document_scope::DocumentScope;
pub use document_store::DocumentStore;
pub use embedding::EmbeddingEngine;
pub use explanation_parser::ExplanationParser;
pub use pipeline::{ExplainabilityRAG, ExplanationResult};
pub use python_bridge::PythonRAGBridge;
pub use reasoning_chain::ReasoningChain;
pub use session_manager::SessionManager;
pub use types::{Document, Explanation, TradingContext, TradingSignal};

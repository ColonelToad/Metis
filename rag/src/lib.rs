// lib.rs
pub mod document_store;
pub mod embedding;
pub mod llm;
pub mod pipeline;
pub mod template;
pub mod types;

pub use pipeline::ExplainabilityRAG;
pub use types::{Explanation, TradingContext, TradingSignal};

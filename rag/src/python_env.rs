use pyo3::prelude::*;

/// Ensure the Metis Python packages (`rag/`, etc.) are importable from the
/// embedded interpreter.
///
/// Appends two entries to `sys.path`:
///   1. A hardcoded path to this machine's Metis checkout. This only works
///      on this machine as written — it should eventually become a
///      build-time or runtime configuration value rather than a literal,
///      but for now it's centralized here instead of copy-pasted across
///      three call sites (`python_bridge.rs`, `document_indexer.rs`,
///      `llm.rs`), which is where it lived before this pass.
///   2. The current working directory, so invocation from a different
///      working directory (e.g. from the Tauri desktop app) also resolves.
///
/// Both appends are best-effort and silently ignored on failure, matching
/// the behavior at all three original call sites.
pub fn setup_sys_path(py: Python<'_>) {
    if let Ok(sys) = py.import_bound("sys") {
        if let Ok(path) = sys.getattr("path") {
            let _ = path.call_method1("append", ("C:\\Users\\legot\\Metis",));
            if let Ok(cwd) = std::env::current_dir() {
                let _ = path.call_method1("append", (cwd.to_string_lossy().as_ref(),));
            }
        }
    }
}

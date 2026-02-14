// DEPRECATED: Orchestrator HTTP server has been integrated into the single Tauri binary
// The orchestrator now runs as a background thread spawned from lib.rs
// See: src/orchestrator/server.rs for the HTTP server implementation
// This file is kept for reference only and should not be compiled as a separate binary
//
// To start the orchestrator server, use:
//   npm run tauri dev
//
// The server will listen on http://localhost:9000 and is managed in lib.rs::run_tauri()

use std::env;
/// Standalone orchestrator HTTP service
/// Runs on localhost:9000 for testing and development
///
/// Usage:
///   cargo run --bin orchestrator -- [project-root]
///   
/// If project-root is not provided, tries to find it by going up directories
/// until it finds the 'research' folder.
use std::path::PathBuf;

#[tokio::main]
async fn main() {
    // Initialize Python for multi-threaded use
    pyo3::prepare_freethreaded_python();

    // Note: Skipping tracing initialization to avoid conflicts when multiple
    // orchestrator instances are spawned in testing. The HTTP server runs fine without it.
    // If tracing is needed for standalone mode, initialize it in the parent Tauri app instead.

    // Get project root from command line or find it
    let (project_root, port) = if let Some(arg) = env::args().nth(1) {
        let project_root = PathBuf::from(&arg);
        // Check if arg is actually a number (port), otherwise it's project root
        if arg.parse::<u16>().is_ok() {
            // First arg is a port
            let port = arg.parse().unwrap_or(9000);
            let root = if let Some(second_arg) = env::args().nth(2) {
                PathBuf::from(second_arg)
            } else {
                find_project_root()
            };
            (root, port)
        } else {
            // First arg is project root, check for port as second arg
            let port = env::args()
                .nth(2)
                .and_then(|p| p.parse::<u16>().ok())
                .unwrap_or(9000);
            (project_root, port)
        }
    } else {
        (find_project_root(), 9000)
    };

    fn find_project_root() -> PathBuf {
        // Try to find project root by looking for research/ directory
        let mut current = env::current_dir().expect("Failed to get current directory");
        loop {
            if current.join("research").exists() {
                return current;
            }
            if !current.pop() {
                // Couldn't find research folder, use current directory
                return env::current_dir().expect("Failed to get current directory");
            }
        }
    }

    println!("═══════════════════════════════════════════════════");
    println!("🚀 METIS ORCHESTRATOR SERVICE - STANDALONE MODE");
    println!("═══════════════════════════════════════════════════");
    println!("Project root: {}", project_root.display());
    println!("Listening on: http://127.0.0.1:{}", port);
    println!();
    println!("Endpoints:");
    println!("  POST   /api/pipeline/run          - Start pipeline");
    println!("  GET    /api/pipeline/status/:id   - Get pipeline status");
    println!("  GET    /api/pipeline/results/:id  - Get pipeline results");
    println!("  GET    /api/health                - Health check");
    println!();
    println!("Press Ctrl+C to stop.");
    println!("═══════════════════════════════════════════════════");
    println!();

    // Run the HTTP server
    metis_lib::orchestrator::server::start_http_server(project_root, port).await;
}

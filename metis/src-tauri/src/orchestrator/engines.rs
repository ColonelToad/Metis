/// Execution-engine lifecycle: health probes and process launch.
///
/// The C++ primary engine runs inside WSL (Debian) on :8080; the Rust
/// fallback is a native Windows binary on :8081. Both speak the msgpack
/// TCP protocol, so a plain connect probe is enough to establish
/// liveness without polluting engine logs with synthetic signals.
use serde::Serialize;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tracing::{info, warn};

pub const CPP_ENGINE_HOST: &str = "127.0.0.1";
pub const CPP_ENGINE_PORT: u16 = 8080;
pub const RUST_ENGINE_HOST: &str = "127.0.0.1";
pub const RUST_ENGINE_PORT: u16 = 8081;

const PROBE_TIMEOUT: Duration = Duration::from_millis(500);
const WSL_DISTRO_DEFAULT: &str = "Debian";
const CPP_ENGINE_DIR_DEFAULT: &str = "/home/tolugenius/Projects/metis-cpp/cpp_engine";

#[derive(Debug, Clone, Serialize)]
pub struct EngineStatus {
    pub name: String,
    pub port: u16,
    pub alive: bool,
    /// TCP connect latency in ms; null when the engine is down.
    pub latency_ms: Option<f64>,
    pub role: &'static str,
}

#[derive(Debug, Serialize)]
pub struct EnginesStatusResponse {
    pub engines: Vec<EngineStatus>,
    pub primary_alive: bool,
}

#[derive(Debug, Serialize)]
pub struct StartEngineResponse {
    pub engine: String,
    /// True when a process was spawned (or was already running).
    pub spawn_attempted: bool,
    pub detail: String,
}

async fn probe(host: &str, port: u16, role: &'static str, name: &str) -> EngineStatus {
    let addr = SocketAddr::new(host.parse().expect("static host"), port);
    let started = std::time::Instant::now();
    let alive = tokio::time::timeout(PROBE_TIMEOUT, tokio::net::TcpStream::connect(addr))
        .await
        .map(|r| r.is_ok())
        .unwrap_or(false);
    let latency_ms = if alive {
        Some(started.elapsed().as_secs_f64() * 1000.0)
    } else {
        None
    };
    EngineStatus {
        name: name.to_string(),
        port,
        alive,
        latency_ms,
        role,
    }
}

pub async fn engines_status() -> EnginesStatusResponse {
    let (cpp, rust) = tokio::join!(
        probe(CPP_ENGINE_HOST, CPP_ENGINE_PORT, "primary", "cpp"),
        probe(RUST_ENGINE_HOST, RUST_ENGINE_PORT, "fallback", "rust"),
    );
    let primary_alive = cpp.alive;
    EnginesStatusResponse {
        engines: vec![cpp, rust],
        primary_alive,
    }
}

/// Launch an execution engine as a detached OS process.
///
/// - `cpp`: runs `research/ops/wsl_start_engine.sh` inside WSL (see that
///   file for why the launch logic must live in a file, not argv).
/// - `rust`: spawn `execution/target/release/metis_server.exe` detached
///   with stdout/stderr redirected to files (long-lived listener).
///
/// Returns Ok(already-running detail string) if the engine answers before
/// spawning, so callers can treat this as idempotent.
pub async fn start_engine(engine: &str, project_root: &Path) -> Result<StartEngineResponse, String> {
    match engine {
        "cpp" => start_cpp_engine(project_root).await,
        "rust" => start_rust_engine(project_root).await,
        other => Err(format!(
            "Unknown engine '{other}' (expected \"cpp\" or \"rust\")"
        )),
    }
}

fn windows_detached_flags() -> Option<u32> {
    #[cfg(windows)]
    {
        // DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so the child
        // survives orchestrator shutdown.
        Some(0x0000_0008 | 0x0000_0200)
    }
    #[cfg(not(windows))]
    {
        None
    }
}

/// Convert a Windows path (C:\a\b) to its WSL /mnt/c/a/b form.
fn windows_path_to_wsl(p: &Path) -> String {
    let s = p.to_string_lossy().replace('\\', "/");
    let bytes = s.as_bytes();
    if bytes.len() >= 2 && bytes[1] == b':' {
        format!("/mnt/{}{}", (bytes[0] as char).to_ascii_lowercase(), &s[2..])
    } else {
        s
    }
}

async fn start_cpp_engine(project_root: &Path) -> Result<StartEngineResponse, String> {
    let status = engines_status().await;
    if let Some(cpp) = status.engines.iter().find(|e| e.name == "cpp") {
        if cpp.alive {
            return Ok(StartEngineResponse {
                engine: "cpp".into(),
                spawn_attempted: false,
                detail: format!("Already running on :{}", cpp.port),
            });
        }
    }

    let distro = std::env::var("METIS_WSL_DISTRO").unwrap_or_else(|_| WSL_DISTRO_DEFAULT.into());
    let dir = std::env::var("METIS_CPP_ENGINE_DIR").unwrap_or_else(|_| CPP_ENGINE_DIR_DEFAULT.into());
    // The launch logic lives in a repo shell script, NOT an inline argv
    // string: wsl.exe mangles quoted multi-token arguments during its
    // Win->Linux command-line reconstruction (bash then sees garbage and
    // dies on a parse error before executing anything). Two clean path
    // args survive any reconstruction.
    let sh = windows_path_to_wsl(&project_root.join("research/ops/wsl_start_engine.sh"));
    if !project_root.join("research/ops/wsl_start_engine.sh").exists() {
        return Err(format!("WSL launcher script missing: {}", sh));
    }

    info!("Starting C++ engine in WSL ({distro}) via {sh}");
    let mut cmd = std::process::Command::new("wsl");
    cmd.args(["-d", &distro, "--", "bash", &sh, &dir]);
    // wsl.exe silently does nothing without a console: CREATE_NO_WINDOW
    // gives it an invisible one. DETACHED_PROCESS (used for the native
    // rust engine binary below) breaks it — bash never executes.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd.spawn()
        .map_err(|e| format!("Failed to spawn wsl.exe: {e}"))?;

    // The bash side holds the session until the port answers; poll here so
    // our report reflects reality rather than a fixed guess.
    let mut alive = false;
    for _ in 0..40 {
        tokio::time::sleep(Duration::from_millis(500)).await;
        let s = engines_status().await;
        if s.engines.iter().any(|e| e.name == "cpp" && e.alive) {
            alive = true;
            break;
        }
    }
    let detail = if alive {
        "Started; responding on :8080".to_string()
    } else {
        "Spawned but not answering within 20s; check /tmp/metis_cpp.log".to_string()
    };
    Ok(StartEngineResponse {
        engine: "cpp".into(),
        spawn_attempted: true,
        detail,
    })
}

async fn start_rust_engine(project_root: &Path) -> Result<StartEngineResponse, String> {
    let status = engines_status().await;
    if let Some(rust) = status.engines.iter().find(|e| e.name == "rust") {
        if rust.alive {
            return Ok(StartEngineResponse {
                engine: "rust".into(),
                spawn_attempted: false,
                detail: format!("Already running on :{}", rust.port),
            });
        }
    }

    let exe = project_root.join("execution/target/release/metis_server.exe");
    if !exe.exists() {
        return Err(format!(
            "Rust engine binary not found at {} — build it first (cargo build --release --bin metis_server)",
            exe.display()
        ));
    }

    let log_dir = project_root.join("data/logs");
    let _ = std::fs::create_dir_all(&log_dir);
    let stdout_path = log_dir.join("metis_rust_stdout.log");
    let stderr_path = log_dir.join("metis_rust_stderr.log");

    warn!("Starting Rust fallback engine from {}", exe.display());
    let mut cmd = std::process::Command::new(&exe);
    cmd.stdout(std::fs::File::create(&stdout_path).map_err(|e| e.to_string())?)
        .stderr(std::fs::File::create(&stderr_path).map_err(|e| e.to_string())?);
    if let Some(flags) = windows_detached_flags() {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(flags);
    }
    let child = cmd.spawn().map_err(|e| format!("Failed to spawn engine: {e}"))?;

    tokio::time::sleep(Duration::from_millis(800)).await;
    let after = engines_status().await;
    let alive = after
        .engines
        .iter()
        .find(|e| e.name == "rust")
        .map(|e| e.alive)
        .unwrap_or(false);
    let detail = if alive {
        format!("Started (pid {}) and answering on :8081", child.id())
    } else {
        format!(
            "Spawned pid {} but not answering; check {}",
            child.id(),
            stderr_path.display()
        )
    };
    Ok(StartEngineResponse {
        engine: "rust".into(),
        spawn_attempted: true,
        detail,
    })
}

/// Path of the project root for the standalone orchestrator binary.
pub fn default_project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."))
}

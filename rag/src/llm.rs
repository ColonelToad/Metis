//! LLM generation via a managed upstream `llama-server` sidecar (HTTP).
//!
//! Previously this module drove llama.cpp in-process through `llama-cpp-2`
//! (dedicated `!Send`-confined worker thread, manual batch/decode loop,
//! per-request KV-cache clear, hand-rolled stop-marker scanning). That
//! reimplemented a worse `llama-server` inside the orchestrator: a global
//! channel+mutex serialized all generations, a worker panic silently killed
//! all future calls, and the pinned bindings crate lagged upstream.
//!
//! Now the engine is an upstream `llama-server` binary (vendored under
//! `rag/llm/server/`, git-ignored) speaking HTTP on 127.0.0.1:8082, and this
//! module is a thin client plus supervisor:
//!
//! - [`LocalLLMEngine::new`] probes the port first (idempotent: an already
//!   running server is reused), otherwise spawns the binary detached —
//!   mirroring `metis/src-tauri/src/orchestrator/engines.rs` — with
//!   stdout/stderr redirected to `data/logs/llm_server_*.log`, then polls
//!   until `/health` reports ready.
//! - [`LocalLLMEngine::generate`] POSTs the caller-built prompt verbatim to
//!   `/completion`, so `pipeline.rs` / `reasoning_chain.rs` prompt
//!   construction is unchanged. A transport failure triggers one
//!   respawn-and-retry; anything else surfaces as an error and the
//!   pipeline's template fallback covers it.
//!
//! Deterministic preset: temperature 0.0 (greedy), fixed seed, server-side
//! stop tokens. Same prompt + same server state → same tokens, and the
//! sidecar's process isolation removes the orchestrator-runtime jitter
//! (blocked executor threads, GIL adjacency) the in-process worker had.
//! Overrides for experimentation: `METIS_LLM_TEMP`, `METIS_LLM_SEED`
//! (any value; `random` = nondeterministic), `METIS_LLM_THREADS`,
//! `METIS_LLM_CTX`, `METIS_LLM_URL` (full base URL, skips supervision).

use anyhow::{anyhow, bail, Context, Result};
use serde_json::json;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// Default sidecar port. 8080/8081/9000 are taken (cpp/rust engines,
/// orchestrator).
const DEFAULT_PORT: u16 = 8082;
const N_CTX: u32 = 4096;
/// Greedy decoding: the determinism half of the sidecar contract.
const TEMPERATURE: f32 = 0.0;
const TOP_P: f32 = 0.95;
/// Fixed seed: the other half. `METIS_LLM_SEED=random` opts back out.
const SEED: u32 = 42;

/// Server-side stop tokens (replaces the old client-side stop scan).
const STOP_MARKERS: &[&str] = &["<|im_end|>", "<|im_start|>"];
/// Extra end-of-sentence marker some tokenizers emit; harmless if absent.
const STOP_MARKERS_EXTRA: &[&str] = &["<｜end▁of▁sentence｜>"];

const STARTUP_TIMEOUT: Duration = Duration::from_secs(180);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(360);

fn env_u16(name: &str, default: u16) -> u16 {
    std::env::var(name)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_u32(name: &str, default: u32) -> u32 {
    std::env::var(name)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_f32(name: &str, default: f32) -> f32 {
    std::env::var(name)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn threads() -> i32 {
    // Sweep on the target machine (i7-155U, 128-token prompt, 7B Q4_K_M):
    //   threads=1: ~72s/~42s (byte-identical across runs — the bit-
    //     determinism recipe, at ~1/4 the throughput of the default)
    //   threads=2: 28.6s/12.0s   threads=4: 19.1s/6.1s
    //   threads=6: 8.0s/5.5s     threads=8: 7.3s/6.5s (E-core throttle)
    // Default 6: the measured knee. Override with METIS_LLM_THREADS.
    std::env::var("METIS_LLM_THREADS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(6)
}

fn use_random_seed() -> bool {
    std::env::var("METIS_LLM_SEED")
        .map(|v| v.eq_ignore_ascii_case("random"))
        .unwrap_or(false)
}

/// Absolute form of `p` (current-dir resolved). Falls back to `p` itself
/// when the file does not exist yet (e.g. unit tests with fake paths).
fn abspath(p: &Path) -> PathBuf {
    std::fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf())
}

/// `rag/llm/server/llama-server.exe`, resolved as a sibling of the model
/// file so no repo-root guessing is needed.
fn server_binary_for(model_path: &Path) -> PathBuf {
    let dir = abspath(model_path)
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("server");
    #[cfg(windows)]
    let exe = dir.join("llama-server.exe");
    #[cfg(not(windows))]
    let exe = dir.join("llama-server");
    if let Ok(url) = std::env::var("METIS_LLM_SERVER_BIN") {
        let p = PathBuf::from(url);
        if p.exists() {
            return p;
        }
    }
    exe
}

/// Best-effort `<repo>/data/logs` derived from the model path
/// (`<repo>/rag/llm/<model>.gguf`); falls back to the current directory.
fn log_dir_for(model_path: &Path) -> PathBuf {
    let abs = abspath(model_path);
    let root = abs
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent);
    match root {
        Some(r) => r.join("data").join("logs"),
        None => PathBuf::from("data").join("logs"),
    }
}

fn port() -> u16 {
    env_u16("METIS_LLM_PORT", DEFAULT_PORT)
}

fn base_url() -> String {
    std::env::var("METIS_LLM_URL")
        .ok()
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| format!("http://127.0.0.1:{}", port()))
}

/// Synchronous HTTP readiness probe: TCP-open is not enough (llama-server
/// binds the port before the model finishes loading; a TCP-only probe lets
/// `new()` return minutes before the first generation can succeed).
/// Returns true only on `200` + `"status":"ok"`.
fn http_health_sync(base: &str) -> bool {
    use std::io::{Read, Write};
    let addr = base
        .trim_start_matches("http://")
        .trim_start_matches("https://");
    let mut stream = match std::net::TcpStream::connect(addr) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(3)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(3)));
    if stream.write_all(b"GET /health HTTP/1.0\r\n\r\n").is_err() {
        return false;
    }
    let mut buf = [0u8; 512];
    let n = match stream.read(&mut buf) {
        Ok(n) => n,
        Err(_) => return false,
    };
    let head = String::from_utf8_lossy(&buf[..n]);
    head.contains(" 200 ") && head.contains("\"status\":\"ok\"")
}

/// A sidecar child process we spawned (and therefore own).
/// Killing on drop ties the server lifetime to the engine lifetime: no
/// orphans, no cross-run thread-count contamination through silent
/// probe-reuse, and observably clean exits. A server we merely reused
/// (`owned = false`) is left running.
struct OwnedServer {
    child: std::process::Child,
    owned: bool,
}

impl Drop for OwnedServer {
    fn drop(&mut self) {
        if !self.owned {
            return;
        }
        match self.child.try_wait() {
            Ok(Some(status)) => tracing::info!(
                "LLM sidecar already exited (status {status}); nothing to stop"
            ),
            Ok(None) => {
                tracing::info!("Stopping owned LLM sidecar (pid {})", self.child.id());
                // Best effort: the OS reaps unconditionally on process exit.
                let _ = self.child.kill();
                let _ = self.child.wait();
            }
            Err(e) => tracing::warn!("LLM sidecar wait failed: {e:#}"),
        }
    }
}

/// Ensure a sidecar answers at `base`. Probes first (idempotent): a running
/// server — ours or someone else's — is reused untouched. Otherwise spawns
/// a foreground child (no detach flags) and returns ownership to the caller.
fn ensure_server_process(model_path: &Path, base: &str) -> Result<Option<OwnedServer>> {
    if http_health_sync(base) {
        tracing::info!("LLM sidecar already answering at {base}; reusing (not owned)");
        return Ok(None);
    }

    let bin = server_binary_for(model_path);
    if !bin.exists() {
        bail!(
            "LLM server binary not found: {} (set METIS_LLM_URL to use an external server)",
            bin.display()
        );
    }

    let log_dir = log_dir_for(model_path);
    let _ = std::fs::create_dir_all(&log_dir);
    let stdout_path = log_dir.join("llm_server_stdout.log");
    let stderr_path = log_dir.join("llm_server_stderr.log");
    let stdout = std::fs::File::create(&stdout_path).with_context(|| {
        format!("cannot create {}", stdout_path.display())
    })?;
    let stderr = std::fs::File::create(&stderr_path).with_context(|| {
        format!("cannot create {}", stderr_path.display())
    })?;

    let n_ctx = env_u32("METIS_LLM_CTX", N_CTX);
    let mut cmd = std::process::Command::new(&bin);
    cmd.arg("-m")
        .arg(model_path)
        .arg("--port")
        .arg(port().to_string())
        .arg("--ctx-size")
        .arg(n_ctx.to_string())
        .arg("--threads")
        .arg(threads().to_string())
        // No --log-disable: stdout/stderr already go to files, and a silent
        // server is undebuggable after a crash.
        .stdout(stdout)
        .stderr(stderr);
    // Foreground child on purpose: OwnedServer::drop stops it when the
    // engine goes away. No DETACHED_PROCESS — orphans are the bug.

    tracing::info!(
        "Spawning LLM sidecar: {} (model={}, port={}, ctx={}, threads={})",
        bin.display(),
        model_path.display(),
        port(),
        n_ctx,
        threads()
    );
    let child = cmd.spawn().context("failed to spawn llama-server")?;
    tracing::info!("LLM sidecar spawned (pid {})", child.id());
    Ok(Some(OwnedServer { child, owned: true }))
}

/// Blocking readiness poll for the synchronous constructor path.
/// HTTP-level: returns only when the model is loaded and serving.
fn wait_ready_sync(base: &str, timeout: Duration) -> Result<()> {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if http_health_sync(base) {
            return Ok(());
        }
        std::thread::sleep(Duration::from_secs(2));
    }
    bail!("LLM sidecar not healthy at {base} within {timeout:?}")
}

/// Async readiness poll (respawn path inside async generation).
async fn wait_ready_async(client: &reqwest::Client, base: &str, timeout: Duration) -> Result<()> {
    let start = Instant::now();
    let url = format!("{base}/health");
    while start.elapsed() < timeout {
        if let Ok(resp) = client.get(&url).send().await {
            if resp.status().is_success() {
                return Ok(());
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    bail!("LLM sidecar not healthy at {url} within {timeout:?}")
}

struct ServerClient {
    base: String,
    client: reqwest::Client,
    temperature: f32,
    seed: Option<u32>,
}

impl ServerClient {
    fn new() -> Result<Self> {
        let client = reqwest::Client::builder()
            .timeout(REQUEST_TIMEOUT)
            .build()
            .context("failed to build HTTP client")?;
        Ok(Self {
            base: base_url(),
            client,
            temperature: env_f32("METIS_LLM_TEMP", TEMPERATURE),
            seed: if use_random_seed() {
                None
            } else {
                Some(env_u32("METIS_LLM_SEED", SEED))
            },
        })
    }

    async fn post_completion(&self, prompt: &str, max_tokens: usize) -> Result<String> {
        let mut stops: Vec<&str> = STOP_MARKERS.to_vec();
        stops.extend_from_slice(STOP_MARKERS_EXTRA);
        let mut req = json!({
            "prompt": prompt,
            "n_predict": max_tokens.max(1),
            "temperature": self.temperature,
            "top_p": TOP_P,
            "stop": stops,
            "stream": false,
        });
        if let Some(seed) = self.seed {
            req["seed"] = json!(seed);
        }

        let url = format!("{}/completion", self.base);
        let started = Instant::now();
        let resp = self
            .client
            .post(&url)
            .json(&req)
            .send()
            .await
            .with_context(|| format!("POST {url} failed"))?;
        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            bail!("llama-server {url} -> {status}: {body}");
        }
        let body: serde_json::Value = resp.json().await.context("invalid JSON from llama-server")?;
        let content = body
            .get("content")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow!("llama-server response missing `content`: {body}"))?;
        if let Some(timings) = body.get("timings") {
            tracing::info!(
                "LLM sidecar generation: {:.1}s, predicted={} tokens ({:.1} tok/s), truncated={}",
                started.elapsed().as_secs_f64(),
                timings.get("predicted_n").and_then(|v| v.as_u64()).unwrap_or(0),
                timings
                    .get("predicted_per_second")
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0),
                body.get("truncated").and_then(|v| v.as_bool()).unwrap_or(false),
            );
        }
        Ok(content.trim().to_string())
    }
}

pub struct LocalLLMEngine {
    mock_mode: bool,
    server: Option<ServerClient>,
    /// Kept so a failed server can be respawned on the next call.
    model_path: Option<PathBuf>,
    /// The sidecar child, if we spawned it. Dropped (killed) with the engine.
    /// `None` when reusing an already-running server or in external/mock mode.
    /// A plain `std::sync::Mutex` (never held across `.await`) so the
    /// respawn path in `generate(&self)` can take ownership.
    _server_proc: std::sync::Mutex<Option<OwnedServer>>,
}

impl LocalLLMEngine {
    pub fn new(model_path: impl AsRef<Path>, mock_mode: bool) -> Result<Self> {
        if mock_mode {
            return Ok(Self {
                mock_mode: true,
                server: None,
                model_path: None,
                _server_proc: std::sync::Mutex::new(None),
            });
        }

        let path = model_path.as_ref();
        if !path.exists() {
            bail!("Model file not found: {}", path.display());
        }

        let base = base_url();
        // External server (METIS_LLM_URL): never supervise, just use it.
        let external = std::env::var("METIS_LLM_URL").ok().filter(|s| !s.is_empty()).is_some();
        let server_proc = if !external {
            let proc = ensure_server_process(path, &base)?;
            wait_ready_sync(&base, STARTUP_TIMEOUT)?;
            proc
        } else {
            None
        };
        let server = ServerClient::new()?;
        tracing::info!(
            "LLM sidecar ready: base={base} temp={} seed={:?} owned={}",
            server.temperature,
            server.seed,
            server_proc.is_some(),
        );
        Ok(Self {
            mock_mode: false,
            server: Some(server),
            model_path: Some(path.to_path_buf()),
            _server_proc: std::sync::Mutex::new(server_proc),
        })
    }

    pub async fn generate(&self, prompt: &str, max_tokens: usize) -> Result<String> {
        if self.mock_mode {
            return Ok(self.mock_generate(prompt));
        }
        let server = self
            .server
            .as_ref()
            .ok_or_else(|| anyhow!("LLM sidecar is not configured"))?;

        match server.post_completion(prompt, max_tokens).await {
            Ok(text) => Ok(text),
            Err(e) => {
                // One respawn-and-retry covers sidecar restarts/crashes.
                // External-URL mode has nothing to respawn; fail through to
                // the pipeline's template fallback.
                //
                // NOTE: respawn replaces a server this engine may not own.
                // The replacement is always owned (killed on drop); a reused
                // server that died is simply gone.
                let external = std::env::var("METIS_LLM_URL")
                    .ok()
                    .filter(|s| !s.is_empty())
                    .is_some();
                let model = match (&self.model_path, external) {
                    (Some(m), false) => m.clone(),
                    _ => return Err(e),
                };
                tracing::warn!("LLM sidecar call failed ({e:#}); respawning once");
                let proc = ensure_server_process(&model, &server.base)?;
                // Stash ownership on the engine; the lock is released before
                // any `.await` below, so no executor blocking.
                *self
                    ._server_proc
                    .lock()
                    .unwrap_or_else(|e| e.into_inner()) = proc;
                wait_ready_async(&server.client, &server.base, STARTUP_TIMEOUT).await?;
                server.post_completion(prompt, max_tokens).await
            }
        }
    }

    fn mock_generate(&self, _prompt: &str) -> String {
        r#"Let me analyze this trade step-by-step:

## 1. Market Condition Analysis
The natural gas market is currently experiencing elevated stress levels. Grid stress index at 75/100 indicates high demand periods, likely driven by weather conditions [Doc 1]. Current price levels suggest supply constraints in key delivery regions.

## 2. Signal Drivers
This BUY signal was triggered by:
- **Weather anomaly**: 8.5°F above seasonal average, driving cooling demand [Doc 2]
- **Grid stress**: Regional transmission congestion limiting supply flexibility
- **Policy context**: Recent FERC order on pipeline capacity may constrain deliveries [Doc 3]

## 3. Risk Factors
Key risks to monitor:
- Weather normalization could reduce demand pressure
- Potential for increased LNG export constraints
- Regulatory uncertainty around pipeline expansions

## 4. Expected Outcome
Based on the confluence of supply constraints and elevated demand, we expect prices to move 3-5% higher over the next 5-7 trading days. The grid stress metric historically correlates with 0.72 accuracy to short-term price movements [Doc 1]."#.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_mock_llm() {
        let llm = LocalLLMEngine::new("mock.gguf", true).unwrap();
        let response = llm.generate("test prompt", 512).await.unwrap();
        assert!(!response.is_empty());
        assert!(response.contains("Market Condition Analysis"));
    }

    #[test]
    fn test_server_binary_resolves_next_to_model() {
        let model = Path::new("rag/llm/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf");
        let bin = server_binary_for(model);
        assert_eq!(
            bin,
            PathBuf::from("rag/llm/server").join(if cfg!(windows) {
                "llama-server.exe"
            } else {
                "llama-server"
            })
        );
    }

    #[test]
    fn test_deterministic_defaults() {
        assert_eq!(TEMPERATURE, 0.0);
        assert_eq!(DEFAULT_PORT, 8082);
    }
}

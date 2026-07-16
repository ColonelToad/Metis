//! Metis execution engine server.
//!
//! Wires `signal_interface::SignalServer` to a real `OrderBook` for the
//! first time. Nothing in this workspace previously connected an actual
//! signal-ingestion path to the order book at all: `metis-core`'s
//! `bridge.rs` (now deprecated) was a stub that only `eprintln!`'d, and
//! `signal_interface::SignalServer` existed but nothing ever called
//! `.run()` on it.
//!
//! `process_signal` here is intentionally minimal: it reads current book
//! state and generates a TWAP execution plan via `execution_algos`, but it
//! doesn't submit orders anywhere (there's no exchange connection yet) and
//! does no risk checks. That's deliberate scope for this pass — the goal is
//! a real, measurable signal-to-response path to get an actual latency
//! number from, not a complete trading system.
//!
//! Run with: cargo run --release --bin metis_server
//! Then drive load against it with: cargo run --release --bin load_test

use anyhow::Result;
use chrono::Utc;
use engine::execution_algos::{ExecutionAlgo, ParentOrder, TwapExecutor};
use engine::latency::LatencyRecorder;
use engine::orderbook::{EventType, MarketEvent, OrderBook};
use engine::signal_interface::{ExecutionResponse, ExecutionStatus, SignalServer, TradingSignal};
use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;
use tracing::{info, warn, Level};

/// Handle one signal: consult the book, generate a TWAP plan, respond.
///
/// No real order is submitted — `filled_quantity` is always 0.0 here,
/// because there's nothing downstream to fill it yet. This measures the
/// signal-to-plan path, not a signal-to-fill path.
fn process_signal(
    signal: TradingSignal,
    book: &Mutex<OrderBook>,
    recorder: &LatencyRecorder,
) -> Result<ExecutionResponse> {
    let start = Instant::now();

    let side = match signal.direction.to_side() {
        Some(side) => side,
        None => {
            // Neutral signal: still touches the book (a real read), so this
            // isn't a no-op branch that skips the thing we're measuring.
            let book_guard = book.lock().unwrap();
            let _ = book_guard.mid_price();
            drop(book_guard);
            let elapsed = start.elapsed();
            recorder.record(elapsed);
            return Ok(ExecutionResponse {
                signal_id: signal.signal_id,
                status: ExecutionStatus::Rejected,
                avg_fill_price: None,
                filled_quantity: 0.0,
                latency_ms: elapsed.as_millis() as u64,
                error_message: Some("Neutral signal: no side to trade".to_string()),
            });
        }
    };

    let reference_price = {
        let book_guard = book.lock().unwrap();
        book_guard.mid_price()
    };

    let Some(reference_price) = reference_price else {
        let elapsed = start.elapsed();
        recorder.record(elapsed);
        return Ok(ExecutionResponse {
            signal_id: signal.signal_id,
            status: ExecutionStatus::Rejected,
            avg_fill_price: None,
            filled_quantity: 0.0,
            latency_ms: elapsed.as_millis() as u64,
            error_message: Some("No liquidity in book (no quotes received yet)".to_string()),
        });
    };

    // Aim for ~5 TWAP slices across the signal's horizon, minimum 60s/slice.
    let horizon_secs = (signal.horizon_minutes.max(1) * 60) as i64;
    let slice_duration_secs = (horizon_secs / 5).max(60);

    let parent = ParentOrder {
        order_id: signal.signal_id.clone(),
        symbol: signal.symbol.clone(),
        side,
        quantity: signal.target_quantity,
        start_time: Utc::now(),
        end_time: Utc::now() + chrono::Duration::seconds(horizon_secs),
        algo: ExecutionAlgo::TWAP,
    };

    let executor = TwapExecutor::new(slice_duration_secs);
    let response = match executor.generate_child_orders(&parent) {
        Ok(children) => {
            info!(
                "Signal {} accepted: {} TWAP slices over {}min, reference price {:.4}",
                signal.signal_id,
                children.len(),
                signal.horizon_minutes,
                reference_price
            );
            ExecutionResponse {
                signal_id: signal.signal_id,
                status: ExecutionStatus::Accepted,
                avg_fill_price: Some(reference_price),
                filled_quantity: 0.0,
                latency_ms: 0, // filled in below, after we measure elapsed
                error_message: None,
            }
        }
        Err(e) => {
            warn!("Signal {} rejected: {}", signal.signal_id, e);
            ExecutionResponse {
                signal_id: signal.signal_id,
                status: ExecutionStatus::Rejected,
                avg_fill_price: None,
                filled_quantity: 0.0,
                latency_ms: 0,
                error_message: Some(e.to_string()),
            }
        }
    };

    let elapsed = start.elapsed();
    recorder.record(elapsed);
    Ok(ExecutionResponse {
        latency_ms: elapsed.as_millis() as u64,
        ..response
    })
}

async fn run_server() -> Result<()> {
    let book = Arc::new(Mutex::new(OrderBook::new("NG:CME".to_string())));
    let recorder = Arc::new(LatencyRecorder::new());

    // Seed the book with a quote so process_signal has liquidity to
    // reference immediately. In the real system this comes from a market
    // data feed, which doesn't exist yet — without this seed, every signal
    // would be rejected for "no liquidity" until something else populates
    // the book, which would make this run measure rejection latency
    // instead of the real path.
    {
        let mut book_guard = book.lock().unwrap();
        book_guard.process_event(MarketEvent {
            timestamp: Utc::now(),
            event_type: EventType::Quote {
                bid_price: 2.500,
                bid_quantity: 1000.0,
                ask_price: 2.505,
                ask_quantity: 1000.0,
            },
        })?;
    }

    // Print latency stats periodically, so a load test running against this
    // server can be observed live without needing to stop the server first.
    {
        let recorder = Arc::clone(&recorder);
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(std::time::Duration::from_secs(10));
            loop {
                interval.tick().await;
                if let Some(summary) = recorder.summary() {
                    info!(
                        "process_signal latency (server-side: lock + book read + TWAP plan only, excludes network/serialization):\n{}",
                        summary
                    );
                }
            }
        });
    }

    let addr: SocketAddr = "127.0.0.1:7878".parse()?;
    info!("Metis engine server starting on {}", addr);
    let server = SignalServer::new(addr);

    server
        .run(move |signal| process_signal(signal, &book, &recorder))
        .await
}

/// Pin every tokio worker thread to a fixed core at creation time.
///
/// Without this, a task can migrate between OS threads at any `.await`
/// point (tokio's multi-thread runtime work-steals across a pool of worker
/// threads), and on a hybrid P-core/E-core CPU an unpinned thread getting
/// scheduled onto a slower core — or paying a migration cost — is a
/// plausible, previously-seen-in-practice explanation for the wide p50-to-
/// p99.9 spread in the first load test (12x at p50, ~37x at max, despite
/// every request doing the same fixed amount of work).
///
/// This round-robins across *all* cores `core_affinity` reports, not just
/// P-cores specifically — unlike the SIMD benchmark's `pin_to_p_core`,
/// which targets index 0 as a documented-but-not-guaranteed Windows/Intel
/// heuristic. The goal here is consistency (every worker thread stays where
/// the OS put it, permanently) rather than maximum single-core throughput,
/// which matches the actual design goal: this system has a generous latency
/// budget and cares more about a narrow p50-to-p99.9 spread than the fastest
/// possible p50.
fn pin_worker_threads() -> impl Fn() + Send + Sync + 'static {
    let core_ids = core_affinity::get_core_ids().unwrap_or_default();
    let next_core = Arc::new(AtomicUsize::new(0));

    move || {
        if core_ids.is_empty() {
            return;
        }
        let idx = next_core.fetch_add(1, Ordering::Relaxed) % core_ids.len();
        let core = core_ids[idx];
        if core_affinity::set_for_current(core) {
            eprintln!("[pinning] tokio worker thread pinned to core {}", core.id);
        } else {
            eprintln!("[pinning] failed to pin tokio worker thread to core {}", core.id);
        }
    }
}

fn main() -> Result<()> {
    tracing_subscriber::fmt().with_max_level(Level::INFO).init();

    // Building the runtime manually (rather than the #[tokio::main] attribute
    // on `main` itself) is what makes on_thread_start available — the
    // attribute macro doesn't expose runtime-builder configuration.
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .on_thread_start(pin_worker_threads())
        .build()?;

    runtime.block_on(run_server())
}

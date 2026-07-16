//! Drives synthetic signal load against a running `metis_server` instance
//! and reports the real, measured round-trip latency distribution.
//!
//! This is the actual deliverable for Phase B: a number to argue the order
//! book's floor question from, instead of speculation about whether it
//! matters. Uses a single persistent connection, sending signals
//! sequentially — matching how the real system will actually be used (one
//! long-running Python process, one connection), not a concurrent
//! multi-connection throughput test. That's a real scope limitation, not an
//! oversight: concurrent load testing is a reasonable next step, not a
//! prerequisite for this first real number.
//!
//! Usage: cargo run --release --bin load_test -- --count 1000

use anyhow::Result;
use chrono::Utc;
use clap::Parser;
use engine::latency::LatencyRecorder;
use engine::signal_interface::{
    ExecutionStatus, SignalClient, SignalDirection, SignalMetadata, TradingSignal,
};
use std::net::SocketAddr;
use std::time::Instant;

#[derive(Parser)]
struct Args {
    #[arg(short, long, default_value = "127.0.0.1:7878")]
    addr: String,

    #[arg(short, long, default_value_t = 1000)]
    count: usize,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    let addr: SocketAddr = args.addr.parse()?;

    let mut client = SignalClient::new(addr);
    client.connect().await?;

    let recorder = LatencyRecorder::new();
    let mut accepted = 0;
    let mut rejected = 0;
    let mut errored = 0;

    println!("Sending {} signals to {}...", args.count, args.addr);

    for i in 0..args.count {
        // Cycle direction so we exercise both the accepted path (Long/Short)
        // and the rejected-neutral path, rather than measuring one branch.
        let direction = match i % 3 {
            0 => SignalDirection::Long,
            1 => SignalDirection::Short,
            _ => SignalDirection::Neutral,
        };

        let signal = TradingSignal {
            signal_id: format!("LOADTEST-{}", i),
            timestamp: Utc::now(),
            symbol: "NG:CME".to_string(),
            direction,
            confidence: 0.75,
            target_quantity: 100.0,
            horizon_minutes: 15,
            metadata: SignalMetadata {
                model_version: "load_test".to_string(),
                features_used: vec![],
                weather_anomaly: None,
                policy_trigger: None,
                uncertainty: 0.1,
            },
        };

        let start = Instant::now();
        let response = client.send_signal(signal).await?;
        recorder.record(start.elapsed());

        match response.status {
            ExecutionStatus::Accepted => accepted += 1,
            ExecutionStatus::Rejected => rejected += 1,
            ExecutionStatus::Error => errored += 1,
            _ => {}
        }
    }

    println!(
        "\nDone. {} sent \u{2014} {} accepted, {} rejected, {} errored.\n",
        args.count, accepted, rejected, errored
    );
    println!("Round-trip latency (client-observed \u{2014} includes TCP + MessagePack serialization,\nthis is the number that actually matters for the Phase B budget question):");
    if let Some(summary) = recorder.summary() {
        println!("{}", summary);
    }

    Ok(())
}

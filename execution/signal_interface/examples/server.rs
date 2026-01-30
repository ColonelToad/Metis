use anyhow::Result;
use signal_interface::{ExecutionResponse, ExecutionStatus, SignalServer, TradingSignal};
use std::net::SocketAddr;
use tracing::{info, Level};
use tracing_subscriber;

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize logging
    tracing_subscriber::fmt().with_max_level(Level::INFO).init();

    info!("Starting Metis signal server...");

    // Start server on localhost:8080
    let addr: SocketAddr = "127.0.0.1:8080".parse()?;
    let server = SignalServer::new(addr);

    // Define signal handler
    let handler = |signal: TradingSignal| -> Result<ExecutionResponse> {
        info!(
            "Processing signal: {} - {:?} {} @ confidence {:.2}",
            signal.signal_id, signal.direction, signal.symbol, signal.confidence
        );

        // Simulate execution logic
        let status = if signal.confidence > 0.7 {
            ExecutionStatus::Accepted
        } else {
            ExecutionStatus::Rejected
        };

        Ok(ExecutionResponse {
            signal_id: signal.signal_id,
            status,
            avg_fill_price: Some(2.505), // Simulated fill price
            filled_quantity: signal.target_quantity,
            latency_ms: 50,
            error_message: None,
        })
    };

    // Run server
    server.run(handler).await?;

    Ok(())
}

use anyhow::Result;
use chrono::{DateTime, Utc};
use orderbook::Side;
use serde::{Deserialize, Serialize};
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tracing::{error, info};

/// Trading signal from Python ML model
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradingSignal {
    pub signal_id: String,
    pub timestamp: DateTime<Utc>,
    pub symbol: String,
    pub direction: SignalDirection,
    pub confidence: f64, // 0.0 - 1.0
    pub target_quantity: f64,
    pub horizon_minutes: i64, // Execution window
    pub metadata: SignalMetadata,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum SignalDirection {
    Long,
    Short,
    Neutral,
}

impl SignalDirection {
    pub fn to_side(&self) -> Option<Side> {
        match self {
            SignalDirection::Long => Some(Side::Bid),
            SignalDirection::Short => Some(Side::Ask),
            SignalDirection::Neutral => None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SignalMetadata {
    pub model_version: String,
    pub features_used: Vec<String>,
    pub weather_anomaly: Option<f64>,
    pub policy_trigger: Option<String>,
    pub uncertainty: f64,
}

/// Response sent back to Python
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionResponse {
    pub signal_id: String,
    pub status: ExecutionStatus,
    pub avg_fill_price: Option<f64>,
    pub filled_quantity: f64,
    pub latency_ms: u64,
    pub error_message: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ExecutionStatus {
    Accepted,
    InProgress,
    Completed,
    PartiallyCompleted,
    Rejected,
    Error,
}

/// TCP server for receiving signals from Python
pub struct SignalServer {
    addr: SocketAddr,
}

impl SignalServer {
    pub fn new(addr: SocketAddr) -> Self {
        Self { addr }
    }

    /// Start listening for incoming signals
    pub async fn run<F>(self, handler: F) -> Result<()>
    where
        F: Fn(TradingSignal) -> Result<ExecutionResponse> + Send + Sync + 'static,
    {
        use std::sync::Arc;
        let listener = TcpListener::bind(self.addr).await?;
        info!("Signal server listening on {}", self.addr);
        let handler = Arc::new(handler);
        loop {
            match listener.accept().await {
                Ok((stream, peer_addr)) => {
                    info!("Accepted connection from {}", peer_addr);
                    let handler = Arc::clone(&handler);
                    tokio::spawn(async move {
                        if let Err(e) = Self::handle_connection(stream, handler).await {
                            error!("Connection error: {}", e);
                        }
                    });
                }
                Err(e) => {
                    error!("Accept error: {}", e);
                }
            }
        }
    }

    async fn handle_connection<F>(mut stream: TcpStream, handler: Arc<F>) -> Result<()>
    where
        F: Fn(TradingSignal) -> Result<ExecutionResponse> + Send + Sync + 'static,
    {
        loop {
            // Read message length (4 bytes)
            let mut len_buf = [0u8; 4];
            if stream.read_exact(&mut len_buf).await.is_err() {
                break; // Connection closed
            }
            let msg_len = u32::from_be_bytes(len_buf) as usize;

            // Read message body
            let mut msg_buf = vec![0u8; msg_len];
            stream.read_exact(&mut msg_buf).await?;

            // Deserialize signal (using MessagePack for efficiency)
            let signal: TradingSignal = rmp_serde::from_slice(&msg_buf)?;
            info!(
                "Received signal: {} ({:?})",
                signal.signal_id, signal.direction
            );

            // Process signal and always serialize ExecutionResponse
            let response = match handler(signal) {
                Ok(resp) => resp,
                Err(e) => ExecutionResponse {
                    signal_id: String::from("error"),
                    status: ExecutionStatus::Error,
                    avg_fill_price: None,
                    filled_quantity: 0.0,
                    latency_ms: 0,
                    error_message: Some(format!("Handler error: {}", e)),
                },
            };

            // Send response
            let response_bytes = rmp_serde::to_vec(&response)?;
            let response_len = (response_bytes.len() as u32).to_be_bytes();
            stream.write_all(&response_len).await?;
            stream.write_all(&response_bytes).await?;
            stream.flush().await?;
        }
        Ok(())
    }
}

/// Python client for sending signals (example implementation)
pub struct SignalClient {
    addr: SocketAddr,
    stream: Option<TcpStream>,
}

impl SignalClient {
    pub fn new(addr: SocketAddr) -> Self {
        Self { addr, stream: None }
    }

    pub async fn connect(&mut self) -> Result<()> {
        let stream = TcpStream::connect(self.addr).await?;
        info!("Connected to signal server at {}", self.addr);
        self.stream = Some(stream);
        Ok(())
    }

    pub async fn send_signal(&mut self, signal: TradingSignal) -> Result<ExecutionResponse> {
        let stream = self
            .stream
            .as_mut()
            .ok_or_else(|| anyhow::anyhow!("Not connected"))?;

        // Serialize and send
        let signal_bytes = rmp_serde::to_vec(&signal)?;
        let signal_len = (signal_bytes.len() as u32).to_be_bytes();

        stream.write_all(&signal_len).await?;
        stream.write_all(&signal_bytes).await?;
        stream.flush().await?;

        // Read response
        let mut len_buf = [0u8; 4];
        stream.read_exact(&mut len_buf).await?;
        let msg_len = u32::from_be_bytes(len_buf) as usize;

        let mut msg_buf = vec![0u8; msg_len];
        stream.read_exact(&mut msg_buf).await?;

        let response: ExecutionResponse = rmp_serde::from_slice(&msg_buf)?;
        Ok(response)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_signal_serialization() {
        let signal = TradingSignal {
            signal_id: "TEST-001".to_string(),
            timestamp: Utc::now(),
            symbol: "NG:CME".to_string(),
            direction: SignalDirection::Long,
            confidence: 0.85,
            target_quantity: 100.0,
            horizon_minutes: 15,
            metadata: SignalMetadata {
                model_version: "v1.0".to_string(),
                features_used: vec!["temp_error".to_string(), "eia_surprise".to_string()],
                weather_anomaly: Some(2.5),
                policy_trigger: None,
                uncertainty: 0.15,
            },
        };

        // Test MessagePack serialization
        let bytes = rmp_serde::to_vec(&signal).unwrap();
        let deserialized: TradingSignal = rmp_serde::from_slice(&bytes).unwrap();

        assert_eq!(signal.signal_id, deserialized.signal_id);
        assert_eq!(signal.confidence, deserialized.confidence);
    }
}

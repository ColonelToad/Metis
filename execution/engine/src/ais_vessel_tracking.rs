use anyhow::Result;
use chrono::{DateTime, Utc};
use futures::stream::StreamExt;
use futures::SinkExt;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use thiserror::Error;
use tokio_tungstenite::{connect_async, tungstenite::Message};

#[derive(Error, Debug)]
pub enum AISError {
    #[error("WebSocket error: {0}")]
    WebSocketError(String),

    #[error("JSON parsing error: {0}")]
    JsonError(#[from] serde_json::Error),

    #[error("Connection error: {0}")]
    ConnectionError(String),
}

/// AIS message wrapper from stream API
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct AISMessage {
    #[serde(rename = "MessageType")]
    pub message_type: String,

    #[serde(rename = "Message")]
    pub message: AISPositionReport,
}

/// AIS Position Report (Message Type 1/2/3)
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct AISPositionReport {
    #[serde(rename = "UserID")]
    pub mmsi: String, // Unique ship identifier

    #[serde(rename = "Latitude")]
    pub latitude: f64,

    #[serde(rename = "Longitude")]
    pub longitude: f64,

    #[serde(rename = "NavigationalStatus")]
    pub nav_status: u8, // 0=underway, 1=anchored, 5=moored

    #[serde(rename = "Cog")]
    pub course_over_ground: f64, // Degrees

    #[serde(rename = "Sog")]
    pub speed_over_ground: f64, // Knots

    #[serde(rename = "ShipType")]
    pub ship_type: u8, // 84=LNG carrier, 80=crude tanker, etc.

    #[serde(skip_deserializing)]
    pub received_at: DateTime<Utc>,
}

/// Ship type classifications
pub mod ship_types {
    pub const LNG_CARRIER: u8 = 84;
    pub const CRUDE_TANKER: u8 = 80;
    pub const PRODUCT_TANKER: u8 = 86;
    pub const GENERAL_CARGO: u8 = 70;
    pub const CONTAINER_SHIP: u8 = 72;
    pub const BULK_CARRIER: u8 = 78;
}

/// Navigation status
pub mod nav_status {
    pub const UNDERWAY: u8 = 0;
    pub const ANCHORED: u8 = 1;
    pub const MOORED: u8 = 5;
    pub const IN_PORT: u8 = 6;
}

/// US Gulf Coast LNG terminal locations (bounding boxes)
pub struct LNGTerminal {
    pub name: &'static str,
    pub lat_min: f64,
    pub lat_max: f64,
    pub lon_min: f64,
    pub lon_max: f64,
}

pub const HOUSTON_FREEPORT: LNGTerminal = LNGTerminal {
    name: "Houston/Freeport",
    lat_min: 29.0,
    lat_max: 30.0,
    lon_min: -95.5,
    lon_max: -94.0,
};

pub const CAMERON_LNG: LNGTerminal = LNGTerminal {
    name: "Cameron LNG",
    lat_min: 29.5,
    lat_max: 30.5,
    lon_min: -93.5,
    lon_max: -92.5,
};

pub const PLAQUEMINES_LNG: LNGTerminal = LNGTerminal {
    name: "Plaquemines",
    lat_min: 29.0,
    lat_max: 30.0,
    lon_min: -90.5,
    lon_max: -89.5,
};

pub const LNG_TERMINALS: &[&LNGTerminal] = &[&HOUSTON_FREEPORT, &CAMERON_LNG, &PLAQUEMINES_LNG];

/// Vessel activity tracking
#[derive(Debug, Clone, Serialize)]
pub struct VesselActivity {
    pub mmsi: String,
    pub ship_type: u8,
    pub last_position: (f64, f64), // (lat, lon)
    pub last_status: u8,
    pub speed_knots: f64,
    pub last_update: DateTime<Utc>,
    pub event: VesselEvent,
}

/// Tracked events
#[derive(Debug, Clone, Serialize, PartialEq)]
pub enum VesselEvent {
    Departure { from_terminal: String },
    Arrival { at_terminal: String },
    InPort { terminal: String },
    Moving { direction: String },
    Anchored { location: String },
}

/// AIS Stream Client for tracking vessels
pub struct AISStreamClient {
    api_key: String,
    ws_url: String,
    active_vessels: Arc<Mutex<HashMap<String, VesselActivity>>>,
}

impl AISStreamClient {
    /// Create a new AIS stream client
    pub fn new(api_key: String) -> Self {
        Self {
            api_key,
            ws_url: "wss://stream.aisstream.io/v0/stream".to_string(),
            active_vessels: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Check if a position is within a terminal bounding box
    fn is_at_terminal(lat: f64, lon: f64, terminal: &LNGTerminal) -> bool {
        lat >= terminal.lat_min
            && lat <= terminal.lat_max
            && lon >= terminal.lon_min
            && lon <= terminal.lon_max
    }

    /// Find which terminal (if any) a vessel is at
    fn find_terminal(lat: f64, lon: f64) -> Option<&'static LNGTerminal> {
        LNG_TERMINALS
            .iter()
            .find(|t| Self::is_at_terminal(lat, lon, t))
            .copied()
    }

    /// Subscribe to LNG terminals
    pub async fn subscribe_to_lng_terminals(&self) -> Result<Message> {
        // Build subscription message
        let subscription = serde_json::json!({
            "APIKey": self.api_key,
            "BoundingBoxes": [
                // Houston/Freeport
                [[29.0, -95.5], [30.0, -94.0]],
                // Cameron LNG
                [[29.5, -93.5], [30.5, -92.5]],
                // Plaquemines
                [[29.0, -90.5], [30.0, -89.5]],
            ],
            "FilterMessageTypes": ["PositionReport"]
        });

        Ok(Message::Text(subscription.to_string()))
    }

    /// Connect to AIS stream and process vessel data
    pub async fn stream_lng_vessels<F>(&self, mut on_event: F) -> Result<()>
    where
        F: FnMut(VesselActivity) + Send,
    {
        // Connect to WebSocket
        let (ws_stream, _) = connect_async(&self.ws_url)
            .await
            .map_err(|e| AISError::ConnectionError(e.to_string()))?;

        tracing::info!("Connected to AIS stream");

        // Subscribe to LNG terminals
        let subscription = self.subscribe_to_lng_terminals().await?;
        let (mut write, mut read) = ws_stream.split();

        write
            .send(subscription)
            .await
            .map_err(|e| AISError::WebSocketError(e.to_string()))?;

        tracing::info!("Subscribed to LNG terminal regions");

        // Process incoming messages
        while let Some(msg) = read.next().await {
            match msg {
                Ok(Message::Text(text)) => {
                    match serde_json::from_str::<AISMessage>(&text) {
                        Ok(ais_msg) => {
                            let mut report = ais_msg.message;
                            report.received_at = Utc::now();

                            // Only track LNG carriers
                            if report.ship_type == ship_types::LNG_CARRIER {
                                self.process_lng_vessel(&report, &mut on_event).await;
                            }
                        }
                        Err(e) => {
                            tracing::warn!("Failed to parse AIS message: {}", e);
                        }
                    }
                }
                Ok(Message::Close(_)) => {
                    tracing::info!("AIS stream closed");
                    break;
                }
                Err(e) => {
                    tracing::error!("WebSocket error: {}", e);
                    break;
                }
                _ => {}
            }
        }

        Ok(())
    }

    /// Process LNG carrier position report
    async fn process_lng_vessel<F>(&self, report: &AISPositionReport, on_event: &mut F)
    where
        F: FnMut(VesselActivity) + Send,
    {
        let mut vessels = self.active_vessels.lock().unwrap();

        // Check if vessel is at a terminal
        let current_terminal = Self::find_terminal(report.latitude, report.longitude);

        let vessel_id = report.mmsi.clone();
        let previous = vessels.get(&vessel_id);

        // Detect events
        let event = if let Some(terminal) = current_terminal {
            // Vessel is at a terminal
            if let Some(prev) = previous {
                // Check if just arrived
                if !Self::find_terminal(prev.last_position.0, prev.last_position.1)
                    .map(|t| t.name == terminal.name)
                    .unwrap_or(false)
                {
                    tracing::info!("LNG carrier {} arrived at {}", vessel_id, terminal.name);
                    VesselEvent::Arrival {
                        at_terminal: terminal.name.to_string(),
                    }
                } else {
                    VesselEvent::InPort {
                        terminal: terminal.name.to_string(),
                    }
                }
            } else {
                VesselEvent::InPort {
                    terminal: terminal.name.to_string(),
                }
            }
        } else if report.nav_status == nav_status::UNDERWAY && report.speed_over_ground > 5.0 {
            // Vessel is moving away from terminal
            if let Some(prev) = previous {
                if Self::find_terminal(prev.last_position.0, prev.last_position.1).is_some() {
                    // Was at terminal, now departing
                    tracing::info!(
                        "LNG carrier {} departing at {} knots",
                        vessel_id,
                        report.speed_over_ground
                    );

                    VesselEvent::Departure {
                        from_terminal: "Gulf Coast".to_string(),
                    }
                } else {
                    VesselEvent::Moving {
                        direction: "Unknown".to_string(),
                    }
                }
            } else {
                VesselEvent::Moving {
                    direction: "Unknown".to_string(),
                }
            }
        } else if report.nav_status == nav_status::ANCHORED || report.speed_over_ground < 2.0 {
            VesselEvent::Anchored {
                location: "Gulf Coast".to_string(),
            }
        } else {
            VesselEvent::Moving {
                direction: "Unknown".to_string(),
            }
        };

        // Create activity record
        let activity = VesselActivity {
            mmsi: vessel_id.clone(),
            ship_type: report.ship_type,
            last_position: (report.latitude, report.longitude),
            last_status: report.nav_status,
            speed_knots: report.speed_over_ground,
            last_update: report.received_at,
            event: event.clone(),
        };

        vessels.insert(vessel_id, activity.clone());

        // Trigger callback for significant events
        match event {
            VesselEvent::Departure { .. } | VesselEvent::Arrival { .. } => {
                on_event(activity);
            }
            _ => {}
        }
    }

    /// Get snapshot of active vessels
    pub fn get_active_vessels(&self) -> Vec<VesselActivity> {
        let vessels = self.active_vessels.lock().unwrap();
        vessels.values().cloned().collect()
    }

    /// Get vessels at a specific terminal
    pub fn get_vessels_at_terminal(&self, terminal_name: &str) -> Vec<VesselActivity> {
        let vessels = self.active_vessels.lock().unwrap();
        vessels
            .values()
            .filter(|v| {
                matches!(
                    &v.event,
                    VesselEvent::InPort { terminal } if terminal == terminal_name
                )
            })
            .cloned()
            .collect()
    }

    /// Calculate port busy-ness metric
    pub fn get_port_activity_summary(&self) -> PortActivitySummary {
        let vessels = self.active_vessels.lock().unwrap();

        let mut inbound = 0;
        let mut outbound = 0;
        let mut anchored = 0;
        let mut in_port = 0;

        for vessel in vessels.values() {
            match &vessel.event {
                VesselEvent::Arrival { .. } => inbound += 1,
                VesselEvent::Departure { .. } => outbound += 1,
                VesselEvent::Anchored { .. } => anchored += 1,
                VesselEvent::InPort { .. } => in_port += 1,
                _ => {}
            }
        }

        PortActivitySummary {
            total_vessels_tracked: vessels.len(),
            inbound_count: inbound,
            outbound_count: outbound,
            anchored_count: anchored,
            in_port_count: in_port,
            activity_index: (inbound + outbound) as f64,
        }
    }
}

/// Port activity summary
#[derive(Debug, Clone, Serialize)]
pub struct PortActivitySummary {
    pub total_vessels_tracked: usize,
    pub inbound_count: usize,
    pub outbound_count: usize,
    pub anchored_count: usize,
    pub in_port_count: usize,
    pub activity_index: f64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_terminal_detection() {
        // Test Houston/Freeport
        assert!(AISStreamClient::is_at_terminal(
            29.5,
            -94.5,
            &HOUSTON_FREEPORT
        ));
        assert!(!AISStreamClient::is_at_terminal(
            28.0,
            -95.0,
            &HOUSTON_FREEPORT
        ));

        // Test find_terminal
        let terminal = AISStreamClient::find_terminal(29.5, -94.5);
        assert!(terminal.is_some());
    }

    #[test]
    fn test_ship_type_constants() {
        assert_eq!(ship_types::LNG_CARRIER, 84);
        assert_eq!(ship_types::CRUDE_TANKER, 80);
    }
}

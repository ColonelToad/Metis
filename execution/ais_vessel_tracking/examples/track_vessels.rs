use ais_vessel_tracking::{AISStreamClient, VesselEvent};
use anyhow::Result;

/// Example: Real-time LNG vessel tracking at US Gulf Coast terminals
///
/// Tracks LNG carrier movements and generates signals for:
/// - Vessel arrivals/departures
/// - Port congestion indicators
/// - Supply chain activity
#[tokio::main]
async fn main() -> Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt::init();

    // Get API key from environment
    let api_key = std::env::var("AIS_API_KEY").expect("AIS_API_KEY environment variable required");

    // Create AIS stream client
    let client = AISStreamClient::new(api_key);

    // Start streaming vessel data
    println!("Starting LNG vessel tracking at US Gulf Coast terminals...");
    println!("Monitoring: Houston/Freeport, Cameron LNG, Plaquemines");

    // Define event handler
    let handler = |activity| match &activity.event {
        VesselEvent::Departure { from_terminal } => {
            println!(
                "📤 LNG DEPARTURE: {} from {} at {:.2}°N, {:.2}°E ({} kts)",
                activity.mmsi,
                from_terminal,
                activity.last_position.0,
                activity.last_position.1,
                activity.speed_knots
            );
        }
        VesselEvent::Arrival { at_terminal } => {
            println!(
                "📥 LNG ARRIVAL: {} to {} at {:.2}°N, {:.2}°E",
                activity.mmsi, at_terminal, activity.last_position.0, activity.last_position.1
            );
        }
        _ => {}
    };

    // Stream vessel data
    client.stream_lng_vessels(handler).await?;

    Ok(())
}

use super::{EventType, MarketEvent};
use anyhow::Result;
use chrono::DateTime;
use csv::ReaderBuilder;
use std::path::Path;

pub struct CsvTickParser;

impl CsvTickParser {
    pub fn parse_file(path: &Path) -> Result<Vec<MarketEvent>> {
        use tracing::{debug, warn};
        let mut reader = ReaderBuilder::new().has_headers(true).from_path(path)?;
        let mut events = Vec::new();
        for (i, result) in reader.records().enumerate() {
            let record = result?;
            debug!("Row {}: {:?}", i + 2, record);
            if record.len() < 6 {
                warn!(
                    "Skipping row {}: expected at least 6 columns, got {}",
                    i + 2,
                    record.len()
                );
                continue;
            }
            let timestamp: DateTime<chrono::Utc> = match record[0].parse() {
                Ok(t) => {
                    debug!("Row {}: Parsed timestamp (default): {}", i + 2, t);
                    t
                }
                Err(e1) => {
                    // Try to parse as "%Y-%m-%d %H:%M:%S"
                    match chrono::NaiveDateTime::parse_from_str(&record[0], "%Y-%m-%d %H:%M:%S") {
                        Ok(naive) => {
                            let t = chrono::DateTime::<chrono::Utc>::from_naive_utc_and_offset(
                                naive,
                                chrono::Utc,
                            );
                            debug!("Row {}: Parsed timestamp (naive fallback): {}", i + 2, t);
                            t
                        }
                        Err(e2) => {
                            warn!(
                                "Skipping row {}: invalid timestamp: {} | fallback error: {}",
                                i + 2,
                                e1,
                                e2
                            );
                            continue;
                        }
                    }
                }
            };
            let bid: f64 = match record[2].parse() {
                Ok(v) => {
                    debug!("Row {}: Parsed bid: {}", i + 2, v);
                    v
                }
                Err(e) => {
                    warn!("Skipping row {}: invalid bid: {}", i + 2, e);
                    continue;
                }
            };
            let ask: f64 = match record[3].parse() {
                Ok(v) => {
                    debug!("Row {}: Parsed ask: {}", i + 2, v);
                    v
                }
                Err(e) => {
                    warn!("Skipping row {}: invalid ask: {}", i + 2, e);
                    continue;
                }
            };
            let bid_qty: f64 = match record[4].parse() {
                Ok(v) => {
                    debug!("Row {}: Parsed bid_qty: {}", i + 2, v);
                    v
                }
                Err(e) => {
                    warn!("Skipping row {}: invalid bid_quantity: {}", i + 2, e);
                    continue;
                }
            };
            let ask_qty: f64 = match record[5].parse() {
                Ok(v) => {
                    debug!("Row {}: Parsed ask_qty: {}", i + 2, v);
                    v
                }
                Err(e) => {
                    warn!("Skipping row {}: invalid ask_quantity: {}", i + 2, e);
                    continue;
                }
            };
            events.push(MarketEvent {
                timestamp,
                event_type: EventType::Quote {
                    bid_price: bid,
                    bid_quantity: bid_qty,
                    ask_price: ask,
                    ask_quantity: ask_qty,
                },
            });
        }
        Ok(events)
    }
}

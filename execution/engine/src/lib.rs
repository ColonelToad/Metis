//! Metis execution engine: order book, execution algorithms, signal
//! transport, and alternative-data ingestion.
//!
//! This crate consolidates what used to be five separate crates
//! (`orderbook`, `execution_algos`, `signal_interface`, `fix_client`,
//! `ais_vessel_tracking`) plus the surviving, previously-unwired pieces of
//! `metis-core` (`fusion`, `simd`, `reasoning`). They were split by data
//! structure rather than by genuine independence — they already shared
//! types (`orderbook::Side`) and called into each other conceptually
//! (`execution_algos` and `signal_interface` both depended on `orderbook`
//! as a separate crate) just not cleanly in code. One crate, one dependency
//! graph, one place for `TradingSignal`/`OrderStatus`/`TwapExecutor` to have
//! a single definition instead of three.
//!
//! `fix_client` isn't carried over as a module: it was a 91-byte no-op stub
//! with no real content (`pub fn placeholder() {}`). FIX support gets a
//! real module here whenever there's an actual implementation to put in
//! one, not a placeholder that reads as more finished than it is.
//!
//! `fusion`, `simd`, and `reasoning` are relocated but not yet wired to
//! anything real — that's a deliberate next step (Phase D), not an
//! oversight. `fusion`'s `ClimateSignal`/`GridSignal`/`PolicySignal` types
//! live in `fusion.rs` itself rather than a crate-wide `types.rs`, since
//! nothing else in this crate needs them; a themed module beats a
//! grab-bag, which is part of how the original type duplication happened
//! in the first place.

pub mod ais_vessel_tracking;
pub mod execution_algos;
pub mod fusion;
pub mod latency;
pub mod orderbook;
pub mod reasoning;
pub mod signal_interface;
pub mod simd;

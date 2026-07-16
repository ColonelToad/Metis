// Minimal benchmark for orderbook crate
use criterion::{criterion_group, criterion_main, Criterion};

fn dummy_bench(_c: &mut Criterion) {
    // No-op
}

criterion_group!(benches, dummy_bench);
criterion_main!(benches);

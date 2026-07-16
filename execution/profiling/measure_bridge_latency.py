"""
End-to-end Python-Rust bridge latency benchmark.

Measures the full cost of calling publish_signal from Python,
including:
- Python argument marshalling
- PyO3 type conversion
- Rust function call
- crossbeam try_send
- Return to Python

Target: <500ns per call (vs 238.9ns Rust-only baseline)
"""

import time
from metis_core import SignalPublisher

def benchmark_bridge_latency(num_signals=10_000):
    """Measure average latency per publish_signal call."""
    pub = SignalPublisher()
    
    # Warmup (let JIT settle, fill CPU caches)
    for _ in range(1_000):
        pub.publish_signal('NG', 1, 0.75, 60)
    
    # Actual measurement
    start = time.perf_counter_ns()
    for i in range(num_signals):
        # Vary inputs slightly to avoid branch prediction artifacts
        direction = 1 if i % 2 == 0 else -1
        confidence = 0.65 + (i % 100) * 0.0035  # 0.65 to 1.0
        pub.publish_signal('NG', direction, confidence, 60)
    end = time.perf_counter_ns()
    
    total_ns = end - start
    avg_ns = total_ns / num_signals
    
    print(f"\n{'='*60}")
    print(f"Python→Rust Bridge Latency Benchmark")
    print(f"{'='*60}")
    print(f"Total signals:        {num_signals:,}")
    print(f"Total time:           {total_ns/1e6:.2f} ms")
    print(f"Average per signal:   {avg_ns:.1f} ns")
    print(f"Throughput:           {num_signals/(total_ns/1e9):.0f} signals/sec")
    print(f"{'='*60}")
    print(f"Rust-only baseline:   238.9 ns (Criterion benchmark)")
    print(f"Python overhead:      {avg_ns - 238.9:.1f} ns ({(avg_ns/238.9 - 1)*100:.1f}% slower)")
    print(f"Target:               <500 ns")
    print(f"Status:               {'✅ PASS' if avg_ns < 500 else '❌ FAIL'}")
    print(f"{'='*60}\n")
    
    return avg_ns

if __name__ == '__main__':
    benchmark_bridge_latency()

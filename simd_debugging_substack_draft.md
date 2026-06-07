# Why My SIMD Code Was Silently Running as Scalar, and What That Taught Me About Production Defaults

When you optimize code for speed, you assume the optimization actually compiles.

I learned this the hard way.

---

## The Anomaly

A few weeks ago, I was benchmarking a trading system core written in Rust. The system uses vectorized operations—SIMD intrinsics to process 1024 floats per calculation in parallel. On paper, the math is solid: AVX2 should process 8 floats per cycle with fused multiply-add, giving me roughly 7-8x speedup over scalar code.

What I got instead: **0.34x speedup. The scalar version was faster.**

```
SIMD result: 3.199677
Scalar result: 3.199682
SIMD time (10000 iterations): 13.6771ms
Scalar time (10000 iterations): 4.6213ms

SIMD speedup: 0.34x ← This should be 7x+
```

The results were identical (within floating point error), so correctness wasn't the issue. The SIMD code was just... slower. This shouldn't be possible.

---

## The Layers of Wrong

The obvious suspects came first:

- **Is the compiler optimizing it away?** No—`black_box()` prevents that.
- **Is the algorithm wrong?** No—horizontal sum is standard, FMA is correct.
- **Is the CPU too old?** No—Intel Core Ultra 7 155U has AVX2.
- **Is the data too small?** No—1024 floats is plenty.

Then I checked the binary itself.

```powershell
objdump -C -d target/release/metis_core.dll | grep "vhaddps\|vfmadd"
```

**Nothing.** Zero AVX2 instructions in the compiled binary. The intrinsics weren't there.

---

## The Debug Cascade

This is where it gets interesting. The code explicitly uses `unsafe` blocks with `_mm256_fmadd_ps`, `_mm256_hadd_ps`, and other intrinsics. Rust compiled it without error. But the binary had no AVX2 instructions.

This meant one thing: **the compiler was silently falling back to scalar code even though it was marked `unsafe`.**

The code was syntactically valid SIMD. It just wasn't actually executing SIMD.

This is the kind of bug that doesn't fail loudly. It compiles. It runs. It's just wrong. And in production, you'd never notice—your code would just be 3x slower than it should be, and you'd blame the algorithm.

---

## The Root Cause

The fix required understanding Rust's CPU feature model.

Rust doesn't assume your CPU supports AVX2. When you write `unsafe { _mm256_fmadd_ps(...) }`, you're telling Rust "trust me, this CPU has AVX2." But if you don't also tell the *compiler* to assume AVX2 is available, rustc compiles it in a way that's safe for CPUs without AVX2—and that "safe fallback" is scalar code.

The fix: **`.cargo/config.toml`**

```toml
[build]
rustflags = ["-C", "target-feature=+avx2,+fma", "-C", "target-cpu=native"]

[profile.release]
opt-level = 3
lto = true
codegen-units = 1
```

This tells the compiler: "Assume this CPU has AVX2 and FMA. Compile accordingly."

After adding this file and rebuilding:

```
Scalar time (10000 iterations): 11.6166ms (462ns per iteration)
SIMD time (10000 iterations): 1.6043ms (160ns per iteration)

SIMD speedup: 7.24x ← There it is
```

The benchmark didn't change. The code didn't change. Only the compiler flags changed. But now the intrinsics were actually being compiled.

---

## Cross-Platform Implications

With the fix in place, I ran the same benchmark on two systems:

1. **Windows native**: 1700 MHz (throttled)
2. **WSL2 (same hardware)**: 2688 MHz (not throttled)
3. Results:

```
SIMD Benchmark Comparison

Benchmark              Windows Mean    WSL Mean        Difference
─────────────────────────────────────────────────────────────
simd_normalization     63.7 ns         5.3 ns          WSL 92% faster
simd_distance          93.97 ns        61.13 ns        WSL 35% faster
```

Interesting: WSL was faster. Not because Linux's SIMD is better optimized. Because **WSL lets the CPU run at 2688 MHz while Windows caps it at 1700 MHz.**

The variance:

| Platform | CPU Frequency | Variance |
|----------|---|---|
| Windows | 1700 MHz (constant) | ±125% on scalar measurements |
| WSL | 2688 MHz (constant) | ±15% on SIMD measurements |

The higher frequency accounts for most of the difference. But there's a secondary insight: WSL's measurements were more stable, suggesting the CPU was running at a consistent frequency rather than fluctuating.

---

## What This Tells You

Three things:

### 1. Silent Defaults Can Hide Massive Performance Gaps

Your code is correct. It compiles. It passes tests. It just doesn't do what you wrote.

This isn't a Rust problem—it's a systems problem. C has the same issue with `-mavx2` flags. The difference is most C developers are trained to think about compiler flags. Most Rust developers aren't. So the bug stays hidden until someone benchmarks across platforms.

### 2. System Configuration Matters as Much as Algorithm

The 58% frequency difference between Windows and WSL isn't a code issue. It's a **system default**. Somewhere in Windows BIOS or power management, this CPU is capped at 1700 MHz. WSL doesn't hit that cap (or Linux has different power governors).

In production, this means: same code, same hardware, 58% performance difference depending on OS and configuration.

When you're optimizing for production, you need to know:
- What frequency does this hardware actually run at?
- What are the OS defaults?
- Can those defaults be changed?

### 3. Measurement Changes Everything

I found this problem because I benchmarked. Not by code review, not by tests, not by inspection. By measuring.

The process was:
1. **Anomalous result**: SIMD slower than scalar
2. **Question the premise**: This shouldn't be possible
3. **Measure what's actually happening**: Check the binary for intrinsics
4. **Find the hidden assumption**: Compiler flags aren't set
5. **Fix the root cause**: Add `.cargo/config.toml`
6. **Measure again across platforms**: Compare Windows vs WSL
7. **Discover the second issue**: System frequency differences

Each measurement revealed a different layer. None of it was obvious from reading the code.

---

## The Production Framing

Here's why this matters for infrastructure:

When you ship code to production, you don't just ship the code. You ship the code + the system configuration + the hardware profile + the OS defaults. A 7x faster algorithm that runs on hardware capped at 1700 MHz is slower than a 1x algorithm running at 3600 MHz.

This is why production benchmarking is different from laptop benchmarking. You need to measure on the actual target hardware, with the actual target configuration, and understand which variables are fixed and which are tunable.

In this case:
- **Fixed**: CPU architecture (AVX2 exists)
- **Tunable**: Compiler flags (add `.cargo/config.toml`)
- **Configuration dependent**: CPU frequency (1700 MHz on Windows, 2688 MHz on WSL)
- **Unknown**: Why the frequency differs

Understanding which is which changes how you make architectural decisions.

---

## Lessons for Systems Work

**1. Distrust the defaults**

Don't assume the compiler is doing what you wrote. Don't assume the CPU is running at full frequency. Measure.

**2. Platform differences hide configuration issues**

WSL being faster isn't "better," it revealed that Windows has a frequency cap. That cap is information you need.

**3. Variance is a signal**

The scalar measurements varied by ±125%. That's not random noise—it's a sign the CPU is fluctuating or the benchmark is noisy. SIMD measurements were more stable. That's meaningful.

**4. Isolate variables**

I needed three benchmarks to separate:
- Code correctness (same results)
- Compilation (binary inspection)
- Algorithm efficiency (isolated tight loop)
- Platform defaults (cross-platform comparison)

Each revealed something different.

---

## The Takeaway

The SIMD optimization was real. The speedup was real. But neither of those would have mattered if the code wasn't actually compiled to use the optimization.

This is the kind of debugging that happens in production all the time, except usually someone else is paying for it. The lesson isn't "use `.cargo/config.toml`"—it's "measure what's actually happening before blaming the code."

In trading systems, in infrastructure, in anything where performance matters: **observable current state reveals future possibilities.** You can't optimize something you don't understand. And you can't understand it without measuring.

The other lesson is harder to articulate but more valuable:

When something is slower than it should be, the problem usually isn't the code. It's an assumption about the system. Find the assumption, question it, measure it, and usually the fix is smaller than you'd expect.

---

## Tooling That Helped

For anyone debugging similar issues:

- **Criterion.rs** for benchmarking (with `black_box()` to prevent elision)
- **objdump** for inspecting compiled intrinsics
- **VTune** for profiling (would have caught the missing instructions immediately)
- **Cross-platform comparison** to isolate OS/configuration issues

The `.cargo/config.toml` with proper rustflags is the real fix, but the debugging method—measure, isolate, repeat—is what works across problems.

---

## Next Steps

The system is now compiled with proper AVX2 support. The cross-platform benchmarks show consistent performance (within measurement variance). The frequency cap on Windows is still there—that's a BIOS/power management question I'm still investigating.

But the core lesson stands: don't trust that your optimization compiled. Measure it. Then measure again on your actual target platform.

[IMAGE PLACEHOLDER 1: Screenshot of objdump output showing zero AVX2 instructions (before fix)]

[IMAGE PLACEHOLDER 2: Screenshot of SIMD speedup 7.24x (after fix)]

[IMAGE PLACEHOLDER 3: Table of Windows vs WSL benchmark results with frequency data]

[IMAGE PLACEHOLDER 4: Graph of measurement variance: scalar vs SIMD across trials]

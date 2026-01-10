"""
Profile the feature engineering pipeline.
Outputs:
- Timings per loader and total
- cProfile stats saved to profiling/features_profile.txt
- Peak memory via tracemalloc
"""
import os
import time
import cProfile
import pstats
import tracemalloc
from datetime import datetime

from research.features.engineer_features import FeatureEngineer, DB_URL

OUTPUT_DIR = "profiling"
PROFILE_OUT = os.path.join(OUTPUT_DIR, "features_profile.txt")


def time_section(label, fn):
    start = time.perf_counter()
    out = fn()
    dur = time.perf_counter() - start
    print(f"[PROFILE] {label}: {dur:.3f}s")
    return out, dur


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("[PROFILE] Starting feature pipeline profiling")
    fe = FeatureEngineer(DB_URL, start_date="2015-01-01")

    tracemalloc.start()
    pr = cProfile.Profile()
    pr.enable()

    df, t_price = time_section("load_price_data", fe.load_price_data)
    df, t_eia = time_section("load_eia_features", lambda: fe.load_eia_features(df))
    df, t_fred = time_section("load_fred_features", lambda: fe.load_fred_features(df))
    df, t_tom = time_section("load_tomtom_features", lambda: fe.load_tomtom_features(df))
    df, t_cong = time_section("load_congress_features", lambda: fe.load_congress_features(df))

    # full engineer run (re-runs loaders internally, for total)
    df2, t_total = time_section("engineer_features_total", fe.engineer_features)

    pr.disable()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    with open(PROFILE_OUT, "w") as f:
        ps = pstats.Stats(pr, stream=f).sort_stats("cumtime")
        ps.print_stats(50)
        f.write("\n\n[PROFILE] Timings (s):\n")
        f.write(f"price={t_price:.3f}, eia={t_eia:.3f}, fred={t_fred:.3f}, tomtom={t_tom:.3f}, congress={t_cong:.3f}, total={t_total:.3f}\n")
        f.write(f"peak_memory={peak/1e6:.1f} MB\n")

    print(f"[PROFILE] Saved cProfile to {PROFILE_OUT}")
    print(f"[PROFILE] Peak memory: {peak/1e6:.1f} MB")


if __name__ == "__main__":
    main()

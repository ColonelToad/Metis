# C++ Engine Contract (`metis-cpp`)

The C++ HFT engine is the **primary live trading engine**. The Rust engine
(`execution/engine`) runs as a **secondary/fallback**. Python signals go to
the primary first and fail over to the secondary automatically.

## Location & build

The C++ repo lives exclusively in WSL (own git repo, no copy in the Windows
checkout):

```
WSL path:   /home/tolugenius/Projects/metis-cpp
Windows:    \\wsl.localhost\Debian\home\tolugenius\Projects\metis-cpp
```

```bash
wsl -d Debian -- bash -c "cd /home/tolugenius/Projects/metis-cpp/cpp_engine \
  && cmake -B build -S . && cmake --build build --target metis-tests metis-server"
ctest --test-dir build          # 34 gtests (incl. msgpack codec fixtures)
./build/src/bin/metis-server    # binds 127.0.0.1:8080, logs to stdout
```

Env overrides: `METIS_CPP_PORT` (default 8080), `METIS_CPP_BIND` (default
127.0.0.1).

## Wire protocol (must stay identical across engines)

Frame: **4-byte big-endian length prefix + msgpack payload**, one
request/response pair per connection exchange, persistent connections OK.

### Inbound `TradingSignal` (msgpack map, string keys)

| field | type |
|---|---|
| `signal_id` | str |
| `timestamp` | ISO-8601 str |
| `symbol` | str (`NG:CME`) |
| `direction` | `"Long"` \| `"Short"` \| `"Neutral"` |
| `confidence` | f64 [0,1] |
| `target_quantity` | f64 |
| `horizon_minutes` | int |
| `metadata` | map of str → scalar or array-of-str (`model_version`, `features_used`, `weather_anomaly`, `policy_trigger`, `uncertainty`) |

Unknown top-level fields are ignored (forward compatible). Malformed frames
close the connection.

### Outbound `ExecutionResponse` — NAMED MAP ONLY

Field order used by both engines:
`signal_id, status, avg_fill_price, filled_quantity, latency_ms,
error_message`.

- `status`: `Accepted | InProgress | Completed | PartiallyCompleted |
  Rejected | Error`
- Positional arrays break the Python client (`'list' object has no
  attribute 'get'`); Rust must keep `rmp_serde::to_vec_named`.
- The C++ encoder's output is byte-for-byte identical to Python
  `msgpack.packb()` of the same dict; gtest fixtures pin this.

### Semantics (both engines)

- Seeded book: bid 2.500 / ask 2.505 ×1000 → mid 2.5025.
- `Neutral` → `Rejected`, error `"Neutral signal: no side to trade"`.
- No liquidity → `Rejected`, error mentions liquidity.
- Accepted signals produce a TWAP plan (~5 slices over horizon, min 60s/slice),
  `avg_fill_price = mid`, `filled_quantity = 0.0` (planning only — no live
  orders yet).

## Ports

| service | port |
|---|---|
| C++ engine (primary) | 8080 |
| Rust engine (secondary) | 8081 (`METIS_ENGINE_PORT`) |
| Orchestrator HTTP | 9000 |

## Python failover

`DualLSTMInference.send_to_execution()` (research/models/inference_pipeline.py)
connects per-send: primary cpp :8080 → on failure fallback rust :8081. The
winning response gets `exec_engine: "cpp"|"rust"` injected;
research/ops/orchestrate_daily_pipeline.py copies it into
`signal["metadata"]["exec_engine"]` alongside the existing `exec_status`,
`exec_latency_ms`, `exec_fill_price`, `exec_error` strings so it persists via
the orchestrator into SQLite and shows up in `/api/signals/recent`.

## Long-running server note (agent tooling)

`metis_server.exe` (Rust) and `metis-server` (C++) are long-lived listeners.
When launching them from scripted/agent tooling, redirect stdout AND stderr
to files and stop the process within the same command — anything waiting on
the process tree will otherwise appear hung. In WSL, `nohup ... &
disown` survives the `wsl` invocation; clean up with an explicit `pkill`.

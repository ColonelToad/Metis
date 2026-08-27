"""
Signal interface client for communicating with Rust execution engine.
Sends trading signals and receives execution reports.
"""

import csv
import socket
import struct
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import msgpack
from loguru import logger


class SignalClient:
    """
    Client for sending trading signals to Rust execution engine via TCP.
    Uses MessagePack for efficient serialization.
    """

    def __init__(self, host: str = "localhost", port: int = 8080):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None

    def connect(self) -> bool:
        """Establish connection to execution engine."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            logger.info(f"Connected to execution engine at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False

    def disconnect(self):
        """Close connection."""
        if self.socket:
            self.socket.close()
            self.socket = None
            logger.info("Disconnected from execution engine")

    def send_signal(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Send trading signal and wait for response.

        Args:
            signal: Dictionary containing signal data:
                - signal_id: str
                - timestamp: ISO format string
                - symbol: str
                - direction: "Long" | "Short" | "Neutral"
                - confidence: float [0, 1]
                - target_quantity: float
                - horizon_minutes: int
                - metadata: dict with model info

        Returns:
            Execution response dictionary or None on error
        """
        if not self.socket:
            logger.error("Not connected to execution engine")
            return None

        try:
            start_time = time.time()

            # Serialize signal with MessagePack
            signal_bytes = msgpack.packb(signal)

            # Send length prefix (4 bytes, big-endian)
            length_prefix = struct.pack(">I", len(signal_bytes))
            self.socket.sendall(length_prefix + signal_bytes)

            # Receive response length
            resp_length_bytes = self._recv_exactly(4)
            if not resp_length_bytes:
                return None

            resp_length = struct.unpack(">I", resp_length_bytes)[0]

            # Receive response body
            resp_bytes = self._recv_exactly(resp_length)
            if not resp_bytes:
                return None

            response = msgpack.unpackb(resp_bytes, raw=False)

            latency_ms = (time.time() - start_time) * 1000
            logger.info(
                f"Signal {signal['signal_id']} processed in {latency_ms:.2f}ms - "
                f"Status: {response.get('status')}"
            )

            return response

        except Exception as e:
            logger.error(f"Error sending signal: {e}")
            return None

    def _recv_exactly(self, n: int) -> Optional[bytes]:
        """Receive exactly n bytes from socket."""
        data = b""
        while len(data) < n:
            chunk = self.socket.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data


class EngineRouter:
    """
    Routes signals to the primary execution engine, failing over to a
    secondary when the primary is unreachable (connect failure or no
    response). Every successful response is tagged with `exec_engine`
    so callers can record which engine handled the signal.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        fallback_host: Optional[str] = None,
        fallback_port: Optional[int] = None,
        primary_name: str = "cpp",
        fallback_name: str = "rust",
    ):
        self.primary = SignalClient(host=host, port=port)
        self.fallback = (
            SignalClient(host=fallback_host, port=fallback_port)
            if fallback_host and fallback_port
            else None
        )
        self.primary_name = primary_name
        self.fallback_name = fallback_name

    def _try(
        self,
        client: SignalClient,
        signal: Dict[str, Any],
        engine_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Connect, send, disconnect. Returns response tagged with
        `exec_engine`, or None if that engine is down/unresponsive."""
        if not client.connect():
            logger.warning(f"{engine_name} execution engine unreachable")
            return None
        try:
            response = client.send_signal(signal)
        finally:
            client.disconnect()
        if response is None:
            logger.warning(f"{engine_name} execution engine failed to respond")
            return None
        response["exec_engine"] = engine_name
        return response

    def send(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send one signal with automatic failover. Returns the winning
        engine's response (with `exec_engine` set) or None."""
        response = self._try(self.primary, signal, self.primary_name)

        if response is None and self.fallback is not None:
            logger.info(
                "Failing over to %s execution engine on :%d",
                self.fallback_name,
                self.fallback.port,
            )
            response = self._try(self.fallback, signal, self.fallback_name)

        if response:
            logger.info(
                f"Execution response: {response['status']} "
                f"(engine={response.get('exec_engine')})"
            )
        else:
            logger.error("No execution engine reachable; signal not confirmed")
        return response

    def shadow_send(
        self, signal: Dict[str, Any], log_path: Optional[Path] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Shadow-run: send to BOTH engines independently, log deltas.
        Returns primary's response (or fallback if primary down) like
        `send()`, but always attempts both when available.
        Log: data/logs/shadow_compare.csv with primary/secondary
        slippage_bps, avg_fill_price, status deltas. For comparative study
        before cutover (see docs/cpp-engine-contract.md shadow-run section).
        """
        # Lazy import to avoid cycle; config holds shadow log path
        try:
            from research.config import EXECUTION_ENGINE_SHADOW_LOG
        except ImportError:
            EXECUTION_ENGINE_SHADOW_LOG = Path("data/logs/shadow_compare.csv")
        if log_path is None:
            log_path = EXECUTION_ENGINE_SHADOW_LOG

        primary_resp = self._try(self.primary, signal, self.primary_name)
        fallback_resp = None
        if self.fallback is not None:
            fallback_resp = self._try(self.fallback, signal, self.fallback_name)

        # Choose return value like send() would (primary wins if available)
        response = primary_resp if primary_resp is not None else fallback_resp

        # Log comparative row (best-effort, never raises)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not log_path.exists()
            # Extract slippage/price/status, handling None
            def _get(d, k):
                return d.get(k) if d else None

            row = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "signal_id": signal.get("signal_id"),
                "primary_status": _get(primary_resp, "status"),
                "primary_slippage_bps": _get(primary_resp, "slippage_bps"),
                "primary_avg_fill": _get(primary_resp, "avg_fill_price"),
                "secondary_status": _get(fallback_resp, "status"),
                "secondary_slippage_bps": _get(fallback_resp, "slippage_bps"),
                "secondary_avg_fill": _get(fallback_resp, "avg_fill_price"),
                "delta_slippage": (
                    (primary_resp.get("slippage_bps") or 0)
                    - (fallback_resp.get("slippage_bps") or 0)
                    if primary_resp and fallback_resp
                    else None
                ),
                "delta_price": (
                    (primary_resp.get("avg_fill_price") or 0)
                    - (fallback_resp.get("avg_fill_price") or 0)
                    if primary_resp and fallback_resp
                    and primary_resp.get("avg_fill_price") is not None
                    and fallback_resp.get("avg_fill_price") is not None
                    else None
                ),
            }
            with open(log_path, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=row.keys())
                if write_header:
                    w.writeheader()
                w.writerow(row)
            logger.info(f"Shadow compare logged to {log_path} (delta_slippage={row['delta_slippage']})")
        except Exception as e:
            logger.warning(f"Shadow log failed (non-fatal): {e}")

        if response:
            logger.info(
                f"Shadow response: {response['status']} "
                f"(engine={response.get('exec_engine')})"
            )
        else:
            logger.error("Shadow: no engine reachable")
        return response


def create_signal(
    signal_id: str,
    symbol: str,
    direction: str,
    confidence: float,
    target_quantity: float,
    horizon_minutes: int = 15,
    model_version: str = "v1.0",
    features_used: list = None,
    weather_anomaly: float = None,
    policy_trigger: str = None,
) -> Dict[str, Any]:
    """
    Helper function to create a properly formatted trading signal.

    Args:
        signal_id: Unique identifier for this signal
        symbol: Instrument symbol (e.g., "NG:CME")
        direction: "Long", "Short", or "Neutral"
        confidence: Confidence score [0, 1]
        target_quantity: Number of contracts to trade
        horizon_minutes: Execution window in minutes
        model_version: ML model version identifier
        features_used: List of feature names used by model
        weather_anomaly: Temperature anomaly z-score
        policy_trigger: Policy event description

    Returns:
        Signal dictionary ready to send
    """
    return {
        "signal_id": signal_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "target_quantity": target_quantity,
        "horizon_minutes": horizon_minutes,
        "metadata": {
            "model_version": model_version,
            "features_used": features_used or [],
            "weather_anomaly": weather_anomaly,
            "policy_trigger": policy_trigger,
            "uncertainty": 1.0 - confidence,
        },
    }


if __name__ == "__main__":
    # Example usage
    client = SignalClient(host="localhost", port=8080)

    if client.connect():
        # Create test signal
        signal = create_signal(
            signal_id="TEST-001",
            symbol="NG:CME",
            direction="Long",
            confidence=0.85,
            target_quantity=10.0,
            horizon_minutes=15,
            features_used=["temp_error", "eia_surprise", "hdd_forecast"],
            weather_anomaly=2.5,
        )

        print("Sending signal:", signal)
        response = client.send_signal(signal)

        if response:
            print("Response:", response)

        client.disconnect()

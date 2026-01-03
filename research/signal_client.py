"""
Signal interface client for communicating with Rust execution engine.
Sends trading signals and receives execution reports.
"""
import msgpack
import socket
import struct
from typing import Optional, Dict, Any
from datetime import datetime
from loguru import logger
import time


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
        }
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

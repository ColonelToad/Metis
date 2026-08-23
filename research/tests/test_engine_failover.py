"""
Test suite: EngineRouter failover logic (cpp primary -> rust secondary).

Covers the critical path used by DualLSTMInference.send_to_execution():
primary healthy, connect failure, unresponsive engine, total outage,
and the no-fallback configuration. Uses fake in-memory signal clients —
no sockets, no TF model load.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from research.signal_client import EngineRouter


class FakeSignalClient:
    """Mimics SignalClient's connect/send_signal/disconnect surface."""

    def __init__(self, port=0, connect_ok=True, respond=True):
        self.port = port
        self.connect_ok = connect_ok
        self.respond = respond
        self.connect_calls = 0
        self.send_calls = 0
        self.disconnect_calls = 0
        self.last_signal = None

    def connect(self):
        self.connect_calls += 1
        return self.connect_ok

    def send_signal(self, signal):
        self.send_calls += 1
        self.last_signal = signal
        if not self.respond:
            return None
        return {
            "signal_id": signal.get("signal_id", "unknown"),
            "status": "Completed",
        }

    def disconnect(self):
        self.disconnect_calls += 1


def make_router(primary=None, fallback=None):
    router = EngineRouter.__new__(EngineRouter)
    router.primary = primary or FakeSignalClient(port=8080)
    router.fallback = fallback
    router.primary_name = "cpp"
    router.fallback_name = "rust"
    return router


SAMPLE_SIGNAL = {"signal_id": "sig-test-001", "direction": "Long"}


def test_primary_used_when_healthy():
    fallback = FakeSignalClient()
    router = make_router(fallback=fallback)

    response = router.send(SAMPLE_SIGNAL)

    assert response is not None
    assert response["exec_engine"] == "cpp"
    assert response["status"] == "Completed"
    assert router.primary.send_calls == 1
    assert fallback.connect_calls == 0  # never touched
    assert router.primary.disconnect_calls == 1


def test_failover_on_connect_failure():
    dead_primary = FakeSignalClient(connect_ok=False)
    fallback = FakeSignalClient()
    router = make_router(dead_primary, fallback)

    response = router.send(SAMPLE_SIGNAL)

    assert response is not None
    assert response["exec_engine"] == "rust"
    assert dead_primary.send_calls == 0  # never got that far
    assert fallback.connect_calls == 1
    assert fallback.send_calls == 1
    assert fallback.last_signal == SAMPLE_SIGNAL


def test_failover_on_unresponsive_primary():
    # Connects fine but send returns None (timeout / protocol error).
    silent_primary = FakeSignalClient(respond=False)
    fallback = FakeSignalClient()
    router = make_router(silent_primary, fallback)

    response = router.send(SAMPLE_SIGNAL)

    assert response is not None
    assert response["exec_engine"] == "rust"
    assert silent_primary.send_calls == 1
    assert silent_primary.disconnect_calls == 1


def test_both_engines_down_returns_none():
    dead_primary = FakeSignalClient(connect_ok=False)
    dead_fallback = FakeSignalClient(connect_ok=False)
    router = make_router(dead_primary, dead_fallback)

    response = router.send(SAMPLE_SIGNAL)

    assert response is None
    assert dead_fallback.connect_calls == 1  # fallback was attempted


def test_no_fallback_configured_single_attempt():
    dead_primary = FakeSignalClient(connect_ok=False)
    router = make_router(dead_primary, fallback=None)

    response = router.send(SAMPLE_SIGNAL)

    assert response is None
    assert router.fallback is None
    assert dead_primary.connect_calls == 1


def test_disconnect_called_even_when_send_raises():
    class ExplodingClient(FakeSignalClient):
        def send_signal(self, signal):
            raise ConnectionError("socket died mid-send")

    exploding = ExplodingClient()
    router = make_router(exploding)

    try:
        router.send(SAMPLE_SIGNAL)
        raised = False
    except ConnectionError:
        raised = True

    assert raised
    assert exploding.disconnect_calls == 1  # finally-block ran


def test_exec_engine_tag_overwrites_stale_value():
    # A malicious/buggy upstream could pre-set exec_engine; router must win.
    primary = FakeSignalClient()

    class TaggedClient(FakeSignalClient):
        def send_signal(self, signal):
            resp = super().send_signal(signal)
            resp["exec_engine"] = "bogus"
            return resp

    router = make_router(TaggedClient())
    response = router.send(SAMPLE_SIGNAL)

    assert response["exec_engine"] == "cpp"

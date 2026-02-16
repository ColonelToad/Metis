"""
Test Phase 1 implementation of database context loading.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path().resolve()))

from rag.ingestion.database_context import (
    SourceStatus,
    ContextSnapshot,
    DatabaseContextLoader,
    SessionContextManager,
)


def test_source_status():
    """Test SourceStatus dataclass."""
    status = SourceStatus(
        name="test_source",
        status="success",
        value="test_value",
        timestamp=datetime.utcnow(),
    )
    assert status.name == "test_source"
    assert status.status == "success"
    
    # Test to_dict
    d = status.to_dict()
    assert d['name'] == "test_source"
    assert d['status'] == "success"
    print("✓ SourceStatus tests passed")


def test_context_snapshot():
    """Test ContextSnapshot dataclass."""
    snapshot = ContextSnapshot(
        signal_id="sig_123",
        session_id="sess_456",
    )
    
    assert snapshot.signal_id == "sig_123"
    assert snapshot.session_id == "sess_456"
    assert snapshot.confidence_adjustment == 1.0
    assert len(snapshot.gaps) == 0
    
    # Test to_dict
    d = snapshot.to_dict()
    assert d['signal_id'] == "sig_123"
    print("✓ ContextSnapshot tests passed")


def test_context_snapshot_roundtrip():
    """Test ContextSnapshot serialization/deserialization."""
    # Create snapshot with data
    status = SourceStatus(
        name="market_price",
        status="success",
        value=2.85,
        timestamp=datetime.utcnow(),
    )
    
    snapshot = ContextSnapshot(
        signal_id="sig_123",
        session_id="sess_456",
    )
    snapshot.sources_status['market_price'] = status
    snapshot.gaps.append("test_gap")
    
    # Serialize
    d = snapshot.to_dict()
    
    # Deserialize
    restored = ContextSnapshot.from_dict(d)
    
    assert restored.signal_id == "sig_123"
    assert restored.session_id == "sess_456"
    assert 'market_price' in restored.sources_status
    assert len(restored.gaps) == 1
    print("✓ ContextSnapshot roundtrip tests passed")


def test_database_context_loader_initialization():
    """Test DatabaseContextLoader can be initialized."""
    loader = DatabaseContextLoader(db_path="data/metis.db")
    assert loader.db_path == "data/metis.db"
    assert loader.connection is None  # Lazy connection
    
    # Test static format methods
    row = {
        'timestamp': '2026-02-16 10:00',
        'storage_bcf': 1847.5,
    }
    doc = loader._format_eia_document(row)
    assert '[EIA Storage Snapshot' in doc
    assert '1847.5' in doc
    
    print("✓ DatabaseContextLoader initialization tests passed")


async def test_async_context_loading():
    """Test async context loading (will use real or empty DB)."""
    loader = DatabaseContextLoader(db_path="data/metis.db")
    
    # Test async methods exist and return proper types
    price, status = await loader.get_market_price_recent(days=1)
    assert isinstance(status, str)
    assert status in ['success', 'not_found', 'failure: FileNotFoundError']
    
    docs, status = await loader.get_eia_storage_recent(days=30)
    assert isinstance(docs, list)
    assert isinstance(status, str)
    
    print("✓ Async context loading tests passed")


async def test_session_context_manager():
    """Test SessionContextManager initialization and basic operations."""
    manager = SessionContextManager(db_path="data/metis.db")
    assert manager.context_dir.exists()
    
    # Test get_or_create_snapshot
    # (This will work even with empty DB - just returns empty data)
    snapshot = await manager.get_or_create_snapshot(
        signal_id="sig_test",
        session_id="sess_test"
    )
    
    assert snapshot.signal_id == "sig_test"
    assert snapshot.session_id == "sess_test"
    assert isinstance(snapshot.sources_status, dict)
    
    # Test caching - second call should return cached
    snapshot2 = await manager.get_or_create_snapshot(
        signal_id="sig_test",
        session_id="sess_test"
    )
    assert snapshot2.snapshot_id == snapshot.snapshot_id
    
    # Test cache clearing
    manager.clear_session_cache("sess_test")
    
    # Test cleanup
    manager.close()
    
    print("✓ SessionContextManager tests passed")


async def main():
    """Run all tests."""
    print("\n=== Testing Phase 1 Implementation ===\n")
    
    # Synchronous tests
    test_source_status()
    test_context_snapshot()
    test_context_snapshot_roundtrip()
    test_database_context_loader_initialization()
    
    # Async tests
    await test_async_context_loading()
    await test_session_context_manager()
    
    print("\n=== All Phase 1 Tests Passed ===\n")


if __name__ == "__main__":
    asyncio.run(main())

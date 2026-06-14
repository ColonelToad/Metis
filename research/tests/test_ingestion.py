"""
Basic tests for Metis data ingestion pipeline.
Validates that ingesters can be imported and have required functions.
"""
import sys
from pathlib import Path

# Add research directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest


class TestIngesters:
    """Test that data ingestion modules are importable and functional."""
    
    def test_eia_ingester_exists(self):
        """Test that EIA ingester module can be imported."""
        try:
            from data_ingest import ingest_eia
            assert hasattr(ingest_eia, 'main') or hasattr(ingest_eia, 'fetch_eia_data')
        except ImportError:
            pytest.skip("EIA module dependencies not installed")
    
    def test_fred_ingester_exists(self):
        """Test that FRED ingester module can be imported."""
        try:
            from data_ingest import ingest_fred
            assert hasattr(ingest_fred, 'main') or hasattr(ingest_fred, 'fetch_fred_data')
        except ImportError:
            pytest.skip("FRED module dependencies not installed")
    
    def test_congress_bills_ingester_exists(self):
        """Test that Congress bills ingester module can be imported."""
        try:
            from data_ingest import ingest_congress_bills_expanded
            assert hasattr(ingest_congress_bills_expanded, 'main')
        except ImportError:
            pytest.skip("Congress module dependencies not installed")
    
    def test_bls_ppi_ingester_exists(self):
        """Test that BLS PPI ingester module can be imported."""
        try:
            from data_ingest import ingest_bls_ppi
            assert hasattr(ingest_bls_ppi, 'main')
        except ImportError:
            pytest.skip("BLS module dependencies not installed")
    
    def test_census_permits_ingester_exists(self):
        """Test that Census permits ingester module can be imported."""
        try:
            from data_ingest import ingest_census_building_permits
            assert hasattr(ingest_census_building_permits, 'main')
        except ImportError:
            pytest.skip("Census module dependencies not installed")


class TestPipeline:
    """Test feature engineering pipeline."""
    
    def test_feature_engineer_imports(self):
        """Test that feature engineering module can be imported."""
        try:
            from features import engineer_features
            assert hasattr(engineer_features, 'FeatureEngineer')
        except ImportError:
            pytest.skip("Feature engineering dependencies not installed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

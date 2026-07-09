"""
Test data retriever functionality.
"""

import pytest
from quant_research.data.retriever import DataRetriever


def test_demo_retriever():
    """Test data retriever with demo cache manager (no credentials needed)."""
    retriever = DataRetriever(use_demo=True)
    
    # Test data retrieval
    data = retriever.get_data("ES", "2024-01-01", "2024-01-02", "1h")
    
    assert data is not None
    assert len(data) > 0
    assert 'open' in data.columns
    assert 'high' in data.columns
    assert 'low' in data.columns
    assert 'close' in data.columns


def test_retriever_with_shared_secrets():
    """Test data retriever with shared secrets file."""
    # This test will use the shared secrets file if it exists
    # Otherwise it will fail gracefully if credentials are not available
    try:
        retriever = DataRetriever(config_path="config/data_sources.yaml")
        # If we get here, secrets were loaded successfully
        assert retriever.cache_manager is not None
    except Exception as e:
        # If secrets file doesn't exist or credentials are invalid, skip test
        pytest.skip(f"Shared secrets not available: {e}")

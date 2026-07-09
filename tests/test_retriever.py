"""
Test data retriever functionality.
"""

import pytest
from quant_research.data.retriever import DataRetriever


def test_demo_retriever():
    """Test data retriever with demo cache manager."""
    retriever = DataRetriever(use_demo=True)
    
    # Test data retrieval
    data = retriever.get_data("ES", "2024-01-01", "2024-01-02", "1h")
    
    assert data is not None
    assert len(data) > 0
    assert 'open' in data.columns
    assert 'high' in data.columns
    assert 'low' in data.columns
    assert 'close' in data.columns

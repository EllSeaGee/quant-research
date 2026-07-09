"""
Data retriever module for fetching market data using the cache manager.
"""

from pathlib import Path
from typing import Optional, Union
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from tradingcore.factory import build_cache_manager, build_demo_cache_manager


class DataRetriever:
    """Wrapper for CacheManager to simplify data retrieval for research."""
    
    def __init__(self, config_path: Optional[Union[str, Path]] = None, 
                 use_demo: bool = False, secrets_path: Optional[Union[str, Path]] = None):
        """
        Initialize data retriever.
        
        Parameters
        ----------
        config_path : str | Path | None
            Path to cache manager configuration file
        use_demo : bool
            If True, use demo cache manager for testing
        secrets_path : str | Path | None
            Path to secrets file (e.g., authvars.env). If None, uses default
            C:\Users\hotst\Projects\.secrets\authvars.env
        """
        # Load environment variables from secrets file
        if secrets_path is None:
            # Default to the shared secrets file
            secrets_path = Path(r"C:\Users\hotst\Projects\.secrets\authvars.env")
        else:
            secrets_path = Path(secrets_path)
        
        if secrets_path.exists():
            load_dotenv(secrets_path)
        
        if use_demo:
            self.cache_manager = build_demo_cache_manager()
        else:
            self.cache_manager = build_cache_manager(config_path)
    
    def get_data(self, symbol: str, start: Union[str, datetime], 
                 end: Union[str, datetime], freq: str = "1h",
                 source: str = "databento") -> pd.DataFrame:
        """
        Retrieve market data for a symbol.
        
        Parameters
        ----------
        symbol : str
            Market symbol (e.g., "ES", "NQ")
        start, end : str | datetime
            Date range for data retrieval
        freq : str
            Data frequency ("1h", "5m", "1d", etc.)
        source : str
            Data source identifier
            
        Returns
        -------
        pd.DataFrame
            OHLCV data for the requested range
        """
        return self.cache_manager.get_data(
            symbol=symbol,
            start=start,
            end=end,
            freq=freq,
            source=source
        )

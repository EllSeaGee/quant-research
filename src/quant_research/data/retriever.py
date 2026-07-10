"""
Data retriever module for fetching market data using the cache manager.
"""

from pathlib import Path
from typing import Optional, Union
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv

# Load shared secrets BEFORE importing tradingcore modules
# This ensures environment variables are available when config_loader.py calls load_dotenv()
_default_secrets_path = Path(r"C:\Users\hotst\Projects\.secrets\authvars.env")
if _default_secrets_path.exists():
    load_dotenv(_default_secrets_path)

# Now import tradingcore modules (config_loader will see the loaded environment variables)
from tradingcore.factory import build_cache_manager, build_demo_cache_manager


class DataRetriever:
    """Wrapper for CacheManager to simplify data retrieval for research."""
    
    def __init__(self, config_path: Optional[Union[str, Path]] = None, 
                 use_demo: bool = False, secrets_path: Optional[Union[str, Path]] = None):
        r"""
        Initialize data retriever.
        
        Parameters
        ----------
        config_path : str | Path | None
            Path to cache manager configuration file
        use_demo : bool
            If True, use demo cache manager for testing
        secrets_path : str | Path | None
            Path to secrets file (e.g., authvars.env). If None, uses default
            C:\Users\hotst\Projects\.secrets\authvars.env. Note: The default
            secrets file is loaded at module import time, so this parameter
            is only needed if you want to use a different secrets file.
        """
        # Load custom secrets file if provided (different from default)
        if secrets_path is not None:
            custom_secrets_path = Path(secrets_path)
            if custom_secrets_path.exists():
                load_dotenv(custom_secrets_path)
        
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

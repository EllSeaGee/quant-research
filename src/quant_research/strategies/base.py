"""
Base strategy class for defining trading strategies.
"""

from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any


class BaseStrategy(ABC):
    """Abstract base class for trading strategies."""
    
    def __init__(self, name: str, params: Dict[str, Any] = None):
        """
        Initialize strategy.
        
        Parameters
        ----------
        name : str
            Strategy name
        params : dict
            Strategy parameters
        """
        self.name = name
        self.params = params or {}
    
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trading signals from market data.
        
        Parameters
        ----------
        data : pd.DataFrame
            OHLCV market data
            
        Returns
        -------
        pd.DataFrame
            Data with added signal columns
        """
        pass
    
    @abstractmethod
    def calculate_positions(self, signals: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate positions from signals.
        
        Parameters
        ----------
        signals : pd.DataFrame
            Data with signals
            
        Returns
        -------
        pd.DataFrame
            Data with position information
        """
        pass

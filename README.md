# Quantitative Research Framework

A Python framework for developing and testing trading strategies using market data from the trading_core_utils cache manager.

## Features

- **Data Retrieval**: Seamless integration with trading_core_utils cache manager
- **Strategy Development**: Base classes for defining custom trading strategies
- **Backtesting**: Framework for strategy evaluation (coming soon)
- **Analysis**: Performance metrics and evaluation tools (coming soon)

## Installation

### Prerequisites

- Python 3.10+
- trading_core_utils package (installed separately)

### Setup

1. Clone this repository:
```bash
git clone <repository-url>
cd quant_research
```

2. Create virtual environment:
```bash
python -m venv .venv
.venv\Scripts\activate  # On Windows
source .venv/bin/activate  # On Unix
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install trading_core_utils:
```bash
cd path/to/trading_core_utils
pip install -e .
```

5. Configure environment:
```bash
# The project uses shared credentials from C:\Users\hotst\Projects\.secrets\authvars.env
# No local .env file is required unless you want to override specific values
# If you need local overrides, create a .env file:
cp .env.example .env
# Edit .env with any local overrides
```

## Usage

### Basic Data Retrieval

```python
from quant_research.data import DataRetriever

# Use demo data for testing (no credentials required)
retriever = DataRetriever(use_demo=True)
data = retriever.get_data("ES", "2024-01-01", "2024-01-31", "1h")

# Use production data (automatically loads shared credentials)
retriever = DataRetriever(config_path="config/data_sources.yaml")
data = retriever.get_data("ES", "2024-01-01", "2024-01-31", "1h", source="databento")
```

**Note:** The DataRetriever automatically loads credentials from `C:\Users\hotst\Projects\.secrets\authvars.env` at module import time. This ensures the trading_core_utils config loader can access the credentials when it interpolates environment variables in the configuration.

### Strategy Development

```python
from quant_research.strategies import BaseStrategy
import pandas as pd

class MyStrategy(BaseStrategy):
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        # Implement signal generation logic
        data['signal'] = 0  # Placeholder
        return data
    
    def calculate_positions(self, signals: pd.DataFrame) -> pd.DataFrame:
        # Implement position sizing logic
        signals['position'] = 0  # Placeholder
        return signals
```

## Project Structure

```
quant_research/
├── config/              # Configuration files
├── src/quant_research/  # Source code
│   ├── data/           # Data retrieval
│   ├── strategies/     # Trading strategies
│   ├── backtest/      # Backtesting engine
│   └── analysis/      # Performance analysis
├── tests/              # Tests
├── notebooks/          # Jupyter notebooks
└── docs/              # Documentation
```

## Testing

Run tests with pytest:
```bash
pytest tests/ -v
```

## License

[Your License Here]

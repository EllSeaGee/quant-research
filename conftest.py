"""Pytest bootstrap: put the src-layout package on sys.path.

The package uses a src/ layout and is not installed (its declared dependency
``tradingcore`` is environment-specific). Adding ``src`` here lets the test
suite import ``quant_research`` without an editable install.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

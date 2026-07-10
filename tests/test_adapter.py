"""Phase 0 — adapter returns ascending bars inclusive of bounds and NOTHING
beyond end_index (the no-look-ahead boundary, convention 2)."""

from quant_research.setups.adapter import (
    CacheManagerBarProvider,
    InMemoryBarProvider,
    bars_from_dataframe,
)
from quant_research.setups.contract import Bar


def _series(n=100):
    return [Bar(bar_index=i, timestamp=f"t{i}", open=100.0, high=101.0,
               low=99.0, close=100.5, volume=10.0) for i in range(n)]


def test_inclusive_bounds():
    p = InMemoryBarProvider({("ES", "1d"): _series(100)})
    bars = p.get_bars("ES", "1d", 10, 20)
    assert [b.bar_index for b in bars] == list(range(10, 21))  # inclusive both ends


def test_no_bars_beyond_end_index():
    p = InMemoryBarProvider({("ES", "1d"): _series(100)})
    bars = p.get_bars("ES", "1d", None, 42)
    assert bars[-1].bar_index == 42  # exactly end_index, nothing after
    assert all(b.bar_index <= 42 for b in bars)


def test_ascending_and_start_open_bound():
    # shuffle input; provider must return ascending
    import random
    s = _series(50)
    random.Random(0).shuffle(s)
    p = InMemoryBarProvider({("ES", "1d"): s})
    bars = p.get_bars("ES", "1d", 5, None)
    idx = [b.bar_index for b in bars]
    assert idx == sorted(idx)
    assert idx[0] == 5 and idx[-1] == 49


def test_unknown_key_returns_empty():
    p = InMemoryBarProvider()
    assert p.get_bars("XX", "1d", 0, 10) == []


def test_end_index_mid_series_exact_last():
    p = InMemoryBarProvider({("ES", "1d"): _series(100)})
    bars = p.get_bars("ES", "1d", 0, 63)
    assert len(bars) == 64
    assert bars[-1].bar_index == 63


# --- CacheManagerBarProvider maps a DataFrame-like source, enforces bound ---

class _FakeFrame:
    """Minimal DataFrame stand-in: columns + iterrows + sort_index, no pandas."""
    def __init__(self, rows):
        # rows: list[(ts, dict)]
        self._rows = rows
        self.columns = ["Open", "High", "Low", "Close", "Volume"]

    def sort_index(self):
        return _FakeFrame(sorted(self._rows, key=lambda r: r[0]))

    def iterrows(self):
        for ts, d in self._rows:
            yield ts, d


class _FakeRetriever:
    def __init__(self, frame):
        self._frame = frame

    def get_data(self, symbol, start, end, freq, source):
        return self._frame


def test_bars_from_dataframe_positional_index():
    rows = [(f"2024-01-{i+1:02d}", {"Open": 1.0 + i, "High": 2.0 + i,
             "Low": 0.5 + i, "Close": 1.5 + i, "Volume": 100.0 + i})
            for i in range(5)]
    frame = _FakeFrame(rows)
    bars = bars_from_dataframe(frame)
    assert [b.bar_index for b in bars] == [0, 1, 2, 3, 4]
    assert bars[2].open == 3.0 and bars[2].close == 3.5


def test_cache_provider_enforces_end_index():
    rows = [(f"2024-01-{i+1:02d}", {"Open": 1.0, "High": 2.0, "Low": 0.5,
             "Close": 1.5, "Volume": 100.0}) for i in range(30)]
    prov = CacheManagerBarProvider(_FakeRetriever(_FakeFrame(rows)),
                                   start="2024-01-01", end="2024-02-01")
    bars = prov.get_bars("ES", "1d", 5, 12)
    assert [b.bar_index for b in bars] == list(range(5, 13))
    assert bars[-1].bar_index == 12

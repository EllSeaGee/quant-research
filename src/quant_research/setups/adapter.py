"""Bind the :class:`BarSeriesProvider` Protocol to bar sources.

Implementation Plan convention 2: the detector never imports the cache manager
directly — it depends only on ``BarSeriesProvider`` (Contract section 6.2). This
adapter is the thin binding written after inspecting the real cache manager.

The single most important guarantee here is the no-look-ahead boundary:
``get_bars`` MUST NOT return any bar beyond the requested ``end_index``. This is
enforced defensively in every provider, because it is the first line of defence
against look-ahead (convention 2).

Two providers are supplied:

* :class:`InMemoryBarProvider` — a pure in-memory provider over an explicit list
  of :class:`~quant_research.setups.contract.Bar`. Used by the synthetic golden
  fixtures and the causal test suite (Phases 0-1 use synthetic data).
* :class:`CacheManagerBarProvider` — binds the Protocol to the project's real
  cache manager (via :class:`quant_research.data.retriever.DataRetriever`). It
  maps the cache manager's timestamp-indexed OHLCV frame to contract ``Bar``
  objects, assigning ``bar_index`` positionally within the retrieved series.
  ``pandas`` / ``tradingcore`` are imported lazily so this module (and the
  synthetic test suite) load without those heavy dependencies present.
"""

from bisect import bisect_left, bisect_right
from typing import Sequence

from .contract import Bar


def _clip_to_bounds(bars: Sequence[Bar], start_index: int | None,
                    end_index: int | None) -> list[Bar]:
    """Return the ascending sub-sequence with start_index <= bar_index <= end_index
    (inclusive). Bars are assumed ascending and contiguous-or-sparse by bar_index.

    This is the no-look-ahead enforcement point: nothing past ``end_index`` is
    ever returned, regardless of what the underlying source holds.
    """
    indices = [b.bar_index for b in bars]
    lo = 0 if start_index is None else bisect_left(indices, start_index)
    hi = len(bars) if end_index is None else bisect_right(indices, end_index)
    return list(bars[lo:hi])


class InMemoryBarProvider:
    """A ``BarSeriesProvider`` backed by an explicit in-memory bar list.

    Bars are keyed by (symbol, timeframe). The provider stores them ascending by
    ``bar_index`` and enforces inclusive-bounds slicing with no look-ahead.
    """

    def __init__(self, bars_by_key: dict[tuple[str, str], Sequence[Bar]] | None = None):
        self._bars: dict[tuple[str, str], list[Bar]] = {}
        if bars_by_key:
            for key, bars in bars_by_key.items():
                self.set_bars(key[0], key[1], bars)

    def set_bars(self, symbol: str, timeframe: str, bars: Sequence[Bar]) -> None:
        ordered = sorted(bars, key=lambda b: b.bar_index)
        self._bars[(symbol, timeframe)] = ordered

    def get_bars(self, symbol: str, timeframe: str,
                 start_index: int | None, end_index: int | None) -> Sequence[Bar]:
        bars = self._bars.get((symbol, timeframe), [])
        return _clip_to_bounds(bars, start_index, end_index)


class CacheManagerBarProvider:
    """Binds ``BarSeriesProvider`` to the real cache manager.

    The cache manager is timestamp-indexed; the contract is ``bar_index``-indexed.
    This provider retrieves the symbol's OHLCV frame for a fixed date range once,
    assigns ``bar_index`` positionally (0..N-1 ascending by timestamp), and slices
    by inclusive integer bounds. ``end_index`` truncation is enforced here too.

    Parameters
    ----------
    retriever:
        A ``DataRetriever``-like object exposing ``get_data(symbol, start, end,
        freq, source)`` returning an OHLCV DataFrame (columns open/high/low/close,
        optional volume; timestamp index).
    start, end, source:
        Passed through to ``get_data`` on first access per (symbol, timeframe).
    """

    def __init__(self, retriever, start, end, source: str = "databento"):
        self._retriever = retriever
        self._start = start
        self._end = end
        self._source = source
        self._cache: dict[tuple[str, str], list[Bar]] = {}

    def _load(self, symbol: str, timeframe: str) -> list[Bar]:
        key = (symbol, timeframe)
        if key not in self._cache:
            df = self._retriever.get_data(
                symbol=symbol, start=self._start, end=self._end,
                freq=timeframe, source=self._source,
            )
            self._cache[key] = bars_from_dataframe(df)
        return self._cache[key]

    def get_bars(self, symbol: str, timeframe: str,
                 start_index: int | None, end_index: int | None) -> Sequence[Bar]:
        bars = self._load(symbol, timeframe)
        return _clip_to_bounds(bars, start_index, end_index)


def bars_from_dataframe(df) -> list[Bar]:
    """Map a cache-manager OHLCV DataFrame to contract ``Bar`` objects.

    ``bar_index`` is the positional row number (0-based, ascending by index);
    ``timestamp`` is the ISO-8601 string of the row's index. Column names are
    matched case-insensitively against open/high/low/close/volume. ``pandas`` is
    imported lazily.
    """
    # Local import: pandas is a declared dependency but this keeps the module
    # importable (and the synthetic test suite runnable) without it installed.
    cols = {c.lower(): c for c in df.columns}
    required = ("open", "high", "low", "close")
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError(f"DataFrame missing required OHLC columns: {missing}")
    has_volume = "volume" in cols

    bars: list[Bar] = []
    df_sorted = df.sort_index()
    for i, (ts, row) in enumerate(df_sorted.iterrows()):
        bars.append(Bar(
            bar_index=i,
            timestamp=str(ts),
            open=float(row[cols["open"]]),
            high=float(row[cols["high"]]),
            low=float(row[cols["low"]]),
            close=float(row[cols["close"]]),
            volume=float(row[cols["volume"]]) if has_volume else None,
        ))
    return bars

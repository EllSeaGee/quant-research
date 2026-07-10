"""Causal primitives shared by the detector and boundary constructor.

Everything here is a pure function of bars and is strictly causal: given a
window of bars, it uses only those bars. The strength-N pivot, True Range, and
ATR definitions follow Detector Spec v1 sections 3 and 7. These are defined once
because impulse endpoints, minor pivots, and trend segmentation all rest on the
same pivot primitive (Detector Spec section 3).

Bars are addressed by their canonical ``bar_index`` (not list position). Helper
lookups build an index map so callers can pass any ascending, contiguous window.
"""

from typing import Sequence

from .contract import Bar


def index_map(bars: Sequence[Bar]) -> dict[int, int]:
    """Map bar_index -> list position for an ascending bar window."""
    return {b.bar_index: i for i, b in enumerate(bars)}


def true_range(bar: Bar, prev_close: float | None) -> float:
    """Gap-absorbing True Range (Detector Spec section 7, FROZEN method choice):
    max(high-low, |high-prev_close|, |low-prev_close|). Uses only this bar and the
    previous close. If prev_close is None (no prior bar), falls back to high-low."""
    hl = bar.high - bar.low
    if prev_close is None:
        return hl
    return max(hl, abs(bar.high - prev_close), abs(bar.low - prev_close))


def true_range_series(bars: Sequence[Bar]) -> list[float]:
    """TR for each bar in an ascending, contiguous window, using the immediately
    preceding bar's close as prev_close (first bar uses high-low)."""
    out: list[float] = []
    prev_close: float | None = None
    for b in bars:
        out.append(true_range(b, prev_close))
        prev_close = b.close
    return out


def atr_ending_at(bars: Sequence[Bar], t: int, period: int) -> float:
    """Simple-average ATR over the ``period`` bars ending at bar_index ``t``,
    using only bars with bar_index <= t. Causal at t.

    The averaging convention is the simple mean of True Range (a VALUE; 14 is the
    provisional period, Detector Spec section 7). TR needs the prior bar's close,
    so the window silently extends one bar back for the prev_close of its first
    bar when available.
    """
    imap = index_map(bars)
    if t not in imap:
        raise ValueError(f"bar_index {t} not present in window")
    pos = imap[t]
    # bars for which we want TR: the `period` bars ending at t
    first_pos = max(0, pos - period + 1)
    window = bars[first_pos:pos + 1]
    # prev_close for the first bar in window, if a prior bar exists
    prev_close = bars[first_pos - 1].close if first_pos - 1 >= 0 else None
    trs: list[float] = []
    pc = prev_close
    for b in window:
        trs.append(true_range(b, pc))
        pc = b.close
    return sum(trs) / len(trs) if trs else 0.0


def mean_true_range_between(bars: Sequence[Bar], start_index: int, t: int) -> float:
    """Mean True Range of the pullback bars from ``start_index`` through ``t``
    inclusive (V(t), Detector Spec section 8.3). The first pullback bar's TR uses
    the preceding bar's close (the impulse-end bar's close) as prev_close, which
    is known; causal at t."""
    imap = index_map(bars)
    if start_index not in imap or t not in imap:
        # tolerate start before window; clamp to available
        positions = [i for i, b in enumerate(bars) if start_index <= b.bar_index <= t]
    else:
        positions = list(range(imap[start_index], imap[t] + 1))
    if not positions:
        return 0.0
    trs: list[float] = []
    for p in positions:
        pc = bars[p - 1].close if p - 1 >= 0 else None
        trs.append(true_range(bars[p], pc))
    return sum(trs) / len(trs)


def is_pivot_high(bars: Sequence[Bar], pos: int, n: int) -> bool:
    """Bar at list position ``pos`` is a strength-N pivot high: strictly greater
    high than the N bars on each side (strict inequality — ties are not pivots,
    Detector Spec section 3). Requires N bars of context on each side."""
    if pos - n < 0 or pos + n >= len(bars):
        return False
    h = bars[pos].high
    for i in range(1, n + 1):
        if not (h > bars[pos - i].high and h > bars[pos + i].high):
            return False
    return True


def is_pivot_low(bars: Sequence[Bar], pos: int, n: int) -> bool:
    """Mirror of :func:`is_pivot_high` using lows and strict less-than."""
    if pos - n < 0 or pos + n >= len(bars):
        return False
    lo = bars[pos].low
    for i in range(1, n + 1):
        if not (lo < bars[pos - i].low and lo < bars[pos + i].low):
            return False
    return True

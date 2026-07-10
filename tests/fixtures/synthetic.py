"""Deterministic synthetic OHLC series with a known impulse-then-pullback.

Built by linear interpolation through price "control points" spaced ``SEG`` bars
apart, with a constant half-range so every control that is a local extreme of the
close path becomes a strength-2 pivot (strict inequality on each side). A flat
lead supplies enough pre-anchor history; a configurable post-region drives the
three terminal branches.

Geometry (LONG), by construction:
  * flat lead: bars 0..39 at 100 (no pivots — strict-inequality rejects flats)
  * rising staircase (higher highs + higher lows) -> non-null pullback_count
  * impulse_origin: pivot low 113 at bar 64
  * impulse_end:    pivot high 124 at bar 68
  * detection_bar = 70, entry_eligible_bar = 71
  * retracement_floor = 124 - (2/3)(124-113) = 116.6667
The post-region after the impulse determines TIMEOUT / INVALIDATED(floor) /
INVALIDATED(reclaim).
"""

from dataclasses import dataclass

from quant_research.setups.contract import Bar

SEG = 4
HALF = 0.4
LEAD = 40  # flat lead bars (indices 0..39)

# controls up to and including the impulse_end (shared by all variants)
_BASE_CONTROLS = [
    100,   # bar 40
    106,   # 44  H
    103,   # 48  L
    111,   # 52  H
    108,   # 56  L
    116,   # 60  H
    113,   # 64  L  <- impulse_origin
    124,   # 68  H  <- impulse_end
]

ORIGIN_BAR = 64
END_BAR = 68
ORIGIN_PRICE = 113.0
END_PRICE = 124.0
DETECTION_BAR = 70
ENTRY_ELIGIBLE_BAR = 71
FLOOR = END_PRICE - (2.0 / 3.0) * (END_PRICE - ORIGIN_PRICE)  # 116.6667

# post-regions (start after the 124@68 control; each control is +SEG bars)
_POST_TIMEOUT = [120, 122, 121, 123, 120, 122, 121, 122]           # 72..100, in-band
_POST_INVAL_FLOOR = [120, 110, 108, 112, 114, 113, 115, 114]        # dives below floor
_POST_INVAL_RECLAIM = [122, 126, 125, 127, 124, 126, 125, 126]      # reclaims 124


def _interp(controls, seg):
    closes = [float(controls[0])]
    for i in range(len(controls) - 1):
        a, b = float(controls[i]), float(controls[i + 1])
        for k in range(1, seg + 1):
            closes.append(a + (b - a) * k / seg)
    return closes


def _closes(post_controls):
    controls = _BASE_CONTROLS + list(post_controls)
    tail = _interp(controls, SEG)          # tail[0] sits at bar LEAD
    return [100.0] * LEAD + tail


def _bars_from_closes(closes, half=HALF):
    bars = []
    prev_close = closes[0]
    for i, c in enumerate(closes):
        bars.append(Bar(bar_index=i, timestamp=f"2020-01-01T00:00:{i:02d}Z",
                        open=prev_close, high=c + half, low=c - half,
                        close=c, volume=1000.0))
        prev_close = c
    return bars


@dataclass(frozen=True)
class SeriesMeta:
    origin_bar: int = ORIGIN_BAR
    end_bar: int = END_BAR
    origin_price: float = ORIGIN_PRICE
    end_price: float = END_PRICE
    detection_bar: int = DETECTION_BAR
    entry_eligible_bar: int = ENTRY_ELIGIBLE_BAR
    floor: float = FLOOR
    data_end_index: int = 0


def make_long_series(variant: str = "timeout") -> tuple[list[Bar], SeriesMeta]:
    """Return (bars, meta) for a LONG setup. variant in
    {'timeout','invalidated_floor','invalidated_reclaim'}."""
    post = {
        "timeout": _POST_TIMEOUT,
        "invalidated_floor": _POST_INVAL_FLOOR,
        "invalidated_reclaim": _POST_INVAL_RECLAIM,
    }[variant]
    closes = _closes(post)
    bars = _bars_from_closes(closes)
    return bars, SeriesMeta(data_end_index=bars[-1].bar_index)

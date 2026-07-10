"""ForwardPath recorder (Contract section 4) — uncensored.

Anchors each path at the config-independent ``entry_eligible_bar`` and records
``total_length == max_pending_window + horizon_H`` daily bars. NO stop / target /
exit logic may touch this module (Contract section 4, anti-default 1); the path is
the raw uncensored bar record from the anchor forward, and together with the
opening's ``pre_anchor_bars`` it forms the complete substrate the materializer
rebuilds geometry from (Contract section 2.1, 4).

``horizon_H`` is provisional (15-20 trading days + a fill-latency buffer, a VALUE
pending sign-off, Contract sections 4, 10); it is a config value flagged here.
"""

from dataclasses import dataclass
from typing import Sequence

from .contract import (
    BarSeriesProvider,
    ForwardPath,
    ForwardPathBar,
)


# provisional H (Contract section 4/10): 15-20 trading days + fill-latency buffer.
DEFAULT_HORIZON_H = 18  # [PROVISIONAL — sign-off]


@dataclass(frozen=True)
class PathRecorderParams:
    max_pending_window: int = 10
    horizon_H: int = DEFAULT_HORIZON_H


class PathRecorder:
    def __init__(self, params: PathRecorderParams | None = None):
        self.params = params or PathRecorderParams()

    def record(self, provider: BarSeriesProvider, symbol: str, timeframe: str,
               setup_id: str, entry_eligible_bar: int,
               data_end_index: int) -> ForwardPath:
        p = self.params
        total_length = p.max_pending_window + p.horizon_H
        last_wanted = entry_eligible_bar + total_length - 1
        # request only bars within [anchor, last_wanted]; the adapter enforces the
        # end_index bound, so nothing beyond last_wanted (or data_end) is returned.
        end = min(last_wanted, data_end_index)
        bars = list(provider.get_bars(symbol, timeframe, entry_eligible_bar, end))

        fp_bars = tuple(
            ForwardPathBar(
                bar_offset=b.bar_index - entry_eligible_bar,
                bar_index=b.bar_index,
                high=b.high,
                low=b.low,
                close=b.close,
                # daily-only v1: intraday fields stay None (convention 8)
                intraday_high=None,
                intraday_low=None,
            )
            for b in bars
        )
        truncated = len(fp_bars) < total_length
        return ForwardPath(
            setup_id=setup_id,
            anchor_bar=entry_eligible_bar,
            max_pending_window=p.max_pending_window,
            horizon_H=p.horizon_H,
            total_length=total_length,
            bars=fp_bars,
            truncated_by_data_end=truncated,
        )

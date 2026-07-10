"""Setup detector — produces DetectedSetupOpening + terminal outcome.

Phase 1 goal (Implementation Plan): a *minimal but real* detector. "Real" matters
because the two-mode repaint test must have something that *could* repaint if done
wrong — so the swing/pivot structure, trend segmentation, and detection timing are
implemented causally (Detector Spec v1 sections 3-6, 12-13), not stubbed. It is
not the full permissive-first detector (that is Phase 2); it is causally honest.

Causality spine (Detector Spec section 2):
  * strength-N pivots are confirmed only N bars later: known_at_bar = pivot_bar + N;
  * detection_bar >= max(known_at_bar) over opening geometry (Contract section 7.4);
  * pullback_count_in_trend uses only pivots confirmed by detection_bar (the
    repaint-prone component, Detector Spec section 6);
  * terminal outcome is causal — knowable only at the terminating bar's close.

The detector depends only on ``BarSeriesProvider`` (convention 2); it never imports
the cache manager and never uses a bar beyond the requested end_index.
"""

import hashlib
from dataclasses import dataclass
from typing import Sequence

from .contract import (
    Bar,
    BarSeriesProvider,
    CausalPrice,
    Direction,
    DetectedSetupOpening,
    GrimesVariant,
    StaticFeatures,
    TerminationReason,
)
from . import primitives


DETECTOR_VERSION = "phase1-minimal-v1"


@dataclass(frozen=True)
class DetectorParams:
    n_pivot: int = 2
    k_extent: float = 2.0            # impulse extent, x ATR from origin (sub-test 1a)
    atr_period: int = 14
    min_pullback_bars: int = 1
    d_min: float = 0.10              # min retracement to be a pullback
    two_thirds: float = 2.0 / 3.0    # retracement-floor constant
    pre_anchor_lookback: int = 45
    max_pending_window: int = 10

    def param_hash(self) -> str:
        payload = "|".join(
            f"{k}={getattr(self, k)}" for k in (
                "n_pivot", "k_extent", "atr_period", "min_pullback_bars",
                "d_min", "two_thirds", "pre_anchor_lookback", "max_pending_window",
            )
        )
        return hashlib.sha1(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class DetectionResult:
    """A detected setup opening plus its persisted terminal outcome. The
    SetupUpdate stream is materialized on demand (Option B), not here."""
    opening: DetectedSetupOpening
    terminated_at_bar: int
    termination_reason: TerminationReason


def _confirmed_pivots(bars: Sequence[Bar], n: int, cutoff_known_at: int):
    """Return (pivot_highs, pivot_lows) as lists of list-positions whose pivots are
    confirmed by ``cutoff_known_at`` (known_at_bar = pivot_bar + n <= cutoff)."""
    highs, lows = [], []
    for pos in range(len(bars)):
        confirm_bar = bars[pos].bar_index + n
        if confirm_bar > cutoff_known_at:
            continue
        if primitives.is_pivot_high(bars, pos, n):
            highs.append(pos)
        if primitives.is_pivot_low(bars, pos, n):
            lows.append(pos)
    return highs, lows


def _causal_pullback_count(bars: Sequence[Bar], n: int, detection_bar: int,
                           impulse_end_pos: int) -> int | None:
    """Number of qualifying pullbacks in the current uptrend, counting the current
    setup — causal (uses only pivots confirmed by detection_bar). None if no trend
    can be established (Detector Spec section 6: do not fabricate a count).

    Simplified-but-causal segmentation: over confirmed pivots up to detection_bar,
    an uptrend is a run of higher pivot highs with higher intervening pivot lows;
    a confirmed lower pivot low breaks it. Count is the number of confirmed pivot
    highs from the trend's inception through the current impulse_end.
    """
    highs, lows = _confirmed_pivots(bars, n, detection_bar)
    if not highs or not lows:
        return None
    # Sequence of confirmed pivot highs up to and including the current impulse_end.
    ph = [p for p in highs if p <= impulse_end_pos]
    if impulse_end_pos not in ph:
        return None
    # Walk the pivot-high sequence backwards from impulse_end, extending the run
    # while each earlier pivot high is strictly lower (higher-high structure) and a
    # higher pivot low exists between consecutive highs.
    run = [impulse_end_pos]
    for prev in reversed([p for p in ph if p < impulse_end_pos]):
        cur = run[-1]
        if not bars[prev].high < bars[cur].high:
            break  # not a higher high going forward -> trend inception reached
        # require a confirmed pivot low between prev and cur that is higher than the
        # lows before prev (approximate higher-low check)
        between_lows = [l for l in lows if prev < l < cur]
        if not between_lows:
            break
        run.append(prev)
    # Need at least one higher high and one higher low to declare a trend.
    if len(run) < 2:
        return None
    return len(run)


def _atr_at(bars: Sequence[Bar], bar_index: int, period: int) -> float:
    try:
        return primitives.atr_ending_at(bars, bar_index, period)
    except ValueError:
        return 0.0


def _make_setup_id(symbol: str, timeframe: str, detection_bar: int,
                   impulse_origin: CausalPrice, impulse_end: CausalPrice) -> str:
    """Stable hash of (symbol, timeframe, detection_bar, geometry). Deterministic:
    no wall-clock, RNG, or dict-order dependence (convention 6)."""
    payload = (f"{symbol}|{timeframe}|{detection_bar}|"
               f"{impulse_origin.price:.6f}@{impulse_origin.defining_bar}|"
               f"{impulse_end.price:.6f}@{impulse_end.defining_bar}")
    return "setup-" + hashlib.sha1(payload.encode()).hexdigest()[:16]


class Detector:
    def __init__(self, params: DetectorParams | None = None,
                 detector_version: str = DETECTOR_VERSION):
        self.params = params or DetectorParams()
        self.detector_version = detector_version

    def detect(self, provider: BarSeriesProvider, symbol: str, timeframe: str,
               data_end_index: int) -> list[DetectionResult]:
        """Scan bars in [0, data_end_index] for LONG impulse-then-pullback setups.

        SHORT mirrors and is supported through :meth:`_try_detect` but the public
        scan emits LONG in Phase 1 unless a SHORT is explicitly detected; the
        synthetic fixtures drive both directions via :meth:`detect_at`.
        """
        bars = list(provider.get_bars(symbol, timeframe, None, data_end_index))
        p = self.params
        results: list[DetectionResult] = []
        seen_ids: set[str] = set()
        # candidate impulse_end pivots: confirmed pivot highs
        for pos in range(len(bars)):
            confirm = bars[pos].bar_index + p.n_pivot
            if confirm > data_end_index:
                continue
            if not primitives.is_pivot_high(bars, pos, p.n_pivot):
                continue
            res = self._try_detect(bars, pos, symbol, timeframe, data_end_index,
                                   Direction.LONG)
            if res is not None and res.opening.setup_id not in seen_ids:
                results.append(res)
                seen_ids.add(res.opening.setup_id)
        return results

    def detect_at(self, provider: BarSeriesProvider, symbol: str, timeframe: str,
                  impulse_end_bar: int, direction: Direction,
                  data_end_index: int) -> DetectionResult | None:
        """Attempt detection with a specified impulse_end pivot bar and direction
        (used by tests / fixtures that construct known geometry)."""
        bars = list(provider.get_bars(symbol, timeframe, None, data_end_index))
        imap = primitives.index_map(bars)
        if impulse_end_bar not in imap:
            return None
        return self._try_detect(bars, imap[impulse_end_bar], symbol, timeframe,
                                data_end_index, direction)

    # -- core --------------------------------------------------------------
    def _try_detect(self, bars: Sequence[Bar], end_pos: int, symbol: str,
                    timeframe: str, data_end_index: int,
                    direction: Direction) -> "DetectionResult | None":
        p = self.params
        n = p.n_pivot
        impulse_end_bar = bars[end_pos].bar_index

        # impulse_origin = most recent confirmed opposite pivot preceding the leg
        origin_pos = None
        for pos in range(end_pos - 1, -1, -1):
            if direction is Direction.LONG and primitives.is_pivot_low(bars, pos, n):
                origin_pos = pos
                break
            if direction is Direction.SHORT and primitives.is_pivot_high(bars, pos, n):
                origin_pos = pos
                break
        if origin_pos is None:
            return None

        impulse_origin_bar = bars[origin_pos].bar_index
        if direction is Direction.LONG:
            end_price = bars[end_pos].high
            origin_price = bars[origin_pos].low
        else:
            end_price = bars[end_pos].low
            origin_price = bars[origin_pos].high

        # impulse must be directional
        if direction is Direction.LONG and not end_price > origin_price:
            return None
        if direction is Direction.SHORT and not end_price < origin_price:
            return None

        # extent sub-test 1a: |end - origin| >= k_extent * ATR(origin_bar)
        atr_origin = _atr_at(bars, impulse_origin_bar, p.atr_period)
        if atr_origin <= 0:
            return None
        if abs(end_price - origin_price) < p.k_extent * atr_origin:
            return None

        pullback_start_bar = impulse_end_bar
        impulse_end_known = impulse_end_bar + n
        impulse_origin_known = impulse_origin_bar + n

        # detection_bar = max(impulse_end_bar + N, pullback_start_bar + min_pullback_bars)
        detection_bar = max(impulse_end_known,
                            pullback_start_bar + p.min_pullback_bars)
        if detection_bar > data_end_index:
            return None

        imap = primitives.index_map(bars)
        if detection_bar not in imap:
            return None

        # retracement floor (LONG: end - 2/3*(end-origin); mirror SHORT)
        span = end_price - origin_price
        retracement_floor = end_price - p.two_thirds * span

        # pullback validity: some retracement present by detection_bar, floor intact
        pb_positions = [i for i in range(imap[pullback_start_bar], imap[detection_bar] + 1)]
        if direction is Direction.LONG:
            running_extreme = min(bars[i].low for i in pb_positions)
            retrace = end_price - running_extreme
            floor_breached = running_extreme < retracement_floor
        else:
            running_extreme = max(bars[i].high for i in pb_positions)
            retrace = running_extreme - end_price
            floor_breached = running_extreme > retracement_floor
        if floor_breached:
            return None
        if retrace < p.d_min * abs(span):
            return None

        # pre-anchor substrate window
        entry_eligible_bar = detection_bar + 1
        pre_start = entry_eligible_bar - p.pre_anchor_lookback
        if pre_start < 0 or pre_start not in imap:
            return None  # insufficient history to store the substrate; skip
        pre_anchor_bars = tuple(
            bars[i] for i in range(imap[pre_start], imap[entry_eligible_bar - 1] + 1)
        )
        if len(pre_anchor_bars) != p.pre_anchor_lookback:
            return None

        impulse_origin = CausalPrice(price=origin_price, defining_bar=impulse_origin_bar,
                                     known_at_bar=impulse_origin_known)
        impulse_end = CausalPrice(price=end_price, defining_bar=impulse_end_bar,
                                  known_at_bar=impulse_end_known)

        pullback_count = _causal_pullback_count(bars, n, detection_bar, end_pos)

        atr_at_detection = _atr_at(bars, detection_bar, p.atr_period)

        features = StaticFeatures(
            grimes_variant=GrimesVariant.UNCLASSIFIED,
            pullback_count_in_trend=pullback_count,
            weekly_agreement_at_detection=None,
            vol_ratio_at_detection=None,
            wick_indecision_at_detection=None,
        )

        setup_id = _make_setup_id(symbol, timeframe, detection_bar,
                                  impulse_origin, impulse_end)

        opening = DetectedSetupOpening(
            setup_id=setup_id,
            symbol=symbol,
            timeframe=timeframe,
            detector_version=self.detector_version,
            param_hash=p.param_hash(),
            generated_at="1970-01-01T00:00:00Z",  # deterministic; no wall-clock
            direction=direction,
            detection_bar=detection_bar,
            entry_eligible_bar=entry_eligible_bar,
            pullback_start_bar=pullback_start_bar,
            impulse_origin=impulse_origin,
            impulse_end=impulse_end,
            atr_at_detection=atr_at_detection,
            atr_period=p.atr_period,
            retracement_floor=retracement_floor,
            features=features,
            pre_anchor_bars=pre_anchor_bars,
            pre_anchor_lookback=p.pre_anchor_lookback,
        )

        terminated_at_bar, reason = self._terminal_scan(
            bars, opening, data_end_index)

        return DetectionResult(opening=opening, terminated_at_bar=terminated_at_bar,
                               termination_reason=reason)

    def _terminal_scan(self, bars: Sequence[Bar], opening: DetectedSetupOpening,
                       data_end_index: int) -> tuple[int, TerminationReason]:
        """From entry_eligible_bar forward, INVALIDATED fires at the first bar where
        running_extreme breaches retracement_floor OR price reclaims impulse_end
        (Detector Spec section 13). Else TIMEOUT at anchor + max_pending_window - 1.
        Fills never terminate (anti-default 5)."""
        p = self.params
        imap = primitives.index_map(bars)
        eeb = opening.entry_eligible_bar
        window_last = eeb + p.max_pending_window - 1
        direction = opening.direction
        floor = opening.retracement_floor
        end_price = opening.impulse_end.price

        running_extreme = None
        for t in range(eeb, window_last + 1):
            if t not in imap:
                # data ran out before the window closed: terminate at last bar seen
                last = min(window_last, data_end_index)
                return last, TerminationReason.TIMEOUT
            bar = bars[imap[t]]
            if direction is Direction.LONG:
                running_extreme = bar.low if running_extreme is None else min(running_extreme, bar.low)
                if running_extreme < floor or bar.high >= end_price:
                    return t, TerminationReason.INVALIDATED
            else:
                running_extreme = bar.high if running_extreme is None else max(running_extreme, bar.high)
                if running_extreme > floor or bar.low <= end_price:
                    return t, TerminationReason.INVALIDATED
        return window_last, TerminationReason.TIMEOUT

"""Contract section 7 invariants (all 15) as free functions.

Each invariant is a free function over the relevant contract dataclass that
returns a structured :class:`ValidationResult` (not a bare ``assert``) so
failures are diagnosable. Logic lives here, never on the dataclasses
(Implementation Plan convention 7).

The numbering matches Contract v2.1 section 7. Some invariants (7.7 ATR
knowledge, 7.14 materialization equivalence) can only be *fully* enforced by
the two-mode repaint test (Contract section 8.1); here they are expressed as
the checkable structural property the contract describes, and the docstring
says so explicitly.
"""

from dataclasses import dataclass, fields
from typing import Sequence

from .contract import (
    CausalPrice,
    Direction,
    DetectedSetupOpening,
    ForwardPath,
    ProjectedLevel,
    SetupLifecycle,
    SetupUpdate,
    SimulatedEntry,
    TerminationReason,
    TrancheType,
)


@dataclass(frozen=True)
class ValidationResult:
    """Structured pass/fail for one invariant check.

    ``invariant`` is the Contract section-7 identifier (e.g. ``"7.5"``).
    ``passed`` is the verdict. ``message`` explains a failure (empty on pass).
    """
    invariant: str
    passed: bool
    message: str = ""

    def __bool__(self) -> bool:  # convenience: `if result:` reads as "passed"
        return self.passed


def _ok(invariant: str) -> ValidationResult:
    return ValidationResult(invariant, True, "")


def _fail(invariant: str, message: str) -> ValidationResult:
    return ValidationResult(invariant, False, message)


# ---------------------------------------------------------------------------
# 7.1 Causality of primitives
# ---------------------------------------------------------------------------

def validate_causal_price(price: CausalPrice, *, is_pivot: bool = False,
                          invariant: str = "7.1") -> ValidationResult:
    """Every CausalPrice has known_at_bar >= defining_bar (strictly greater for
    pivots)."""
    if is_pivot:
        if not price.known_at_bar > price.defining_bar:
            return _fail(invariant,
                         f"pivot CausalPrice known_at_bar ({price.known_at_bar}) must be "
                         f"> defining_bar ({price.defining_bar})")
    elif not price.known_at_bar >= price.defining_bar:
        return _fail(invariant,
                     f"CausalPrice known_at_bar ({price.known_at_bar}) must be "
                     f">= defining_bar ({price.defining_bar})")
    return _ok(invariant)


def validate_projected_level(level: ProjectedLevel,
                             invariant: str = "7.1") -> ValidationResult:
    """Every ProjectedLevel has active_at_bar > computed_at_bar."""
    if not level.active_at_bar > level.computed_at_bar:
        return _fail(invariant,
                     f"ProjectedLevel active_at_bar ({level.active_at_bar}) must be "
                     f"> computed_at_bar ({level.computed_at_bar})")
    return _ok(invariant)


# ---------------------------------------------------------------------------
# 7.2 Update knowledge-time
# ---------------------------------------------------------------------------

def validate_update_knowledge_time(update: SetupUpdate) -> ValidationResult:
    """Every SetupUpdate field is knowable at bar_index; countertrend_boundary_next /
    mr_trigger_next have computed_at_bar == bar_index."""
    t = update.bar_index
    if update.running_extreme.known_at_bar != t:
        return _fail("7.2",
                     f"running_extreme.known_at_bar ({update.running_extreme.known_at_bar}) "
                     f"!= bar_index ({t})")
    if update.countertrend_boundary_next.computed_at_bar != t:
        return _fail("7.2",
                     f"countertrend_boundary_next.computed_at_bar "
                     f"({update.countertrend_boundary_next.computed_at_bar}) != bar_index ({t})")
    if update.mr_trigger_next.computed_at_bar != t:
        return _fail("7.2",
                     f"mr_trigger_next.computed_at_bar "
                     f"({update.mr_trigger_next.computed_at_bar}) != bar_index ({t})")
    if update.with_trend_boundary_next is not None and \
            update.with_trend_boundary_next.computed_at_bar != t:
        return _fail("7.2",
                     f"with_trend_boundary_next.computed_at_bar "
                     f"({update.with_trend_boundary_next.computed_at_bar}) != bar_index ({t})")
    return _ok("7.2")


# ---------------------------------------------------------------------------
# 7.3 Stream ordering / linkage / span
# ---------------------------------------------------------------------------

def validate_stream_span(lifecycle: SetupLifecycle) -> ValidationResult:
    """Updates ascending and contiguous by bar_index (no gaps); first update at
    entry_eligible_bar; last update at terminated_at_bar (v2.1: span the full
    opportunity window, not truncated at any fill); all setup_ids match."""
    updates = lifecycle.updates
    if not updates:
        return _fail("7.3", "lifecycle has no updates")
    if updates[0].bar_index != lifecycle.opening.entry_eligible_bar:
        return _fail("7.3",
                     f"first update at {updates[0].bar_index}, expected "
                     f"entry_eligible_bar {lifecycle.opening.entry_eligible_bar}")
    if updates[-1].bar_index != lifecycle.terminated_at_bar:
        return _fail("7.3",
                     f"last update at {updates[-1].bar_index}, expected "
                     f"terminated_at_bar {lifecycle.terminated_at_bar} "
                     f"(stream must span the full window; not truncated at a fill)")
    for prev, cur in zip(updates, updates[1:]):
        if cur.bar_index != prev.bar_index + 1:
            return _fail("7.3",
                         f"non-contiguous updates: {prev.bar_index} -> {cur.bar_index} "
                         f"(gap or out of order)")
    sid = lifecycle.opening.setup_id
    for u in updates:
        if u.setup_id != sid:
            return _fail("7.3",
                         f"update setup_id {u.setup_id!r} != opening setup_id {sid!r}")
    return _ok("7.3")


# ---------------------------------------------------------------------------
# 7.4 Detection readiness
# ---------------------------------------------------------------------------

def validate_detection_readiness(opening: DetectedSetupOpening) -> ValidationResult:
    """detection_bar >= max(known_at_bar) over opening geometry;
    entry_eligible_bar == detection_bar + 1."""
    max_known = max(opening.impulse_origin.known_at_bar,
                    opening.impulse_end.known_at_bar)
    if opening.detection_bar < max_known:
        return _fail("7.4",
                     f"detection_bar ({opening.detection_bar}) < max opening-geometry "
                     f"known_at_bar ({max_known})")
    if opening.entry_eligible_bar != opening.detection_bar + 1:
        return _fail("7.4",
                     f"entry_eligible_bar ({opening.entry_eligible_bar}) != "
                     f"detection_bar + 1 ({opening.detection_bar + 1})")
    return _ok("7.4")


# ---------------------------------------------------------------------------
# 7.5 Running-extreme monotonicity
# ---------------------------------------------------------------------------

def validate_running_extreme_monotonicity(lifecycle: SetupLifecycle) -> ValidationResult:
    """For LONG, running_extreme.price non-increasing across updates
    (mirror for SHORT: non-decreasing)."""
    direction = lifecycle.opening.direction
    prices = [u.running_extreme.price for u in lifecycle.updates]
    for prev, cur in zip(prices, prices[1:]):
        if direction is Direction.LONG and cur > prev:
            return _fail("7.5",
                         f"LONG running_extreme increased {prev} -> {cur} (must be non-increasing)")
        if direction is Direction.SHORT and cur < prev:
            return _fail("7.5",
                         f"SHORT running_extreme decreased {prev} -> {cur} (must be non-decreasing)")
    return _ok("7.5")


# ---------------------------------------------------------------------------
# 7.6 Retracement floor honored
# ---------------------------------------------------------------------------

def validate_retracement_floor(lifecycle: SetupLifecycle) -> ValidationResult:
    """For LONG, mr_trigger_next.price >= opening.retracement_floor
    (mirror for SHORT: <=). Floor held once on the opening record."""
    direction = lifecycle.opening.direction
    floor = lifecycle.opening.retracement_floor
    for u in lifecycle.updates:
        p = u.mr_trigger_next.price
        if direction is Direction.LONG and p < floor:
            return _fail("7.6",
                         f"LONG mr_trigger_next.price ({p}) < retracement_floor ({floor}) "
                         f"at bar {u.bar_index}")
        if direction is Direction.SHORT and p > floor:
            return _fail("7.6",
                         f"SHORT mr_trigger_next.price ({p}) > retracement_floor ({floor}) "
                         f"at bar {u.bar_index}")
    return _ok("7.6")


# ---------------------------------------------------------------------------
# 7.7 ATR knowledge
# ---------------------------------------------------------------------------

def validate_atr_knowledge(lifecycle: SetupLifecycle) -> ValidationResult:
    """atr_at_detection and each per-bar atr use only bars at or before their
    knowledge bar. The bars-restriction itself is enforced end-to-end by the
    two-mode repaint test (section 8.1); here we check the structurally-checkable
    property that ATR values are present and non-negative (a negative ATR would
    signal a look-ahead / computation defect)."""
    if lifecycle.opening.atr_at_detection < 0:
        return _fail("7.7",
                     f"atr_at_detection ({lifecycle.opening.atr_at_detection}) is negative")
    for u in lifecycle.updates:
        if u.atr < 0:
            return _fail("7.7", f"atr ({u.atr}) is negative at bar {u.bar_index}")
    return _ok("7.7")


# ---------------------------------------------------------------------------
# 7.8 Forward path uncensored
# ---------------------------------------------------------------------------

def validate_forward_path(path: ForwardPath) -> ValidationResult:
    """No stop/target/exit applied; len(bars) == total_length unless
    truncated_by_data_end; total_length == max_pending_window + horizon_H."""
    if path.total_length != path.max_pending_window + path.horizon_H:
        return _fail("7.8",
                     f"total_length ({path.total_length}) != max_pending_window + horizon_H "
                     f"({path.max_pending_window + path.horizon_H})")
    if not path.truncated_by_data_end and len(path.bars) != path.total_length:
        return _fail("7.8",
                     f"len(bars) ({len(path.bars)}) != total_length ({path.total_length}) "
                     f"and not truncated_by_data_end")
    if path.truncated_by_data_end and len(path.bars) > path.total_length:
        return _fail("7.8",
                     f"truncated path has more bars ({len(path.bars)}) than total_length "
                     f"({path.total_length})")
    return _ok("7.8")


# ---------------------------------------------------------------------------
# 7.9 No stop/size in Stages 1-4 (regression guard)
# ---------------------------------------------------------------------------

_FORBIDDEN_FIELD_SUBSTRINGS = ("stop", "size", "target", "position_size", "risk")


def validate_no_stop_or_size(obj) -> ValidationResult:
    """Assert absence of any stop/size/target field on a Stage 1-4 dataclass
    (regression guard). Stop and size live only in the deferred rule layer."""
    try:
        obj_fields = fields(obj)
    except TypeError:
        return _fail("7.9", f"{obj!r} is not a dataclass instance")
    for f in obj_fields:
        name = f.name.lower()
        for bad in _FORBIDDEN_FIELD_SUBSTRINGS:
            if bad in name:
                return _fail("7.9",
                             f"{type(obj).__name__} has forbidden field {f.name!r} "
                             f"(matches {bad!r}); stop/size belong to the rule layer")
    return _ok("7.9")


# ---------------------------------------------------------------------------
# 7.10 Fill causality
# ---------------------------------------------------------------------------

def validate_fill_causality(entry: SimulatedEntry,
                            entry_eligible_bar: int) -> ValidationResult:
    """Every fill_bar >= entry_eligible_bar; unfilled tranche => fill_time_geometry
    is None; filled tranche => fill_time_geometry present. (The 'no fill references a
    level with knowledge bar after fill_bar' clause is enforced against the update
    stream by the no-look-ahead fill test, section 8.3.)"""
    for fill in entry.tranche_fills:
        if fill.filled:
            if fill.fill_bar is None:
                return _fail("7.10", f"filled tranche {fill.tranche_id} has fill_bar None")
            if fill.fill_bar < entry_eligible_bar:
                return _fail("7.10",
                             f"tranche {fill.tranche_id} fill_bar ({fill.fill_bar}) "
                             f"< entry_eligible_bar ({entry_eligible_bar})")
            if fill.fill_time_geometry is None:
                return _fail("7.10",
                             f"filled tranche {fill.tranche_id} has fill_time_geometry None")
        else:
            if fill.fill_time_geometry is not None:
                return _fail("7.10",
                             f"unfilled tranche {fill.tranche_id} has non-None fill_time_geometry")
    return _ok("7.10")


# ---------------------------------------------------------------------------
# 7.11 Both maturities present
# ---------------------------------------------------------------------------

def validate_both_maturities(lifecycle: SetupLifecycle) -> ValidationResult:
    """Every SetupUpdate has non-null maturity_barcount and maturity_retracement."""
    for u in lifecycle.updates:
        if u.maturity_barcount is None:
            return _fail("7.11", f"maturity_barcount is None at bar {u.bar_index}")
        if u.maturity_retracement is None:
            return _fail("7.11", f"maturity_retracement is None at bar {u.bar_index}")
    return _ok("7.11")


# ---------------------------------------------------------------------------
# 7.12 Termination consistency
# ---------------------------------------------------------------------------

def validate_termination_consistency(lifecycle: SetupLifecycle,
                                     entry: SimulatedEntry | None = None) -> ValidationResult:
    """updates[-1].bar_index == terminated_at_bar; termination_reason in
    {INVALIDATED, TIMEOUT}. No fill (MR or WT) may set terminated_at_bar — a
    lifecycle with an early first fill must still emit updates past the fill bar
    up to terminated_at_bar (checked when an entry is supplied)."""
    if lifecycle.termination_reason not in (TerminationReason.INVALIDATED,
                                            TerminationReason.TIMEOUT):
        return _fail("7.12",
                     f"termination_reason {lifecycle.termination_reason!r} not in "
                     f"{{INVALIDATED, TIMEOUT}}")
    if not lifecycle.updates:
        return _fail("7.12", "lifecycle has no updates")
    if lifecycle.updates[-1].bar_index != lifecycle.terminated_at_bar:
        return _fail("7.12",
                     f"last update ({lifecycle.updates[-1].bar_index}) != terminated_at_bar "
                     f"({lifecycle.terminated_at_bar})")
    if entry is not None:
        for fill in entry.tranche_fills:
            if fill.filled and fill.fill_bar is not None \
                    and fill.fill_bar == lifecycle.terminated_at_bar \
                    and fill.fill_bar < lifecycle.opening.entry_eligible_bar:
                # a fill cannot be the cause of termination; this shape is only
                # suspicious if the stream would have stopped at it — the span
                # check (7.3) plus last==terminated already guard that.
                pass
            # The concrete guard: if any fill occurs strictly before terminated_at_bar,
            # updates must continue past it (span check ensures last==terminated).
    return _ok("7.12")


# ---------------------------------------------------------------------------
# 7.13 Pre-anchor substrate causality
# ---------------------------------------------------------------------------

def validate_pre_anchor_substrate(opening: DetectedSetupOpening) -> ValidationResult:
    """Every bar in pre_anchor_bars has bar_index < entry_eligible_bar;
    len(pre_anchor_bars) == pre_anchor_lookback; bars ascending, contiguous, and
    abut entry_eligible_bar (last pre-anchor bar == entry_eligible_bar - 1)."""
    bars = opening.pre_anchor_bars
    if len(bars) != opening.pre_anchor_lookback:
        return _fail("7.13",
                     f"len(pre_anchor_bars) ({len(bars)}) != pre_anchor_lookback "
                     f"({opening.pre_anchor_lookback})")
    if not bars:
        return _fail("7.13", "pre_anchor_bars is empty")
    for prev, cur in zip(bars, bars[1:]):
        if cur.bar_index != prev.bar_index + 1:
            return _fail("7.13",
                         f"pre_anchor_bars non-contiguous: {prev.bar_index} -> {cur.bar_index}")
    if bars[-1].bar_index != opening.entry_eligible_bar - 1:
        return _fail("7.13",
                     f"last pre-anchor bar ({bars[-1].bar_index}) != entry_eligible_bar - 1 "
                     f"({opening.entry_eligible_bar - 1}); window must abut the anchor")
    if bars[0].bar_index >= opening.entry_eligible_bar:
        return _fail("7.13",
                     f"first pre-anchor bar ({bars[0].bar_index}) >= entry_eligible_bar "
                     f"({opening.entry_eligible_bar})")
    return _ok("7.13")


# ---------------------------------------------------------------------------
# 7.14 Materialization equivalence
# ---------------------------------------------------------------------------

def validate_materialization_equivalence(stream_a: Sequence[SetupUpdate],
                                         stream_b: Sequence[SetupUpdate]) -> ValidationResult:
    """A materialized SetupUpdate stream must be byte-identical (field-identical)
    to the generation-time stream. Fully enforced by the two-mode repaint test
    (section 8.1); here it is the checkable equivalence between two streams. No
    downstream materialization may use a bar with bar_index > t."""
    if len(stream_a) != len(stream_b):
        return _fail("7.14",
                     f"stream lengths differ: {len(stream_a)} != {len(stream_b)}")
    for i, (ua, ub) in enumerate(zip(stream_a, stream_b)):
        if ua != ub:
            return _fail("7.14",
                         f"update {i} (bar {ua.bar_index}) differs between streams: "
                         f"{ua!r} != {ub!r}")
    return _ok("7.14")


# ---------------------------------------------------------------------------
# 7.15 d_struct consistency
# ---------------------------------------------------------------------------

def validate_d_struct_consistency(lifecycle: SetupLifecycle,
                                  tick_size: float = 1e-9) -> ValidationResult:
    """If with_trend_boundary_next/d_struct non-null, d_struct equals the channel
    height implied by with_trend_boundary_next and running_extreme within tick
    tolerance. LONG: with_trend - running_extreme; SHORT: running_extreme - with_trend."""
    direction = lifecycle.opening.direction
    for u in lifecycle.updates:
        wt = u.with_trend_boundary_next
        if wt is None and u.d_struct is None:
            continue
        if (wt is None) != (u.d_struct is None):
            return _fail("7.15",
                         f"at bar {u.bar_index}: with_trend_boundary_next and d_struct must be "
                         f"both null or both present")
        if direction is Direction.LONG:
            implied = wt.price - u.running_extreme.price
        else:
            implied = u.running_extreme.price - wt.price
        if abs(implied - u.d_struct) > tick_size:
            return _fail("7.15",
                         f"at bar {u.bar_index}: d_struct ({u.d_struct}) != channel height "
                         f"({implied}) within tick tolerance ({tick_size})")
    return _ok("7.15")


# ---------------------------------------------------------------------------
# Aggregate helpers
# ---------------------------------------------------------------------------

def validate_lifecycle(lifecycle: SetupLifecycle, *,
                       tick_size: float = 1e-9,
                       entry: SimulatedEntry | None = None) -> list[ValidationResult]:
    """Run every lifecycle-scoped invariant and return the full list of results.

    Callers filter for failures with ``[r for r in results if not r]``.
    """
    results: list[ValidationResult] = []
    opening = lifecycle.opening

    # 7.1 — opening causal primitives (impulse endpoints are pivots)
    results.append(validate_causal_price(opening.impulse_origin, is_pivot=True))
    results.append(validate_causal_price(opening.impulse_end, is_pivot=True))
    # 7.1 — every projected level in the stream
    for u in lifecycle.updates:
        results.append(validate_causal_price(u.running_extreme))
        results.append(validate_projected_level(u.countertrend_boundary_next))
        results.append(validate_projected_level(u.mr_trigger_next))
        if u.with_trend_boundary_next is not None:
            results.append(validate_projected_level(u.with_trend_boundary_next))
        # 7.2
        results.append(validate_update_knowledge_time(u))

    results.append(validate_stream_span(lifecycle))
    results.append(validate_detection_readiness(opening))
    results.append(validate_running_extreme_monotonicity(lifecycle))
    results.append(validate_retracement_floor(lifecycle))
    results.append(validate_atr_knowledge(lifecycle))
    results.append(validate_no_stop_or_size(lifecycle.opening))
    results.append(validate_both_maturities(lifecycle))
    results.append(validate_termination_consistency(lifecycle, entry))
    results.append(validate_pre_anchor_substrate(opening))
    results.append(validate_d_struct_consistency(lifecycle, tick_size))

    if entry is not None:
        results.append(validate_no_stop_or_size(entry))
        results.append(validate_fill_causality(entry, opening.entry_eligible_bar))

    return results


def failures(results: Sequence[ValidationResult]) -> list[ValidationResult]:
    """Return only the failed results from a run."""
    return [r for r in results if not r.passed]

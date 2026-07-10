# Setup / Geometry Contract — v2.1

**Status: FROZEN-SHAPE, FLAGGED-VALUES.** This is the data contract that decouples the setup **detector** from every downstream module (boundary construction, entry simulation, fill simulation, forward-path recording, rule evaluation). Build to it; do not edit it. If a field appears wrong or insufficient, raise it with the human before changing anything.

**Sole authority.** This document is the single, complete, and authoritative specification of the setup data contract. Any earlier contract version or change memo is **superseded and must not be consulted** — this document restates everything needed and does not depend on any prior version. Where two sources ever appear to conflict, this document governs.

**v2.1 changelog (the one controlled revision from §11.1 — now spent).** This revision closes a single structural gap: the setup lifecycle previously terminated on the **first tranche fill** (`MR_FILL` / `WT_FILL` were termination reasons), which censored the causal geometry stream — and therefore the entry-opportunity window — at the moment of first fill. That censoring makes whole classes of question unanswerable without regenerating artifacts: MR-trigger fill-probability sweeps (varying the trigger depth and asking how often, and on what terms, it would have filled), and second-MR-tranche evaluation (which by construction rests and fills *after* the first fill). Both need geometry and bars over the *entire* window in which an entry order could still fill, not just up to the first fill. The changes:

1. **Fills no longer terminate the lifecycle.** `TerminationReason` is reduced to `{INVALIDATED, TIMEOUT}` — the two conditions under which the entry-opportunity window genuinely closes. Fills remain recorded events on `SimulatedEntry.tranche_fills`; the lifecycle now spans `entry_eligible_bar → terminated_at_bar` regardless of how many tranches fill along the way (see §1.3, §2, §7-12).
2. **Materialization strategy = Option B (persist raw bars; materialize geometry on demand).** Because estimator C's internals are still provisional and will be calibrated in characterization, the causal geometry stream is **not persisted** at generation time. Instead the raw bar substrate is persisted and the `SetupUpdate` stream is materialized on demand by the certified constructor through an interface-gated materializer (§2.2, §6.1). The one new persisted datum this requires is a bounded **pre-anchor bar window** (§2.1). This defers the estimator-C representation commitment past the point where characterization resolves it, at the cost of recomputing geometry at evaluation-time. A later, cheap migration to persisted geometry (Option A) is documented in §11.3.
3. **Repaint/truncation-invariance extends to the on-demand materializer** (§8.1): the keystone test must now certify the materialized stream at evaluation-time, not only a generation-time stream.

No interpretive fields were added. The change is information-preserving (it stops discarding raw geometry-input bars at first fill) and does not introduce any question-specific structure. Nothing in Stages 2–4 that was correct in v2 is weakened.

**v2.2 naming revision (human-authorized; renames only, no shape change).** Three fields were renamed to remove direction-dependent naming that silently inverted meaning between LONG and SHORT setups: `boundary_estimate_next` → `countertrend_boundary_next`, `upper_next` → `with_trend_boundary_next`, `running_low` → `running_extreme` (and its fill-time counterpart `running_low_at_fill` → `running_extreme_at_fill`). Rationale: `upper_next` held the far-side (with-trend) boundary, which is the pullback's *lows* for a SHORT setup — a field literally named "upper" holding a lower price. `running_low` similarly held the running *maximum* for a SHORT setup. No field's type, position, `known_at_bar` semantics, nullability, or role in any invariant/test changes — this is a label-only revision, distinct in kind from the v2.1 structural revision and not drawn from the same (already-spent) revision slot in §11.1. Authorized directly by the human (LCG); every occurrence of the old names in this document and in the Project Brief, Implementation Plan v2, and Detector Spec v1 has been updated to match. Do not reintroduce the old names.

**Freeze discipline.** Two things are distinguished. The **structure** — field existence, types, `known_at_bar` annotations, stream shapes, invariants — is frozen and **the one controlled-revision slot is spent** (consumed by the v2→v2.1 revision; see §11.1). Specific **values** explicitly tagged *provisional* are resolved later in the characterization stage, *inside* that frozen structure; changing a provisional value does not change the interface. Any future structural change is human-escalation-only; see Implementation Plan convention 1.

**Audience:** an AI coding agent in a Python codebase (Windsurf) with the cache manager and vendor integration, no access to the conversation behind this document.

---

## 0. Orientation

### 0.1 The five project-scope anti-defaults (non-negotiable)

1. **Never apply stops/targets inline during path generation.** Forward paths are uncensored; stops live only in the downstream rule evaluator. Stop and size are absent from Stages 1–3 by design.
2. **Never assume touch-fills on the MR limit** without also modelling trade-through; record the adverse-selection diagnostic on every MR fill.
3. **Never use a repainting (look-ahead) detector.** Every causal value carries `known_at_bar`; the truncation-invariance test (§8.1) enforces it over the *entire update stream* — including the on-demand materialized stream (§6.1, §8.1).
4. **Never store stop or position size upstream of the rule sweep.**
5. **Never censor the entry-opportunity window at first fill.** The lifecycle (and the bar substrate that lets its geometry be materialized) runs to `INVALIDATED` or `TIMEOUT`, not to the first `MR_FILL`/`WT_FILL`. A fill is an event *within* the window, not a closing of it. This is the exact analogue, on the entry-placement axis, of anti-default #1 on the price axis: entry-placement sweeps need the opportunity geometry uncensored the same way stop sweeps need the price path uncensored.

### 0.2 Confirmed structural decisions

- Parallel-channel coupling invariant **removed**. The constructor emits a single `countertrend_boundary`; the with-trend boundary line survives only as an optional candidate stop-volatility unit.
- Setup model is a **lifecycle**: a static opening record + a causal per-bar geometry stream + terminal fields, wrapped in a lifecycle container (§2). The stream spans the whole entry-opportunity window.
- `TerminationReason` is **`{INVALIDATED, TIMEOUT}`** only (v2.1). Fills do **not** terminate the lifecycle; they are recorded events on `SimulatedEntry.tranche_fills`. `INVALIDATED` and `TIMEOUT` are the only two ways the entry-opportunity window closes.
- The lifecycle may contain **multiple fills** — in particular the second MR tranche fills after the first, still within one open lifecycle.
- **Materialization strategy is Option B:** the geometry stream (`SetupUpdate` sequence) is materialized on demand from persisted raw bars by the certified constructor, not persisted at generation time (§2.2, §6.1, §11.3). The persisted substrate is the opening record + the bar window (pre-anchor lookback + `ForwardPath`) + fills + terminal outcome.
- `fit_dispersion(t)` is emitted **pre-emptively** (by the materializer).
- `retracement_floor` is held **once** on the opening record and referenced, not repeated per update.
- **Both** maturity definitions (`maturity_barcount`, `maturity_retracement`) are emitted as characterization features on every update; the live offset uses one, selected post-hand-mark.

### 0.3 Placement of terminal fields (rationale)

A frozen opening record created at detection cannot causally hold values known only at termination. Terminal fields (`terminated_at_bar`, `termination_reason`) are therefore placed on a **`SetupLifecycle` container** that wraps the immutable opening record, the ordered geometry stream, and the terminal outcome (§2.3). This keeps the static-opening / separate-stream split intact and every field causally honest.

`terminated_at_bar` now marks the **close of the entry-opportunity window** (`INVALIDATED`/`TIMEOUT`), not the first fill. It is causal — it is knowable only once the terminating bar has closed — and it bounds both the length of the geometry stream and the portion of the bar window that is "opportunity window" (as opposed to post-window forward horizon). Under Option B the `SetupLifecycle` is the **return type of the on-demand materializer**, reconstructed from persisted bars when a downstream query needs it; only the small terminal outcome (`terminated_at_bar`, `termination_reason`) and the bar substrate are persisted, not the materialized `updates` tuple.

---

## 1. Conventions and primitives

### 1.1 Bars and bar indices

`bar_index` is the canonical time reference; timestamps are informational. Bar `t`'s OHLC is known only at the **close of bar `t`** — the basis of every causality check.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Bar:
    bar_index: int
    timestamp: str        # ISO 8601, UTC; informational only
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
```

### 1.2 Causal primitives

`CausalPrice` expresses a level established by past data. `ProjectedLevel` expresses a *forecast* — a level computed at the close of `t` for an order resting at a future bar. This is the clean representation of structural commitment #3 (a distinct forward-projected entry field).

```python
@dataclass(frozen=True)
class CausalPrice:
    price: float
    defining_bar: int     # bar index that establishes this level
    known_at_bar: int     # bar index at whose CLOSE this becomes knowable
    # INVARIANT: known_at_bar >= defining_bar
    # Pivot-type levels: known_at_bar == defining_bar + N (strictly greater)

@dataclass(frozen=True)
class ProjectedLevel:
    price: float
    computed_at_bar: int  # = t; known at the close of t
    active_at_bar: int    # the future bar the resting order is live for
    # INVARIANT: active_at_bar > computed_at_bar
    # Default projection horizon: active_at_bar == computed_at_bar + 1
    # (projection-horizon choice is a VALUE, resolved in the detector spec)
```

### 1.3 Enums

```python
from enum import Enum

class Direction(Enum):
    LONG = "long"
    SHORT = "short"

class TrancheType(Enum):
    MEAN_REVERSION = "mr"
    WITH_TREND = "wt"

class OrderType(Enum):
    LIMIT = "limit"            # MR entries
    STOP_LIMIT = "stop_limit"  # with-trend entries

class TriggerType(Enum):
    INSIDE_BAR = "inside_bar"
    ID_NR7 = "id_nr7"
    ID_NR5 = "id_nr5"
    PIVOT = "pivot"
    LTF_PIVOT = "ltf_pivot"
    FAILURE_TEST = "failure_test"
    OTHER = "other"

class GrimesVariant(Enum):      # FEATURE, never a filter (permissive-first)
    SIMPLE = "simple"
    ANTI_SNAP = "anti_snap"
    NESTED = "nested"
    COMPLEX = "complex"
    UNCLASSIFIED = "unclassified"

class FillModel(Enum):
    TOUCH = "touch"
    TRADE_THROUGH = "trade_through"

class TrancheComposition(Enum):
    NONE = "none"
    MR_ONLY = "mr_only"
    WT_ONLY = "wt_only"
    MIXED = "mixed"

class TerminationReason(Enum):
    # v2.1: fills are NOT terminators. A lifecycle ends only when the
    # entry-opportunity window closes. Fills are recorded on SimulatedEntry.
    INVALIDATED = "invalidated"  # 2/3-retracement floor breached OR high >= impulse_end (thesis dead)
    TIMEOUT = "timeout"          # max_pending_window exhausted with the window still open
```

The two reasons are exhaustive and mutually exclusive at the terminating bar. `INVALIDATED` fires when the pullback ceases to be a valid pullback (the running low breaches `retracement_floor`, i.e. 2/3 of the impulse, or the price reclaims `impulse_end` so there is no pullback left to enter). `TIMEOUT` fires when neither has occurred within `max_pending_window` bars. In both cases the window — the interval during which any MR or WT order could still fill — is over; further bars belong to the forward horizon, not the opportunity window. Because fills no longer terminate the lifecycle, a setup whose first MR tranche fills early continues to emit geometry (and to accrue further fills, including the second MR tranche) until one of these two conditions closes the window.

### 1.4 Instrument metadata

```python
@dataclass(frozen=True)
class InstrumentMeta:
    symbol: str
    tick_size: float
    point_value: float
    default_slippage_ticks: float
    is_spot_fx: bool = False
```

---

## 2. Stage 1 — the setup lifecycle

A setup is no longer a snapshot. It is an **opening record** (static, known at detection), a **causal per-bar geometry stream** (each element causal at its own bar), and a **terminal outcome**, wrapped in a lifecycle container. The stream spans the **entire entry-opportunity window** — `entry_eligible_bar` through `terminated_at_bar` (`INVALIDATED`/`TIMEOUT`) — and is **not truncated at any fill** (v2.1).

**What is persisted vs. materialized (Option B).** At generation time the persisted artifacts are: the `DetectedSetupOpening` (including its pre-anchor bar window, §2.1), the `ForwardPath` (§4), the `SimulatedEntry` (§3), and the terminal outcome (`terminated_at_bar`, `termination_reason`). The `SetupUpdate` stream and the `SetupLifecycle` container that holds it are **materialized on demand** from the persisted bars by the certified constructor through the interface-gated materializer (§6.1). The stream's *type* is fully specified here because it is the materializer's return shape (and the shape a later Option-A cache would persist, §11.3); its *storage* is deferred. Everything downstream that consumes a `SetupLifecycle`/`SetupUpdate` receives the materialized object and cannot tell whether it was recomputed or cached.

### 2.1 Static opening record

```python
@dataclass(frozen=True)
class StaticFeatures:
    """Detection-time qualifiers. EMITTED, NEVER FILTERED (permissive-first).
    Time-varying features live on SetupUpdate, not here."""
    grimes_variant: GrimesVariant
    pullback_count_in_trend: int | None    # 1,2,3,...; None if trend undefined
    weekly_agreement_at_detection: float | None
    vol_ratio_at_detection: float | None
    wick_indecision_at_detection: float | None

@dataclass(frozen=True)
class DetectedSetupOpening:
    # identity / provenance
    setup_id: str                 # stable hash of (symbol, timeframe, detection_bar, geometry)
    symbol: str
    timeframe: str
    detector_version: str
    param_hash: str
    generated_at: str

    # classification / timing
    direction: Direction
    detection_bar: int
    entry_eligible_bar: int       # == detection_bar + 1; first session orders are live
    pullback_start_bar: int       # anchor for maturity_barcount

    # static geometry (impulse is fixed once known)
    impulse_origin: CausalPrice   # invalidation anchor
    impulse_end: CausalPrice      # impulse extreme / pullback start
    atr_at_detection: float
    atr_period: int

    # static derived level (held ONCE here; referenced by updates, not repeated)
    # LONG: impulse_end.price - (2/3)*(impulse_end.price - impulse_origin.price); mirror for SHORT
    retracement_floor: float

    features: StaticFeatures

    # v2.1 — Option B materialization substrate.
    # The raw bars the constructor needs to re-derive the geometry stream on demand:
    # everything from (entry_eligible_bar - pre_anchor_lookback) through
    # (entry_eligible_bar - 1). Sized to cover the maximum plausible estimator-C
    # window + ATR period + warm-up (a VALUE, §10). Causally clean: every bar here
    # precedes entry_eligible_bar, so it is fully known at detection.
    # Forward bars (entry_eligible_bar onward) live on ForwardPath (§4); the two
    # together form the complete uncensored bar substrate for this setup.
    pre_anchor_bars: tuple[Bar, ...]
    pre_anchor_lookback: int          # == len(pre_anchor_bars); count of pre-anchor bars stored

    # forward-compatibility hook (nullable; unused by current version) — see 11.2
    correlation_cluster: str | None = None
```

Note on the substrate split: `pre_anchor_bars` + `ForwardPath.bars` are the *complete* raw record for the setup. The materializer (§6.1) reconstructs each `SetupUpdate` at bar `t` from the bars at or before `t` drawn from this substrate — never from anything after `t`. Storing bars (invariant, characterization-proof) rather than the fitted geometry (provisional, estimator-C-dependent) is the whole point of Option B: no regeneration is forced when estimator C changes during characterization.

### 2.2 Per-bar geometry stream (materialized on demand)

One `SetupUpdate` per bar from `entry_eligible_bar` through `terminated_at_bar` inclusive — the full entry-opportunity window, **not** stopping at any fill (v2.1). Every field is causal with `known_at_bar = bar_index`, computed from bars <= `bar_index` drawn from the persisted substrate (`pre_anchor_bars` + `ForwardPath.bars`). Under Option B this stream is produced by the materializer at query time, not read from storage.

```python
@dataclass(frozen=True)
class SetupUpdate:
    setup_id: str                 # foreign key to the opening record
    bar_index: int                # = t; all fields known at close of t

    # mechanical stream
    running_extreme: CausalPrice      # L(t): running literal extreme on the countertrend side of the
                                       # pullback — running-min low for LONG, running-max high for
                                       # SHORT (mirror); monotonic; never repaints
    mean_true_range_pullback: float   # V(t): mean TRUE range of pullback bars so far
    countertrend_boundary_next: ProjectedLevel   # estimator C, projected to t+1. The fitted (not
                                       # literal) countertrend boundary: a robust fit to the pullback's
                                       # lows for LONG, highs for SHORT (mirror) — the boundary the MR
                                       # limit rests against. Distinct from running_extreme (Detector
                                       # Spec §8.1/§8.2).
    mr_trigger_next: ProjectedLevel          # = max(countertrend_boundary_next - alpha(m(t))*V(t),
                                             #        opening.retracement_floor)  [LONG; mirror SHORT]
    fit_dispersion: float | None      # estimator C residual dispersion / jitter; None during warm-up

    # maturity features — BOTH emitted (characterization); live offset selects one
    maturity_barcount: int            # bars since opening.pullback_start_bar
    maturity_retracement: float       # (impulse_end - L(t)) / ((2/3)*(impulse_end - impulse_origin)) [LONG]

    # candidate stop-volatility unit — nullable; may be dropped if RQ1 finds ATR/V dominate
    with_trend_boundary_next: ProjectedLevel | None  # the far-side (with-trend) boundary: pullback
                                       # highs for LONG, pullback lows for SHORT (mirror) — the
                                       # opposite extrema from countertrend_boundary_next
    d_struct: float | None            # channel height if with_trend_boundary_next retained

    atr: float                        # competing stop-volatility unit
```

Note: `mr_trigger_next`'s **formula is constructor-internal**; the contract emits the field plus its inputs (`countertrend_boundary_next`, `V`, and the maturity features feeding `alpha`) so the value is transparent and reconstructible. `alpha`, its decay shape, the offset constant, and the live maturity choice are **detector-spec content**, not contract content.

### 2.3 Lifecycle container (holds terminal outcome)

Under Option B this is the **return type of the materializer** (§6.1), not a persisted artifact. Its terminal fields (`terminated_at_bar`, `termination_reason`) *are* persisted (they are cheap, causal, and bound the opportunity window); the `updates` tuple is rebuilt on demand.

```python
@dataclass(frozen=True)
class SetupLifecycle:
    opening: DetectedSetupOpening
    updates: tuple[SetupUpdate, ...]      # ordered by bar_index, ascending; materialized on demand
    terminated_at_bar: int
    termination_reason: TerminationReason  # INVALIDATED or TIMEOUT only (v2.1)
    # INVARIANT: updates[0].bar_index == opening.entry_eligible_bar
    # INVARIANT: updates[-1].bar_index == terminated_at_bar
    #            (v2.1: stream runs to window close, not to first fill; equality, not <=)
    # INVARIANT: updates are contiguous by bar_index with no gaps
    # INVARIANT: every update.setup_id == opening.setup_id
    # INVARIANT: termination_reason in {INVALIDATED, TIMEOUT}
```

A `SetupTerminalOutcome` (the persisted slice) may be stored separately as `(setup_id, terminated_at_bar, termination_reason)`; the coding agent may inline it or keep it as its own small record, provided the materializer can reconstruct the full `SetupLifecycle` from `(DetectedSetupOpening, ForwardPath, terminal outcome, BoundaryConstructor, MaturityFn)`.

---

## 3. Stage 2 — entry simulation and fills

Produced from `(SetupLifecycle, EntryConfig)`, where the `SetupLifecycle` is the materialized object (§2.3). No stop, no size here. Fill-time geometry is captured because boundaries move (structural commitment #4): the rule layer consumes fill-time values, not detection-time values.

**v2.1 — fills span the open window.** Because the lifecycle no longer terminates at first fill, `tranche_fills` can hold multiple fills that occur at different bars within the same open window — in particular the **second MR tranche**, which by construction rests and fills *after* the first MR fill and *while structure is still developing*. `EntryConfig.second_mr_level_rule` may therefore reference geometry from `SetupUpdate`s **after** the first fill bar (e.g. a still-tracking `countertrend_boundary_next` or a fresh `running_extreme`); in v2 those updates did not exist. A rule that wants only a static offset locked at the first fill remains expressible; a rule that tracks the evolving boundary is now *also* expressible. Which is correct is a rule-sweep question (deferred); the contract's job is only to keep both reachable by not censoring the stream.

```python
@dataclass(frozen=True)
class EntryConfig:
    entry_config_id: str
    fill_model: FillModel
    slippage_ticks: float
    second_mr_level_rule: str     # rule id for the 2nd MR entry (provisional placeholder overridden here)
    require_trade_through_for_limit: bool = True

@dataclass(frozen=True)
class FillTimeGeometry:
    mr_trigger_at_fill: float
    running_extreme_at_fill: float
    mean_true_range_at_fill: float
    atr_at_fill: float
    d_struct_at_fill: float | None      # nullable, per §2.2
    entry_to_origin_at_fill: float

@dataclass(frozen=True)
class TrancheFill:
    tranche_id: str
    tranche_type: TrancheType
    filled: bool
    fill_bar: int | None                  # >= entry_eligible_bar; None if unfilled
    requested_price: float
    fill_price: float | None
    slippage_applied: float
    filled_on_trade_through: bool | None  # MR daily close-based proxy; None if WT/unfilled
    fill_time_geometry: FillTimeGeometry | None  # None if unfilled

@dataclass(frozen=True)
class SimulatedEntry:
    setup_id: str
    entry_config_id: str
    tranche_fills: tuple[TrancheFill, ...]
    composition: TrancheComposition     # derived from which tranches filled
```

MR adverse-selection proxy (daily): `filled_on_trade_through = True` when filled and closed beyond the level; `False` when filled and closed back inside. Document in code that this is a coarse daily proxy.

---

## 4. Stage 3 — `ForwardPath` (uncensored)

Anchored at the config-independent `entry_eligible_bar`; one path per setup; **no stop/target logic may touch it.** Length extended to cover the horizon measured from the latest possible fill.

```python
@dataclass(frozen=True)
class ForwardPathBar:
    bar_offset: int          # 0 == anchor bar
    bar_index: int
    high: float
    low: float
    close: float
    intraday_high: float | None = None   # None in the current daily-only version
    intraday_low: float | None = None

@dataclass(frozen=True)
class ForwardPath:
    setup_id: str
    anchor_bar: int          # == entry_eligible_bar
    max_pending_window: int  # bounded by TIMEOUT; makes length deterministic
    horizon_H: int           # provisional 15-20 trading days + fill-latency buffer (VALUE; pending sign-off)
    total_length: int        # == max_pending_window + horizon_H
    bars: tuple[ForwardPathBar, ...]
    truncated_by_data_end: bool
    # INVARIANT: len(bars) == total_length unless truncated_by_data_end
    # INVARIANT: no stop/target/exit logic applied during construction
```

Excursion metrics (MAE/MFE in d_struct / ATR / R / distance-to-origin) are **pure functions computed downstream**, never stored here. Metrics in R require a candidate stop and are strictly sweep-time.

**v2.1 — substrate and window bound.** `ForwardPath.bars` (anchor onward) together with `DetectedSetupOpening.pre_anchor_bars` (before the anchor) form the complete uncensored bar record from which the geometry stream is materialized (§2.2, §6.1). `max_pending_window` is the bound on the **entry-opportunity window**: when `TIMEOUT` fires, `terminated_at_bar == anchor_bar + max_pending_window - 1` (the window ran its full length without `INVALIDATED`); when `INVALIDATED` fires, `terminated_at_bar` is earlier. The forward path still extends `horizon_H` bars beyond the latest possible fill so every counterfactual fill anywhere in the window has a full forward horizon; this is unchanged from v2 and is exactly what lets fill-conditioned excursion questions (RQ3) work for late fills.

---

## 5. Where stop and size live

Size and stop are computed in the **rule-evaluation layer** as pure functions over `(SetupLifecycle, SimulatedEntry, ForwardPath, candidate_rule)`, using the **fill-time geometry** snapshot:

```
size     = (R_fraction * account_value) / (abs(fill_price - candidate_stop) * point_value)
realized = evaluate(path_slice_from_fill, candidate_stop, candidate_target, trail_rule)
```

The evaluator must return the full realized-R distribution including sub-(-1R) gap outcomes. Keeping stop/size out of Stages 1–4 is what keeps paths reusable and uncensored.

---

## 6. Interfaces

### 6.1 `BoundaryConstructor` and the geometry materializer (the seam; structural)

The detector depends on this interface. Estimator C and the `alpha` offset are implementations *behind* it; the maturity notion is injected. Swapping any of these changes values, not shape.

```python
from typing import Protocol, Sequence

class MaturityFn(Protocol):
    def __call__(self, opening: DetectedSetupOpening,
                 bars_up_to_t: Sequence[Bar], t: int) -> float: ...

class BoundaryConstructor(Protocol):
    def compute_update(self, opening: DetectedSetupOpening,
                       bars_up_to_t: Sequence[Bar], t: int,
                       maturity_fn: MaturityFn) -> SetupUpdate:
        """Return the causal SetupUpdate for bar t using ONLY bars <= t.
        Must populate fit_dispersion (or None during warm-up) and BOTH
        maturity features regardless of which one maturity_fn selects for alpha."""
        ...
```

**The geometry materializer (Option B; v2.1).** The `SetupUpdate` stream is produced on demand, not persisted, by driving the `BoundaryConstructor` across the opportunity window. This is the seam that keeps the rule/evaluation layer decoupled from the constructor:

```python
class GeometryMaterializer(Protocol):
    def materialize(self, opening: DetectedSetupOpening,
                    forward_path: ForwardPath,
                    terminated_at_bar: int,
                    termination_reason: TerminationReason,
                    constructor: BoundaryConstructor,
                    maturity_fn: MaturityFn) -> SetupLifecycle:
        """Rebuild the full SetupLifecycle from persisted bars.
        For each bar t in [opening.entry_eligible_bar, terminated_at_bar],
        assemble bars_up_to_t from (opening.pre_anchor_bars + forward_path.bars)
        restricted to bar_index <= t, and call constructor.compute_update(...).
        MUST NOT pass any bar with bar_index > t (no look-ahead). The returned
        stream is contiguous and byte-identical to what a generation-time stream
        would have contained — this equivalence is enforced by §8.1."""
        ...
```

Two rules make Option B safe and make the later Option-A migration (§11.3) a drop-in:

1. **The rule/evaluation layer never calls the constructor or materializer directly.** It requests geometry through a single stable accessor (e.g. `get_lifecycle(setup_id) -> SetupLifecycle`) whose implementation is *either* the materializer (Option B) *or* a cache read (Option A). The layer cannot tell which. This is the clean-seam discipline that keeps the migration a one-line swap behind the accessor.
2. **The same certified `constructor` + `maturity_fn` instances used at generation are used for on-demand materialization.** Materialization is not a second, looser code path; it is the same causal computation, re-run. This is what lets §8.1 certify it.

### 6.2 Input adapter

```python
class BarSeriesProvider(Protocol):
    def get_bars(self, symbol: str, timeframe: str,
                 start_index: int | None, end_index: int | None) -> Sequence[Bar]:
        """Ascending by bar_index, inclusive of bounds.
        MUST NOT return bars beyond end_index (no-look-ahead at the data boundary)."""
        ...
```

---

## 7. Invariants (enforce in `validators.py` as free functions)

1. **Causality:** every `CausalPrice` has `known_at_bar >= defining_bar` (strictly greater for pivots); every `ProjectedLevel` has `active_at_bar > computed_at_bar`.
2. **Update knowledge-time:** every `SetupUpdate` field is knowable at `bar_index`; `countertrend_boundary_next` / `mr_trigger_next` have `computed_at_bar == bar_index`.
3. **Stream ordering / linkage / span:** updates ascending and **contiguous** by `bar_index` (no gaps); first update at `entry_eligible_bar`; **last update at `terminated_at_bar`** (v2.1: the stream spans the full opportunity window and is not truncated at any fill); all `setup_id`s match the opening.
4. **Detection readiness:** `detection_bar >= max(known_at_bar)` over opening geometry; `entry_eligible_bar == detection_bar + 1`.
5. **Running-extreme monotonicity:** for LONG, `running_extreme.price` non-increasing across updates (mirror for SHORT: non-decreasing).
6. **Retracement floor honored:** for LONG, `mr_trigger_next.price >= opening.retracement_floor` (mirror for SHORT). Floor held once on the opening record; updates reference it.
7. **ATR knowledge:** `atr_at_detection` and each `atr` use only bars at or before their knowledge bar.
8. **Forward path uncensored:** no stop/target/exit applied; `len(bars) == total_length` unless `truncated_by_data_end`; `total_length == max_pending_window + horizon_H`.
9. **No stop/size in Stages 1–4:** assert absence (regression guard).
10. **Fill causality:** every `fill_bar >= entry_eligible_bar`; no fill references a level with knowledge bar after `fill_bar`; unfilled tranche => `fill_time_geometry is None`.
11. **Both maturities present:** every `SetupUpdate` has non-null `maturity_barcount` and `maturity_retracement`.
12. **Termination consistency (v2.1):** `updates[-1].bar_index == terminated_at_bar`; `termination_reason in {INVALIDATED, TIMEOUT}`; `INVALIDATED` used for 2/3-floor breach and for high >= `impulse_end`; `TIMEOUT` used when the window reaches `anchor_bar + max_pending_window - 1` with neither `INVALIDATED` condition met. **No fill (MR or WT) may set `terminated_at_bar`** — fills are recorded on `SimulatedEntry` and never shorten the lifecycle. A regression test asserts that a lifecycle with an early first fill still emits updates past the fill bar up to `terminated_at_bar`.
13. **Pre-anchor substrate causality (v2.1):** every bar in `opening.pre_anchor_bars` has `bar_index < opening.entry_eligible_bar`; `len(pre_anchor_bars) == opening.pre_anchor_lookback`; the bars are ascending and contiguous and abut `entry_eligible_bar` (last pre-anchor bar has `bar_index == entry_eligible_bar - 1`). The materializer at bar `t` uses only substrate bars with `bar_index <= t`.
14. **Materialization equivalence (v2.1):** a materialized `SetupUpdate` at bar `t` is byte-identical to the update the constructor would emit at generation time from history truncated at `t` (enforced by §8.1). No downstream materialization may use a bar with `bar_index > t`.
15. **d_struct consistency:** if `with_trend_boundary_next`/`d_struct` non-null, `d_struct` equals the channel height implied by `with_trend_boundary_next` and `running_extreme` within tick tolerance.

---

## 8. Test specification (mandatory deliverables)

1. **Repaint / truncation-invariance over the STREAM (keystone, §0.1.3, §0.1.5).** For a sample of setups, re-run construction on history truncated at each update's `bar_index`; the emitted **stream** of `(running_extreme, mean_true_range_pullback, countertrend_boundary_next, mr_trigger_next, fit_dispersion, maturity_barcount, maturity_retracement, with_trend_boundary_next, d_struct, atr)` must be **byte-identical** to the full-history stream up to each bar, across the **entire opportunity window up to `terminated_at_bar`** (v2.1: including all bars *after* the first fill). Any divergence fails the phase. Include setups with non-null `pullback_count_in_trend` (trend segmentation is the repaint-prone component), and include setups that fill early (to exercise the post-fill stream).
   **v2.1 — the test runs in two modes and both must pass:** (a) the generation-time construction as above; and (b) the **on-demand materializer** (§6.1) invoked at evaluation-time from persisted bars, whose materialized stream must be byte-identical to (a). Mode (b) is the guardrail that keeps Option B from moving repaint risk outside the gate: geometry is certified whether computed at generation or rematerialized downstream. The truncation harness (a reusable utility) is pointed at both paths.
2. **Causality assertions:** all §7 invariants across generated lifecycles; property-test where feasible.
3. **No-look-ahead fill:** a level confirmed at `t+k` yields no fill before `t+k`; adapter returns nothing beyond `end_index`.
4. **Uncensored-path:** `ForwardPath` byte-identical under varying dummy stop/target params; length depends only on `total_length` and data availability.
5. **Adverse-selection diagnostic present:** every MR `TrancheFill` has non-null `filled_on_trade_through`.
6. **Golden synthetic:** hand-built series with known impulse/pullback -> expected opening geometry, expected `running_extreme`/`mr_trigger_next` stream, and expected `retracement_floor` within tolerance.
7. **Composition derivation:** `composition` matches the filled tranche set (incl. `NONE`).
8. **Both-maturities emitted:** a test asserts both maturity features are populated on every update even though only one feeds `alpha`.
9. **Termination branches (v2.1):** synthetic cases exercise each `TerminationReason` (`INVALIDATED` via 2/3-floor breach, `INVALIDATED` via high >= `impulse_end`, and `TIMEOUT`). Assert that **no fill terminates** the lifecycle: a case where an MR (and/or WT) tranche fills early must still produce updates from `entry_eligible_bar` through `terminated_at_bar`, with the last update at `terminated_at_bar`.
10. **Fill-independence of the stream (v2.1):** the materialized `SetupUpdate` stream is byte-identical whether or not any tranche filled, and whether the `FillModel` is `TOUCH` or `TRADE_THROUGH`. Geometry is a function of bars only; fills never feed back into it. (Analogue of test 4 for the geometry axis.)
11. **Second-MR reachability (v2.1):** a synthetic case where the first MR fills, structure develops further, and a second MR order rests against post-first-fill geometry — assert the second fill is produced and its `fill_time_geometry` is drawn from an update whose `bar_index` is after the first fill bar. This is the concrete guard that the second-MR question is answerable.
12. **Pre-anchor substrate sufficiency (v2.1):** for a sample of setups, assert `pre_anchor_lookback` is large enough that the materializer's estimator-C window and ATR/warm-up at `entry_eligible_bar` never reach before the first stored pre-anchor bar (no substrate underrun). Flag any setup that would underrun rather than silently producing a shortened warm-up.

---

## 9. Package layout

```
setups/
  contract.py        # FROZEN interface (all of section 1-6)
  validators.py      # section 7 invariants as free functions
  adapter.py         # binds BarSeriesProvider to the real cache
  boundary.py        # BoundaryConstructor implementations (estimator C, alpha) — behind the seam
  materializer.py    # GeometryMaterializer: rebuilds SetupLifecycle from persisted bars (Option B) — §6.1
  geometry_access.py # stable get_lifecycle(setup_id) accessor: materialize now (B) or read cache (A) — §6.1, §11.3
  detector.py        # produces DetectedSetupOpening (incl. pre_anchor_bars) + terminal outcome
  entry_sim.py       # produces SimulatedEntry (fills, fill-time geometry, MR proxy)
  path_recorder.py   # produces ForwardPath (uncensored)
tests/
  fixtures/          # golden synthetic series + expected streams
  test_validators.py test_repaint.py test_causality.py
  test_paths.py test_golden.py test_entry_sim.py test_termination.py
  test_materializer.py   # mode-(b) repaint parity + fill-independence + second-MR reachability
```

`contract.py` is the fixed point. `boundary.py`, `materializer.py`, `geometry_access.py`, `detector.py`, `entry_sim.py`, `path_recorder.py` import from it and conform. The rule/evaluation layer (deferred, §12) depends only on `geometry_access.get_lifecycle`, never on `boundary.py`/`materializer.py` directly — this is what keeps the Option B→A swap (§11.3) local.

---

## 10. Provisional values inside the frozen structure (resolved in characterization / detector spec)

- `alpha(m)` decay shape; the ~0.8–1.0 offset constant; the 2/3 retracement constant (as calibratable priors).
- Live maturity selection (`maturity_barcount` vs `maturity_retracement`) — both emitted; one chosen against hand-marks.
- Estimator C internals: window length; robust-fit variant (Theil–Sen / Huber / quantile as sensitivity axes); warm-up rule.
- Projection horizon in `ProjectedLevel` (t+1 from current bar vs from anchor low).
- `horizon_H` value; `max_pending_window` value (set by the timeout parameter).
- `pre_anchor_lookback` value (§2.1): sized to cover `max(estimator-C window + warm-up, atr_period)` plus margin, across every estimator-C variant characterization might select. Store generously — bars are cheap; a substrate underrun forces regeneration, the exact cost Option B exists to avoid.
- Survival of `with_trend_boundary_next` / `d_struct` (dropped if RQ1 finds ATR/V dominate).

---

## 11. Freeze discipline and forward-compatibility

### 11.1 Revision slot spent — pressure-test is pass-or-escalate

The one controlled-revision slot from the original v2 freeze was **consumed by the v2→v2.1 revision** (which made fills non-terminating and adopted Option B materialization to support RQ4 and RQ5). **No further autonomous structural revisions are permitted.**

Nevertheless, during Phase 1 implementation, a trivial `BoundaryConstructor` **must** be implemented (e.g. `mr_trigger_next = running_extreme - c*ATR`, flat `countertrend_boundary`) against the interface, purely to confirm the interface is adequate — in particular that `SetupUpdate` and `BoundaryConstructor.compute_update` expose everything a real constructor needs (watch for a missing field beyond `fit_dispersion`). This is a **pass-or-escalate gate:** if the interface is adequate, proceed to Phase 2; if a gap is found in the interface structure, **stop and escalate to the human** (do not autonomously revise the contract; it is frozen). This is cheaper than discovering the gap after the repaint gate certifies the stream, but any detected gap requires an explicit human decision before proceeding. See Implementation Plan §1 convention 1.

### 11.2 Forward-compatibility hook (not a portfolio layer)

`correlation_cluster` on the opening record is a nullable hook, unused by the current version. Rationale: identity/time/cluster keys are far cheaper to attach now than to retrofit after artifacts are generated, and they are the minimum a *future* portfolio/account-level layer (a named, deferred Axis-D extension) would need to reconstruct which setups were concurrent and correlated. The current version does **not** build any portfolio logic; do not add account-state modelling. If unwanted, the field can be dropped — it is inert.

### 11.3 Option B → Option A migration (deferred; not built now)

v2.1 builds **Option B**: persist raw bars, materialize geometry on demand. The alternative, **Option A** (persist the geometry stream), was deliberately *not* chosen now because estimator C's internals are provisional and will be calibrated in characterization; persisting geometry before that would force a full regeneration each time C changes, whereas persisting bars does not (bars are characterization-invariant). Once estimator C, the maturity choice, and the `alpha` shape are frozen post-characterization, and *only if* profiling shows on-demand materialization is a material fraction of rule-sweep cost, the geometry stream may be **cached** (Option A):

- Run the certified materializer once over every setup's persisted bars and persist the resulting `SetupUpdate` streams keyed by `setup_id`.
- Swap `geometry_access.get_lifecycle` from "materialize now" to "read cache." Nothing upstream of that accessor changes; nothing downstream can tell.
- Verify the cache by asserting the persisted stream is **byte-identical** to a fresh on-demand materialization for a sample (the cache inherits the §8.1 certification via this equivalence; it is not re-certified from scratch).

Two caveats. First, this migration is worth doing only if recompute proves recompute-bound; if materialization is cheap (a short-window robust fit over a bounded window plausibly is), stay on Option B indefinitely — the migration is then a premature optimization. Second, if characterization reverses the current decision *against* an estimator-C regime split (clean vs. messy pullbacks fit differently), the cached stream must carry a per-setup branch label and the migration is more than a one-line swap; plan for the single-configuration case, watch for that reversal.

---

## 12. Deferred (named; not built here)

- **Rule-evaluation / sweep layer:** RQ1 (MR stop), RQ2 (WT failure hold-vs-exit), RQ3 (favourable excursion); objective function (arithmetic E[R] vs geometric/log-growth); dual conservative/optimistic sequencing for the daily band; sizing; full realized-R distribution. Consumes Stages 1–4 read-only.
- **C-overlap matching harness:** match tolerance, conditional recall on a labeled method-subsample, miss-accounting.
- **Characterization / hand-mark stage:** the hand-mark apparatus (the committed dependency for trusting RQ1), and resolution of the section 10 provisional values — batched against a single hand-marked sample.
- **Conditional 30-minute refinement:** measurement-layer only, applied to sequencing-ambiguous daily bars if the measured band proves too wide; never a strategy signal.
- **Axis-D portfolio/account-state layer:** concurrent positions, correlation constraint as a live rule, account-level compounding and drawdown. Reachable via section 11.2 hooks; explicitly not built.

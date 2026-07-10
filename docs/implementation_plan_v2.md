# Implementation Plan v2 — Pullback Tranche-Entry Backtest

**Status: build instructions.** This document defines *what to build, in what order, and how to know each step is done.* It assumes the **Project Brief** (the why) and the **Setup/Geometry Contract v2.1** (the frozen data interface) have been read. It does **not** specify the detector's structural thresholds or the boundary estimator's internals — those are in the **Detector Spec v1**, referenced where needed.

**This is v2 of the plan, reconciled to Contract v2.1.** The previous plan predated the setup-as-lifecycle model. Three families of change flow from the reconciliation, and the phase structure below embeds them rather than bolting them on:

1. **The setup is a lifecycle, not a snapshot.** The detector emits a static `DetectedSetupOpening` (including a bounded pre-anchor bar window) plus a terminal outcome; the per-bar causal geometry stream (`SetupUpdate` sequence) is a separate object. There is no `DetectedSetup` snapshot type anymore.
2. **Fills do not terminate the lifecycle (v2.1).** The entry-opportunity window — and its geometry stream — runs to `INVALIDATED` or `TIMEOUT`, never to first fill. Multiple fills per lifecycle are expected (in particular the second MR tranche, which rests and fills *after* the first).
3. **Geometry is materialized on demand, not persisted (Option B, v2.1).** Raw bars are persisted; the geometry stream is recomputed by a certified `BoundaryConstructor` driven by a `GeometryMaterializer`, reached only through a stable `geometry_access.get_lifecycle` accessor. This adds two modules (`boundary.py`, `materializer.py`, plus the accessor), and it adds a second mode to the keystone repaint test.

**Audience:** an AI coding agent in a Python codebase (Windsurf) containing the cache manager and data-vendor integration, with no access to the conversation behind these documents.

**Governing principle (from Brief §10):** prove the causal spine — no repaint, no censoring **on either axis** (price *and* entry-opportunity) — end to end on a *single market* before widening to the universe, fill realism, or rule evaluation. The phase structure operationalizes that. Do not reorder it to build breadth before the spine is verified.

---

## 0. Scope

**In scope for this plan:** the contract module; the input adapter; the boundary-constructor seam and a trivial constructor for the interface pressure-test; the on-demand geometry materializer and its stable accessor; the detector (per Detector Spec v1), which emits the opening record and the terminal outcome; the forward-path recorder; the entry-simulation/fill layer; the causal test suite; and widening to the full market universe.

**Explicitly out of scope (separate specs, named in §7):** the rule-evaluation/sweep layer that answers RQ1–RQ6, the real estimator-C internals (Detector Spec v1 owns those; this plan builds the *module and seam*, not the fit math), the C-overlap matching harness, the Option B→A geometry-cache migration, and any 30-minute refinement. Build the system so these attach cleanly later; do not build them now, and do not let anticipation of them add fields or logic to the modules in this plan.

**A note on the two new research questions.** RQ4 (MR trigger placement) and RQ5 (second MR tranche viability) are the questions that motivated Contract v2.1. This plan does not answer them — they live in the deferred rule-sweep layer — but the artifacts this plan produces must *support* them, which is exactly why the lifecycle now runs past fills and why the second MR tranche must be reachable in entry simulation (Phase 3). If a module built here would make RQ4/RQ5 unanswerable (e.g. by truncating geometry at a fill), that is a defect even if every test in that module passes.

---

## 1. Engineering conventions (non-negotiable)

These hold across every phase. Violating one is a defect regardless of whether tests pass.

1. **The contract is frozen and its one revision slot is spent — any structural change is human-escalation-only.** `contract.py` is transcribed from Contract v2.1 verbatim — same field names, types, enums, `known_at_bar` annotations, and protocol signatures. **Do not rename, retype, collapse, or "improve" any field.** If a field appears wrong or insufficient, **stop and raise it with the human; do not edit the contract.** Governance state (decided): the single controlled-revision slot the contract reserved (its §11.1 slot) was **consumed by the v2→v2.1 revision.** There is **no remaining autonomous revision.** Where Contract §11.1 reads as if a pressure-test-triggered revision is still reserved ("v2 gets one controlled revision"), that language is **superseded on this point** — it predates the decision recorded here. Consequently the interface pressure-test in Phase 1 is a **pass-or-escalate** gate: if it (or anything else) reveals that the frozen structure is inadequate, the coding agent **stops and raises it with the human** and waits for an explicit decision; it does **not** patch the contract itself. Treat every structural change as human-decision-only, full stop.

2. **The detector never imports the cache manager directly.** It depends only on the `BarSeriesProvider` Protocol (Contract §6.2). A thin adapter — written after inspecting the actual cache manager — binds the Protocol to the real cache. The adapter's `get_bars` **must not return bars beyond the requested `end_index`**; enforce this at the boundary, because it is the first line of defense against look-ahead. **The same applies to the materializer and boundary constructor:** they operate only on the persisted bar substrate handed to them (`pre_anchor_bars` + `ForwardPath.bars`), and at bar `t` they may use only substrate bars with `bar_index <= t`. Neither reaches back to the cache.

3. **Geometry is a pure function of bars; fills never feed back into it.** The `SetupUpdate` stream is computed from bars alone. No fill, `FillModel`, `EntryConfig`, stop, or size may influence any geometry value. This is the entry-opportunity-axis analogue of "no stop/target inline in path generation" (Brief §7, anti-default 1 and its sibling anti-default 5), and it is what makes the fill-independence test (Contract §8.10) pass. If geometry ever reads a fill, that is a critical bug.

4. **The rule/evaluation layer touches geometry only through `geometry_access.get_lifecycle`.** Downstream code never imports `boundary.py` or `materializer.py` directly. This clean-seam discipline is what keeps Option B safe (the constructor is reached through one certified path) and what makes the future B→A cache migration (Contract §11.3) a one-line swap behind the accessor. Build the accessor early and route everything through it, even in tests where calling the materializer directly would be shorter.

5. **The same certified constructor + maturity_fn are used at generation and at on-demand materialization.** Materialization is not a second, looser code path; it is the same causal computation re-run. Do not write a "quick" materializer that approximates the generation-time geometry. This identity is what lets the two-mode repaint test (Contract §8.1) certify the on-demand path.

6. **Determinism and reproducibility.** `setup_id` is a stable hash of `(symbol, timeframe, detection_bar, geometry)` so re-runs are identical and the later C-overlap harness can key on it. `param_hash` captures the full detector + constructor parameter set so any output is traceable to the configuration that produced it. Same inputs + same params ⇒ byte-identical outputs. No wall-clock, no RNG, no dict-ordering dependence in any value that affects output. Byte-identity is not a nicety here: two spine tests (repaint, uncensored-path) and the fill-independence test are byte-identity comparisons.

7. **Dataclasses stay pure data.** No detection logic, no I/O, no methods other than the derived read-only properties the contract specifies. Logic lives in the producing modules; validation lives in `validators.py` as free functions.

8. **Daily bars only (v1).** No timeframe alignment, no sub-bar logic. The contract's `intraday_high/low` fields stay `None`. (Rationale and the conditional future refinement are in Brief §8; do not implement the refinement now.)

9. **No look-ahead, enforced not hoped.** Every causally-derived value carries `known_at_bar`; the two-mode truncation-invariance test (Phase 1) is the enforcement over the *entire* geometry stream, generation-time and on-demand. Treat it as a build requirement, not a nicety.

---

## 2. Module and package layout

```
setups/
  contract.py        # FROZEN interface (Contract §1–§6): Bar, CausalPrice, ProjectedLevel,
                     #   enums, InstrumentMeta, StaticFeatures, DetectedSetupOpening,
                     #   SetupUpdate, SetupLifecycle, EntryConfig/FillTimeGeometry/
                     #   TrancheFill/SimulatedEntry, ForwardPath, and the Protocols
                     #   (BarSeriesProvider, MaturityFn, BoundaryConstructor, GeometryMaterializer)
  validators.py      # Contract §7 invariants (all 15) as free functions
  adapter.py         # binds BarSeriesProvider Protocol to the real cache manager
  boundary.py        # BoundaryConstructor implementations, behind the seam:
                     #   Phase 1 a trivial constructor (interface pressure-test);
                     #   Phase 2 estimator C + alpha offset per Detector Spec v1
  materializer.py    # GeometryMaterializer: rebuilds SetupLifecycle from persisted bars (Option B)
  geometry_access.py # stable get_lifecycle(setup_id) accessor: materialize now (B) [read cache = A, deferred]
  detector.py        # produces DetectedSetupOpening (incl. pre_anchor_bars) + terminal outcome
  path_recorder.py   # produces ForwardPath (uncensored)
  entry_sim.py       # produces SimulatedEntry (fills incl. 2nd MR, fill-time geometry, MR proxy)
tests/
  fixtures/          # golden synthetic series + expected opening geometry + expected stream
  test_validators.py
  test_repaint.py    # the keystone — TWO MODES (generation-time + on-demand materializer)
  test_causality.py
  test_paths.py
  test_golden.py
  test_termination.py    # termination branches; no fill terminates the lifecycle
  test_materializer.py   # mode-(b) repaint parity, fill-independence, 2nd-MR reachability, pre-anchor sufficiency
  test_entry_sim.py
```

`contract.py` is the fixed point. Every other module imports from it and conforms. `boundary.py`, `materializer.py`, `geometry_access.py`, `detector.py`, `path_recorder.py`, and `entry_sim.py` depend on it and on `adapter.py`; they depend on each other only through contract types and the `geometry_access` accessor.

---

## 3. Dependency graph

```
contract.py ──┬─> validators.py
              ├─> adapter.py ────────────> (real cache manager)
              ├─> boundary.py ─────────────┐
              ├─> materializer.py ─────────┤  (drives a BoundaryConstructor + MaturityFn over
              │                            │   persisted bars to yield a SetupLifecycle)
              ├─> geometry_access.py ──────┤  (composes materializer + certified constructor +
              │                            │   maturity_fn; exposes get_lifecycle(setup_id))
              ├─> detector.py ─────────────┤  (DetectedSetupOpening + terminal outcome)
              ├─> path_recorder.py ────────┤  (ForwardPath, uncensored)
              └─> entry_sim.py ────────────┘  (SimulatedEntry; consumes get_lifecycle + ForwardPath)

tests/ depend on all of the above.

Rule sweep + C-overlap harness (DEFERRED) will consume, READ-ONLY:
  geometry_access.get_lifecycle(setup_id) -> SetupLifecycle,
  SimulatedEntry, ForwardPath.
  They MUST NOT import boundary.py or materializer.py directly (convention 4).
```

Persistence note (Option B): the persisted artifacts are `DetectedSetupOpening` (incl. `pre_anchor_bars`), `ForwardPath`, `SimulatedEntry`, and the terminal outcome `(setup_id, terminated_at_bar, termination_reason)`. The `SetupUpdate` stream and the `SetupLifecycle` container are **not persisted** in v1; they are the return shape of the materializer. A downstream consumer cannot tell whether a `SetupLifecycle` was recomputed (Option B, now) or read from a cache (Option A, deferred) — that is the point of the accessor.

---

## 4. Build phases

### Phase 0 — Contract, validators, adapter (no detection or geometry logic)

**Goal:** the fixed interface exists and the system can read bars causally.

**Tasks**
- Transcribe `contract.py` verbatim from Contract v2.1 — all dataclasses, enums, and the four Protocols (`BarSeriesProvider`, `MaturityFn`, `BoundaryConstructor`, `GeometryMaterializer`). `TerminationReason` has exactly two members, `{INVALIDATED, TIMEOUT}`.
- Implement `validators.py`: each of the 15 Contract §7 invariants as a free function over the relevant dataclass, returning structured pass/fail (not bare asserts), so failures are diagnosable. Do not skip the v2.1-specific invariants: §7.3 (stream spans to `terminated_at_bar`, contiguous, no gaps), §7.12 (termination consistency; no fill sets `terminated_at_bar`), §7.13 (pre-anchor substrate causality), §7.14 (materialization equivalence — expressed here as a checkable property; enforced fully by §8.1).
- Inspect the cache manager; write `adapter.py` binding `BarSeriesProvider`. Confirm bar fields map to the contract `Bar` (bar_index, timestamp, OHLC, optional volume) and that `end_index` truncation is honored.

**Acceptance criteria**
- `contract.py` imports cleanly; field names/types/enum members/protocol signatures match the spec exactly (diff against the spec, not by eye). In particular `TerminationReason` is two-valued.
- `validators.py` runs on hand-built valid and invalid instances of every dataclass and correctly classifies both, including a lifecycle whose stream is (wrongly) truncated at a fill — it must be flagged by §7.3/§7.12.
- `adapter.get_bars(...)` returns ascending bars for one real market, inclusive of bounds, and **returns nothing beyond `end_index`** (test with an `end_index` mid-series; assert the last returned bar is exactly `end_index`).

---

### Phase 1 — Interface pressure-test + causal geometry spine on a single market (THE GATE)

**Goal:** prove no-repaint and no-censoring end to end — on both axes — before anything widens. Nothing in Phases 2–4 begins until this phase's tests pass. This phase also runs the Contract §11.1 interface pressure-test: confirm the `BoundaryConstructor`/`SetupUpdate`/`GeometryMaterializer` interfaces are adequate *before* the real estimator C is built.

**Tasks**
- **Trivial `BoundaryConstructor` (the §11.1 pressure-test).** Implement a deliberately trivial constructor in `boundary.py` — e.g. `countertrend_boundary_next` flat at the running extreme, `mr_trigger_next = running_extreme − c·ATR`, floored at `retracement_floor`. It must still populate `fit_dispersion` (or `None` during warm-up) and **both** maturity features (`maturity_barcount`, `maturity_retracement`) on every update, regardless of which one a real `alpha` would use. Purpose: confirm the interface exposes everything a real constructor needs (watch for a missing field beyond `fit_dispersion`). This is a **pass-or-escalate** gate, not a pass/escalate/self-fix gate: the §11.1 revision slot is already spent (convention 1), so **if a gap is found, stop and raise it with the human and wait for an explicit decision** — do not autonomously edit the contract, notwithstanding Contract §11.1's older "gets one controlled revision" wording.
- **`GeometryMaterializer` + `geometry_access`.** Implement `materializer.py` to drive the trivial constructor across the opportunity window: for each bar `t` in `[entry_eligible_bar, terminated_at_bar]`, assemble `bars_up_to_t` from `(pre_anchor_bars + ForwardPath.bars)` restricted to `bar_index <= t`, call `constructor.compute_update(...)`, and assemble the `SetupLifecycle`. **It must never pass a bar with `bar_index > t`.** Implement `geometry_access.get_lifecycle` as the stable accessor (Option B: materialize now). Route all geometry access — including tests — through it (convention 4).
- **Minimal but real detector.** In `detector.py`, emit a fully-populated `DetectedSetupOpening` — including a generously-sized `pre_anchor_bars` window (Contract §10) — with honest `known_at_bar` on every causal field, plus the terminal outcome. "Real" matters: use swing/pivot logic that *could* repaint if done wrong, or the repaint test tests nothing. It need not be the full spec; it must be causally honest. The terminal-outcome scan (find the first bar at which `INVALIDATED` fires — running extreme breaches `retracement_floor`, or price reclaims `impulse_end` — else `TIMEOUT` at `anchor_bar + max_pending_window − 1`) is part of this module; `terminated_at_bar` is causal (knowable only at the terminating bar's close).
- **`path_recorder.py`.** Anchor each `ForwardPath` at `entry_eligible_bar` (config-independent); record `total_length == max_pending_window + horizon_H` daily bars (provisional **H = 15–20 trading days + a fill-latency buffer**; make it a config value flagged for sign-off); set `truncated_by_data_end` when data runs out. **No stop/target/exit logic may touch this module.**
- Build the spine test classes (see §5).

**Acceptance criteria — all must pass on one market**

- **Two-mode repaint / truncation-invariance over the STREAM (keystone, Contract §8.1).** For a sample of ≥30 setups across varied dates: re-run construction on history truncated at each update's `bar_index`; the emitted **stream** — `(running_extreme, mean_true_range_pullback, countertrend_boundary_next, mr_trigger_next, fit_dispersion, maturity_barcount, maturity_retracement, with_trend_boundary_next, d_struct, atr)` — must be **byte-identical** to the full-history stream up to each bar, across the **entire opportunity window through `terminated_at_bar`**. This runs in **both** modes and both must pass: (a) generation-time construction; (b) the on-demand materializer invoked from persisted bars. Mode (b) parity is what keeps Option B from moving repaint risk outside the gate. The sample **must include** setups with non-null `pullback_count_in_trend` (trend segmentation is the repaint-prone component) **and** setups that fill early (to exercise the post-fill stream). Any divergence fails the phase outright.
- **Causality assertions (Contract §8.2):** all 15 §7 invariants hold across generated lifecycles; property-test where feasible.
- **No-look-ahead at the data boundary (Contract §8.3):** adapter returns nothing beyond `end_index`; the materializer never consumes a bar with `bar_index > t`.
- **Uncensored-path (Contract §8.4):** `ForwardPath` is **byte-identical** under varying (dummy) stop/target parameters — proves no rule logic leaked into path generation. Length depends only on `total_length` and data availability.
- **Fill-independence of the geometry stream (Contract §8.10):** the materialized `SetupUpdate` stream is **byte-identical** whether or not a (dummy) fill signal is present, and whether the `FillModel` is `TOUCH` or `TRADE_THROUGH`. Geometry is a function of bars only.
- **Termination branches (Contract §8.9):** synthetic cases exercise each `TerminationReason` — `INVALIDATED` via 2/3-floor breach, `INVALIDATED` via reclaim of `impulse_end`, and `TIMEOUT`. **Assert no fill terminates the lifecycle:** a case with an early (dummy) fill still emits updates from `entry_eligible_bar` through `terminated_at_bar`, last update at `terminated_at_bar`.
- **Pre-anchor substrate sufficiency (Contract §8.12):** for the sample, `pre_anchor_lookback` is large enough that the constructor's window + ATR/warm-up at `entry_eligible_bar` never reach before the first stored pre-anchor bar. Flag any would-be underrun rather than silently shortening warm-up.
- **Golden synthetic (Contract §8.6):** on a hand-built series with known impulse/pullback geometry, the detector emits the expected `impulse_origin`, boundaries, ATR, and `retracement_floor`, and the materialized stream emits the expected `running_extreme`/`mr_trigger_next` sequence, within tick tolerance.

> **Gate.** If any acceptance criterion fails, fix it here. Do not proceed to Phase 2. A repainting detector or a fill-censored stream discovered after Phase 3 means every excursion and every entry-placement statistic built on it is void.

---

### Phase 2 — Full detector + real boundary constructor, to spec

**Goal:** replace the minimal detector and the trivial constructor with the permissive-first detector and the real estimator C defined in **Detector Spec v1**, without breaking the spine.

**Tasks**
- Implement the detector per Detector Spec v1: tight structural skeleton (a real impulse-then-pullback must exist) with loose qualification. Qualifiers (`grimes_variant`, `pullback_count_in_trend`, `vol_ratio_at_detection`, `wick_indecision_at_detection`, `weekly_agreement_at_detection`) are emitted as **`StaticFeatures`** — never used to drop setups. Time-varying features live on `SetupUpdate`, not here.
- Implement the real `BoundaryConstructor` in `boundary.py` per Detector Spec v1: estimator C (robust short-window local fit to the countertrend-side extrema — pullback lows for LONG, pullback highs for SHORT — e.g. OLS, with Theil–Sen/Huber/quantile as sensitivity axes), the `alpha(m)` offset with its decay shape, the warm-up rule, and the projection horizon. **Both maturities remain emitted; only one feeds `alpha`, selected post-hand-mark.** Note explicitly in code: estimator C's internals are *provisional* and will be recalibrated in characterization — which is exactly why geometry is materialized from bars (Option B), not persisted, so recalibration forces no regeneration.
- **Field-set note (do not look for v1 fields).** Contract v2.1 has **no** `resting_orders` field and **no** `second_mr_entry` placeholder on the opening record. The MR entry level is the stream's `mr_trigger_next` (emitted by the constructor). The second MR level is supplied later by `EntryConfig.second_mr_level_rule` at entry-simulation time (Phase 3). WT trigger identification (`TriggerType`) is a Detector-Spec/entry-sim concern, not a stored opening field. If a v1-era field seems to be missing, it was removed by design; do not reintroduce it.
- Re-run the full Phase 1 spine suite against the new detector and real constructor.

**Acceptance criteria**
- All Phase 1 spine tests still pass with the full detector and real constructor (re-run, not assumed) — **both modes** of the repaint test especially.
- No qualifier gates emission: a test confirms setups with poor feature scores are still emitted.
- `known_at_bar` correctness re-verified for any new pivot/trend-segmentation logic. The trend-position feature is the most repaint-prone component; the two-mode truncation test must specifically include setups whose `pullback_count_in_trend` is non-null.
- The real constructor and the trivial constructor produce **materially different** geometry on the same setups (confirming estimator C adds signal, not noise) — a sanity check, not a byte-identity test.

---

### Phase 3 — Entry simulation and fill realism

**Goal:** turn setups into simulated fills, with honest fill mechanics, **multiple fills per lifecycle**, and the adverse-selection diagnostic.

**Tasks**
- Implement `entry_sim.py` producing `SimulatedEntry` from `(SetupLifecycle, EntryConfig)`, where the `SetupLifecycle` is obtained via `geometry_access.get_lifecycle` (never by calling the materializer directly):
  - MR limit fills and WT stop-limit fills, resolved from the forward path with the configured `FillModel` and slippage.
  - **Multiple fills are expected (v2.1).** The lifecycle no longer ends at first fill, so `tranche_fills` may hold several fills at different bars within one open window. In particular the **second MR tranche** rests and fills *after* the first MR fill, against **post-first-fill geometry** — a still-tracking `countertrend_boundary_next` or a fresh `running_extreme` from an update whose `bar_index` is later than the first fill bar. Take its level from `EntryConfig.second_mr_level_rule`. Both a rule that locks a static offset at the first fill **and** a rule that tracks the evolving boundary must be expressible; which is correct is a deferred rule-sweep question. Do not hard-code either.
  - **Second WT add (daily reformulation):** confirm follow-through on a daily *close* beyond the trigger by ~10%×D, then rest the add for the next session, subject to the "too far" cap (skip if the add is ≥40% of the way to the ⅓R target). If price runs without pulling back to the add level, the add does not fill — record "unfilled" as a valid outcome, not an error.
  - **Fill-time geometry (Contract §3):** capture `FillTimeGeometry` per fill from the update at the fill bar (fill-time snapshot, not detection-time) — this is what the rule layer consumes because boundaries move.
  - **MR adverse-selection diagnostic (daily proxy):** populate `filled_on_trade_through` via the close-based proxy — filled-and-closed-beyond ≈ trade-through (`True`); filled-and-closed-back-inside ≈ touch-and-reject (`False`). Document in code that this is a coarse daily proxy.
  - Derive `composition`.
- **Do not** compute or store stop or position size here. They belong to the deferred rule layer (Brief §7, anti-default 4; Contract §5).

**Acceptance criteria**
- **Fill causality (Contract §7.10, tested via §8.3):** every `fill_bar >= entry_eligible_bar`; no fill references a level with `known_at_bar > fill_bar`; unfilled tranche ⇒ `fill_time_geometry is None`. Test with a level confirmed late and assert no early fill.
- **Adverse-selection diagnostic present (Contract §8.5):** every MR `TrancheFill` has a non-null `filled_on_trade_through`.
- **Composition derivation (Contract §8.7):** `composition` matches the set of filled tranches across all combinations (incl. `NONE`).
- **Second-MR reachability (Contract §8.11):** a synthetic case where the first MR fills, structure develops further, and a second MR order rests against post-first-fill geometry — assert the second fill is produced and its `fill_time_geometry` is drawn from an update whose `bar_index` is *after* the first fill bar. This is the concrete guard that RQ5 is answerable.
- An unfilled second WT add produces a valid `SimulatedEntry`, not an exception.
- Assert absence of any stop/size field on `SimulatedEntry` (regression guard, Contract §7.9).

---

### Phase 4 — Widen to the full universe

**Goal:** run detector → path recorder → entry sim across all markets and full history, with data-quality and plausibility checks.

**Tasks**
- Bind `InstrumentMeta` (tick size, point value, slippage, spot-FX flag) for every market from the codebase source.
- Run the pipeline across the universe; persist the **Option B artifact set** keyed by `setup_id`: `DetectedSetupOpening` (incl. `pre_anchor_bars`), `ForwardPath`, `SimulatedEntry`, and the terminal outcome `(setup_id, terminated_at_bar, termination_reason)`. **Do not persist the `SetupUpdate` stream** — it is materialized on demand through `geometry_access`.
- Add a **generation-rate sanity check**: setups produced per market per year. A plausible count means the control population (un-traded setups) is usable; an implausibly high count means the permissive skeleton is too loose and the population is noise. Flag outliers for human review rather than silently accepting them.

**Acceptance criteria**
- Spine tests pass on a sample drawn from **across the universe** (not just the original single market) — including the two-mode repaint test.
- `InstrumentMeta` resolves for every market; "a few ticks" and slippage are expressed in real tick sizes.
- Generation rate is within a plausible band per market per year.
- Persisted artifacts reload and re-validate: `validators.py` passes on reloaded objects, **and** a `SetupLifecycle` materialized on demand from reloaded bars re-passes mode-(b) of the repaint test on a sample (the materialization equivalence, Contract §7.14/§8.1, survives a persistence round-trip).

---

## 5. Testing infrastructure

- **The two-mode truncation harness (Phase 1 keystone)** is a reusable utility: given a certified constructor + maturity_fn, a market, and a set of setups, it (a) re-detects/re-constructs on history truncated at each field's knowledge bar and diffs the generation-time stream, and (b) invokes the on-demand materializer from persisted bars and diffs *that* stream against (a). Build it once; Phases 1, 2, and 4 all use it. Both modes must produce byte-identical streams.
- **Property-based testing** for the §7 invariants (generate randomized valid geometries; assert invariants) catches edge cases hand-written cases miss. Include generators that produce early-fill lifecycles and non-null `pullback_count_in_trend`.
- **Golden fixtures** (synthetic series + expected opening geometry + expected materialized stream) live in `tests/fixtures/` and are version-controlled — the regression anchor independent of real data.
- **Byte-identity comparisons** (repaint, uncensored-path, fill-independence) require deterministic serialization: stable field order, fixed float formatting. Decide the serialization once and reuse it everywhere byte-identity is asserted.
- Tests run on synthetic data wherever possible (fast, deterministic) and on a small real-market sample for integration.

---

## 6. Definition of done (handoff state to the rule-sweep spec)

The plan is complete when, across the full universe:

1. The detector emits causally-clean `DetectedSetupOpening`s (incl. `pre_anchor_bars`) and terminal outcomes that pass the two-mode truncation test.
2. The geometry stream materializes on demand through `geometry_access.get_lifecycle`, runs contiguously from `entry_eligible_bar` to `terminated_at_bar`, is **never truncated at a fill**, and is byte-identical between generation-time and on-demand modes.
3. `ForwardPath`s are recorded uncensored, anchored at `entry_eligible_bar`, one per setup.
4. `SimulatedEntry`s are produced with honest daily fills, **multiple fills where warranted (including the second MR tranche against post-first-fill geometry)**, and the adverse-selection proxy.
5. All 15 §7 invariants and all 12 §8 tests pass.
6. Artifacts persist (Option B set) and reload under validation, and on-demand materialization survives the persistence round-trip.

At that point the rule-evaluation layer can attach: it consumes `get_lifecycle`, `SimulatedEntry`, and `ForwardPath` read-only and applies candidate stop/target/hold rules as pure functions over stored paths and materialized geometry. **No part of this plan computes an outcome in R, applies a stop, or sizes a position** — those first appear in the rule sweep.

---

## 7. Deferred (named so the system is built to receive them; not built here)

- **Rule-evaluation / sweep layer:** answers RQ1 (MR stop distance), RQ2 (WT failure hold-vs-exit), RQ3 (favourable excursion), **RQ4 (MR trigger placement)**, **RQ5 (second MR tranche viability)**, and RQ6 (WT early-continuation). Carries the objective-function choice (arithmetic E[R] vs. geometric/log-growth), the dual conservative/optimistic sequencing evaluation for the daily-data band, position sizing, the full realized-R distribution including sub-(−1R) gap outcomes, and the multiple-testing correction. Note the **joint** dependence of RQ1/RQ4/RQ5 (shared stop, shared sizing): the honest sweep is a joint grid, not three independent one-dimensional sweeps, which enlarges the rule count and tightens the correction (Brief §3, §9). Separate spec; consumes this plan's artifacts read-only through the accessor.
- **Option B → A geometry-cache migration (Contract §11.3):** once estimator C, the maturity choice, and the `alpha` shape are frozen post-characterization, *and only if* profiling shows on-demand materialization is a material fraction of rule-sweep cost, run the certified materializer once over all persisted bars, cache the `SetupUpdate` streams, and swap `geometry_access.get_lifecycle` from "materialize now" to "read cache." Verified by byte-identity against fresh materialization. A one-line swap behind the accessor *only if* convention 4 has been honored. Not built now; watch for the characterization-time reversal caveat (an estimator-C clean/messy regime split would make the cache carry a per-setup branch label).
- **C-overlap matching harness:** match tolerance, conditional recall against a labeled method-subsample, and miss-accounting discipline. Separate spec.
- **Characterization / hand-mark stage:** the hand-mark apparatus (the committed dependency for trusting RQ1) and resolution of the Contract §10 provisional values (estimator C internals, live maturity choice, offset constants, `with_trend_boundary_next` survival, `horizon_H`, `pre_anchor_lookback`). Separate spec.
- **Conditional 30-minute refinement:** surgical, measurement-layer-only, applied solely to sequencing-ambiguous daily bars *if* the measured band proves too wide. Never a strategy signal. Separate spec; only after the daily band is measured.

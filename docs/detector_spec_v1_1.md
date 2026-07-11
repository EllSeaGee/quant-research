# Detector Spec v1.1 — Pullback Tranche-Entry Backtest

**Status: DEFINITIONAL / PARAMETERIZED — values provisional, structure frozen elsewhere.** This document specifies *how a setup is structurally identified* and *how its per-bar geometry is constructed*. It is consumed by **Implementation Plan v2, Phase 2** ("per Detector Spec v1") for the real detector and the real `BoundaryConstructor`. It is the immediate blocker for that phase.

**Changelog — v1 → v1.1 (this revision).** If you (coding agent) have already implemented against v1, only the two items below changed. Everything else in this document is unchanged from v1.

1. **§4, criterion 2 (impulse efficiency).** Formula changed from `net_displacement / Σ|bar_close_to_close|` to `net_displacement / Σ TR(t)`, where `TR(t)` reuses the existing §7 True Range formula (`max(high−low, |high−prev_close|, |low−prev_close|)`), summed per-bar over the impulse leg. **`k_efficiency` changed from `0.55` to `0.35`.** Reason: the close-to-close version is blind to gaps and intrabar whipsaws that don't move the closing price — a bar can gap and round-trip violently intraday yet contribute the same small amount to the ratio as a calm bar covering the same close-to-close distance. Switching to True Range is provably one-directional (`Σ TR >= Σ|close-to-close|` always, since `low <= close <= high`), so the ratio can only fall under the new formula for any leg, including clean ones — `k_efficiency` had to come down to compensate, or every genuinely clean impulse would newly fail a threshold calibrated for the old, smaller denominator. `0.35` is a rough estimate (not empirically derived); flagged for verification against the 500-trade record before hand-marking.
2. **§4, criterion 3 (intra-impulse retracement).** `running_extent` and `max_adverse_run` are now explicitly defined on **intrabar highs/lows** rather than left ambiguous (the prior text specified the ratio but never stated the basis). This mirrors the basis `impulse_origin`/`impulse_end` are already defined on (§3's pivot primitive uses `high`/`low`), not a new convention. **`k_intra` changed from `0.40` to `0.45`.** Reason: unlike criterion 2, this basis change inflates both numerator and denominator, so there's no proof the ratio must move in one direction — but ordinary intrabar wick on retracement bars likely inflates the numerator somewhat more than the denominator on average, warranting a modest loosening. This is a softer, less-certain estimate than `k_efficiency`'s; flagged for the same empirical check, with lower confidence.

Neither change touches criterion 1 (extent, 1a/1b), the Keltner-band addition, `pre_anchor_lookback`, or the weekly-swing feature from the prior revision — those stand as previously specified.

**What this document is.** A research-design definition: the structural skeleton (impulse → pullback → trend position), the MR boundary/trigger construction (the unified offset model), the optional with-trend boundary line, the permissive-first qualification features, and the with-trend (WT) trigger recognition rules — each with a *provisional prior value* flagged for calibration and each *environment-dependent quantity* named as a "bind from codebase" parameter rather than hard-coded.

**What this document is not.** It is **not** a data-contract change and **not** a codebase-integration document. It assigns **values inside the frozen structure of Setup/Geometry Contract v2.1**; it introduces **no new fields, types, enums, or invariants**. The single controlled-revision slot of the contract is **spent** (Contract §11.1; Implementation Plan convention 1). If anything here reveals the frozen contract cannot express the detector, that is a **human escalation**, not a change this spec is licensed to make. The detector is architecturally walled off from the cache manager: it depends only on the `BarSeriesProvider` Protocol (Contract §6.2); the cache-facing binding lives in `adapter.py` and is out of scope here.

**Audience:** an AI coding agent in a Python codebase (Devin, formerly Windsurf) with the cache manager and vendor integration, and a human reviewer (LCG) who signs off the discretion-encoding thresholds (§8 of the drafting summary).

**Reading order:** Contract v2.1 (data shape, the binding authority) → Project Brief (why) → Implementation Plan v2 (build order) → this document (how a setup is identified). Where this document and the contract ever appear to conflict, **the contract governs** and the conflict is an escalation.

---

## 0. Tagging conventions used throughout

Every quantity in this spec carries exactly one disposition tag so the reviewer and the coding agent can see, at a glance, who owns it:

- **`[PROVISIONAL — sign-off]`** — a prior value I have assigned. It is a starting point, calibrated later in characterization. It should be reviewed by LCG (it encodes discretion) but does not block the build; the agent uses the stated value until told otherwise.
- **`[OPEN — characterization]`** — deliberately *not* assigned here. Writing it as settled would pre-commit a decision the characterize-before-optimize methodology keeps open. The build must keep it parameterized (often: keep two options live).
- **`[BIND — codebase]`** — an environment-dependent value the coding agent reads/confirms from the codebase at build time (tick sizes, bar-field names, roll conventions, history depth). The agent reports misfits via the pass-or-escalate discipline; the spec never guesses these.
- **`[FROZEN — contract]`** — fixed by Contract v2.1; restated here only for locality. Not editable.

A **direction convention** applies to the whole document: all rules are written for **LONG** and **mirror for SHORT** (highs↔lows, above↔below, `>=`↔`<=`). Where the mirror is non-obvious it is stated explicitly.

A **boundary-naming convention** also applies throughout, replacing directional terms ("upper"/"lower," "entry-side"/"far-side") that flip meaning between LONG and SHORT with two role-based terms that do not:
- **Countertrend boundary** — the boundary the MR limit rests against: the far edge of the pullback's excursion against the trend. Pullback lows for LONG, pullback highs for SHORT. Field: `countertrend_boundary_next` (fitted) and `running_extreme` (literal running value); see §8.
- **With-trend boundary** — the opposite (far-side) boundary, roughly where WT breakout triggers cluster and the point beyond which the pullback would resume the trend. Pullback highs for LONG, pullback lows for SHORT. Field: `with_trend_boundary_next`; see §9.

---

## 1. Scope

**In scope.** Definitions and provisional priors for: the swing/pivot primitive (§3); impulse identification → `impulse_origin`, `impulse_end` (§4); pullback identification → `pullback_start_bar`, `detection_bar`, `entry_eligible_bar`, `retracement_floor` (§5); trend segmentation → `pullback_count_in_trend` (§6); ATR fields (§7); the MR boundary/trigger construction — estimator C, `V`, `α(m)`, both maturities, `fit_dispersion`, `running_extreme`, the floor clamp (§8); the optional with-trend boundary line → `with_trend_boundary_next`, `d_struct` (§9); permissive qualification features → `StaticFeatures` (§10); WT trigger recognition rules for the `TriggerType` enum (§11); the pre-anchor lookback sizing rule (§12); and the terminal-outcome scan that yields `terminated_at_bar` / `termination_reason` (§13).

**Out of scope (named, not built here).** The cache adapter (`adapter.py`); the rule-evaluation / sweep layer (all stop/target/size/outcome logic — Contract §5, §12; these appear in **no** field this spec produces); the C-overlap matching harness; the characterization / hand-mark stage that resolves the `[OPEN]` items; any 30-minute refinement. The spec must be written so these attach cleanly, and must not add fields or logic in anticipation of them.

---

## 2. Causality discipline (the non-negotiable spine)

Every value the detector or constructor emits carries a `known_at_bar` (Contract §1.2, §7). A value is legitimate at bar `t` **only if it is computable from bars with `bar_index <= t`**. The two enforcement facts that shape every definition below:

1. **Pivot-type levels are known late.** A level defined by a swing pivot of strength `N` (§3) is *not* knowable at the pivot bar; it is knowable only `N` bars later, when the pivot is confirmed. Hence `known_at_bar = pivot_bar + N` (strictly greater than `defining_bar`, per Contract §7.1). This is the single most common source of accidental look-ahead and the reason `detection_bar` sits several bars after the impulse extreme.
2. **The two-mode truncation-invariance test (Contract §8.1) is the gate.** Every field defined here must emit byte-identically whether computed on full history or on history truncated at its own `known_at_bar`, in **both** the generation-time path and the on-demand materializer. Trend segmentation (§6) is the most repaint-prone component and is stressed specifically by that test; it is specified causally on purpose.

If any definition below cannot be made causal, it is a defect in the definition, not a licence to repaint — raise it.

---

## 3. The swing/pivot primitive (causal foundation)

Impulse endpoints, minor pivots (a WT trigger type), and trend segmentation all rest on one primitive, so it is defined once.

**Definition — strength-`N` pivot.** Bar `p` is a **pivot high of strength `N`** iff `high[p] > high[p−i]` for all `i ∈ 1..N` **and** `high[p] > high[p+j]` for all `j ∈ 1..N`. Pivot low mirrors with `low` and `<`. Ties (`==`) are treated as **not** a pivot (strict inequality) so that flat tops do not spuriously confirm; this is a `[PROVISIONAL — sign-off]` choice and an obvious sensitivity axis (strict vs. `>=`-with-first-occurrence).

**Causality.** A strength-`N` pivot at bar `p` is **confirmed only at the close of bar `p+N`**. Therefore any level anchored on it has `defining_bar = p`, `known_at_bar = p + N`.

**Prior.** `N_pivot = 2` **`[PROVISIONAL — sign-off]`**. Rationale: on daily bars a 2-bar pivot confirms in two sessions, which keeps `detection_bar` close to the impulse extreme (important because a large confirmation lag shrinks the usable pending window and delays entry eligibility), while still rejecting single-bar noise. Larger `N` (3–4) yields cleaner swings but later detection and fewer of the sharp *anti/snap* variants (§10) that resolve in 1–2 bars. `N_pivot` is an explicit sensitivity axis.

**Resolved input (affects this whole section).** LCG has confirmed there is **no existing swing/pivot logic** in the codebase (the environment is Devin, formerly Windsurf). This spec therefore **defines the structural vocabulary from scratch**, as written here; the coding agent implements the strength-`N` pivot to this definition rather than conforming to a pre-existing primitive. The reconstruction-error limitation the Brief commits to stating in every RQ conclusion is honest precisely because these definitions are deliberately authored and sensitivity-tested here, not inherited.

---

## 4. Impulse identification → `impulse_origin`, `impulse_end`

The impulse is the strong directional leg the pullback retraces. It must yield the two causal levels the opening record holds (Contract §2.1): `impulse_origin` (the swing point the move began from — the **invalidation anchor**) and `impulse_end` (the impulse extreme = pullback start).

**Structural definition (LONG).**
- `impulse_end` = a **pivot high of strength `N_pivot`** (§3). It is the local extreme from which the pullback begins. `defining_bar = impulse_end_bar`; `known_at_bar = impulse_end_bar + N_pivot`.
- `impulse_origin` = the most recent **pivot low of strength `N_pivot`** *preceding* the impulse leg, i.e. the swing low the up-move launched from. `defining_bar = impulse_origin_bar`; `known_at_bar = impulse_origin_bar + N_pivot` (already in the past by the time `impulse_end` confirms).
- The **impulse leg** is the bar span `[impulse_origin_bar, impulse_end_bar]`.

**Qualification thresholds (a real impulse must exist — this is the *tight* skeleton).** Criteria 2 and 3 must hold, and criterion 1 must hold via **at least one** of two sub-tests (1a OR 1b — see below). All values are `[PROVISIONAL — sign-off]` unless marked otherwise, and encode LCG's discretion about what "strong … sharp … little retracement" means:

1. **Extent — satisfied by either sub-test.** LCG's own discretionary practice judges extent by proximity to a Keltner channel rather than a fixed-origin ATR multiple. Both are kept live in v1 rather than choosing one, following the same "keep candidates parallel, let characterization decide" treatment already used for the dual maturity measures (§8) and the trend-segmentation proxy (§6).
   - **1a — ATR-multiple from origin.** `impulse_end.price − impulse_origin.price >= k_extent × ATR(impulse_origin_bar)`, with `k_extent = 2.0`. (Displacement of at least ~2 ATR distinguishes an impulse from ordinary drift.)
   - **1b — Keltner-band proximity.** Full definition immediately below this list (values LCG-specified: 20-period EMA, 20-period ATR, 2.25× multiplier).
   - **Extent passes if 1a OR 1b holds.** This widens the qualifying population (permissive-first, consistent with §10's philosophy); it never drops a setup the single-measure test would have passed.
2. **Sharpness / efficiency.** Over the impulse leg, `net_displacement / Σ TR(t) >= k_efficiency`, with `k_efficiency = 0.35`, **and** leg length `<= L_impulse_max` bars, with `L_impulse_max = 6`. `TR(t)` is the **same True Range formula already frozen in §7** (`max(high−low, |high−prev_close|, |low−prev_close|)`), summed per-bar across the leg rather than averaged over `atr_period` — reused, not redefined. **`[PROVISIONAL — sign-off; rough estimate, verify against the 500-trade record before hand-marking]`.** (Efficiency ≈ 1 means a near-straight move measured against actual intrabar/gap travel, not just where each bar happened to close; the cap on bar count prevents a slow grind from qualifying.) **Revised from v1** — see the changelog note near the top of this document for what changed and why.
3. **Low intra-impulse retracement.** The deepest counter-move *within* the leg satisfies `max_adverse_run <= k_intra × running_extent`, with `k_intra = 0.45`. Both quantities are now computed on **intrabar highs/lows**, not closes: `running_extent(t) = running_high(t) − impulse_origin.price`, where `running_high(t)` is the highest intrabar **high** reached so far in the leg; `max_adverse_run` is the deepest giveback from that running peak measured against subsequent intrabar **lows**. This matches the basis `impulse_origin`/`impulse_end` are already defined on (§3's pivot primitive uses `high`/`low`, not `close`), rather than introducing a new convention. **`[PROVISIONAL — sign-off; rough estimate, verify against the 500-trade record before hand-marking]`.** (No pullback larger than ~45% of progress-so-far inside the impulse itself; larger internal give-back means it is really two legs, not one impulse.) **Revised from v1** — see the changelog note near the top of this document for what changed and why.

**1b — Keltner-band proximity, full definition (LONG; mirror SHORT).**

- **Centerline.** `EMA_20(t)` = 20-period exponential moving average of `close`, seeded by the simple average of the first 20 closes in the lookback window, standard recursion (`α = 2/21`) thereafter. **`[LCG-specified]`.**
- **Band volatility unit.** `ATR_20(t)` = average True Range over a 20-bar period, using the same True Range formula as §7 (`max(high−low, |high−prev_close|, |low−prev_close|)` — gap-absorbing, `[FROZEN — method choice]`) and the same averaging convention (simple or Wilder) the coding agent uses for the existing `atr_period`-based series, so the two ATR series differ **only** in window length (20 vs. 14), not in method. **This is a distinct series from `atr_period`/`atr_at_detection` (§7) — do not conflate the two; name it `atr_20` (or equivalent) to avoid collision.**
- **Band multiplier.** `k_keltner = 2.25`. **`[LCG-specified]`.**
- **Band level.** `keltner_upper(t) = EMA_20(t) + k_keltner × ATR_20(t)` (mirror: `keltner_lower(t) = EMA_20(t) − k_keltner × ATR_20(t)` for SHORT).
- **Tolerance ("close, doesn't have to touch").** Expressed as a fraction of the same volatility unit that scales the band, so "closeness" moves with the same regime the band moves with: `keltner_tolerance(t) = k_tol × ATR_20(t)`, with **`k_tol = 0.25`** proposed as the v1 prior **`[PROVISIONAL — sign-off]`**.
  - **Mechanical note worth internalising:** "within `k_tol × ATR_20` of a `k_keltner × ATR_20` band" is algebraically identical to "reaching a `(k_keltner − k_tol) × ATR_20` band outright" — at the proposed prior, `k_tol` simply lowers the effective multiplier from 2.25 to 2.00. It is not an independent free parameter; it is a direct dial on the 2.25 you specified. 0.25 was chosen only because it lands on a round effective multiple for illustration — there is no evidence yet that this is the right amount of "closeness"; it is exactly the kind of value characterization should calibrate.
- **Pass condition.** `keltner_proximity_pass = impulse_end.price >= keltner_upper(impulse_end_bar) − keltner_tolerance(impulse_end_bar)`. Touching or exceeding the band is automatically satisfied by this inequality (the shortfall is ≤ 0), so no separate "touch or beyond" branch is needed.
- **Evaluation bar.** At `impulse_end_bar` — the pivot that already defines the extreme of the leg, so this reuses the existing anchor rather than introducing a new "where in the leg" question. `known_at_bar` for this pass/fail result equals `impulse_end`'s own confirmation bar, `impulse_end_bar + N_pivot` (§3) — `EMA_20`/`ATR_20` at `impulse_end_bar` are themselves ordinary causal rolling series (knowable immediately at that bar), so this introduces **no new look-ahead**; the binding constraint remains the pivot-confirmation lag already in the document.
- **Substrate consequence.** `EMA_20`/`ATR_20` need 20 bars of history *before* `impulse_end_bar`, which sits earlier than `entry_eligible_bar`. See §12 for the pre-anchor lookback consequence of this — the sizing rule there is updated to include this term.

**Rationale to preserve (so values are not "corrected" into a defect).** Criteria 2 and 3 encode "sharp rate of change" and "little retracement" from the trading method; criterion 1 (via 1a or 1b) encodes "large enough to matter" — 1a as raw displacement from the leg's own origin, 1b as extension relative to a rolling, volatility-adjusted mean, which is closer to LCG's actual visual heuristic for calling a leg impulsive. They are deliberately generous starting points, not tuned to any outcome. **Do not tighten any of them to maximise recovery of the 500 real trades** (Brief §4): recovery is a diagnostic, not a target, and tightening reintroduces selection bias and destroys the control population.

**Why 1a and 1b are OR'd rather than AND'd, and why that choice is itself provisional.** `[OPEN — characterization]` The two measures diverge predictably on later pullbacks within an established trend: an impulse launching from a pivot that already sits well above `EMA_20` (typical of a 2nd or 3rd pullback in a strong trend) can satisfy 1a's raw-displacement test comfortably while never reaching the Keltner band, because the centerline has been dragged up by the prior move. OR-logic keeps such setups in the qualifying population (permissive-first); it is not evidence that the two measures agree, and this divergence is exactly what hand-marking should quantify — in particular, whether setups passing on 1a alone (Keltner-fails) behave differently at `pullback_count_in_trend >= 2` than setups passing on both.

**Diagnostic persistence — resolved, not a contract question.** `StaticFeatures` (Contract §2.1) is a frozen, five-field dataclass with no open slot for an arbitrary new feature, and the contract's single controlled-revision slot is already spent (§11.1) — but this does not need to be worked around, because it does not need to be persisted at all. Once §12's sizing rule accounts for the Keltner reach-back (below), `pre_anchor_bars` contains everything needed to recompute `EMA_20`, `ATR_20`, the band, and both 1a/1b pass/fail for any setup, under any parameterization, on demand — this is exactly what Option B materialization exists for. A `keltner_proximity_pass` **field** would duplicate information already recoverable from stored bars, and worse, would freeze it under whatever `k_tol`/`k_keltner` values happened to be current at generation time; a persisted boolean computed under a provisional `k_tol = 0.25` goes silently stale the moment characterization revises that value, requiring full regeneration to correct, whereas a function recomputed from substrate is always current and can be swept across candidate `k_tol` values during characterization instead of being fixed to one. **Implementation:** the 1a-vs-1b comparison (including the `pullback_count_in_trend >= 2` divergence check above) is an **analysis-time function** over a materialized `SetupLifecycle`'s `pre_anchor_bars`, called from the hand-marking/characterization scripts — not a detector-emitted field, not a `StaticFeatures` addition, no contract change, no escalation.

**Counter-consideration — partially resolved this revision, not fully closed.** The gap-and-wick blind spot in criterion 2 (a close-based ratio cannot see a gappy, whippy leg whose closes happen to net a straight line) is addressed by the TR-based formula above: `Σ TR(t)` captures gaps and intrabar round-trips that `Σ|close-to-close|` was blind to, so a leg like that now scores a lower, more honest ratio. Two things remain genuinely open, not resolved by this change:
- **Single-bar dominance.** Whether a single efficiency scalar suffices, or a max-single-bar-contribution constraint is also needed (so one outsized bar can't carry the whole leg's ratio), is still `[OPEN — characterization]`. v1 uses the single scalar; the alternative remains a sensitivity axis, not a v1 branch.
- **Cumulative vs. single-worst-instance texture.** Criterion 3's `max_adverse_run` measures the single deepest giveback, not the leg's overall gappiness/choppiness. A leg with several smaller whipsaws, each individually under `k_intra`, still passes both criteria even after this revision — that remains an acknowledged, unresolved gap, not something the intrabar-basis switch fixes.

---

## 5. Pullback identification → `pullback_start_bar`, `detection_bar`, `entry_eligible_bar`, `retracement_floor`

**Pullback start.** `pullback_start_bar = impulse_end_bar` **`[FROZEN — contract]`** by construction (the impulse extreme is where the retracement begins). It anchors `maturity_barcount` (§8).

**Pullback validity (permissive on depth, strict on "is it a pullback at all").**
- **Lower volatility than the impulse.** `mean_TR(pullback_bars_so_far) <= k_vol × mean_TR(impulse_bars)`, `k_vol = 0.75` **`[PROVISIONAL — sign-off]`**. (The method's defining contrast: the pullback is calmer than the impulse.)
- **Some retracement present.** running retracement `>= d_min × (impulse_end − impulse_origin)`, `d_min = 0.10` **`[PROVISIONAL — sign-off]`** — enough to distinguish a pullback from a flat pause. This is a *minimum to be a setup at all*, **not** a preference filter: pullback depth beyond this is emitted through `maturity_retracement` (§8), never gated.
- **Upper bound is the floor, not a filter.** The pullback must not have already breached `retracement_floor` at detection; if it has, no valid setup exists (there is nothing left to enter). Depth between `d_min` and the floor is all admissible and scored, never dropped (permissive-first).

**`retracement_floor`** `= impulse_end.price − (2/3)(impulse_end.price − impulse_origin.price)` (LONG; mirror SHORT) **`[FROZEN — contract §2.1]`**. Held once on the opening record; the MR trigger may never cross it (§8). The `2/3` constant is a `[PROVISIONAL — sign-off]` prior carried from the method and calibrated in characterization, but the *field* and its clamp role are frozen.

**`detection_bar`.** The first bar at which **all** of the following are simultaneously true, evaluated causally (using only bars `<= detection_bar`):
1. `impulse_end` is pivot-confirmed → requires `detection_bar >= impulse_end_bar + N_pivot`.
2. `impulse_origin` is pivot-confirmed (already true by 1).
3. Impulse qualification (§4) passes.
4. Pullback validity (this section) passes, with at least `min_pullback_bars` pullback bars elapsed, `min_pullback_bars = 1` **`[PROVISIONAL — sign-off]`** (the estimator's warm-up, §8, handles the single-bar case; a value of 2 would defer detection until a line is fittable — a sensitivity axis).

Formally `detection_bar = max(impulse_end_bar + N_pivot, pullback_start_bar + min_pullback_bars)` subject to §4/§5 predicates holding. Contract §7.4 (`detection_bar >= max(known_at_bar)` over opening geometry; `entry_eligible_bar == detection_bar + 1`) is satisfied by construction because condition 1 forces `detection_bar` past the latest opening-geometry knowledge bar.

**`entry_eligible_bar` = `detection_bar + 1`** **`[FROZEN — contract]`** — the first session on which resting orders are live.

**Consequence to internalise.** Because `impulse_end` is a pivot confirmed `N_pivot` bars into the pullback, the detector *never* fires at the impulse extreme; it fires several bars later. This is causally correct, not a latency bug. It also means the earliest MR geometry the trader would form "at the 2-bar stage" corresponds to `maturity_barcount ≈ N_pivot`, which is why `α`'s high-offset regime (§8) starts around there rather than at bar 0.

---

## 6. Trend segmentation → `pullback_count_in_trend` (the repaint-prone component)

`pullback_count_in_trend` (Contract `StaticFeatures`, `int | None`) records whether this is the 1st, 2nd, 3rd… pullback of the current trend. The method prefers early pullbacks and treats late ones with caution — **as a score, never a gate** (§10). This is the component most able to repaint if written carelessly, so it is specified strictly causally.

**Causal trend definition (LONG).** An uptrend is an ongoing sequence of **higher pivot highs and higher pivot lows**, each pivot of strength `N_pivot` and therefore each confirmed `N_pivot` bars after its bar. The trend's **inception bar** is the confirmed pivot low that began the current run of higher-high/higher-low structure (i.e. the first higher-low after the prior structure break). All pivots used must have `known_at_bar <= detection_bar`.

**Counting rule.** `pullback_count_in_trend` = the number of qualifying impulse-then-pullback units (each a §4+§5 pass) whose `impulse_end` pivots are confirmed within `[trend_inception_bar, detection_bar]`, counting the current setup. If no trend can be established causally at `detection_bar` (insufficient confirmed structure), the value is **`None`** **`[FROZEN — contract allows None]`** — do not fabricate a count.

**Provisional structural parameters.**
- Trend-break rule: a confirmed **lower** pivot low (below the prior higher-low) ends the uptrend; the next higher-low starts a new count. `[PROVISIONAL — sign-off]`.
- Minimum structure to *declare* a trend: at least one confirmed higher-high **and** one confirmed higher-low after inception. `[PROVISIONAL — sign-off]`.

**Repaint hazard, stated bluntly.** The temptation is to segment the trend using the *most recent* swing structure visible at analysis time — which, on truncated history, differs from what was visible in real time, producing a different count for the same setup. That is exactly the repaint the two-mode truncation test (Contract §8.1, Implementation Plan Phase 1/2 acceptance) is designed to catch, and the acceptance criteria explicitly require the test sample to include setups with non-null `pullback_count_in_trend`. Treat every pivot used in segmentation as unknown until its `+N_pivot` confirmation bar. Do not use any smoothing or zig-zag that references future extrema.

**`[OPEN — characterization]`.** Whether swing-structure segmentation or an alternative causal trend proxy (e.g. a moving-average-slope regime, which is trivially causal but coarser) better matches the trader's sense of "1st/2nd pullback" is left open; v1 ships the swing-structure definition because it is closest to the method's language, and the alternative is a sensitivity axis, not a v1 branch.

---

## 7. ATR fields → `atr_at_detection`, `atr_period`, per-bar `atr`

- **`atr_period`** = 14 **`[PROVISIONAL — sign-off]`** (the conventional daily default; 20 is the obvious alternative and a sensitivity axis).
- **True range** = `max(high−low, |high−prev_close|, |low−prev_close|)` — the version that absorbs overnight gaps, which matters on daily futures. **`[FROZEN — method choice, mirrors V in §8]`**.
- **`atr_at_detection`** = ATR over the `atr_period` bars ending at `detection_bar`, using only bars `<= detection_bar`. `known_at_bar = detection_bar`.
- **Per-bar `atr`** on each `SetupUpdate` = ATR over the `atr_period` bars ending at that update's `bar_index`, causal at `bar_index`. This is the competing stop-volatility unit against `d_struct`; both are emitted so RQ1 can decide (Contract §2.2).

ATR warm-up interacts with the pre-anchor lookback (§12): the ATR window at `entry_eligible_bar` reaches `atr_period` bars back, which must lie within the stored substrate.

---

## 8. The MR boundary/trigger construction — the core of the spec

This formalises the unified offset model. The confirmed architecture (Contract §2.2; decisions record §3):

```
countertrend_boundary(t+1) = estimator C, projected to t+1                        # countertrend boundary
mr_trigger(t+1)            = countertrend_boundary(t+1) − α(m(t))·V(t)            # offset below it (LONG)
mr_trigger(t+1)            = max(mr_trigger(t+1), retracement_floor)              # never cross the floor
```

The constructor implements this behind the `BoundaryConstructor` Protocol (Contract §6.1) and must, on **every** `SetupUpdate`, populate `countertrend_boundary_next`, `mr_trigger_next`, `fit_dispersion` (or `None` in warm-up), `running_extreme`, `mean_true_range_pullback` (V), **both** maturity features, `atr`, and `with_trend_boundary_next`/`d_struct` (or `None`) per §9.

### 8.1 `running_extreme` — L(t)

`running_extreme` = the running literal extreme on the countertrend side of the pullback: the running minimum `low` for LONG, the running maximum `high` for SHORT (mirror), over pullback bars from `pullback_start_bar` through `t` **`[FROZEN — contract §2.2]`**: a step function, monotonic (non-increasing for LONG, non-decreasing for SHORT; Contract §7.5), never repainting. This is the literal extreme, **distinct** from the fitted `countertrend_boundary` (below), which is a robust fit over a window of such extremes, not the single most recent one. `running_extreme` feeds fill-time geometry, the invalidation scan (§13), and `d_struct` (§9). `known_at_bar = t`.

### 8.2 `countertrend_boundary_next` — estimator C

**Definition (confirmed).** Estimator C is a **robust short-window local fit to the countertrend-side boundary extremes** — for a **LONG**, the pullback **lows** (the boundary the MR limit is placed against); for a **SHORT**, the pullback **highs** — projected forward to `t+1`. The countertrend boundary is the boundary the MR limit order approaches: lows for longs, highs for shorts. The offset (§8.6) then rests the trigger just beyond it.

> **Resolved.** The earlier phrasing "OLS on pullback highs" (decisions record §3.2, drafting summary §5.2) is the **SHORT** case, where the countertrend boundary *is* the highs. For a LONG the countertrend boundary is the lows. This is now confirmed by LCG and the direction-aware definition above is authoritative; the separate *with-trend* boundary (§9) is the opposite-side boundary and is used only as a candidate stop-volatility unit.

**Fit variant.** OLS (least-squares line through the mean of the countertrend-side extrema) **`[PROVISIONAL — sign-off]`** as the default. Rationale: fitting through the mean lets individual extremes penetrate the line on both sides ("allow small penetrations"), which matches how the trader treats a boundary as a soft centre-of-mass rather than a hard envelope. **`[OPEN — characterization]`** sensitivity variants: Theil–Sen (robust to a single outlier low), Huber (down-weights outliers continuously), and quantile regression (a *supporting-line* fit through, say, the lower quantile rather than the mean). These are sensitivity axes; v1 ships OLS and does **not** build a variant-selection branch.

**Window length.** Fit over the last `min(pullback_bars_so_far, W_fit)` countertrend-side extrema, `W_fit = 8` **`[PROVISIONAL — sign-off]`**. Pullbacks are short, so a small window is both sufficient and more responsive; `W_fit` interacts with pre-anchor lookback sizing (§12).

**Projection horizon.** Project the fitted line to `t+1` (Contract `ProjectedLevel.active_at_bar == computed_at_bar + 1`, the default). **`[OPEN — characterization]`**: "t+1 from the current bar" vs. "t+1 measured from the anchor low." v1 uses *from the current bar*; the alternative is a value swap, not a structural change.

**Warm-up.** A line needs ≥2 points. With `min_pullback_bars = 1`, the first update may have a single countertrend-side extreme: during warm-up set `countertrend_boundary_next` = the single extreme (equivalently `running_extreme` for a long) projected flat to `t+1`, and `fit_dispersion = None` **`[FROZEN — contract permits None in warm-up]`**. From the second pullback bar onward the fit is defined and `fit_dispersion` is populated. `warm_up_bars = 1` **`[PROVISIONAL — sign-off]`**.

**`fit_dispersion`.** Residual dispersion of the fit — the RMS (or robust equivalent) of countertrend-side extrema about the fitted line **`[PROVISIONAL — sign-off]`** for the exact statistic. It is emitted as a characterization feature (a proxy for "clean vs. messy pullback"); it is **not** used to branch the estimator in v1 (Contract §0.2 / decisions record: single robust fit unless hand-marks show it fails — `[OPEN — characterization]`).

`known_at_bar = t` for the computation; the `ProjectedLevel` is `computed_at_bar = t`, `active_at_bar = t+1`.

### 8.3 `V(t)` — `mean_true_range_pullback`

`V(t)` = mean **true range** of the pullback bars from `pullback_start_bar` through `t` **`[FROZEN — method choice]`** (true range, not bar range, to absorb overnight gaps on daily futures — settled; the spec only states it). The first pullback bar's true range uses the impulse-end bar's close as `prev_close`, which is known, so `V` is defined from the first pullback bar. `known_at_bar = t`.

### 8.4 Maturity — `maturity_barcount` and `maturity_retracement` (BOTH emitted)

Both are populated on **every** update regardless of which one drives `α`; this is a hard contract invariant (Contract §7.11) that even the trivial Phase-1 constructor honours.

- **`maturity_barcount`** = `t − pullback_start_bar` (integer bars since the pullback began). Literal to the trader's "≤2-bar stage" language.
- **`maturity_retracement`** = `(impulse_end.price − running_extreme.price) / ((2/3)(impulse_end.price − impulse_origin.price))` (LONG; mirror SHORT) — the fraction of the 2/3 retracement budget consumed. Scale-invariant; unifies with the floor (reaches `1.0` exactly when `running_extreme` hits `retracement_floor`, i.e. at the `INVALIDATED` boundary).

**Which one drives `α` is `[OPEN — characterization]`.** Hand-marking selects it (which measure better predicts the trader's aggressiveness and outcomes). The spec must keep both live and must **not** hard-code the choice. For the build to be runnable before selection, `α` is defined over a *normalised* maturity `m̂ ∈ [0,1]` (§8.5) and the code exposes a switch defaulting to `maturity_retracement` **`[PROVISIONAL — default for runnable build only, not a selection]`**; the barcount path must be equally exercised so selection is a config flip, not a rewrite.

### 8.5 `α(m)` — the maturity-decaying offset

`α` starts high (order rests well below the boundary early, when misses are cheap and MR is less valuable) and decays toward zero and slightly negative (order creeps to the boundary and just inside it late, when misses are costly and breakout is imminent) — the cost asymmetry from the method. State this rationale so the values are not "corrected."

**Normalisation to `m̂ ∈ [0,1]`** (so either maturity can drive it):
- barcount path: `m̂ = clip((maturity_barcount − m_start)/(m_full − m_start), 0, 1)`, with `m_start = N_pivot` (≈ the "2-bar stage" after confirmation) and `m_full = 8` **`[PROVISIONAL — sign-off]`**.
- retracement path: `m̂ = clip(maturity_retracement, 0, 1)` directly (already normalised to the 2/3 budget).

**Decay shape and endpoints** **`[PROVISIONAL — sign-off]`**:
```
α(m̂) = α0 + (α_end − α0) · f(m̂)
```
- `α0 = 0.9` (midpoint of the method's 0.8–1.0 early offset).
- `α_end = −0.2` (allows entry slightly *inside* the boundary at full maturity — the trader's "eventually inside it").
- `f(m̂) = m̂` (linear) as the default shape. `[OPEN — characterization]` alternatives: convex `f = m̂^p` (holds the offset high, then collapses near maturity — matching "late misses are costly") and stepped (discrete regimes). v1 ships linear; convex is the leading sensitivity candidate given the stated asymmetry.

`α` itself, its shape, its constants, and the live-maturity choice are **detector-spec content, not contract content** (Contract §2.2 note): the contract emits `mr_trigger_next` plus its inputs so the value is transparent and reconstructible, but does not fix the formula.

### 8.6 `mr_trigger_next` — assembly and floor clamp

```
mr_trigger_next.price = max( countertrend_boundary_next.price − α(m̂)·V(t),  retracement_floor )   # LONG
                        min( countertrend_boundary_next.price + α(m̂)·V(t),  retracement_floor )   # SHORT (mirror)
```
`computed_at_bar = t`, `active_at_bar = t+1`. The clamp enforces Contract §7.6 (trigger never crosses the floor). Note the clamp can make the trigger *degenerate to the floor* on deep pullbacks — that is intended (it caps how far the MR order can reach) and downstream fill logic treats a floor-pinned trigger normally.

### 8.7 What the constructor must NOT do

- It must **not** read any fill, `EntryConfig`, stop, or size — geometry is a pure function of bars (Contract §7.9, Implementation Plan convention 3). The fill-independence test (Contract §8.10) enforces this.
- It must **not** use any bar with `bar_index > t` (the materializer restricts the substrate; the constructor must not reach around it).
- The **same** constructor + `maturity_fn` instances are used at generation-time and on-demand materialization (Contract §6.1 rule 2); there is no "quick" approximate materialiser.

---

## 9. Optional with-trend boundary → `with_trend_boundary_next`, `d_struct` (emitted-until-disproven)

The with-trend (far-side) boundary survives **only** as a candidate stop-volatility unit; the parallel-channel coupling is removed (Contract §0.2). It is **nullable** and may be dropped entirely if RQ1 finds ATR or V dominates `d_struct`.

**Definition.** `with_trend_boundary_next` is the **far-side** boundary — the opposite extrema from the countertrend boundary of §8.2: pullback **highs** for a LONG, pullback **lows** for a SHORT.
- `with_trend_boundary_next` = OLS fit to the far-side extrema, projected to `t+1` — the same fit machinery as estimator C, applied to the opposite extrema. **`[PROVISIONAL — sign-off]`** (this is the "OLS for with-trend boundary: accepted" decision from the record; it is a *different* line from `countertrend_boundary_next`, which is the countertrend boundary — §8.2).
- `d_struct` = the channel height, i.e. the absolute distance between `with_trend_boundary_next.price` and `running_extreme.price` (`with_trend_boundary_next.price − running_extreme.price` for LONG, mirrored to `running_extreme.price − with_trend_boundary_next.price` for SHORT, both taken positive). Because `running_extreme` and `with_trend_boundary_next` are already direction-neutral field names — each individually holding the correct literal price for either direction — this single mirrored formula is the whole rule; no separate SHORT-case relabeling of the fields themselves is needed. Contract §7.15 requires `d_struct` equal the channel height implied by `with_trend_boundary_next` and `running_extreme` within tick tolerance — conform exactly.

**Nullability.** Emit `with_trend_boundary_next`/`d_struct` from the first update at which the far-side fit is defined (≥2 far-side extrema); `None` during warm-up. `known_at_bar = t`; `active_at_bar = t+1`.

**`[OPEN — characterization]`.** Survival of `with_trend_boundary_next`/`d_struct` is decided by RQ1 (does a `d_struct`-scaled stop beat ATR/V-scaled?). Until then it is emitted; do not remove it, and do not let anything depend on it being non-null.

---

## 10. Permissive-first qualification → `StaticFeatures` (features, never filters)

These are emitted on the opening record and **never used to drop a setup** (Contract §2.1; Brief §4). Permissiveness is protective: it preserves the Option-C control population of untaken setups. **Do not tune any threshold here to recover the 500 real trades.**

- **`grimes_variant`** (`GrimesVariant`: `SIMPLE`/`ANTI_SNAP`/`NESTED`/`COMPLEX`/`UNCLASSIFIED`) — classify the pullback structure, do not filter. Provisional recognisers **`[PROVISIONAL — sign-off]`**:
  - `SIMPLE`: a single, roughly monotone retracement leg.
  - `ANTI_SNAP`: a sharp, deep counter-move against the prior swing resolving in few bars (high per-bar retracement rate; depth reached in `<= 2–3` bars). This is the variant most in tension with a larger `N_pivot` (§3).
  - `NESTED`: a smaller pullback contained within a larger one (a sub-impulse+sub-pullback inside the main pullback).
  - `COMPLEX`: a multi-leg corrective structure (≥2 legs) rather than one clean retrace.
  - `UNCLASSIFIED`: none of the above matched confidently.
  Classification is coarse in v1 and expected to be noisy; it is a scored feature, and its refinement is `[OPEN — characterization]`.
- **`pullback_count_in_trend`** (`int | None`) — from §6. A *score* (early preferred, late = caution), never a gate.
- **`weekly_agreement_at_detection`** (`float | None`) — signed agreement of the weekly trend direction with the daily setup direction, in `{−1, 0, +1}`. **Resolved: last confirmed weekly swing direction.** (The SMA-of-20-weekly-closes alternative previously named here is dropped; rationale below.) Compute from **completed** weekly bars only (`known_at_bar <= detection_bar`); never let a partial current week leak future information. Weekly resampling boundaries/session stamping are **`[BIND — codebase]`**.

  **Definition — weekly swing direction.** Mirrors the strength-`N` pivot primitive (§3), applied to weekly-resampled bars instead of daily. A weekly bar `w` is a **weekly pivot high of strength `N_pivot_weekly`** iff `weekly_high[w] > weekly_high[w−i]` for all `i ∈ 1..N_pivot_weekly` and `weekly_high[w] > weekly_high[w+j]` for all `j ∈ 1..N_pivot_weekly` (weekly pivot low mirrors, using `weekly_low` and `<`). Confirmed `N_pivot_weekly` weeks after `w`, same causal-lag mechanism as §3.
  - **`N_pivot_weekly = 1`** **`[PROVISIONAL — sign-off]`** — kept smaller than the daily `N_pivot = 2` deliberately: this is a soft diagnostic feature, not core structure, and a longer weekly confirmation lag would push `known_at_bar` needlessly far back for little benefit.
  - Scanning backward from `detection_bar`, find the **most recently confirmed** weekly pivot (high or low, whichever confirms first). If it is a pivot **high**, the last completed weekly swing just topped → direction = **−1** (down, post-top). If it is a pivot **low**, the swing just bottomed → direction = **+1** (up, post-bottom).
  - **Search cap.** `W_weekly_search = 6` weeks **`[PROVISIONAL — sign-off]`** — if no weekly pivot of either type confirms within 6 weeks scanning back from `detection_bar`, emit **`None`** rather than searching indefinitely (mirrors §6's "do not fabricate a count" rule for `pullback_count_in_trend`). Since this feature is a `StaticFeatures` diagnostic that is **never a gate** (§10 header), `None` here is an honest "no clear recent read," not a defect — expected to fire in genuinely rangebound weekly conditions.
  - **Total weekly reach:** `N_pivot_weekly + W_weekly_search = 7` completed weekly bars — the feature never needs to look further back than that. Converted to daily bars for §12's sizing rule (`[BIND — codebase]` for the exact trading-days-per-week count; ~5/week assumed): **≈ 35 daily bars**, versus the ~100 daily bars the dropped SMA(20-week) construction would have required.

  **Why the SMA(20-week) alternative was dropped.** It forced roughly 100 daily bars of pre-anchor storage onto *every* setup in the dataset, purely to support a feature that is explicitly never used to gate a setup (§10 header). The swing-direction construction needs at most ~35, is cheaper to reason about, and reuses a primitive (§3) already defined and justified in this document rather than introducing a new mechanism — it is the same pivot logic applied to a coarser timeframe.
- **`vol_ratio_at_detection`** (`float | None`) = `mean_TR(pullback_bars) / mean_TR(impulse_bars)` at detection. (`< 1` is the expected regime; it overlaps the §5 `k_vol` gate conceptually but is emitted as a continuous feature, not a threshold.)
- **`wick_indecision_at_detection`** (`float | None`) = a wick-prominence measure over the pullback bars — provisionally the mean of `(upper_wick + lower_wick)/range` across pullback bars, or the fraction of pullback bars whose wick ratio exceeds `0.5` **`[PROVISIONAL — sign-off]`**. Encodes the method's "indecision bars" caution as a score.

Time-varying features (`fit_dispersion`, maturities, per-bar `atr`) live on `SetupUpdate`, **not** here (Contract §2.1 note).

---

## 11. WT trigger recognition → `TriggerType` (definitions only; no stored opening field)

**Field-set reality (Contract v2.1, drafting summary §5.5) — do not reintroduce removed fields.** There is **no** `resting_orders` field and **no** stored WT-trigger field on the opening record. The MR entry level is the stream's `mr_trigger_next` (§8). The second MR level comes from `EntryConfig.second_mr_level_rule` at entry-sim time. WT trigger identification is a **recognition rule the entry simulator consumes** to place WT stop-limit orders; this section defines *how a trigger is recognised*, and produces **no** new stored field.

**Trigger definitions on daily bars** (each activated a few ticks beyond its structural level; the "few ticks" offset and tick size are **`[BIND — codebase]`**, provisionally `2 ticks`):
- **`INSIDE_BAR`** — `high[t] <= high[t−1]` and `low[t] >= low[t−1]`. Known at close of `t`.
- **`ID_NR7`** — an inside bar (as above) **and** `range[t] == min(range[t−6..t])`. Known at close of `t`.
- **`ID_NR5`** — inside bar **and** `range[t] == min(range[t−4..t])`. Known at close of `t`.
- **`PIVOT`** — a minor **strength-`N_pivot` pivot** within the pullback (§3), used as a with-trend trigger level. Known at `pivot_bar + N_pivot` — the entry simulator must respect this `known_at_bar` when deciding fill eligibility (no fill before confirmation).
- **`FAILURE_TEST`** — a bar that probes **beyond the countertrend boundary** (for a long, `low[t] <` the prevailing countertrend boundary / prior pullback low) and **closes back inside** (`close[t] >` that boundary): a rejection of the breakdown that then resumes with-trend. Known at close of `t`.
- **`LTF_PIVOT`** — a lower-timeframe pivot. **Not computable in daily-only v1** (it requires intraday data). The enum member exists `[FROZEN — contract]`, but the detector emits it **never** in v1; note this explicitly so its absence is understood as scope, not omission. If the conditional 30-minute measurement layer is ever added (Brief §8), LTF pivots would become recognisable — but only as measurement, never as a v1 strategy signal.
- **`OTHER`** — any recognised with-trend trigger not in the above set; the catch-all, kept permissive.

**Activation offset and the second WT add** are entry-sim concerns (Implementation Plan Phase 3), not detector fields: the daily reformulation of the "price acceptance beyond 10%×D" acceptance test and the "too far" (≥40% to ⅓R) cap live there. This spec only fixes the *recognition* of the trigger bars and their `known_at_bar`.

---

## 12. Pre-anchor lookback sizing → `pre_anchor_bars`, `pre_anchor_lookback`

The detector emits a **generously sized** pre-anchor bar window on the opening record so the on-demand materializer (Option B) can rebuild geometry without ever reaching back to the cache (Contract §2.1, §7.13; Implementation Plan Phase 1).

**Sizing rule.** `pre_anchor_lookback >= margin + max( W_fit + warm_up_bars, atr_period, weekly_swing_reach_in_daily_bars, (entry_eligible_bar − impulse_end_bar) + atr_period_keltner )`, evaluated across **every** estimator-C variant characterization might later select — because a substrate underrun forces the full regeneration Option B exists to avoid.

**Term-by-term, with current values:**

| Term | Source | Value |
|---|---|---|
| `W_fit + warm_up_bars` | estimator-C fit window (§8.2) | `8 + 1 = 9` |
| `atr_period` | §7 ATR | `14` |
| `weekly_swing_reach_in_daily_bars` | §10, resolved this revision | `(N_pivot_weekly + W_weekly_search) × ~5 ≈ 7 × 5 = 35` |
| `(entry_eligible_bar − impulse_end_bar) + atr_period_keltner` | §4.1b Keltner term | typical ≈ `4 + 20 = 24`; **not bounded above** — see the verification flag already on this term |

**New term (Keltner-band proximity, §4.1b).** Unlike the other terms, the Keltner `EMA_20`/`ATR_20` (period 20) is anchored at `impulse_end_bar`, not `entry_eligible_bar` — it sits *earlier* in time by however many bars the pullback ran before detection. Its reach-back from `entry_eligible_bar` is therefore `(entry_eligible_bar − impulse_end_bar) + 20`, not simply `20`. With `N_pivot = 2` and `min_pullback_bars = 1`, the typical case is `entry_eligible_bar − impulse_end_bar ≈ N_pivot + 2 = 4`, giving a typical reach of ~24 bars, but a slow-maturing pullback pushes this higher and it is **not bounded above** elsewhere in this document. `[OPEN — characterization / verify]`: confirm this against realistic pullback durations; if it exceeds the value below for a non-trivial fraction of setups, the value needs revisiting rather than silently trusted.

**Provisional value.** `pre_anchor_lookback = 45` daily bars **`[PROVISIONAL — sign-off]`** — the binding term is now the resolved weekly-swing reach (~35) rather than the dropped SMA(20-week) figure (~100), so the required value **drops from the prior 40-bar prior's implied insufficiency to a smaller, arithmetically consistent number**; 45 adds a ~10-bar margin over the ~35-bar weekly term and comfortably covers `atr_period = 14`, `W_fit = 8`, and the *typical-case* Keltner reach of ~24 — but see the verification flag above for the untypical Keltner case, which is the one term here still not rigorously bounded. **Store generously — bars are cheap; an underrun is expensive.** Contract §8.12 tests that no setup's window/warm-up ever reaches before the first stored pre-anchor bar; §7.13 tests that the window abuts `entry_eligible_bar` (last pre-anchor bar at `entry_eligible_bar − 1`) and is contiguous.

---

## 13. Terminal-outcome scan → `terminated_at_bar`, `termination_reason`

The detector's terminal scan produces the two persisted terminal fields (Contract §2.3; Implementation Plan Phase 1). `TerminationReason` has exactly two members (Contract §1.3) — **fills never terminate** (anti-default 5).

**Scan (LONG; mirror SHORT), from `entry_eligible_bar` forward:**
- **`INVALIDATED`** fires at the **first** bar where either:
  - `running_extreme.price < retracement_floor` (the 2/3 budget is breached — no valid pullback left), or
  - `high >= impulse_end.price` (the impulse extreme is reclaimed — the pullback has resolved to the upside; no pullback left to enter).
  `terminated_at_bar` = that bar; it is causal (knowable only at that bar's close).
- **`TIMEOUT`** fires if neither condition occurs within the window: `terminated_at_bar = anchor_bar + max_pending_window − 1`.

**`max_pending_window` = 10** daily bars **`[PROVISIONAL — sign-off]`** (the count of sessions a setup stays live awaiting a fill; a value, set by the timeout parameter, Contract §10). Rationale: the method rests orders a session or two ahead and holds working trades a few days to ~2 weeks, so a ~10-bar pending window covers realistic fill latency without letting stale setups linger; 5 and 15 are the sensitivity bounds.

The geometry stream (§8) spans `entry_eligible_bar → terminated_at_bar` inclusive and is **not truncated at any fill** (Contract §7.3, §7.12). The forward path extends `horizon_H` bars beyond the window (path-recorder concern; `horizon_H` provisional 15–20 + buffer, Contract §10).

---

## 14. Provisional-value summary (assign vs. leave open)

**Assigned here as priors (`[PROVISIONAL — sign-off]`; calibrated in characterization):**

| Parameter | Prior | Section |
|---|---|---|
| `N_pivot` (pivot strength) | 2 | §3 |
| `k_extent` (impulse extent, ×ATR, sub-test 1a) | 2.0 | §4 |
| `ema_period_keltner` (centerline, sub-test 1b) | 20 | §4 |
| `atr_period_keltner` (band unit, sub-test 1b) | 20 | §4 |
| `k_keltner` (band multiplier, sub-test 1b) | 2.25 | §4 |
| `k_tol` (Keltner "close enough" fraction, ×ATR_20) | 0.25 | §4 |
| `k_efficiency` (impulse efficiency, TR-based since v1.1) | 0.35 | §4 |
| `L_impulse_max` (impulse leg cap, bars) | 6 | §4 |
| `k_intra` (max intra-impulse retrace, intrabar-based since v1.1) | 0.45 | §4 |
| `k_vol` (pullback vol ≤ ×impulse vol) | 0.75 | §5 |
| `d_min` (min retrace to be a pullback) | 0.10 | §5 |
| `min_pullback_bars` | 1 | §5 |
| `atr_period` | 14 | §7 |
| estimator-C fit variant | OLS | §8.2 |
| `W_fit` (fit window, bars) | 8 | §8.2 |
| `warm_up_bars` | 1 | §8.2 |
| `α0`, `α_end` | 0.9, −0.2 | §8.5 |
| `α` decay shape `f` | linear | §8.5 |
| `m_start`, `m_full` (barcount normalisation) | `N_pivot`, 8 | §8.5 |
| with-trend boundary fit | OLS on far-side extrema (highs for LONG, lows for SHORT) | §9 |
| `N_pivot_weekly` (weekly pivot strength, §10 swing direction) | 1 | §10 |
| `W_weekly_search` (weekly swing search cap) | 6 wks | §10 |
| wick-indecision statistic | mean `(wicks/range)` | §10 |
| WT activation offset | 2 ticks | §11 |
| `pre_anchor_lookback` | 45 bars | §12 |
| `max_pending_window` | 10 bars | §13 |

**Left open (`[OPEN — characterization]`; the spec must keep parameterized, not settle):**

| Decision | Why deferred | Section |
|---|---|---|
| Which maturity drives `α` (barcount vs. retracement) | Selected against hand-marks; **both stay emitted** | §8.4 |
| Estimator-C regime split (clean vs. messy branch) | Ship single robust fit unless hand-marks show it fails; **do not build the branch** | §8.2 |
| `α` decay shape final (linear vs. convex vs. stepped) | Sensitivity axis; convex is the leading alternative | §8.5 |
| Projection horizon (from current bar vs. from anchor low) | Value swap, not structural | §8.2 |
| Final offset-constant calibration | Priors here; empirical values in characterization | §8.5 |
| `with_trend_boundary_next`/`d_struct` survival | Decided by RQ1 (does `d_struct` beat ATR/V?) | §9 |
| `grimes_variant` recogniser refinement | Coarse in v1; scored feature | §10 |
| Trend-segmentation proxy (swing structure vs. MA-slope) | Ship swing structure; alternative is sensitivity | §6 |
| Extent: 1a vs. 1b agreement/divergence, esp. at `pullback_count_in_trend >= 2` | OR-gated for v1 (permissive-first); divergence checked via an analysis-time function over stored bars, not a persisted field | §4 |
| `pre_anchor_lookback = 45` sufficiency given the Keltner reach-back term | Typical case fits; slow-maturing pullbacks unverified | §12 |

---

## 15. Resolved inputs from LCG (record)

All four drafting-stage inputs are now resolved. Recorded here so the coding agent and future contributors see the decisions and their date without re-litigating them.

1. **Estimator-C side — RESOLVED.** `countertrend_boundary_next` tracks the **countertrend** boundary: pullback **lows** for a LONG (the boundary the MR limit rests against), pullback **highs** for a SHORT. The earlier "OLS on pullback highs" phrasing was the SHORT case. §8.2 and §9 are updated to the confirmed, direction-aware definition; this is authoritative for the Phase-2 real constructor. (v2.2 naming revision: the field was subsequently renamed from `boundary_estimate_next` to `countertrend_boundary_next`, and the far-side `upper_next` field to `with_trend_boundary_next`, to remove the direction-dependent "upper"/"lower" naming this very resolution had to work around — see Contract v2.2 changelog.)
2. **Existing pivot/swing logic — RESOLVED.** There is **none** in the codebase; the environment is **Devin** (formerly Windsurf). §3–§6 therefore **define the structural vocabulary from scratch**, and the agent implements to this spec rather than conforming to a pre-existing primitive.
3. **Discretion priors (§14) — ACCEPTED for now, may be adjusted.** LCG accepts the §4 impulse thresholds (`k_extent`, `k_efficiency`, `L_impulse_max`, `k_intra`), `k_vol` (§5), `N_pivot` (§3), and the remaining §14 priors as starting values, reserving the right to adjust them later (during review or characterization). They remain tagged `[PROVISIONAL — sign-off]`; the build proceeds on them.
4. **`max_pending_window` (§13) — ACCEPTED for now, may be adjusted.** The provisional 10-bar window stands; LCG reserves later adjustment. It continues to drive the `TIMEOUT` boundary and, with `horizon_H`, the forward-path length.
5. **v1.1 revision — criteria 2 and 3 basis, RESOLVED.** Criterion 2 (efficiency) moved from a close-to-close denominator to a True Range denominator (§7's TR formula, reused) to close a gap/wick blind spot; `k_efficiency` moved `0.55 → 0.35` as a direct, provable consequence (TR-based sums are always `>=` close-based sums, so the ratio can only fall). Criterion 3 (intra-impulse retracement) had its basis made explicit — intrabar highs/lows, matching §3's own pivot basis — where it was previously unstated; `k_intra` moved `0.40 → 0.45` as a softer, non-provable estimate. Both new constants are rough starting priors, not empirically derived, and are flagged in §4 for verification against the 500-trade record before hand-marking. See the changelog block at the top of this document for the full reasoning.

**Still genuinely open (by design, not awaiting an answer):** the `[OPEN — characterization]` items in the §14 lower table — which maturity drives `α`, estimator-C regime split, final `α` decay shape, projection horizon, offset-constant calibration, `with_trend_boundary_next`/`d_struct` survival, `grimes_variant` refinement, and the trend-segmentation proxy. These are resolved by hand-marking/characterization, not by a drafting-stage sign-off, and the build keeps them parameterized.

---

## 16. Cross-reference map

| This spec produces | Contract home | Consumed by |
|---|---|---|
| `impulse_origin`, `impulse_end`, `retracement_floor`, `atr_at_detection`, `atr_period`, `detection_bar`, `entry_eligible_bar`, `pullback_start_bar`, `pre_anchor_bars`, `pre_anchor_lookback`, `StaticFeatures` | `DetectedSetupOpening` (§2.1) | detector.py (Plan Phase 1/2) |
| `running_extreme`, `mean_true_range_pullback` (V), `countertrend_boundary_next`, `mr_trigger_next`, `fit_dispersion`, `maturity_barcount`, `maturity_retracement`, `with_trend_boundary_next`, `d_struct`, `atr` | `SetupUpdate` (§2.2) | boundary.py behind `BoundaryConstructor` (Plan Phase 2), materialized via `geometry_access` |
| `terminated_at_bar`, `termination_reason` | `SetupLifecycle` / terminal outcome (§2.3) | detector.py terminal scan (Plan Phase 1) |
| WT trigger recognition (`TriggerType` semantics, `known_at_bar`) | `TriggerType` enum (§1.3) — no stored field | entry_sim.py (Plan Phase 3) |

**Governance reminder.** This spec assigns values only. Any finding that the frozen structure cannot express a needed definition is a **pass-or-escalate** event (Contract §11.1; Plan convention 1) — stop and raise it; do not edit the contract.

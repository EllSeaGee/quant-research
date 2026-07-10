# Project Brief — Pullback Tranche-Entry Backtest

**Read this first.** This is the orienting document for the engineering work. It explains *what the system is for* and *why it is built the way it is*. It deliberately does not contain the data schema (see the Setup/Geometry Contract), the build order (see the Implementation Plan), or the detector's thresholds (see the Detector Spec). Its job is to install the reasoning, so that locally-reasonable engineering choices do not silently violate the design.

**Reconciliation status.** This revision reconciles the Brief to two changes that post-date its original draft: (a) the **setup-as-lifecycle** model — a detected setup is a per-bar causal stream, not a single-bar snapshot — and (b) **Setup/Geometry Contract v2.1**, whose one controlled revision made fills *non-terminating* (the entry-opportunity window now runs to `INVALIDATED`/`TIMEOUT`, not to first fill) and adopted **Option B** materialization (persist raw bars, materialize geometry on demand). Where earlier Brief text assumed a pre-lifecycle or v2 world, it has been corrected. Two genuinely new research questions (RQ4, RQ5) are added; they are what motivated the v2.1 revision.

**Audience:** an AI coding agent, working in a Python codebase (Windsurf) that already contains a cache manager and data-vendor integration, with no access to the conversation that produced these documents. Where a decision looks arbitrary, the rationale is given so it is not "corrected" into a defect.

---

## 0. The document set and how it fits together

| Document | Answers | Status |
|---|---|---|
| **Project Brief** (this file) | *Why* the system exists; what it can and cannot prove; project-scope rules | orienting; reconciled to Contract v2.1 |
| **Setup/Geometry Contract v2.1** | *What shape* the data takes (frozen interface) | FROZEN structure; provisional values resolved in characterization; **one controlled revision consumed** (§11.1 slot) |
| **Implementation Plan v2** | *In what order* to build, with acceptance criteria | reconciled to Contract v2.1 |
| **Detector Spec v1** | *How* a setup is structurally identified, with permissive defaults | to follow |
| Deferred: rule-sweep spec, C-overlap harness spec, characterization/hand-mark spec | rule evaluation, trade-recovery check, provisional-value calibration | later |

Read the brief, then the contract, then the implementation plan, then the detector spec. Build against the contract; do not edit it. The contract is the **sole authority** on data shape; any earlier contract version or change memo is superseded and must not be consulted.

---

## 1. What this system is — and is not

**It is** a research instrument for refining the *rules* of an existing discretionary pullback-trading strategy: principally the stop-placement rule for mean-reversion entries, the entry-trigger placement for those entries, the hold-vs-exit decision for failed with-trend entries, the question of whether a second mean-reversion tranche is worth taking, and the favourable-excursion profile that informs targets and trailing.

**It is not** a system that validates, certifies, or optimizes the strategy as actually traded. This distinction is not pedantic; it determines what conclusions are legitimate. The trader uses discretion to qualify setups (impulse quality, pullback structure, trigger quality) and to manage trades (trailing, profit-taking). Discretion cannot be backtested. Any mechanical test either (a) replaces discretion with proxies — in which case it tests a *different* strategy — or (b) anchors on setups the discretion already selected — in which case it inherits that selection bias. **The output is therefore evidence about rules, conditioned on stated assumptions. It is never a verdict on the strategy itself.** Every conclusion document must restate this.

---

## 2. The strategy under study (context, not specification)

Daily-timeframe pullback trading. The trader identifies a strong directional impulse, then a lower-volatility pullback from it, then enters in up to three **tranches**, each risking ~⅓R, with total trade risk capped at 1R:

- **Mean-reversion (MR) tranche:** a limit order at/just beyond the **countertrend boundary** of the pullback — the boundary marking the deepest point of the pullback's excursion against the trend: the pullback's lows for a long, the pullback's highs for a short. Intended to catch the pullback's exhaustion. There may be a **second MR tranche**, resting deeper and filling *after* the first while the pullback is still developing; it shares a common initial stop with the first, so the deeper fill carries proportionally larger size (see RQ5).
- **With-trend (WT) tranche:** a stop-limit order a few ticks beyond a structural trigger (inside bar, ID-NR7/NR5, pivot, failure test). Intended to catch resumption of the trend. A second WT add is possible on daily-close follow-through, subject to a "too far" cap.

Orders rest *before* the session in which they may trigger. `R` = one unit of risk = 2% of account value. Position size for a tranche is set so that a move from entry to the initial stop loses ⅓R — meaning **size is a function of the entry-to-stop distance**, which is exactly why the stop rule is worth studying and why size must never be hard-coded upstream of it. Because the MR *entry level* (trigger), the MR *stop*, and the *second MR level* all feed the same sizing arithmetic and share a stop, they are studied jointly, not in isolation (see §3).

This summary exists so the agent understands the domain. The authoritative behavioural details live in the detector and entry-simulation specs.

---

## 3. Research questions

The strategy's entry structure has two axes that the machinery must keep uncensored: the **price axis** (how far a filled trade runs before an exit truncates it) and the **entry-placement axis** (over what window, and on what terms, an order could still fill). RQ1–RQ3 are primarily price-axis questions answerable over already-stored fill-time geometry; RQ4–RQ5 are entry-placement questions that require geometry to keep evolving *after* a fill — the capability v2.1 restored (see §4, §7).

**Primary.**

- **RQ1 — MR stop distance.** How far beyond the pullback boundary should the MR tranche's initial stop sit? The incumbent rule (entry − one full pullback depth `D`) over-widens on deep pullbacks, placing the stop below the **impulse origin** — the level at which the trend thesis is already invalid. Candidate rules to sweep include `k×D`, `impulse_origin ∓ m×ATR`, MAE-quantile rules, and hybrids such as `tighter_of(1.0×D, impulse_origin − m×ATR)` with a floor near `0.75×D`. *Price-axis; supported by stored fill-time geometry over the uncensored path.*

- **RQ2 — WT failure: hold overnight vs. exit at close.** When a WT entry triggers, makes some progress (~0.3R), then closes back at/inside the pullback boundary, which *kinds* of failure justify holding to the next session versus exiting at the close? *Reconstructable from stored OHLC, fills, and the update stream; no contract change was required.*

- **RQ3 — favourable excursion vs. structure.** How far do favourable moves run, expressed in `D`, `ATR`, and `R`, and — critically — with what intervening give-back (heat-before-reward)? This informs targets and trailing. *Price-axis; a pure function over stored paths.*

- **RQ4 — MR trigger (entry-level) placement.** *(New.)* Where should the MR limit rest so that it fills often enough to matter, trading fill probability against entry quality? A shallower trigger fills more often but at a worse price and with a nearer target; a deeper trigger fills rarely (and adversely-selected — it fills preferentially when the pullback *fails through* the boundary) but at a better location. This is inherently a **counterfactual** question: for a candidate trigger depth, how often would it have filled, and on what terms, *across the whole opportunity window*. Answering it requires the boundary/volatility/maturity forecast to keep evolving after the bar a real trigger would have filled — precisely the geometry the pre-v2.1 lifecycle discarded at first fill. RQ4 is one of the two questions that motivated Contract v2.1.

- **RQ5 — Second MR tranche viability.** *(New.)* Is a second MR tranche worth taking at all, and if so, where should it rest? By construction it rests deeper and fills *after* the first MR fill, under a common stop, so it carries a larger share of the 1R budget and a larger size. Evaluating it requires post-first-fill geometry (a still-tracking countertrend boundary, a fresh running extreme, updated maturity) — the same capability RQ4 needs, and the second question that motivated v2.1. The prior Brief listed "define/optimize the second MR level" only as a deferred meta-item; it is promoted here to a first-class research question.

- **RQ6 — WT early-continuation probability.** *(Adjacent; already supported.)* When a WT tranche is entered *early* in the pullback, what is the probability it reaches a full ⅓R before failing? The **outcome** side is a stop/target-dependent pure function over the stored path (an RQ3-family computation). The **conditioning** side ("early in the pullback") requires a join to the pullback's maturity at the fill bar; v2.1 guarantees that join is always well-defined, because the geometry stream now runs through window-close and therefore *every* fill bar has a corresponding update to read maturity from. Listed here because the trader named it explicitly; no contract change was needed for it.

**The joint-dependence caveat (important).** RQ1 (MR stop), RQ4 (MR trigger), and RQ5 (second MR level) are **not independent**, and must not be optimized one at a time as three separate one-dimensional sweeps. They couple through sizing and a shared stop: the stop sets size (`size = risk / (entry − stop)`); the trigger sets the entry; the second tranche's deeper entry under a *common* stop enlarges its size and its share of the 1R budget. Optimizing any one against fixed-but-arbitrary settings of the others finds a local artifact. The eventual rule sweep should treat these jointly (a modest joint grid), accepting that the joint sweep multiplies the rule count and therefore tightens the multiple-testing correction (§9). This is flagged now so later specs plan for it rather than discovering it late.

**Secondary / meta (deferred but recorded so the architecture supports them):**

- Does the tranche structure earn its complexity? Decompose expectancy by composition (MR-only, WT-only, mixed) versus a single full-size entry.
- Time-stop: does expectancy decay past a max hold?
- Does the correlation-avoidance rule cost or save expectancy? (Portfolio/account-level; needs an Axis-D layer not built in v1 — see §9 and Contract §11.2.)
- Do the discretionary qualifiers (impulse quality, pullback position, wick/indecision) predict outcome when proxied mechanically?

---

## 4. The central data problem (why the architecture is non-obvious)

There is a record of 500+ real trades, but it holds only entry/exit dates, initial stop, sizes, and entry/exit prices — **not** the pullback boundaries, impulse origin, ATR-at-entry, setup type, or trigger levels the method is parameterized on. The trades were also not all taken with this method. Two independent contaminations follow, and conflating them is the classic way this study fails:

1. **Censoring.** Every realized price excursion was truncated by whatever stop/exit was actually used. The adverse-excursion data RQ1 needs was destroyed by the historical stop policy. Naive maximum-adverse-excursion analysis on realized trades is therefore not merely noisy here — it is *biased toward the policy that generated the sample.*
2. **Specification mismatch.** Realized entries were not placed at this method's tranche levels, so the trades evidence *setups identified*, not *how this method trades them*.

Consequence: realized trades can characterize **setups**; they cannot validate **rules**. Rules must be tested against price paths that the historical policy did not truncate.

**There are two censoring axes, not one.** The censoring above is on the **price axis** — the historical exit truncated how far the trade was observed to run. There is a second, structurally identical hazard on the **entry-placement axis**: if the setup's geometry stream is terminated at the first fill, the boundary/volatility/maturity forecast stops being computed exactly where RQ4 (counterfactual trigger fills) and RQ5 (a second tranche resting *after* the first) would read it. Terminating at first fill censors the entry-opportunity window the same way a stop censors the price path. v2.1 removed that second censoring by making fills non-terminating (see §7, anti-default 5); this Brief treats the two axes as the same problem seen twice.

**Anchoring decision (settled): option C, hybrid.** Build a setup **detector** over full history; check what fraction of the 500 real trades it recovers; use it to expand the sample with a control population of setups the trader did *not* take. The detector is **permissive-first**: a *tight structural skeleton* (a real impulse-then-pullback must exist) but *loose qualification* (the quality filters start wide and are emitted as scored features, not used to drop setups). Permissiveness is deliberate and protective — it preserves the control group. **Do not tune the detector to maximize recovery of the 500 trades**; doing so reintroduces the trader's selection bias through the back door and discards the control group the hybrid exists to create. Detector/trade overlap is a *diagnostic*, not an accuracy score to maximize, because some real trades were other strategies and *should* be missed.

---

## 5. The architectural principle

**Separate path generation from rule evaluation, and generate the raw substrate uncensored, once.**

For each detected setup: reconstruct geometry, place the method's hypothetical orders, and record the **full forward price path** over a fixed horizon **with no stop and no target applied.** Then evaluate every candidate rule (stop, target, hold/exit, trail) as a **pure function over the stored path.** This is what makes a rule *sweep* both correct (same underlying data, only the rule varies) and cheap (no re-simulation per variant), and it is the direct structural answer to the censoring problem.

The forward path is anchored at a **config-independent** bar (the first session orders are live), so a single stored path serves every entry/stop/target variant. Excursion-from-fill is a slice computed downstream.

**Why store artifacts at all, rather than a fused single-pass backtest loop?** A fused engine that runs detection, rules, and price-tracking together in one bar-by-bar pass embeds exactly one rule per run. Sweeping many candidate rules would then mean re-running detection for every variant (expensive) and risks accidental coupling between detection logic and rule logic — the precise coupling the causal-honesty tests exist to forbid. A fused pass also cannot naturally produce the Option-C **control population** of untaken setups, which requires a rule-*independent* detection pass over full history. Separating generation from evaluation makes sweeps both cheap (one detection pass, many evaluations) and provably safe (the geometry is byte-identical across rule variants because no rule touched it).

**The setup is a lifecycle, not a snapshot.** Entry levels move as the pullback develops, so a single detection-time snapshot cannot represent a forecast that updates each bar. A detected setup is therefore a **static opening record** (impulse geometry, ATR, static qualifiers, all fixed at detection) plus a **per-bar causal geometry stream** (running countertrend extreme, pullback volatility, projected countertrend boundary, projected MR trigger, both maturity measures) that runs from the first live-order bar (`entry_eligible_bar`) to the close of the **entry-opportunity window**. That window closes on exactly two conditions — `INVALIDATED` (the pullback ceases to be a valid pullback: the running extreme breaches the 2/3-retracement floor, or price reclaims the impulse extreme) or `TIMEOUT` (the pending window is exhausted). **Fills are not window closers.** A fill is an event *within* an open window, recorded separately; the stream keeps emitting past it (this is what makes RQ4/RQ5 answerable). The full mechanics live in the Contract; this Brief states only the principle so downstream choices respect it.

**How the geometry is stored (Option B, stated once).** The causal geometry stream is **not persisted** at generation time. Instead the **raw bars** are persisted (a bounded pre-anchor lookback window plus the forward path), and the geometry stream is **materialized on demand** by the certified boundary constructor behind a single stable accessor. The reason is deferral: the boundary estimator's internals are still provisional and will be calibrated in characterization, so persisting the fitted geometry now would force a full regeneration each time the estimator changes — whereas persisting bars does not, because raw bars are characterization-invariant. This is contract/implementation mechanics and is cited here only because it shapes what "generate once, evaluate many" means: the thing generated once is the *bar substrate*, and the repaint/truncation-invariance test is extended to certify the on-demand materialized stream as well as the generation-time stream. (Storage strategy, the accessor seam, and a later cache migration are Contract §6.1/§11.3; do not re-derive them here.) The discipline governing which such changes are even permitted is §6.

---

## 6. Change discipline — what may change at generation-time vs evaluation-time

This principle governs how the contract is allowed to evolve, and exists so future contributors neither over-engineer the artifact store for hypothetical questions nor under-protect it against named ones. It is stated at top level, rather than buried in the architecture section, because it is the operative test applied to *every* proposed contract change over the life of the project.

- **Generation-time** is when the detector, boundary constructor, path recorder, and entry simulator run once and write artifacts to storage. Whatever is *not* captured here is gone; recovering it later means re-running generation over full history and the full universe, and re-passing the repaint gate. Expensive.
- **Evaluation-time** is when the rule-evaluation layer reads already-persisted artifacts and computes an answer as a pure function. Adding a new evaluation-time function costs the stored artifacts nothing. Cheap to defer indefinitely.
- **Rule:** the only changes that should happen *now*, at generation-time, are **information-preserving** ones — retaining more raw data. **Interpretation-adding** changes (precomputed R, failure-type enums, stop levels, anything that encodes what a specific question *means*) belong in the deferred rule-evaluation layer and are added only when a concrete, named question needs them.
- **Test to apply to any proposed contract change:** does answering the question require re-invoking the detector/constructor with bars or history it was never given? If yes, it is a generation-time change — and should be made now *only if the question is already named*. If the answer is arithmetic over what is already stored, it is an evaluation-time change and is always safe to defer.
- **v2.1 is the worked example.** It was an information-preserving generation-time change (stop discarding raw geometry-input bars at first fill; add a bounded pre-anchor bar window) made for two *already-named* questions, RQ4 and RQ5. It added **no interpretive fields.** Everything else stays build-as-needed.

---

## 7. The five project-scope anti-defaults

A coding agent without this context will reach for conventional choices, each silently wrong here. These are restated from the contract at *project* scope because they govern modules the contract does not reach. They correspond one-to-one with the Contract's §0.1 five anti-defaults.

1. **Never apply stops/targets inline during path generation.** That censors the data. Stops live only in the downstream rule evaluator.
2. **Never assume touch-fills on the MR limit.** The MR limit fills preferentially on setups *failing through* the boundary — adverse selection. Whether the MR edge survives realistic fills is potentially make-or-break for RQ1, and bears directly on RQ4/RQ5 (which are fill-probability questions). Model trade-through and record a diagnostic for every MR fill.
3. **Never use a repainting (look-ahead) detector.** A level defined with hindsight contaminates every excursion statistic downstream. The contract's `known_at_bar` annotations and the truncation-invariance test exist to enforce this; under v2.1 that test runs in two modes — the generation-time stream *and* the on-demand materialized stream — and both must be byte-identical. Treat it as a build requirement, not a nicety.
4. **Never store stop or position size upstream of the rule sweep.** Size is a function of the entry-to-stop distance and the stop is the object of study. Hard-coding either re-introduces censoring.
5. **Never censor the entry-opportunity window at first fill.** *(v2.1.)* The setup lifecycle and its geometry stream run to `INVALIDATED` or `TIMEOUT`, not to the first MR/WT fill. A fill is an event *within* the window, not a closing of it. This is the entry-placement-axis analogue of anti-default 1: entry-placement sweeps (RQ4, RQ5) need the opportunity geometry uncensored the same way stop sweeps need the price path uncensored. Terminating at first fill discards the post-fill boundary/volatility/maturity forecast that a counterfactual trigger (RQ4) or a second MR tranche (RQ5) would be evaluated against.

---

## 8. Daily-data scope and its consequences

**The strategy uses daily bars. Build daily-only.** (The trading background mentions a 30-minute acceptance test for the second WT tranche; in practice intraday is rarely used, so v1 ignores it.) This simplifies most of the system — no timeframe alignment, no sub-bar logic, and the entry-day exit decision resolves naturally at the daily close. But daily resolution weakens two things, both bearing on RQ1 (and, now, on RQ4/RQ5, which are fill-probability questions), and the agent must not let the simplification hide them:

- **MR adverse-selection diagnostic degrades to a proxy.** Within-bar touch-vs-trade-through is invisible on daily data. Use a close-based proxy: filled-and-closed-beyond ≈ trade-through; filled-and-closed-back-inside ≈ touch-and-reject. Coarser, wider error bar; state it in any RQ1/RQ4/RQ5 conclusion.
- **Same-bar sequencing ambiguity, and it biases against tight stops.** A daily bar gives high and low but not their order. When a candidate stop and a favourable extreme fall in the same bar, the evaluator must assume which came first. The conservative convention (adverse first) penalizes *tight* stops specifically, because they more often co-locate with a favourable extreme in the same bar. Since RQ1 *is* the stop-tightness question, this confound pushes the answer toward wider stops. The rule sweep must run every stop comparison under **both** conservative and optimistic sequencing to bound the effect; gap-opens beyond a stop are unambiguous on daily data and can be treated as certain. RQ1's honest output is a *region bounded by the sequencing band*, not a single optimal number.

**The measurement-vs-strategy wall (important).** 30-minute data exists in the cache. It may *never* be used as a strategy signal (to place or time daily orders) — that would change the strategy into one the trader does not trade, reintroducing specification mismatch. It *may* legitimately be used, later and only if warranted, as a **measurement layer** to score the outcome of daily-determined orders more accurately (reality occurs at tick resolution; finer data is closer to truth, not look-ahead). v1 does not use it. If the measured sequencing band proves too wide to separate candidate stops, a later, *surgical* refinement is permitted: detect only the daily bars that are genuinely sequencing-ambiguous and zoom to 30-minute resolution for those bars alone, keyed to the same setup. The contract's optional `intraday_high/low` fields support this with no schema change; they are `None` in v1.

---

## 9. What this can and cannot establish (honest limits)

State these in conclusion documents; do not let the machinery imply more certainty than it has.

- **The discretion gap is unfixable by backtest** (§1). Results refine rules; they do not certify the strategy as traded.
- **Reconstruction error propagates.** Impulse origin and boundaries are reconstructed and the stop rules are sensitive to them. The *geometry-detection parameters themselves* must be sensitivity-tested, or a stop rule may be "optimized" against an artifact of the swing detector.
- **Statistical power is likely the binding constraint — and worse for the new questions.** MR fills are a subset of a subset. Run a power analysis early; if the data cannot distinguish (say) `0.75×D` from `1.0×D` at the effect size that matters, the correct output is a *region of acceptable rules with overlapping confidence intervals*, not a winner. RQ4 (fill probability at deep triggers) and RQ5 (second MR fills) concern events *even rarer* than first MR fills; expect wide intervals there. Note the reflexivity: RQ4 partly *is* the power question, since it studies where to place the trigger to obtain fills in the first place — a shallower trigger that fills more often is also the one on which everything downstream is better-powered.
- **Multiple testing — amplified by the joint sweep.** Sweeping many `k`, `m` invites data-mining bias. The joint dependence of RQ1/RQ4/RQ5 (§3) means the honest sweep is a joint grid over stop × trigger × second-level, which multiplies the rule count and therefore tightens the required data-snooping correction. Defend with out-of-sample walk-forward validation (optimize on one segment, confirm on a later untouched segment), report the whole response surface rather than the single best point, and apply a formal data-snooping correction (e.g. White's Reality Check or a permutation/Bonferroni-style bound) before claiming a rule "wins."
- **Cross-sectional dependence.** Correlated markets pull back together; setups cluster; nominal trade count overstates independent observations. Use a block bootstrap (blocking on time and correlation cluster) for confidence intervals.
- **Objective function is a real choice, made before optimizing.** Fixed-fractional sizing means the quantity that compounds is expected *log* return, not arithmetic E[R]; the two can select different stops, and the geometric objective penalizes variance/drawdown more. (Deferred to the rule-sweep spec, but flagged here so it is not defaulted silently.)
- **Costs and non-stationarity.** Net of commissions, slippage, futures rolls, and spot-FX financing on cross pairs, edges shrink — and tighter stops with larger size amplify slippage. Volatility regime is the most likely non-stationarity to break a stop rule; consider conditioning results on a vol-regime split.
- **Portfolio/account-level questions are out of scope in v1.** The correlation-avoidance rule and concurrent-position capital allocation (Axis-D) need a layer this design does not build. Identity/time/cluster keys are preserved (Contract §11.2) so a future layer can reconstruct which setups were concurrent and correlated; nothing account-level is modelled now.

---

## 10. Build philosophy

**Thin vertical slice first.** Build, for a *single market*: detector → uncensored path recorder → repaint test + golden test passing. Prove the causal spine (no repaint, no censoring) end to end on a small surface where bugs are findable, *before* widening to all markets, fill realism, the rule sweep, or the C-overlap harness. Building all stages wide before the spine is verified is how a repainting detector is discovered only after excursion statistics have been computed on top of it.

Under v2.1 the causal spine has two additions the gate must exercise, without changing the philosophy: the geometry stream must run *past* fills to window-close (so the repaint test includes setups that fill early), and the repaint/truncation-invariance test runs in **two modes** — generation-time construction and the on-demand materializer — both required to produce byte-identical streams. The mechanics and acceptance criteria are in the Implementation Plan and Contract §8; the principle is unchanged: prove the spine on one market, then widen.

---

## 11. Glossary

- **R** — one unit of risk; here 2% of account value. Trade outcomes are expressed in multiples of R.
- **D** — pullback depth; the absolute distance between the pullback's countertrend and with-trend boundaries. Time-varying, not a fixed scalar.
- **ATR** — Average True Range; a volatility measure used to scale stops to recent market range.
- **Tranche** — one of up to three sub-entries composing a single trade, each sized to ~⅓R.
- **MR (mean-reversion) tranche** — limit entry at/just beyond the pullback's countertrend boundary.
- **MR trigger** — the *entry level* at which the MR limit rests (distinct from the MR *stop*). Its placement trades fill probability against entry quality (RQ4).
- **Second MR tranche** — a deeper MR limit resting after the first MR fill, sharing a common stop; because of the shared stop it carries larger size (RQ5).
- **WT (with-trend) tranche** — stop-limit entry beyond a structural trigger.
- **Impulse origin** — the swing point the impulse move began from; the level at which the trend thesis is considered invalidated, and the conceptually correct anchor for an MR stop.
- **Countertrend boundary** — the pullback boundary marking the deepest point of its excursion against the trend: the pullback's lows for a long, the pullback's highs for a short. This is where the MR tranche rests; replaces the direction-dependent "lower boundary"/"upper boundary" language (which side is physically "lower" or "upper" flips between longs and shorts, so those words are avoided as role labels here).
- **With-trend boundary** — the opposite (far-side) pullback boundary: the pullback's highs for a long, the pullback's lows for a short. Used only as a candidate stop-volatility unit (`d_struct`, the channel height between the two boundaries); survival of this machinery is an open RQ1 question.
- **Setup lifecycle** — the representation of a detected setup as a static opening record plus a per-bar causal geometry stream plus a terminal outcome, rather than a single-bar snapshot.
- **Entry-opportunity window** — the interval, `entry_eligible_bar` through `terminated_at_bar`, during which any MR or WT order could still fill. It closes only on `INVALIDATED` or `TIMEOUT`; fills do not close it.
- **INVALIDATED / TIMEOUT** — the two (and only two) reasons the entry-opportunity window closes. `INVALIDATED`: the running extreme breaches the 2/3-retracement floor, or price reclaims the impulse extreme (no pullback left to enter). `TIMEOUT`: the pending window is exhausted with neither invalidation condition met.
- **Maturity (of a pullback)** — how far along the pullback is, measured two ways (bar-count since pullback start; retracement-budget consumed against the 2/3 cap). Both are emitted as features on every update; which one drives the entry offset is selected later against hand-marks.
- **Materialization (Option B)** — the strategy of persisting raw bars and recomputing the geometry stream on demand, rather than persisting the fitted geometry, chosen so a provisional boundary estimator can change without forcing regeneration.
- **Generation-time vs evaluation-time** — generation-time is the one-time write of artifacts (detector/constructor/path/entry-sim); evaluation-time is the pure-function reading of those artifacts by the rule layer. Only information-preserving changes belong at generation-time (§6).
- **MAE / MFE** — Maximum Adverse / Favourable Excursion: the worst / best unrealized move over a holding window.
- **Censoring** — truncation of an observation by a rule, biasing any statistic computed on the truncated sample. Occurs on two axes here: the price axis (an exit truncates the excursion) and the entry-placement axis (terminating at first fill truncates the opportunity window).
- **Repaint / look-ahead** — assigning a past label using future bars; invalidates causal claims.
- **Sequencing band** — the gap between conservative and optimistic assumptions about intra-bar order, within which a daily-data result is genuinely undetermined.
- **Pullback variants** — structural variations the method also trades, emitted as a feature (not filtered) in v1: the *anti* (or snap) pullback, a sharp counter-move against the prior swing; *nested* pullbacks, a smaller pullback inside a larger one; and *complex* pullbacks, multi-leg consolidations rather than a single clean retracement.

---

## 12. Open decisions (non-blocking; resolved in later specs)

- **Horizon H:** provisionally 15–20 trading days plus a fill-latency buffer; pending sign-off. Note the forward path must extend `H` bars beyond the *latest possible* fill (i.e. beyond the whole opportunity window), so late fills still get a full forward horizon (RQ3/RQ4/RQ5).
- **Objective function:** arithmetic E[R] vs. geometric/log-growth; decided in the rule-sweep spec, before any optimization.
- **Second MR entry level:** promoted from a deferred meta-item to a named research question (RQ5). In v1 it is supplied by the entry-simulation config at fill time; it is defined and optimized later, *jointly* with the MR stop (RQ1) and MR trigger (RQ4), not in isolation.
- **Pre-anchor lookback window:** the count of pre-anchor bars persisted for on-demand materialization is a provisional value (Contract §10); it must be sized generously enough that the estimator's window and ATR/warm-up never underrun the stored substrate. Store generously — bars are cheap; an underrun forces the regeneration Option B exists to avoid.
- **Instrument metadata source** (tick size, point value, slippage): discoverable by the agent in the codebase; bound to the contract's `InstrumentMeta`.
- **Trade-log schema:** needed only for the deferred C-overlap harness, not for the first build.

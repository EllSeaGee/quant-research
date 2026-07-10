"""Hand-built contract instances for validator and causality tests.

These builders construct *structurally valid* opening records, update streams,
lifecycles, and simulated entries, plus knobs to introduce specific defects so
the validators can be tested against both valid and invalid inputs. They use no
detector logic — they are pure data, so a validator failure is unambiguous.
"""

from dataclasses import replace

from quant_research.setups.contract import (
    Bar,
    CausalPrice,
    Direction,
    DetectedSetupOpening,
    EntryConfig,
    FillModel,
    FillTimeGeometry,
    ForwardPath,
    ForwardPathBar,
    GrimesVariant,
    ProjectedLevel,
    SetupLifecycle,
    SetupUpdate,
    SimulatedEntry,
    StaticFeatures,
    TerminationReason,
    TrancheComposition,
    TrancheFill,
    TrancheType,
)


def make_bar(i: int, o=100.0, h=101.0, l=99.0, c=100.0, v=1000.0) -> Bar:
    return Bar(bar_index=i, timestamp=f"2024-01-{(i % 27) + 1:02d}T00:00:00Z",
               open=o, high=h, low=l, close=c, volume=v)


def make_pre_anchor_bars(entry_eligible_bar: int, lookback: int) -> tuple[Bar, ...]:
    """Contiguous bars abutting entry_eligible_bar (last == entry_eligible_bar - 1)."""
    start = entry_eligible_bar - lookback
    return tuple(make_bar(i) for i in range(start, entry_eligible_bar))


def make_static_features(pullback_count_in_trend: int | None = 1) -> StaticFeatures:
    return StaticFeatures(
        grimes_variant=GrimesVariant.SIMPLE,
        pullback_count_in_trend=pullback_count_in_trend,
        weekly_agreement_at_detection=1.0,
        vol_ratio_at_detection=0.6,
        wick_indecision_at_detection=0.3,
    )


def make_opening(*, direction=Direction.LONG, detection_bar=50,
                 pre_anchor_lookback=45,
                 impulse_origin_price=90.0, impulse_end_price=110.0,
                 pullback_count_in_trend=1) -> DetectedSetupOpening:
    entry_eligible_bar = detection_bar + 1
    pullback_start_bar = detection_bar - 4
    # LONG floor = end - (2/3)(end - origin)
    span = impulse_end_price - impulse_origin_price
    if direction is Direction.LONG:
        retracement_floor = impulse_end_price - (2.0 / 3.0) * span
    else:
        retracement_floor = impulse_end_price - (2.0 / 3.0) * span  # mirror handled by callers
    impulse_end_bar = pullback_start_bar
    impulse_origin_bar = pullback_start_bar - 5
    return DetectedSetupOpening(
        setup_id="setup-test-0001",
        symbol="ES",
        timeframe="1d",
        detector_version="test",
        param_hash="deadbeef",
        generated_at="2024-01-01T00:00:00Z",
        direction=direction,
        detection_bar=detection_bar,
        entry_eligible_bar=entry_eligible_bar,
        pullback_start_bar=pullback_start_bar,
        impulse_origin=CausalPrice(price=impulse_origin_price,
                                   defining_bar=impulse_origin_bar,
                                   known_at_bar=impulse_origin_bar + 2),
        impulse_end=CausalPrice(price=impulse_end_price,
                                defining_bar=impulse_end_bar,
                                known_at_bar=impulse_end_bar + 2),
        atr_at_detection=2.5,
        atr_period=14,
        retracement_floor=retracement_floor,
        features=make_static_features(pullback_count_in_trend),
        pre_anchor_bars=make_pre_anchor_bars(entry_eligible_bar, pre_anchor_lookback),
        pre_anchor_lookback=pre_anchor_lookback,
    )


def make_update(setup_id: str, t: int, *, running_extreme_price: float,
                floor: float, direction=Direction.LONG,
                pullback_start_bar: int = 46,
                impulse_end_price: float = 110.0,
                impulse_origin_price: float = 90.0,
                with_trend: bool = True) -> SetupUpdate:
    # trivial-style geometry: countertrend flat at running_extreme, trigger offset,
    # clamped to floor.
    atr = 2.5
    v = 1.5
    raw_trigger = running_extreme_price - 0.5 * atr
    if direction is Direction.LONG:
        trigger = max(raw_trigger, floor)
    else:
        trigger = min(running_extreme_price + 0.5 * atr, floor)
    budget = (2.0 / 3.0) * (impulse_end_price - impulse_origin_price)
    maturity_retracement = (impulse_end_price - running_extreme_price) / budget
    wt_level = None
    d_struct = None
    if with_trend:
        wt_price = running_extreme_price + 4.0  # far-side above for LONG
        wt_level = ProjectedLevel(price=wt_price, computed_at_bar=t, active_at_bar=t + 1)
        d_struct = wt_price - running_extreme_price
    return SetupUpdate(
        setup_id=setup_id,
        bar_index=t,
        running_extreme=CausalPrice(price=running_extreme_price,
                                    defining_bar=t, known_at_bar=t),
        mean_true_range_pullback=v,
        countertrend_boundary_next=ProjectedLevel(price=running_extreme_price,
                                                  computed_at_bar=t, active_at_bar=t + 1),
        mr_trigger_next=ProjectedLevel(price=trigger, computed_at_bar=t, active_at_bar=t + 1),
        fit_dispersion=None if t == pullback_start_bar else 0.1,
        maturity_barcount=t - pullback_start_bar,
        maturity_retracement=maturity_retracement,
        with_trend_boundary_next=wt_level,
        d_struct=d_struct,
        atr=atr,
    )


def make_lifecycle(*, direction=Direction.LONG, n_updates=6,
                   termination_reason=TerminationReason.TIMEOUT,
                   with_trend=True) -> SetupLifecycle:
    opening = make_opening(direction=direction)
    eeb = opening.entry_eligible_bar
    # descending running extreme (LONG) staying above floor
    updates = []
    price = opening.impulse_end.price - 3.0
    for k in range(n_updates):
        re = price - k * 0.5  # non-increasing for LONG
        updates.append(make_update(
            opening.setup_id, eeb + k,
            running_extreme_price=re, floor=opening.retracement_floor,
            direction=direction, pullback_start_bar=opening.pullback_start_bar,
            impulse_end_price=opening.impulse_end.price,
            impulse_origin_price=opening.impulse_origin.price,
            with_trend=with_trend,
        ))
    terminated_at_bar = updates[-1].bar_index
    return SetupLifecycle(
        opening=opening,
        updates=tuple(updates),
        terminated_at_bar=terminated_at_bar,
        termination_reason=termination_reason,
    )


def make_forward_path(*, anchor_bar=51, max_pending_window=10, horizon_H=18,
                      truncated=False, short_by=0) -> ForwardPath:
    total_length = max_pending_window + horizon_H
    n = total_length - short_by if truncated else total_length
    bars = tuple(
        ForwardPathBar(bar_offset=k, bar_index=anchor_bar + k,
                       high=101.0 + k, low=99.0 - k, close=100.0)
        for k in range(n)
    )
    return ForwardPath(
        setup_id="setup-test-0001",
        anchor_bar=anchor_bar,
        max_pending_window=max_pending_window,
        horizon_H=horizon_H,
        total_length=total_length,
        bars=bars,
        truncated_by_data_end=truncated,
    )


def make_simulated_entry(*, entry_eligible_bar=51, mr_filled=True,
                         mr_fill_bar=53) -> SimulatedEntry:
    ftg = FillTimeGeometry(
        mr_trigger_at_fill=104.0, running_extreme_at_fill=104.0,
        mean_true_range_at_fill=1.5, atr_at_fill=2.5,
        d_struct_at_fill=4.0, entry_to_origin_at_fill=14.0,
    )
    fills = (
        TrancheFill(
            tranche_id="mr-1", tranche_type=TrancheType.MEAN_REVERSION,
            filled=mr_filled, fill_bar=mr_fill_bar if mr_filled else None,
            requested_price=104.0, fill_price=104.0 if mr_filled else None,
            slippage_applied=0.0,
            filled_on_trade_through=False if mr_filled else None,
            fill_time_geometry=ftg if mr_filled else None,
        ),
    )
    composition = TrancheComposition.MR_ONLY if mr_filled else TrancheComposition.NONE
    return SimulatedEntry(
        setup_id="setup-test-0001", entry_config_id="cfg-1",
        tranche_fills=fills, composition=composition,
    )


def make_entry_config() -> EntryConfig:
    return EntryConfig(
        entry_config_id="cfg-1", fill_model=FillModel.TRADE_THROUGH,
        slippage_ticks=1.0, second_mr_level_rule="static_offset_at_first_fill",
    )

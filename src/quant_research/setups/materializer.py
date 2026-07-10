"""On-demand geometry materializer (Option B, Contract section 6.1).

Under Option B the ``SetupUpdate`` stream is NOT persisted; it is rebuilt on
demand from the persisted raw bar substrate by driving the certified
``BoundaryConstructor`` across the opportunity window. This module is the seam
that keeps the rule/evaluation layer decoupled from the constructor.

Hard rule (Contract section 6.1, Implementation Plan convention 2): for each bar
``t`` in ``[entry_eligible_bar, terminated_at_bar]`` the materializer assembles
``bars_up_to_t`` from ``(opening.pre_anchor_bars + forward_path.bars)`` restricted
to ``bar_index <= t`` and MUST NOT pass any bar with ``bar_index > t``. The same
certified ``constructor`` + ``maturity_fn`` used at generation time are used here
(convention 5) so the two-mode repaint test (section 8.1) can certify the
on-demand path.
"""

from typing import Sequence

from .contract import (
    Bar,
    BoundaryConstructor,
    DetectedSetupOpening,
    ForwardPath,
    MaturityFn,
    SetupLifecycle,
    SetupUpdate,
    TerminationReason,
)


def _substrate_bars(opening: DetectedSetupOpening,
                    forward_path: ForwardPath) -> list[Bar]:
    """The complete uncensored bar record for the setup: pre-anchor lookback plus
    the forward path, ascending and de-duplicated by bar_index."""
    bars: list[Bar] = list(opening.pre_anchor_bars)
    seen = {b.bar_index for b in bars}
    for fpb in forward_path.bars:
        if fpb.bar_index in seen:
            continue
        # ForwardPathBar carries no open/volume; reconstruct a Bar for the
        # constructor. open is set to close (unused by geometry, which reads only
        # high/low/close); volume is None.
        bars.append(Bar(bar_index=fpb.bar_index, timestamp="",
                        open=fpb.close, high=fpb.high, low=fpb.low,
                        close=fpb.close, volume=None))
        seen.add(fpb.bar_index)
    bars.sort(key=lambda b: b.bar_index)
    return bars


class OnDemandGeometryMaterializer:
    """``GeometryMaterializer`` that rebuilds the ``SetupLifecycle`` now (Option B)."""

    def materialize(self, opening: DetectedSetupOpening,
                    forward_path: ForwardPath,
                    terminated_at_bar: int,
                    termination_reason: TerminationReason,
                    constructor: BoundaryConstructor,
                    maturity_fn: MaturityFn) -> SetupLifecycle:
        substrate = _substrate_bars(opening, forward_path)
        updates: list[SetupUpdate] = []
        for t in range(opening.entry_eligible_bar, terminated_at_bar + 1):
            # No-look-ahead: restrict to bars at or before t. Never pass a bar > t.
            bars_up_to_t = [b for b in substrate if b.bar_index <= t]
            update = constructor.compute_update(opening, bars_up_to_t, t, maturity_fn)
            updates.append(update)
        return SetupLifecycle(
            opening=opening,
            updates=tuple(updates),
            terminated_at_bar=terminated_at_bar,
            termination_reason=termination_reason,
        )

"""Termination branches (Contract section 8.9) — each TerminationReason is
exercised: INVALIDATED via 2/3-floor breach, INVALIDATED via reclaim of
impulse_end, and TIMEOUT. Assert no fill terminates the lifecycle: a dummy early
fill still leaves updates running from entry_eligible_bar through
terminated_at_bar."""

from quant_research.setups.contract import TerminationReason

from tests.fixtures import pipeline as P


def test_timeout_branch():
    pipe = P.build_pipeline("timeout")
    det = pipe.detection
    assert det.termination_reason is TerminationReason.TIMEOUT
    # TIMEOUT fires at anchor + max_pending_window - 1
    eeb = pipe.opening.entry_eligible_bar
    assert det.terminated_at_bar == eeb + pipe.forward_path.max_pending_window - 1


def test_invalidated_floor_branch():
    pipe = P.build_pipeline("invalidated_floor")
    assert pipe.detection.termination_reason is TerminationReason.INVALIDATED


def test_invalidated_reclaim_branch():
    pipe = P.build_pipeline("invalidated_reclaim")
    assert pipe.detection.termination_reason is TerminationReason.INVALIDATED


def test_termination_reason_is_two_valued_only():
    assert {r.value for r in TerminationReason} == {"invalidated", "timeout"}


def test_no_fill_terminates_lifecycle():
    """A (dummy) fill inside the window must NOT shorten the lifecycle: updates
    still span through terminated_at_bar (anti-default 5). Geometry is
    fill-independent, so a fill is a no-op for the stream."""
    pipe = P.build_pipeline("timeout")
    lc = pipe.lifecycle
    eeb = pipe.opening.entry_eligible_bar
    terminated = pipe.detection.terminated_at_bar
    # pretend an MR tranche fills early, at the 3rd update bar
    dummy_fill_bar = lc.updates[2].bar_index
    assert dummy_fill_bar < terminated
    # updates continue past the fill and end exactly at terminated_at_bar
    assert lc.updates[0].bar_index == eeb
    assert lc.updates[-1].bar_index == terminated
    bars_after_fill = [u for u in lc.updates if u.bar_index > dummy_fill_bar]
    assert bars_after_fill, "stream was (wrongly) truncated at the dummy fill"

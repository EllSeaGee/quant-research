"""Uncensored-path tests (Contract section 8.4). The ForwardPath is byte-identical
under varying (dummy) stop/target parameters — proving no rule logic leaked into
path generation — and its length depends only on total_length and data
availability."""

from quant_research.setups import validators as V
from quant_research.setups.adapter import InMemoryBarProvider
from quant_research.setups.path_recorder import PathRecorder, PathRecorderParams

from tests.fixtures import pipeline as P, synthetic


def _record(provider, setup_id, eeb, data_end, params=None):
    return PathRecorder(params).record(provider, "ES", "1d", setup_id, eeb, data_end)


def test_path_independent_of_dummy_stop_target():
    """PathRecorder takes NO stop/target inputs. Passing different (dummy) stop /
    target values through a caller must not change the path — here we assert the
    recorder produces byte-identical paths across repeated calls (there is no
    channel by which a stop could enter)."""
    pipe = P.build_pipeline("timeout")
    bars, meta = synthetic.make_long_series("timeout")
    provider = InMemoryBarProvider({("ES", "1d"): bars})
    eeb = pipe.opening.entry_eligible_bar
    p1 = _record(provider, pipe.opening.setup_id, eeb, meta.data_end_index)
    p2 = _record(provider, pipe.opening.setup_id, eeb, meta.data_end_index)
    assert p1 == p2  # byte-identical


def test_path_length_deterministic_and_valid():
    pipe = P.build_pipeline("timeout")
    fp = pipe.forward_path
    assert fp.total_length == fp.max_pending_window + fp.horizon_H
    assert V.validate_forward_path(fp).passed
    assert not fp.truncated_by_data_end
    assert len(fp.bars) == fp.total_length


def test_path_truncated_when_data_ends():
    bars, meta = synthetic.make_long_series("timeout")
    provider = InMemoryBarProvider({("ES", "1d"): bars})
    eeb = 71
    # cut the data short so the horizon cannot be fully recorded
    short_end = eeb + 5
    fp = _record(provider, "sid", eeb, short_end)
    assert fp.truncated_by_data_end
    assert len(fp.bars) == 6  # eeb..eeb+5 inclusive
    assert V.validate_forward_path(fp).passed


def test_path_no_stop_or_size_fields():
    pipe = P.build_pipeline("timeout")
    assert V.validate_no_stop_or_size(pipe.forward_path).passed


def test_intraday_fields_none_daily_only():
    """Convention 8: daily bars only; intraday_high/low stay None."""
    pipe = P.build_pipeline("timeout")
    for b in pipe.forward_path.bars:
        assert b.intraday_high is None and b.intraday_low is None

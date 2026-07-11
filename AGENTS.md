# Project Testing Rules

## Testing Requirements

Use **pytest** to write tests for all code you write. Test coverage does not need to be 100%, but it must cover all functionality set out in the project planning documents:

- **Project Brief** (`docs/project_brief.md`) - Research questions and system scope
- **Implementation Plan v2** (`docs/implementation_plan_v2.md`) - Build phases and acceptance criteria  
- **Setup/Geometry Contract v2.1** (`docs/setup_geometry_contract_v2_1.md`) - Data interface and invariants
- **Detector Spec v1.1** (`docs/detector_spec_v1_1.md`) - Setup detection logic. **v1.1 is now authoritative** and supersedes `docs/detector_spec_v1.md`.

## Detector Spec Version

`docs/detector_spec_v1_1.md` (v1.1) is the authoritative detector spec. Its v1 → v1.1 changelog revised **§4 impulse qualification criteria 2 & 3 only**:

- **Criterion 2 (efficiency):** denominator changed from `Σ|close-to-close|` to `Σ TR(t)` (the §7 True Range formula); `k_efficiency` `0.55 → 0.35`.
- **Criterion 3 (intra-impulse retracement):** `running_extent`/`max_adverse_run` now defined on **intrabar highs/lows** (not closes); `k_intra` `0.40 → 0.45`.

These criteria are **Phase-2** work (the Phase-1 minimal detector implements only criterion 1a), so no code change was made when v1.1 landed. Apply the v1.1 values/formulas when building the full §4 impulse qualification in Phase 2.

## Testing Approach

1. **Write tests before or alongside implementation** - Each module should have corresponding test coverage
2. **Focus on contract invariants** - The 15 invariants in `validators.py` must be tested
3. **Test causal spine integrity** - No repaint, no censoring on price or entry-opportunity axes
4. **Cover all acceptance criteria** - Each phase in Implementation Plan v2 has specific acceptance criteria that must be tested
5. **Test engineering conventions** - The 9 non-negotiable conventions in Implementation Plan §1 must be enforced through tests

## Test Organization

Place tests in a `tests/` directory with structure mirroring the source code:
- `tests/test_contract.py` - Contract dataclass and protocol tests
- `tests/test_validators.py` - All 15 invariant validations
- `tests/test_detector.py` - Setup detection logic
- `tests/test_geometry.py` - Boundary construction and materialization
- `tests/test_entry_simulation.py` - Fill simulation and entry logic
- `tests/test_causal_integrity.py` - Repaint, uncensored-path, and fill-independence tests
# Project Testing Rules

## Testing Requirements

Use **pytest** to write tests for all code you write. Test coverage does not need to be 100%, but it must cover all functionality set out in the project planning documents:

- **Project Brief** (`docs/project_brief.md`) - Research questions and system scope
- **Implementation Plan v2** (`docs/implementation_plan_v2.md`) - Build phases and acceptance criteria  
- **Setup/Geometry Contract v2.1** (`docs/setup_geometry_contract_v2_1.md`) - Data interface and invariants
- **Detector Spec v1** (`docs/detector_spec_v1.md`) - Setup detection logic

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
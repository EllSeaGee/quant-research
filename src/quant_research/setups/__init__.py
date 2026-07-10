"""Pullback tranche-entry setup detection package.

Modules:
    contract        FROZEN data interface (Setup/Geometry Contract v2.1)
    validators      Contract section 7 invariants as free functions
    adapter         binds BarSeriesProvider to the real cache manager
    boundary        BoundaryConstructor implementations (behind the seam)
    materializer    GeometryMaterializer: rebuilds SetupLifecycle on demand (Option B)
    geometry_access stable get_lifecycle accessor (Option B: materialize now)
    detector        produces DetectedSetupOpening + terminal outcome
    path_recorder   produces ForwardPath (uncensored)
"""

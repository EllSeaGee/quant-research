"""Stable geometry accessor — the single certified path to a SetupLifecycle.

Implementation Plan convention 4: the rule/evaluation layer (and everything
else, including tests) touches geometry ONLY through
``GeometryAccess.get_lifecycle(setup_id)``. Downstream code never imports
``boundary`` or ``materializer`` directly. This clean-seam discipline is what
keeps Option B safe (the constructor is reached through one certified path) and
makes the future Option B -> A cache migration (Contract section 11.3) a one-line
swap behind this accessor.

In Option B (now) ``get_lifecycle`` materializes on demand. In Option A (deferred)
it would read a cache. A caller cannot tell which.
"""

from dataclasses import dataclass

from .boundary import RealBoundaryConstructor, maturity_retracement_fn
from .contract import (
    BoundaryConstructor,
    DetectedSetupOpening,
    ForwardPath,
    GeometryMaterializer,
    MaturityFn,
    SetupLifecycle,
    TerminationReason,
)
from .materializer import OnDemandGeometryMaterializer


@dataclass(frozen=True)
class PersistedSetup:
    """The Option B persisted artifact set for one setup (Contract section 2.3,
    Implementation Plan Phase 1 persistence note). The SetupUpdate stream is NOT
    here — it is rematerialized on demand."""
    opening: DetectedSetupOpening
    forward_path: ForwardPath
    terminated_at_bar: int
    termination_reason: TerminationReason


class GeometryAccess:
    """Composes the materializer + certified constructor + maturity_fn and exposes
    the stable ``get_lifecycle`` accessor.

    The same ``constructor`` and ``maturity_fn`` instances handed here are the
    certified ones; use them at generation time too (convention 5) so the
    two-mode repaint test certifies both paths.
    """

    def __init__(self, constructor: BoundaryConstructor, maturity_fn: MaturityFn,
                 materializer: GeometryMaterializer | None = None):
        self._constructor = constructor
        self._maturity_fn = maturity_fn
        self._materializer = materializer or OnDemandGeometryMaterializer()
        self._repo: dict[str, PersistedSetup] = {}

    def register(self, persisted: PersistedSetup) -> None:
        self._repo[persisted.opening.setup_id] = persisted

    def get_lifecycle(self, setup_id: str) -> SetupLifecycle:
        """Return the fully materialized lifecycle for ``setup_id`` (Option B:
        materialize now). Downstream cannot tell this from a cache read."""
        p = self._repo.get(setup_id)
        if p is None:
            raise KeyError(f"no persisted setup registered for setup_id {setup_id!r}")
        return self._materializer.materialize(
            opening=p.opening,
            forward_path=p.forward_path,
            terminated_at_bar=p.terminated_at_bar,
            termination_reason=p.termination_reason,
            constructor=self._constructor,
            maturity_fn=self._maturity_fn,
        )


def build_default_access() -> GeometryAccess:
    """Phase-2 default wiring: the real estimator-C constructor + retracement
    maturity path.

    ``maturity_retracement`` is the runnable-build default (Detector Spec section 8.4,
    PROVISIONAL — not a selection); the barcount path stays equally exercised so
    selection is a config flip, not a rewrite.
    """
    return GeometryAccess(
        constructor=RealBoundaryConstructor(),
        maturity_fn=maturity_retracement_fn,
    )

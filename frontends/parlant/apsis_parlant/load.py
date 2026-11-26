"""Resolve the entry spec to parlant journeys: ``(journey, nodes, edges)`` triples as ``JourneyStore`` lists them."""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile

from apsis_common.loader import resolve_entry


def _resolve(obj) -> list:
    from parlant.core.journeys import Journey

    # a zero-arg factory: calling it builds the journeys without starting a session
    if callable(obj) and not isinstance(obj, (list, tuple)):
        obj = obj()
    journeys = list(obj)
    if not journeys or not all(isinstance(j, (list, tuple)) and len(j) == 3 and isinstance(j[0], Journey) for j in journeys):
        raise TypeError("expected a list of (journey, nodes, edges) triples")
    return journeys


def get_journeys(spec: str):
    # parlant creates its data directory when imported; keep it out of the caller's directory
    if "PARLANT_HOME" not in os.environ:
        home = tempfile.mkdtemp(prefix="apsis-parlant-")
        atexit.register(shutil.rmtree, home, ignore_errors=True)
        os.environ["PARLANT_HOME"] = home
    return resolve_entry(spec, _resolve, "parlant", module_name="apsis_user_journeys")

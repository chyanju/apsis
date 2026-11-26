"""Resolve the entry spec to built CrewAI crews, never kicking them off."""
from __future__ import annotations

import os

from apsis_common.loader import resolve_entry

from . import probe


def _resolve(obj) -> list:
    from crewai import Crew

    # a zero-arg factory: calling it builds the crews without running them
    if callable(obj) and not isinstance(obj, (Crew, list, tuple)):
        obj = obj()
    crews = list(obj) if isinstance(obj, (list, tuple)) else [obj]
    if not crews or not all(isinstance(c, Crew) for c in crews):
        raise TypeError(f"expected a Crew or a list of crews, got {type(obj).__name__}")
    return crews


def get_crews(spec: str):
    """Return ``(crews, provenance)``; several crews are several builds, each a workflow of the program."""
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")  # reading a workflow sends nothing
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    probe.install()
    return resolve_entry(spec, _resolve, "crewai", module_name="apsis_user_crew")

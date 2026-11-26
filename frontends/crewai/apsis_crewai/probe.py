"""Record what CrewAI's agents, tasks and crews are constructed with, before CrewAI validates or converts it.

A construction CrewAI rejects is recorded, and the object is built without validation so that the rest of the
workflow can be read."""
from __future__ import annotations

import functools

GIVEN: dict[int, tuple[object, dict]] = {}  # id(object) -> (object, keyword arguments of its construction)
REJECTED: dict[int, dict[str, str]] = {}  # id(object) -> {field: CrewAI's message}


def install() -> None:
    from crewai import Agent, Crew, Task
    from pydantic import ValidationError

    for cls in (Agent, Task, Crew):
        init = cls.__init__
        if getattr(init, "_apsis_probe", False):
            continue

        @functools.wraps(init)
        def probed(self, *args, _init=init, **kwargs):
            GIVEN[id(self)] = (self, dict(kwargs))  # the object is kept, so its id is not reused
            try:
                _init(self, *args, **kwargs)
            except ValidationError as e:
                REJECTED[id(self)] = {str(err["loc"][0]): err["msg"] for err in e.errors() if err.get("loc")}
                _build_unvalidated(self, kwargs)

        probed._apsis_probe = True
        cls.__init__ = probed


def given(obj, field: str):
    """``(found, value)``: the value the construction of `obj` passed for `field`."""
    entry = GIVEN.get(id(obj))
    if entry is None or entry[0] is not obj or field not in entry[1]:
        return False, None
    return True, entry[1][field]


def _build_unvalidated(self, kwargs: dict) -> None:
    built = type(self).model_construct(**kwargs)
    for name in ("__dict__", "__pydantic_fields_set__", "__pydantic_extra__", "__pydantic_private__"):
        object.__setattr__(self, name, getattr(built, name))

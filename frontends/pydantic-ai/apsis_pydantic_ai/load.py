"""Resolve the entry spec to PydanticAI runs: ``(agent, deps)`` pairs, an agent with the deps one run is given."""
from __future__ import annotations

from apsis_common.loader import resolve_entry


def _resolve(obj) -> list:
    from pydantic_ai import Agent

    # a zero-arg factory: calling it builds the agents and deps without starting a run
    if callable(obj) and not isinstance(obj, (Agent, list, tuple)):
        obj = obj()
    if isinstance(obj, Agent):
        obj = [(obj, None)]
    elif isinstance(obj, tuple) and len(obj) == 2 and isinstance(obj[0], Agent):
        obj = [obj]
    runs = list(obj)
    if not runs or not all(isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], Agent) for r in runs):
        raise TypeError("expected an Agent, an (agent, deps) pair or a list of pairs")
    return runs


def get_runs(spec: str):
    return resolve_entry(spec, _resolve, "pydantic-ai", module_name="apsis_user_agent")

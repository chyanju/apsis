"""Start an agent's run with test models in place of the models, to record the runs its tools start.

A run's test model calls, once each, the tools that hand ``deps`` to a call (the tools that start runs of agents),
then ends the run. Every run that starts is recorded with the deps it is given and the tool that started it; runs
from depth MAX_DEPTH on call no tool. No other tool runs."""
from __future__ import annotations

import ast
import contextlib
import contextvars
from dataclasses import dataclass, field

from .changes import function_def

MAX_DEPTH = 2


@dataclass
class Run:
    agent: object
    deps: object
    parent: "Run | None" = None
    tool: str | None = None  # the tool of the parent run that started it
    depth: int = 0
    children: list = field(default_factory=list)


_RUN: contextvars.ContextVar = contextvars.ContextVar("apsis_run", default=None)
_TOOL: contextvars.ContextVar = contextvars.ContextVar("apsis_tool", default=None)


def tools(agent) -> dict:
    """The agent's function tools by name."""
    return dict(agent._function_toolset.tools)


def starts_runs(tool) -> bool:
    node = function_def(tool.function)
    return node is not None and any(
        isinstance(c, ast.Call) and any(k.arg == "deps" for k in c.keywords) for c in ast.walk(node)
    )


def starting_tools(agent) -> list:
    return [name for name, tool in tools(agent).items() if starts_runs(tool)]


def probe(agent, deps) -> Run:
    """Run the agent once under test models; the root of the tree of runs that started."""
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.toolsets.function import FunctionToolset

    original_iter, original_call = Agent.iter, FunctionToolset.call_tool
    roots: list = []

    @contextlib.asynccontextmanager
    async def iter(self, *args, **kwargs):
        parent = _RUN.get()
        run = Run(self, kwargs.get("deps"), parent, _TOOL.get() if parent else None, parent.depth + 1 if parent else 0)
        (parent.children if parent else roots).append(run)
        kwargs["model"] = TestModel(call_tools=starting_tools(self) if run.depth < MAX_DEPTH else [])
        token = _RUN.set(run)
        try:
            async with original_iter(self, *args, **kwargs) as agent_run:
                yield agent_run
        finally:
            _RUN.reset(token)

    async def call_tool(self, name, tool_args, ctx, tool):
        token = _TOOL.set(name)
        try:
            return await original_call(self, name, tool_args, ctx, tool)
        finally:
            _TOOL.reset(token)

    Agent.iter, FunctionToolset.call_tool = iter, call_tool
    try:
        agent.run_sync("", deps=deps)
    except Exception:  # a run that fails still leaves the runs it started
        pass
    finally:
        Agent.iter, FunctionToolset.call_tool = original_iter, original_call
    return roots[0] if roots else Run(agent, deps)

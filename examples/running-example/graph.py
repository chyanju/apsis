"""The running example of the paper: a research pipeline whose `verify` step always routes back to `analyze`.

`research` hands over to `analyze`, `analyze` to `verify`, and `verify` back to `analyze`. No edge leaves the
`analyze`/`verify` cycle, so once a run enters it the two steps are invoked again and again until the engine's
recursion limit stops the run.

`graph_fixed.py` is the same pipeline with an exit from the cycle.
"""
from typing import TypedDict

from langgraph.graph import START, StateGraph


class State(TypedDict):
    notes: str
    verified: bool


def research(state: State):
    return {"notes": "sources"}


def analyze(state: State):
    return {"notes": state["notes"] + " / analysis"}


def verify(state: State):
    return {"verified": False}


g = StateGraph(State)
g.add_node("research", research)
g.add_node("analyze", analyze)
g.add_node("verify", verify)
g.add_edge(START, "research")
g.add_edge("research", "analyze")
g.add_edge("analyze", "verify")
g.add_edge("verify", "analyze")  # always loops back

graph = g.compile()  # analyze <-> verify never reaches END

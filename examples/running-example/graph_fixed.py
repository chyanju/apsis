"""The pipeline of `graph.py` with an exit from the cycle: `verify` routes back to `analyze` only while the
analysis is not verified, and to `END` once it is."""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    notes: str
    verified: bool


def research(state: State):
    return {"notes": "sources"}


def analyze(state: State):
    return {"notes": state["notes"] + " / analysis"}


def verify(state: State):
    return {"verified": "analysis" in state["notes"]}


def after_verify(state: State) -> str:
    return "done" if state["verified"] else "again"


g = StateGraph(State)
g.add_node("research", research)
g.add_node("analyze", analyze)
g.add_node("verify", verify)
g.add_edge(START, "research")
g.add_edge("research", "analyze")
g.add_edge("analyze", "verify")
g.add_conditional_edges("verify", after_verify, {"again": "analyze", "done": END})

graph = g.compile()

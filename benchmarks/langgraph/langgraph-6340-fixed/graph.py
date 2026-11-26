from typing import Literal

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.store.base import BaseStore
from langchain_core.runnables import RunnableConfig


def simple_node(state: MessagesState) -> dict:
    return {"messages": [("ai", "handled by simple_node")]}


def read_store(
    state: MessagesState,
    config: RunnableConfig,
    store: BaseStore,
) -> dict:
    user_id = config.get("configurable", {}).get("user_id", "default")
    namespace = ("preferences", user_id)
    preferences = list(store.search(namespace))
    finished = len(state.get("messages", [])) > 1 or bool(preferences)
    return {"messages": [("ai", "store read")], "route": "end" if finished else "loop"}


def route_on_state(state: MessagesState) -> Literal["simple_node", "__end__"]:
    if state.get("route") == "end":
        return END
    return "simple_node"


class State(MessagesState):
    route: str


def build():
    g = StateGraph(State)
    g.add_node("simple_node", simple_node)
    g.add_node("read_store", read_store)
    g.add_edge(START, "simple_node")
    g.add_edge("simple_node", "read_store")
    g.add_conditional_edges("read_store", route_on_state)
    return g.compile()


graph = build()

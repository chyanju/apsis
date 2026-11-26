from operator import add
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END


class PersonState(TypedDict):
    name: str
    money: Annotated[int, add]


class PurchasesState(TypedDict):
    purchases: Annotated[list[str], add]
    total_cost: Annotated[int, add]


class OverallState(PersonState, PurchasesState):
    pass


def pay_salary(state: PersonState) -> OverallState:
    return {"money": 1000}


def subtract_expenses(state: OverallState) -> OverallState:
    return {"money": -100, "purchases": ["new iphone"], "total_cost": 100}


def add_assistance(state: OverallState) -> OverallState:
    return {"money": 100}


def check_if_poor(state: OverallState):
    if state["money"] < 100:
        return "node_3"
    return END


def build():
    g = StateGraph(OverallState, input=PersonState)
    g.add_node("node_1", pay_salary)
    g.add_node("node_2", subtract_expenses)
    g.add_node("node_3", add_assistance)
    g.add_edge(START, "node_1")
    g.add_edge("node_1", "node_2")
    g.add_conditional_edges("node_2", check_if_poor, {"node_3": "node_3", END: END})
    g.add_edge("node_3", END)
    return g.compile()


graph = build()

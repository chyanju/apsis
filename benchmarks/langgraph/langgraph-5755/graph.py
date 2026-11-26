from langchain_core.messages import RemoveMessage
from langgraph.graph import END, START, MessagesState, StateGraph


class BaseSchema(MessagesState):
    pass


def remove_message(state: BaseSchema) -> BaseSchema:
    return {"messages": [RemoveMessage(m.id) for m in state["messages"]]}


def build_subgraph():
    g = StateGraph(BaseSchema)
    g.add_node("removing_message", remove_message)
    g.add_edge(START, "removing_message")
    g.add_edge("removing_message", END)
    return g.compile()


subgraph = build_subgraph()


def build():
    g = StateGraph(BaseSchema)
    g.add_node("subgraph", subgraph)
    g.add_edge(START, "subgraph")
    g.add_edge("subgraph", END)
    return g.compile()


graph = build()

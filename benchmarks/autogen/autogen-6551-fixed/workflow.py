from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow


def _agent(name: str, system_message: str) -> AssistantAgent:
    return AssistantAgent(name, model_client=None, system_message=system_message)


def build() -> GraphFlow:
    agent_a = _agent("A", "Search the web.")
    agent_b = _agent(
        "B",
        "Determine whether the previous agent obtained the optimal result. "
        "Respond 'APPROVE' if found, 'SEARCH_AGAIN' to search again, "
        "'NOT_FOUND' if multiple searches yield nothing.",
    )
    agent_c = _agent("C", "Use the search results to answer the question.")
    agent_d = _agent("D", "You are a helpful assistant.")
    agent_e = _agent("E", "Translate input to Japanese.")

    builder = DiGraphBuilder()
    builder.add_node(agent_a).add_node(agent_b).add_node(agent_c).add_node(agent_d)
    builder.add_node(agent_e, activation="any")

    builder.add_edge(agent_a, agent_b)
    builder.add_edge(agent_b, agent_a, condition="SEARCH_AGAIN")
    builder.add_edge(agent_b, agent_c, condition="APPROVE")
    builder.add_edge(agent_b, agent_d, condition="NOT_FOUND")
    builder.add_edge(agent_c, agent_e)
    builder.add_edge(agent_d, agent_e)
    builder.set_entry_point(agent_a)

    graph = builder.build()
    return GraphFlow(
        participants=builder.get_participants(),
        graph=graph,
        termination_condition=MaxMessageTermination(10),
    )


workflow = build()

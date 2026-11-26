from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMessageTermination
from autogen_core.model_context import BufferedChatCompletionContext
from autogen_ext.models.openai import OpenAIChatCompletionClient


def query_sow(question: str) -> str:
    """Return a snippet of the Scope-of-Work knowledge base."""
    return "SOW section: Due Diligence scope and deliverables."


model_client = OpenAIChatCompletionClient(model="gpt-4o-mini", api_key="PLACEHOLDER")


SHARED_MODEL_CONTEXT = BufferedChatCompletionContext(buffer_size=25)

assistant_configs = {
    "AgentSowWriter": {
        "tools": [query_sow],
        "model_context": SHARED_MODEL_CONTEXT,
        "reflect_on_tool_use": True,
        "system_message": "You help write a Due Diligence Scope of Work (SOW) document.",
    },
}


def get_team(assistant: str, session_id: str) -> RoundRobinGroupChat:
    import hashlib

    session_hash = hashlib.md5(session_id.encode()).hexdigest()[:8]
    unique_agent_name = f"{assistant}_s{session_hash}"

    config = assistant_configs[assistant]
    agent = AssistantAgent(name=unique_agent_name, model_client=model_client, **config)

    termination_condition = TextMessageTermination(unique_agent_name)
    team = RoundRobinGroupChat([agent], termination_condition=termination_condition)
    return team


def build():
    team_session_a = get_team("AgentSowWriter", "6b5cf9d6-3d5a-48c5-b09d-775510e7401c")
    team_session_b = get_team("AgentSowWriter", "fdd33bfd-345f-494d-a73b-99c257bd3a60")
    return [team_session_a, team_session_b]


workflow = build()

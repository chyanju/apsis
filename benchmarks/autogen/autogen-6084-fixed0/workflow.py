from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_ext.agents.web_surfer import MultimodalWebSurfer
from autogen_ext.models.openai import OpenAIChatCompletionClient


model_client = OpenAIChatCompletionClient(model="gpt-4o", api_key="PLACEHOLDER")


test_agent = AssistantAgent(
    name="test_agent",
    description="A test agent that returns a string.",
    model_client=model_client,
    system_message="You are a test agent.",
)

multi_modal_web_surfer = MultimodalWebSurfer(
    name="web_surfer",
    description="A web surfer agent that can surf the web for information.",
    model_client=model_client,
)

termination = TextMentionTermination("TERMINATE")


def build():
    team = RoundRobinGroupChat(
        participants=[test_agent, multi_modal_web_surfer],
        termination_condition=termination,
    )
    return team


workflow = build()

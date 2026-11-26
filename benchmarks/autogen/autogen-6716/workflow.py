from autogen_agentchat.agents import (
    AssistantAgent,
    MessageFilterAgent,
    MessageFilterConfig,
    PerSourceFilter,
)
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_core.tools import FunctionTool
from autogen_ext.models.openai import OpenAIChatCompletionClient


model_client = OpenAIChatCompletionClient(model="gpt-4o", api_key="PLACEHOLDER")


generator = AssistantAgent(
    "generator",
    model_client=model_client,
    system_message="Generate a list of creative ideas.",
)
reviewer = AssistantAgent(
    "reviewer",
    model_client=model_client,
    system_message="Review ideas and provide feedback, or just 'APPROVE' for final approval.",
)
summarizer_core = AssistantAgent(
    "summary",
    model_client=model_client,
    system_message="Summarize the user request and the final feedback.",
)


def web_search(search: str) -> str:
    return "search results placeholder"


web_search_tool = FunctionTool(web_search, description="Search the web for information.")

web_surfer = AssistantAgent(
    "web_surfer",
    model_client,
    system_message="You are a web surfer agent. Search the web for information.",
    tools=[web_search_tool],
)

filtered_summarizer = MessageFilterAgent(
    name="summary",
    wrapped_agent=summarizer_core,
    filter=MessageFilterConfig(
        per_source=[
            PerSourceFilter(source="user", position="first", count=1),
            PerSourceFilter(source="reviewer", position="last", count=1),
        ]
    ),
)


def build() -> GraphFlow:
    builder = DiGraphBuilder()
    builder.add_node(generator).add_node(reviewer).add_node(filtered_summarizer).add_node(
        web_surfer
    )

    builder.add_edge(generator, web_surfer)
    builder.add_edge(web_surfer, reviewer)

    builder.add_edge(
        reviewer,
        filtered_summarizer,
        condition=lambda msg: "APPROVE" in msg.to_model_text(),
    )
    builder.add_edge(
        reviewer,
        web_surfer,
        condition=lambda msg: "APPROVE" not in msg.to_model_text(),
    )

    builder.set_entry_point(generator)
    graph = builder.build()
    return GraphFlow(participants=builder.get_participants(), graph=graph)


workflow = build()

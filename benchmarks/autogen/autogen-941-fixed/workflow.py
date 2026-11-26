from autogen import ConversableAgent, GroupChat, GroupChatManager


def _sanitize(name: str) -> str:
    return name.replace(" ", "_").strip("_")


class StubAgentBuilder:
    def __init__(self, builder_model: str = "gpt-3.5-turbo") -> None:
        self.builder_model = builder_model

    def build(self, building_task: str):
        emitted_specs = [
            {"name": " Content_Generator", "system_message": "You generate content for the requested topic."},
            {"name": "Reviewer", "system_message": "You review the generated content and suggest edits."},
            {"name": "Editor", "system_message": "You finalize the content. Reply TERMINATE when done."},
        ]
        return [
            ConversableAgent(
                name=_sanitize(spec["name"]),
                system_message=spec["system_message"],
                llm_config=False,
                human_input_mode="NEVER",
            )
            for spec in emitted_specs
        ]


builder = StubAgentBuilder(builder_model="gpt-3.5-turbo")
agents = builder.build(building_task="Build a content-writing group: a generator, a reviewer, an editor.")

groupchat = GroupChat(
    agents=agents,
    messages=[],
    max_round=12,
)

manager = GroupChatManager(
    groupchat=groupchat,
    llm_config={"config_list": [{"model": "gpt-4", "api_key": "PLACEHOLDER"}]},
)

workflow = manager

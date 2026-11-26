from autogen import (
    AssistantAgent,
    UserProxyAgent,
    GroupChat,
    GroupChatManager,
    register_function,
)


def say_hello(name: str) -> str:
    return f"Hi, {name}, how are you doing?"


def say_goodbye(name: str) -> str:
    return f"bye, {name}, have a good day"


def write_txt(text: str) -> str:
    return "done"


FUNCTIONS = [
    {
        "name": "say_hello",
        "description": "Use this function to say hello to someone",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "say_goodbye",
        "description": "Use this function to say goodbye to someone",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "write_txt",
        "description": "Use this function to write content to a file",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
]

config_list = [{"model": "gpt-4", "api_key": "PLACEHOLDER"}]

tool_llm_config = {
    "functions": FUNCTIONS,
    "config_list": config_list,
    "seed": 45,
}

plain_llm_config = {"config_list": config_list, "seed": 45}

manager_llm_config = {k: v for k, v in tool_llm_config.items() if k != "functions"}


def build():
    user_proxy = UserProxyAgent(
        name="user_proxy",
        system_message="A human that executes suggested function calls.",
        human_input_mode="NEVER",
        code_execution_config=False,
    )

    assistant = AssistantAgent(
        name="assistant",
        system_message="You propose the execution of functions to the user proxy.",
        llm_config=tool_llm_config,
    )

    architect = AssistantAgent(
        name="azure_architect",
        system_message="You create a plan for the assistant to execute the functions.",
        llm_config=plain_llm_config,
    )

    for fn in (say_hello, say_goodbye, write_txt):
        register_function(
            fn,
            caller=assistant,
            executor=user_proxy,
            name=fn.__name__,
            description=fn.__name__,
        )

    groupchat = GroupChat(
        agents=[user_proxy, assistant, architect],
        messages=[],
        max_round=20,
    )

    manager = GroupChatManager(
        groupchat=groupchat,
        llm_config=manager_llm_config,
        system_message="Choose one agent to play the role of the user proxy.",
    )
    return manager


workflow = build()

# Derived from Langflow (github.com/langflow-ai/langflow, MIT) and modified; license text in LICENSE.

from collections.abc import Callable
from typing import Any, cast

from crewai import Task
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


# lfx/base/agents/crewai/crew.py

def _find_api_key(model):
    key_patterns = ["key", "token"]

    for attr in dir(model):
        attr_lower = attr.lower()

        if any(pattern in attr_lower for pattern in key_patterns):
            value = getattr(model, attr, None)

            if isinstance(value, str):
                return value
            if isinstance(value, SecretStr):
                return value.get_secret_value()

    return None


def convert_llm(llm: Any, excluded_keys=None):
    try:
        from crewai import LLM
    except ImportError as e:
        msg = "CrewAI is not installed. Please install it with `uv pip install crewai`."
        raise ImportError(msg) from e

    if not llm:
        return None

    if isinstance(llm, LLM):
        return llm

    if hasattr(llm, "model_name") and llm.model_name:
        model_name = llm.model_name
    elif hasattr(llm, "model") and llm.model:
        model_name = llm.model
    elif hasattr(llm, "deployment_name") and llm.deployment_name:
        model_name = llm.deployment_name
    else:
        msg = "Could not find model name in the LLM object"
        raise ValueError(msg)

    provider = llm.get_lc_namespace()[0]
    api_base = None
    if provider.startswith("langchain_"):
        provider = provider[10:]
        model_name = f"{provider}/{model_name}"
    elif hasattr(llm, "azure_endpoint"):
        api_base = llm.azure_endpoint
        model_name = f"azure/{model_name}"

    if excluded_keys is None:
        excluded_keys = {"model", "model_name", "_type", "api_key", "azure_deployment"}

    api_key = _find_api_key(llm)

    return LLM(
        model=model_name,
        api_key=api_key,
        api_base=api_base,
        **{k: v for k, v in llm.dict().items() if k not in excluded_keys},
    )


def convert_tools(tools):
    try:
        from crewai.tools.base_tool import Tool
    except ImportError as e:
        msg = "CrewAI is not installed. Please install it with `uv pip install crewai`."
        raise ImportError(msg) from e

    if not tools:
        return []

    return [Tool.from_langchain(tool) for tool in tools]


class Component:
    """What the CrewAI components use of Langflow's component: their inputs as attributes."""

    inputs: dict[str, Any] = {}
    display_name = None
    _vertex = None

    def __init__(self, **values):
        for name, value in {**self.inputs, **values}.items():
            setattr(self, name, value)

    def log(self, message, name=None):
        pass


class BaseCrewComponent(Component):
    inputs = {"verbose": 0, "memory": False, "use_cache": True, "max_rpm": 100, "share_crew": False,
              "function_calling_llm": None}

    manager_llm = None

    def get_tasks_and_agents(self, agents_list=None) -> tuple[list, list]:
        # Allow passing a custom list of agents
        if not agents_list:
            agents_list = self.agents or []

        # Set all the agents llm attribute to the crewai llm
        for agent in agents_list:
            # Convert Agent LLM and Tools to proper format
            agent.llm = convert_llm(agent.llm)
            agent.tools = convert_tools(agent.tools)

        return self.tasks, agents_list

    def get_manager_llm(self):
        if not self.manager_llm:
            return None

        self.manager_llm = convert_llm(self.manager_llm)

        return self.manager_llm

    def get_task_callback(
        self,
    ) -> Callable:
        try:
            from crewai.task import TaskOutput
        except ImportError as e:
            msg = "CrewAI is not installed. Please install it with `uv pip install crewai`."
            raise ImportError(msg) from e

        def task_callback(task_output: TaskOutput) -> None:
            vertex_id = self._vertex.id if self._vertex else self.display_name or self.__class__.__name__
            self.log(task_output.model_dump(), name=f"Task (Agent: {task_output.agent}) - {vertex_id}")

        return task_callback

    def get_step_callback(
        self,
    ) -> Callable:
        try:
            from langchain_core.agents import AgentFinish
        except ImportError as e:
            msg = "langchain_core is not installed. Please install it with `uv pip install langchain-core`."
            raise ImportError(msg) from e

        def step_callback(agent_output) -> None:
            id_ = self._vertex.id if self._vertex else self.display_name
            if isinstance(agent_output, AgentFinish):
                messages = agent_output.messages
                self.log(cast("dict", messages[0].to_json()), name=f"Finish (Agent: {id_})")

        return step_callback


# lfx/base/agents/crewai/tasks.py

class SequentialTask(Task):
    pass


# lfx/components/crewai/crewai.py

class CrewAIAgentComponent(Component):
    inputs = {"tools": [], "memory": True, "verbose": False, "allow_delegation": True,
              "allow_code_execution": False, "kwargs": None}

    def build_output(self):
        try:
            from crewai import Agent
        except ImportError as e:
            msg = "CrewAI is not installed. Please install it with `uv pip install crewai`."
            raise ImportError(msg) from e

        kwargs = self.kwargs or {}

        # Define the Agent
        agent = Agent(
            role=self.role,
            goal=self.goal,
            backstory=self.backstory,
            llm=convert_llm(self.llm),
            verbose=self.verbose,
            memory=self.memory,
            tools=convert_tools(self.tools),
            allow_delegation=self.allow_delegation,
            allow_code_execution=self.allow_code_execution,
            **kwargs,
        )

        self.status = repr(agent)

        return agent


# lfx/components/crewai/sequential_task.py

class SequentialTaskComponent(Component):
    inputs = {"tools": [], "async_execution": True, "task": None}

    def build_task(self) -> list[SequentialTask]:
        tasks: list[SequentialTask] = []
        task = SequentialTask(
            description=self.task_description,
            expected_output=self.expected_output,
            tools=self.agent.tools,
            async_execution=False,
            agent=self.agent,
        )
        tasks.append(task)
        self.status = task
        if self.task:
            if isinstance(self.task, list) and all(isinstance(task_item, SequentialTask) for task_item in self.task):
                tasks = self.task + tasks
            elif isinstance(self.task, SequentialTask):
                tasks = [self.task, *tasks]
        return tasks


# lfx/components/crewai/sequential_task_agent.py

class SequentialTaskAgentComponent(Component):
    inputs = {"tools": [], "memory": True, "verbose": True, "allow_delegation": False,
              "allow_code_execution": False, "agent_kwargs": None, "async_execution": False, "previous_task": None}

    def build_agent_and_task(self) -> list[SequentialTask]:
        try:
            from crewai import Agent, Task
        except ImportError as e:
            msg = "CrewAI is not installed. Please install it with `uv pip install crewai`."
            raise ImportError(msg) from e

        # Build the agent
        agent_kwargs = self.agent_kwargs or {}
        agent = Agent(
            role=self.role,
            goal=self.goal,
            backstory=self.backstory,
            llm=self.llm,
            verbose=self.verbose,
            memory=self.memory,
            tools=self.tools or [],
            allow_delegation=self.allow_delegation,
            allow_code_execution=self.allow_code_execution,
            **agent_kwargs,
        )

        # Build the task
        task = Task(
            description=self.task_description,
            expected_output=self.expected_output,
            agent=agent,
            async_execution=self.async_execution,
        )

        # If there's a previous task, create a list of tasks
        if self.previous_task:
            tasks = [*self.previous_task, task] if isinstance(self.previous_task, list) else [self.previous_task, task]
        else:
            tasks = [task]

        self.status = f"Agent: {agent!r}\nTask: {task!r}"
        return tasks


# lfx/components/crewai/sequential_crew.py

class SequentialCrewComponent(BaseCrewComponent):
    @property
    def agents(self: "SequentialCrewComponent") -> list:
        # Derive agents directly from linked tasks
        return [task.agent for task in self.tasks if hasattr(task, "agent")]

    def get_tasks_and_agents(self, agents_list=None) -> tuple[list, list]:
        # Use the agents property to derive agents
        if not agents_list:
            existing_agents = self.agents
            agents_list = existing_agents + (agents_list or [])

        return super().get_tasks_and_agents(agents_list=agents_list)

    def build_crew(self):
        try:
            from crewai import Crew, Process
        except ImportError as e:
            msg = "CrewAI is not installed. Please install it with `uv pip install crewai`."
            raise ImportError(msg) from e

        tasks, agents = self.get_tasks_and_agents()

        return Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            verbose=self.verbose,
            memory=self.memory,
            cache=self.use_cache,
            max_rpm=self.max_rpm,
            share_crew=self.share_crew,
            function_calling_llm=self.function_calling_llm,
            step_callback=self.get_step_callback(),
            task_callback=self.get_task_callback(),
        )


# Flows built from these components. `model` is the output of a Language Model component.

model = ChatOpenAI(model="gpt-4o-mini", api_key="sk-placeholder")


def researcher():
    return CrewAIAgentComponent(role="Researcher", goal="Find facts", backstory="An analyst", llm=model).build_output()


def research_task(agent, description="Research the topic"):
    return SequentialTaskComponent(task_description=description, expected_output="A summary", agent=agent).build_task()


# 13846: Langflow keeps a built component and builds it again for the next request
crew_component = SequentialCrewComponent(tasks=research_task(researcher()))
crew_builds = [crew_component.build_crew(), crew_component.build_crew()]

# 13847: one agent wired into the tasks of two crews, and into two tasks of one crew
shared_agent = researcher()
crews_sharing_an_agent = [
    SequentialCrewComponent(tasks=research_task(shared_agent)).build_crew(),
    SequentialCrewComponent(tasks=research_task(shared_agent)).build_crew(),
]
two_task_agent = researcher()
crew_reusing_an_agent = SequentialCrewComponent(
    tasks=research_task(two_task_agent) + research_task(two_task_agent, "Check the summary")
).build_crew()

# 13848: the legacy factory builds the agent and its task
task_agent_crew = SequentialCrewComponent(
    tasks=SequentialTaskAgentComponent(
        role="Researcher", goal="Find facts", backstory="An analyst", llm=model,
        task_description="Research the topic", expected_output="A summary",
    ).build_agent_and_task()
).build_crew()

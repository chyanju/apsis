import asyncio

from llama_index.core.llms.mock import MockFunctionCallingLLM
from llama_index.protocols.ag_ui.router import get_default_workflow_factory

# the operator's state, handed to the router once
initial_state = {"counter": 0, "items": [], "user": {"name": "default", "roles": []}}

workflow_factory = get_default_workflow_factory(llm=MockFunctionCallingLLM(), initial_state=initial_state, timeout=30)

# the AG-UI router builds one workflow per request
workflows = [asyncio.run(workflow_factory()), asyncio.run(workflow_factory())]

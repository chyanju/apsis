import atexit
import shutil
import tempfile

from langchain.agents import create_agent
from langchain_anthropic.middleware import (
    FilesystemClaudeMemoryMiddleware,
    FilesystemClaudeTextEditorMiddleware,
    StateClaudeMemoryMiddleware,
    StateClaudeTextEditorMiddleware,
)
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


root = tempfile.mkdtemp(prefix="claude-files-")
atexit.register(shutil.rmtree, root, ignore_errors=True)

# the four file-tool middlewares of the issue: Claude's text editor and memory, kept in the agent state or on disk
agents = [
    create_agent(ToolModel(messages=iter([])), tools=[],
                 middleware=[StateClaudeTextEditorMiddleware(), StateClaudeMemoryMiddleware()]),
    create_agent(ToolModel(messages=iter([])), tools=[],
                 middleware=[FilesystemClaudeTextEditorMiddleware(root_path=root), FilesystemClaudeMemoryMiddleware(root_path=root)]),
]

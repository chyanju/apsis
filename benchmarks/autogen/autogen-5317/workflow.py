import asyncio
from dataclasses import dataclass
from typing import Callable

from autogen_core import (
    DefaultTopicId,
    MessageContext,
    RoutedAgent,
    SingleThreadedAgentRuntime,
    default_subscription,
    message_handler,
)


@dataclass
class Message:
    content: int


@default_subscription
class Modifier(RoutedAgent):
    def __init__(self, modify_val: Callable[[int], int]) -> None:
        super().__init__("A modifier agent.")
        self._modify_val = modify_val

    @message_handler
    async def handle_message(self, message: Message, ctx: MessageContext) -> None:
        val = self._modify_val(message.content)
        await self.publish_message(Message(content=val), DefaultTopicId())


@default_subscription
class Checker(RoutedAgent):
    def __init__(self, run_until: Callable[[int], bool]) -> None:
        super().__init__("A checker agent.")
        self._run_until = run_until

    @message_handler
    async def handle_message(self, message: Message, ctx: MessageContext) -> None:
        if not self._run_until(message.content):
            await self.publish_message(Message(content=message.content), DefaultTopicId())


async def register(runtime: SingleThreadedAgentRuntime) -> None:
    await Modifier.register(runtime, "modifier", lambda: Modifier(modify_val=lambda x: x - 1))
    await Modifier.register(runtime, "modifier2", lambda: Modifier(modify_val=lambda x: x - 1))
    await Checker.register(runtime, "checker", lambda: Checker(run_until=lambda x: x <= 1))


def build():
    runtime = SingleThreadedAgentRuntime()
    asyncio.run(register(runtime))
    return runtime


workflow = build()

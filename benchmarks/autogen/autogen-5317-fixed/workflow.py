import asyncio
from dataclasses import dataclass
from typing import Callable

from autogen_core import (
    DefaultTopicId,
    MessageContext,
    RoutedAgent,
    SingleThreadedAgentRuntime,
    TypeSubscription,
    message_handler,
)


@dataclass
class Message:
    content: int


class Modifier(RoutedAgent):
    def __init__(self, topic_type: str, modify_val: Callable[[int], int]) -> None:
        super().__init__("A modifier agent.")
        self._topic_type = topic_type
        self._modify_val = modify_val

    @message_handler
    async def handle_message(self, message: Message, ctx: MessageContext) -> None:
        val = self._modify_val(message.content)
        await self.publish_message(Message(content=val), DefaultTopicId(type=self._topic_type))


class Checker(RoutedAgent):
    def __init__(self, run_until: Callable[[int], bool]) -> None:
        super().__init__("A checker agent.")
        self._run_until = run_until

    @message_handler
    async def handle_message(self, message: Message, ctx: MessageContext) -> None:
        if not self._run_until(message.content):
            await self.publish_message(Message(content=message.content), ctx.topic_id)


async def register(runtime: SingleThreadedAgentRuntime) -> None:
    await Modifier.register(runtime, "modifier1", lambda: Modifier(topic_type="modifier1", modify_val=lambda x: x - 1))
    await Modifier.register(runtime, "modifier2", lambda: Modifier(topic_type="modifier2", modify_val=lambda x: x - 1))
    await Checker.register(runtime, "checker", lambda: Checker(run_until=lambda x: x <= 1))
    await runtime.add_subscription(TypeSubscription("modifier1", "modifier1"))
    await runtime.add_subscription(TypeSubscription("modifier2", "modifier2"))
    await runtime.add_subscription(TypeSubscription("modifier1", "checker"))
    await runtime.add_subscription(TypeSubscription("modifier2", "checker"))


def build():
    runtime = SingleThreadedAgentRuntime()
    asyncio.run(register(runtime))
    return runtime


workflow = build()

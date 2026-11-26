import asyncio
from typing import Any, Generic, Mapping, TypeVar

from parlant import sdk as p
from parlant.core.common import DefaultBaseModel
from parlant.core.journeys import JourneyStore
from parlant.core.nlp.embedding import NullEmbedder
from parlant.core.nlp.generation import SchematicGenerator, StreamingTextGenerator
from parlant.core.nlp.moderation import ModerationService, NoModeration
from parlant.core.nlp.service import EmbedderHints, NLPService, SchematicGeneratorHints, StreamingTextGeneratorHints
from parlant.core.nlp.tokenization import ZeroEstimatingTokenizer

T = TypeVar("T", bound=DefaultBaseModel)


class DummyGenerator(SchematicGenerator[T], Generic[T]):
    def __init__(self, schema: type[T]) -> None:
        self._schema = schema
        self._tokenizer = ZeroEstimatingTokenizer()

    @property
    def schema(self) -> type[T]:
        return self._schema

    async def generate(self, prompt: str | Any, hints: Mapping[str, Any] = {}):
        raise RuntimeError("no generation while journeys are authored")

    @property
    def id(self) -> str:
        return f"dummy:{self._schema.__name__}"

    @property
    def max_tokens(self) -> int:
        return 8192

    @property
    def tokenizer(self):
        return self._tokenizer


class NoopNLPService(NLPService):
    @property
    def supports_streaming(self) -> bool:
        return False

    async def get_schematic_generator(self, t: type[T], hints: SchematicGeneratorHints = {}) -> SchematicGenerator[T]:
        return DummyGenerator[t](t)  # type: ignore[index]

    async def get_streaming_text_generator(self, hints: StreamingTextGeneratorHints = {}) -> StreamingTextGenerator:
        raise RuntimeError("no generation while journeys are authored")

    async def get_embedder(self, hints: EmbedderHints = {}):
        return NullEmbedder()

    async def get_moderation_service(self) -> ModerationService:
        return NoModeration()


class Authored(Exception):
    """Leaves the server once the journeys are stored, before it evaluates them."""


async def build_journeys():
    server = p.Server(port=18800, tool_service_port=18818, nlp_service=lambda c: NoopNLPService())
    try:
        async with server:
            agent = await server.create_agent(name="Support Agent", description="Answers customers")

            journey1 = await agent.create_journey(title="Journey One", conditions=[], description="First journey")
            journey2 = await agent.create_journey(title="Journey Two", conditions=[], description="Second journey")

            journey2_transition = await journey2.initial_state.transition_to(chat_state="inside journey two")
            await journey1.initial_state.transition_to(condition="jump across journeys", state=journey2_transition.target)

            store = server.container[JourneyStore]
            raise Authored([(j, await store.list_nodes(j.id), await store.list_edges(j.id)) for j in await store.list_journeys()])
    except Authored as done:
        return done.args[0]


journeys = asyncio.run(build_journeys())

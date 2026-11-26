from haystack import Pipeline, component


@component
class TextEmbedder:
    @component.output_types(embedding=str)
    def run(self, text: str):
        return {"embedding": text}


@component
class Retriever:
    @component.output_types(documents=str)
    def run(self, embedding: str):
        return {"documents": embedding}


@component
class PromptBuilder:
    @component.output_types(prompt=str)
    def run(self, documents: str, replies: str = ""):
        return {"prompt": documents + replies}


@component
class Generator:
    @component.output_types(replies=str)
    def run(self, prompt: str):
        return {"replies": prompt}


@component
class OutputValidator:
    def __init__(self):
        self.iteration_counter = 0

    @component.output_types(valid_replies=str, invalid_replies=str)
    def run(self, replies: str):
        self.iteration_counter += 1
        if self.iteration_counter > 1:
            return {"valid_replies": replies}
        return {"invalid_replies": replies}


def build() -> Pipeline:
    p = Pipeline()
    p.add_component("embedder", TextEmbedder())
    p.add_component("retriever", Retriever())
    p.add_component("prompt_builder", PromptBuilder())
    p.add_component("generator", Generator())
    p.add_component("validator", OutputValidator())
    p.connect("embedder.embedding", "retriever.embedding")
    p.connect("retriever.documents", "prompt_builder.documents")
    p.connect("prompt_builder.prompt", "generator.prompt")
    p.connect("generator.replies", "validator.replies")
    p.connect("validator.invalid_replies", "prompt_builder.replies")
    return p


pipeline = build()

from haystack import Pipeline, component


@component
class PromptBuilder:
    @component.output_types(prompt=str)
    def run(self, schema: str, passage: str, replies: str = ""):
        return {"prompt": schema + passage + replies}


@component
class Generator:
    @component.output_types(replies=str)
    def run(self, prompt: str):
        return {"replies": prompt}


@component
class Validator:
    @component.output_types(replies=str)
    def run(self, replies: str):
        return {"replies": replies}


def build() -> Pipeline:
    p = Pipeline()
    p.add_component("prompt_builder", PromptBuilder())
    p.add_component("generator", Generator())
    p.add_component("validator", Validator())
    p.connect("prompt_builder.prompt", "generator.prompt")
    p.connect("generator.replies", "validator.replies")
    p.connect("validator.replies", "prompt_builder.replies")
    return p


pipeline = build()

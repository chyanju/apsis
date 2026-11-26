from typing import List

from haystack import Pipeline, component


@component
class PromptBuilder1:
    @component.output_types(prompt=str)
    def run(self, question: str):
        return {"prompt": question}


@component
class Generator:
    @component.output_types(replies=List[str])
    def run(self, prompt: str = ""):
        return {"replies": [prompt]}


@component
class PromptBuilder2:
    @component.output_types(prompt=str)
    def run(self, documents: str = "", question: str = ""):
        return {"prompt": f"{documents} {question}"}


@component
class PromptBuilder3:
    @component.output_types(prompt=str)
    def run(self, replies: List[str] = None):
        return {"prompt": " ".join(replies or [])}


def build() -> Pipeline:
    p = Pipeline()
    p.add_component("prompt_builder1", PromptBuilder1())
    p.add_component("spellchecker", Generator())
    p.add_component("prompt_builder3", PromptBuilder3())
    p.add_component("prompt_builder2", PromptBuilder2())
    p.add_component("llm", Generator())

    p.connect("prompt_builder1.prompt", "spellchecker.prompt")
    p.connect("spellchecker.replies", "prompt_builder3.replies")
    p.connect("prompt_builder3.prompt", "prompt_builder2.question")
    p.connect("prompt_builder2.prompt", "llm.prompt")
    return p


pipeline = build()

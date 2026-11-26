from haystack import Pipeline, component


@component
class Generator:
    @component.output_types(replies=str)
    def run(self, prompt: str):
        return {"replies": prompt}


@component
class Reader:
    @component.output_types(answer=str)
    def run(self, query: str = ""):
        return {"answer": query}


def build() -> Pipeline:
    p = Pipeline()
    p.add_component("generator", Generator())
    p.add_component("reader", Reader())
    p.connect("generator.replies", "reader.query")
    return p


pipeline = build()

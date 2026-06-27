class NoopLLM:
    def complete(self, prompt: str, *, temperature: float | None = None) -> str:
        return "[noop llm response]"

    def stream(self, prompt: str, *, temperature: float | None = None):
        yield "[noop llm response]"

"""LLM access through the internal gateway only (AGT-09).

No external AI APIs. Production points at a local vLLM/Ollama endpoint;
tests use StubLLM. Phase 1 agents are rule-based and template-driven, so
nothing calls this yet.
"""

from typing import Protocol


class LLM(Protocol):
    async def complete(self, prompt: str) -> str: ...


class StubLLM:
    """Deterministic stand-in for tests: echoes a fixed prefix and the prompt."""

    async def complete(self, prompt: str) -> str:
        return f"[stub] {prompt}"

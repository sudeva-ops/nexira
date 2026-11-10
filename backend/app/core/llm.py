"""LLM access through the internal gateway only (AGT-09).

No external AI APIs. Production points at a local vLLM/Ollama endpoint;
tests use StubLLM. Phase 1 agents are rule-based and template-driven, so
nothing calls this yet.

The AI Risk Copilot (D-50) writes through a Writer: grounded facts in, cited sentences out.
Its TemplateWriter is simulated wording; a writer backed by the local model can replace it
later, given the same facts, keeping only sentences that cite the sources it was given
(COP-05, docs/plan-pilot-cop.md §5).
"""

from dataclasses import dataclass
from typing import Protocol, TypeVar


class LLM(Protocol):
    async def complete(self, prompt: str) -> str: ...


class StubLLM:
    """Deterministic stand-in for tests: echoes a fixed prefix and the prompt."""

    async def complete(self, prompt: str) -> str:
        return f"[stub] {prompt}"


@dataclass(frozen=True)
class Source:
    """A record a sentence rests on, with the screen that shows it."""

    kind: str  # INCIDENT, CHECKIN, PLAYBOOK_RUN, PROPOSAL, TRIP, EXERCISE, FORECAST, MISSION
    reference: str
    href: str


@dataclass(frozen=True)
class Sentence:
    text: str
    sources: tuple[Source, ...]


F_contra = TypeVar("F_contra", contravariant=True)


class Writer(Protocol[F_contra]):
    def write(self, facts: F_contra) -> list[Sentence]: ...

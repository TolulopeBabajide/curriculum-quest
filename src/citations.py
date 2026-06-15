"""Per-turn citation capture — the authoritative grounding for the Turn contract.

The Game Master narrates its sources in prose (e.g. "(Source: NERDC …)"), but it sometimes shortens
or paraphrases them — observed: it relayed "NERDC JSS1 Basic Science · Theme 1" when Foundry IQ
actually returned "NERDC JSS1 Basic Science · Theme 1 (Learning About Our Environment) · Topic:
Family Health". So prose is a lossy source of truth.

The reliable source of what a turn was grounded in is the retrieval TOOL output (Foundry IQ
references / local-fallback chunks). The retrieval tools in `tools/lore.py` record their citations
here as they run; `turn.py` reads them to build `Turn.citations`, independent of how the GM phrased
them. Prose `(Source: …)` parsing remains a fallback for anything not tool-sourced.

Async-safe: a ContextVar scopes the accumulator to the current turn's task — the same mechanism
`tools/state.py` uses for per-session state, so it propagates through the nested agent orchestration.
"""
from __future__ import annotations

import contextvars

_turn_citations: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "turn_citations", default=None)


def begin_turn_citations() -> None:
    """Start a fresh citation accumulator for a new turn (call once at the start of each turn)."""
    _turn_citations.set([])


def record_citation(citation: str, *, title: str | None = None, source: str | None = None) -> None:
    """Record one citation captured from a retrieval tool result.

    No-op when called outside a turn (no accumulator) or with an empty citation. De-dupes by label.
    """
    bucket = _turn_citations.get()
    if bucket is None or not citation:
        return
    if any(c["label"] == citation for c in bucket):
        return
    bucket.append({"label": citation, "title": title, "source": source})


def get_turn_citations() -> list[dict]:
    """Citations captured during the current turn (authoritative, full-text). Empty if none/outside a turn."""
    return list(_turn_citations.get() or [])

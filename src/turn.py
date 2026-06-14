"""Structured turn — the shared contract between the game engine and any frontend.

The agents produce rich prose. This module normalizes one Game-Master turn into a small,
stable JSON shape so a CLI, a 2D visual novel, or a 3D world can all render the same game
from one backend. The parsing is deterministic (regex over the prose the GM reliably emits):

  Turn = {
    speaker:    who is talking this turn (currently always the Storyteller/GM narrator),
    text:       the narration to display,
    citations:  [{label}]   — every "(Source: …)" the turn grounded itself in,
    choices:    [{id,label}] — any numbered "1) … 2) …" options offered,
    state:      a snapshot of campaign state (confidence, skills, location, learner context),
  }

Richer per-character attribution (so a UI can show the right portrait per line) and
spatial/animation hints for a 3D world are a future enhancement — they need the GM to emit
structured output directly (response_format). This layer is intentionally non-destructive: it
reads what the working agents already produce.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .citations import get_turn_citations
from .tools.state import load_state

# Examiner verdict contract (M-03). The Examiner is instructed to return STRICT JSON of this
# shape; `parse_verdict` validates it before anything downstream could trust it. Today the
# verdict is consumed by the Game Master LLM reading the examiner's text (LLM-orchestrated), so
# this validator is exposed for callers/tests and as the enforcement point if/when consumption
# becomes deterministic. Wiring a hard "reject malformed verdict" gate into the live loop would
# require an orchestration change (the GM, not Python, currently routes the examiner output).
_VALID_VERDICTS = {"correct", "partial", "wrong"}
_VERDICT_KEYS = ("verdict", "why", "hint", "citation")
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_verdict(text: str) -> dict | None:
    """Parse + validate an Examiner verdict from possibly-prose-wrapped text.

    Returns the verdict dict when `text` contains a JSON object with all required keys
    (`verdict`, `why`, `hint`, `citation`) and `verdict` is one of correct/partial/wrong.
    Returns None for malformed JSON, a missing key, or an out-of-range verdict.
    """
    if not text:
        return None
    candidate = text.strip()
    try:
        obj = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        m = _JSON_OBJECT_RE.search(candidate)  # tolerate surrounding prose/code fences
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(obj, dict):
        return None
    if any(k not in obj for k in _VERDICT_KEYS):
        return None
    if obj["verdict"] not in _VALID_VERDICTS:
        return None
    return obj

# The opening prompt that kicks off a session — single source of truth for CLI + server.
OPENING = (
    "Begin the story. Do the friendly first-turn onboarding: greet the learner warmly, tell them "
    "Teacher Adaeze, the neighbours, and Tunde are AI characters, then ask their name and a little "
    "about their real surroundings (village/town/city; what their family uses to cook and for light; "
    "whether a market, farm, or stream is nearby). Save it with set_learner_context. Then briefly "
    "introduce today's learning journey — name the science topics they'll explore in order, following "
    "the curriculum — and begin LESSON 1 at their home & compound. You guide the path in order; do NOT "
    "ask the learner to pick a scene."
)

_CITATION_RE = re.compile(r"\(Source:\s*([^)]+)\)", re.IGNORECASE)
_CHOICE_RE = re.compile(r"^\s*(\d+)[\).]\s+(.+?)\s*$", re.MULTILINE)


_CONTINUE_RE = re.compile(r"say\s+['\"]?continue['\"]?", re.IGNORECASE)


@dataclass
class Turn:
    speaker: str
    text: str
    citations: list[dict] = field(default_factory=list)
    choices: list[dict] = field(default_factory=list)
    expecting: str = "free"
    state: dict = field(default_factory=dict)


def _parse_prose_citations(text: str) -> list[dict]:
    """Fallback: pull any '(Source: …)' labels the GM wrote into the narration."""
    seen, out = set(), []
    for m in _CITATION_RE.finditer(text):
        label = m.group(1).strip()
        if label.lower() not in seen:
            seen.add(label.lower())
            out.append({"label": label, "title": None, "source": "narration"})
    return out


def _norm_citation(label: str) -> str:
    """Normalize a citation for comparison: punctuation/separators → spaces, collapsed, lowercased.

    Makes "A · Theme 1 (B) · Topic: C" and "A — Theme 1 (B" compare as one is-substring-of the other,
    so the GM re-rendering a captured citation with different punctuation is recognized as a duplicate.
    """
    return re.sub(r"\s+", " ", re.sub(r"[·—–\-|:.]+", " ", label.lower())).strip()


def _merge_citations(text: str) -> list[dict]:
    """Authoritative citations from the retrieval tools, plus any prose-only ones not already covered.

    A prose mention that (after punctuation-normalization) is contained in — or contains — a captured
    citation is dropped in favour of the full captured one. This fixes the GM's lossy paraphrasing
    (shortening or re-punctuating a citation) while still keeping a genuinely distinct prose citation.
    """
    captured = get_turn_citations()
    out = list(captured)
    norm_captured = [_norm_citation(c["label"]) for c in captured]
    seen = set(norm_captured)
    for prose in _parse_prose_citations(text):
        n = _norm_citation(prose["label"])
        if n in seen:
            continue
        if any(n in full or full in n for full in norm_captured):  # same source, re-phrased — skip
            continue
        out.append(prose)
        seen.add(n)
    return out


def _expecting(text: str) -> str:
    """Best-effort hint for the UI: is the learner expected to answer, continue, or free-type next?"""
    if _CONTINUE_RE.search(text):
        return "continue"
    if "?" in text:  # a challenge/question was posed — expect an answer
        return "answer"
    return "free"


def _parse_choices(text: str) -> list[dict]:
    out = []
    for m in _CHOICE_RE.finditer(text):
        label = m.group(2).strip()
        # strip a trailing "(Source: …)" if it bled into the option line
        label = _CITATION_RE.sub("", label).strip()
        out.append({"id": m.group(1), "label": label})
    return out


def _state_snapshot() -> dict:
    s = load_state()
    return {
        "learner_name": s.get("learner_name", ""),
        "confidence": s.get("confidence", 0),
        "location": s.get("current_place", ""),
        "lesson_index": s.get("lesson_index", 0),
        "skills": s.get("skills", []),
        "places_helped": s.get("places_helped", []),
        "learner_context": s.get("learner_context", {}),
    }


def build_turn(text: str, speaker: str = "Storyteller") -> dict:
    """Normalize one GM narration into the Turn contract (a JSON-serializable dict)."""
    turn = Turn(
        speaker=speaker,
        text=text,
        citations=_merge_citations(text),
        choices=_parse_choices(text),
        expecting=_expecting(text),
        state=_state_snapshot(),
    )
    return asdict(turn)

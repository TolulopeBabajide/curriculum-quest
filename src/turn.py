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
    "whether a market, farm, or stream is nearby). Save it with set_learner_context, then open the "
    "morning at their home & compound and offer their first choices."
)

_CITATION_RE = re.compile(r"\(Source:\s*([^)]+)\)", re.IGNORECASE)
_CHOICE_RE = re.compile(r"^\s*(\d+)[\).]\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class Turn:
    speaker: str
    text: str
    citations: list[dict] = field(default_factory=list)
    choices: list[dict] = field(default_factory=list)
    state: dict = field(default_factory=dict)


def _parse_citations(text: str) -> list[dict]:
    seen, out = set(), []
    for m in _CITATION_RE.finditer(text):
        label = m.group(1).strip()
        if label.lower() not in seen:
            seen.add(label.lower())
            out.append({"label": label})
    return out


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
        "skills": s.get("skills", []),
        "places_helped": s.get("places_helped", []),
        "learner_context": s.get("learner_context", {}),
    }


def build_turn(text: str, speaker: str = "Storyteller") -> dict:
    """Normalize one GM narration into the Turn contract (a JSON-serializable dict)."""
    turn = Turn(
        speaker=speaker,
        text=text,
        citations=_parse_citations(text),
        choices=_parse_choices(text),
        state=_state_snapshot(),
    )
    return asdict(turn)

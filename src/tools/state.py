"""Campaign state — the shared, mutable world memory.

Kept deliberately separate from the static world lore (which lives in Foundry IQ). State is a small
JSON file the agents read and update through function tools.
"""
from __future__ import annotations

import contextvars
import copy
import json
import re
from pathlib import Path

from agent_framework import ai_function

from ..config import ROOT

STATE_PATH = ROOT / "state" / "campaign_state.json"

# Bounds for the state-mutating tools (M-04) — defence-in-depth against a model (or
# prompt-injected learner text routed through it) writing unbounded or malformed values.
CONFIDENCE_MIN = 0
CONFIDENCE_MAX = 10
MAX_NAME_LEN = 60
MAX_NOTES_LEN = 500
MAX_SKILL_LEN = 80
MAX_PLACE_LEN = 80
MAX_FEATURE_LEN = 60
MAX_FLAG_KEY_LEN = 60
MAX_FLAG_VALUE_LEN = 120
MAX_FLAGS = 100
# Flag keys are internal story markers (e.g. "market_gutter_cleared") — restrict to a safe charset.
_FLAG_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,%d}$" % MAX_FLAG_KEY_LEN)


def _clip(text: str, limit: int) -> str:
    """Trim a string to a sane maximum length."""
    return text[:limit]
_DEFAULT = {
    "learner_name": "",
    "confidence": 3,
    "current_place": "Home & compound",
    "lesson_index": 0,         # position in the ordered curriculum path (see game_master CURRICULUM_PATH)
    "skills": [],
    "places_helped": [],
    "world_flags": {},
    # Learner's real environment — drives localization of every example and challenge.
    "learner_context": {
        "home_type": "",          # village / town / city
        "cooking_energy": "",     # firewood / charcoal / kerosene / gas / electric / solar
        "lighting_energy": "",    # lamp / candle / electricity / generator / solar
        "nearby_features": [],    # e.g. ["market", "stream", "farm"]
        "notes": "",
    },
}


# Per-session isolation: the server points each connection at its own state file via this context
# variable so concurrent sessions don't clobber the shared file. The CLI and direct tool use fall
# back to STATE_PATH. Because each connection runs in its own asyncio task (which copies the current
# context), a value set per-connection is visible to that connection's tool calls only.
SESSIONS_DIR = ROOT / "state" / "sessions"
_active_state_path: contextvars.ContextVar[Path] = contextvars.ContextVar(
    "active_state_path", default=STATE_PATH
)


def _path() -> Path:
    return _active_state_path.get()


def _load() -> dict:
    p = _path()
    if p.exists():
        return json.loads(p.read_text())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_DEFAULT, indent=2))
    return copy.deepcopy(_DEFAULT)


def _save(state: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2))


def begin_session(session_id: str) -> contextvars.Token:
    """Point the current context at a fresh private state file for this session. Returns a reset token."""
    token = _active_state_path.set(SESSIONS_DIR / f"{session_id}.json")
    reset_state()  # writes fresh defaults to the session's file (via _path())
    return token


def end_session(token: contextvars.Token) -> None:
    """Delete this session's state file and restore the previous context path."""
    try:
        p = _path()
        if p != STATE_PATH and p.exists():
            p.unlink()
    finally:
        _active_state_path.reset(token)


def load_state() -> dict:
    """Public read of the current campaign state (used by the API to build turn payloads)."""
    return _load()


def reset_state() -> dict:
    """Reset to a fresh campaign (used by the server at the start of a new play session)."""
    fresh = copy.deepcopy(_DEFAULT)
    _save(fresh)
    return fresh


@ai_function
def get_campaign_state() -> str:
    """Return the current campaign state (confidence, place, skills, learner context) as JSON."""
    return json.dumps(_load())


@ai_function
def set_learner_context(
    learner_name: str = "",
    home_type: str = "",
    cooking_energy: str = "",
    lighting_energy: str = "",
    nearby_features: str = "",
    notes: str = "",
) -> str:
    """Save what the game learns about the learner's REAL environment, for localizing every scene.

    Only pass the fields you have; leave others blank. `nearby_features` is a comma-separated list
    (e.g. "market, stream, farm"). Returns updated state JSON.
    """
    state = _load()
    if learner_name:
        state["learner_name"] = _clip(learner_name, MAX_NAME_LEN)
    ctx = state["learner_context"]
    if home_type:
        ctx["home_type"] = _clip(home_type, MAX_FEATURE_LEN)
    if cooking_energy:
        ctx["cooking_energy"] = _clip(cooking_energy, MAX_FEATURE_LEN)
    if lighting_energy:
        ctx["lighting_energy"] = _clip(lighting_energy, MAX_FEATURE_LEN)
    if nearby_features:
        ctx["nearby_features"] = [
            _clip(f.strip(), MAX_FEATURE_LEN) for f in nearby_features.split(",") if f.strip()
        ]
    if notes:
        ctx["notes"] = _clip(notes, MAX_NOTES_LEN)
    _save(state)
    return json.dumps(state)


@ai_function
def award_skill(skill: str) -> str:
    """Award a Skill for a mastered topic (e.g. 'Pollution Stopper'). Returns updated state JSON."""
    state = _load()
    skill = _clip(skill, MAX_SKILL_LEN)
    if skill and skill not in state["skills"]:
        state["skills"].append(skill)
    _save(state)
    return json.dumps(state)


@ai_function
def adjust_confidence(delta: int) -> str:
    """Change the learner's Confidence by delta (e.g. -1 for a wrong answer). Clamped to 0-10."""
    state = _load()
    state["confidence"] = max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, state["confidence"] + delta))
    _save(state)
    return json.dumps(state)


@ai_function
def set_flag(key: str, value: str) -> str:
    """Set a story flag (e.g. 'market_gutter_cleared' = 'true'). Returns updated state JSON.

    Keys are restricted to a safe charset (letters, digits, `_.-`) and a capped count, so the
    flag store can't be turned into an unbounded scratchpad for arbitrary model/learner content.
    """
    state = _load()
    if not _FLAG_KEY_RE.match(key):
        return json.dumps(state)  # reject malformed/oversized keys; state unchanged
    if key not in state["world_flags"] and len(state["world_flags"]) >= MAX_FLAGS:
        return json.dumps(state)  # cap distinct flags
    state["world_flags"][key] = _clip(value, MAX_FLAG_VALUE_LEN)
    _save(state)
    return json.dumps(state)


@ai_function
def mark_place_helped(place: str) -> str:
    """Record that the learner has improved a place in the community. Returns updated state JSON."""
    state = _load()
    place = _clip(place, MAX_PLACE_LEN)
    if place and place not in state["places_helped"]:
        state["places_helped"].append(place)
    _save(state)
    return json.dumps(state)


@ai_function
def advance_lesson() -> str:
    """Move to the NEXT lesson in the curriculum path. Call this only after the current lesson's
    teach -> challenge -> verify is complete. Returns updated state JSON (with the new lesson_index)."""
    state = _load()
    state["lesson_index"] = int(state.get("lesson_index", 0)) + 1
    _save(state)
    return json.dumps(state)


STATE_TOOLS = [
    get_campaign_state,
    set_learner_context,
    award_skill,
    adjust_confidence,
    set_flag,
    mark_place_helped,
    advance_lesson,
]

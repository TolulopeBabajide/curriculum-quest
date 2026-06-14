"""Campaign state — the shared, mutable world memory.

Kept deliberately separate from the static world lore (which lives in Foundry IQ). State is a small
JSON file the agents read and update through function tools.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from agent_framework import ai_function

from ..config import ROOT

STATE_PATH = ROOT / "state" / "campaign_state.json"
_DEFAULT = {
    "learner_name": "",
    "confidence": 3,
    "current_place": "Home & compound",
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


def _load() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(_DEFAULT, indent=2))
    return dict(_DEFAULT)


def _save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


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
        state["learner_name"] = learner_name
    ctx = state["learner_context"]
    if home_type:
        ctx["home_type"] = home_type
    if cooking_energy:
        ctx["cooking_energy"] = cooking_energy
    if lighting_energy:
        ctx["lighting_energy"] = lighting_energy
    if nearby_features:
        ctx["nearby_features"] = [f.strip() for f in nearby_features.split(",") if f.strip()]
    if notes:
        ctx["notes"] = notes
    _save(state)
    return json.dumps(state)


@ai_function
def award_skill(skill: str) -> str:
    """Award a Skill for a mastered topic (e.g. 'Pollution Stopper'). Returns updated state JSON."""
    state = _load()
    if skill not in state["skills"]:
        state["skills"].append(skill)
    _save(state)
    return json.dumps(state)


@ai_function
def adjust_confidence(delta: int) -> str:
    """Change the learner's Confidence by delta (e.g. -1 for a wrong answer). Floors at 0."""
    state = _load()
    state["confidence"] = max(0, state["confidence"] + delta)
    _save(state)
    return json.dumps(state)


@ai_function
def set_flag(key: str, value: str) -> str:
    """Set a story flag (e.g. 'market_gutter_cleared' = 'true'). Returns updated state JSON."""
    state = _load()
    state["world_flags"][key] = value
    _save(state)
    return json.dumps(state)


@ai_function
def mark_place_helped(place: str) -> str:
    """Record that the learner has improved a place in the community. Returns updated state JSON."""
    state = _load()
    if place not in state["places_helped"]:
        state["places_helped"].append(place)
    _save(state)
    return json.dumps(state)


STATE_TOOLS = [
    get_campaign_state,
    set_learner_context,
    award_skill,
    adjust_confidence,
    set_flag,
    mark_place_helped,
]

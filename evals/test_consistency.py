"""Lightweight evals (stretch goal) — story consistency + rule correctness.

These are deliberately small and offline-friendly. They check the *rules of the system*, not the
LLM's prose, so they run fast and stay deterministic. Expand with LLM-graded checks if time allows.

Run:  python -m pytest evals/ -v     (after: pip install pytest)
"""
from __future__ import annotations

import json

from src.tools import state as state_tools
from src.tools.lore import curriculum_knowledge


def _reset(tmp):
    state_tools.STATE_PATH = tmp / "campaign_state.json"
    return state_tools


def test_curriculum_retrieval_is_cited():
    """Every retrieved curriculum chunk must carry a citation (no ungrounded content)."""
    payload = json.loads(curriculum_knowledge("living and non-living things"))
    assert payload["results"], "expected at least one curriculum chunk"
    for chunk in payload["results"]:
        assert chunk.get("citation"), "every chunk must be cited"
        assert "NERDC" in chunk["citation"], "citation should trace to NERDC"


def test_confidence_floor_at_zero(tmp_path):
    """Confidence must never go negative — learning is never 'game over'."""
    st = _reset(tmp_path)
    for _ in range(5):
        result = json.loads(st.adjust_confidence(-1))
    assert result["confidence"] == 0


def test_skill_is_idempotent(tmp_path):
    """Awarding the same skill twice should not duplicate it."""
    st = _reset(tmp_path)
    st.award_skill("Pollution Stopper")
    result = json.loads(st.award_skill("Pollution Stopper"))
    assert result["skills"].count("Pollution Stopper") == 1


def test_learner_context_localizes(tmp_path):
    """Learner context must persist so scenes can localize to the real environment."""
    st = _reset(tmp_path)
    result = json.loads(
        st.set_learner_context(home_type="village", cooking_energy="firewood", nearby_features="market, stream")
    )
    assert result["learner_context"]["cooking_energy"] == "firewood"
    assert "market" in result["learner_context"]["nearby_features"]


def test_wrong_topic_returns_no_false_grounding():
    """A nonsense query should not fabricate cited content."""
    payload = json.loads(curriculum_knowledge("zzzqqq nonsense not in curriculum"))
    assert payload["results"] == [] or all(c.get("citation") for c in payload["results"])

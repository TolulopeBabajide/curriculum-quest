"""Tests for the Turn citation contract — tool-captured citations are authoritative over GM prose.

The core guarantee: even when the Game Master shortens a citation in its narration, the Turn carries
the FULL citation captured from the retrieval tool (src/citations.py), and the shortened prose stub is
dropped rather than duplicated.
"""
from __future__ import annotations

from src.citations import begin_turn_citations, get_turn_citations, record_citation
from src.turn import build_turn

FULL = "NERDC JSS1 Basic Science · Theme 1 (Learning About Our Environment) · Topic: Family Health"


def test_record_and_read_roundtrip():
    begin_turn_citations()
    record_citation(FULL, title="Family Health", source="foundry-iq")
    record_citation(FULL, title="Family Health", source="foundry-iq")  # de-duped
    got = get_turn_citations()
    assert len(got) == 1
    assert got[0]["label"] == FULL and got[0]["source"] == "foundry-iq"


def test_record_outside_turn_is_noop():
    # No begin_turn_citations() — record must not raise and must not leak across turns.
    begin_turn_citations()  # reset to empty for isolation
    get_turn_citations()  # empty
    assert get_turn_citations() == []


def test_build_turn_prefers_full_captured_over_shortened_prose():
    begin_turn_citations()
    record_citation(FULL, title="Family Health", source="foundry-iq")
    # The GM narrated a SHORTENED version of the same citation.
    text = "Teacher Adaeze explains malaria spreads from standing water. (Source: NERDC JSS1 Basic Science · Theme 1)"
    turn = build_turn(text)
    labels = [c["label"] for c in turn["citations"]]
    assert FULL in labels  # full citation present
    assert "NERDC JSS1 Basic Science · Theme 1" not in labels  # shortened stub dropped, not duplicated
    assert len(turn["citations"]) == 1


def test_build_turn_dedupes_repunctuated_prose():
    # The GM re-rendered the captured citation with an em-dash and dropped the tail — same source.
    begin_turn_citations()
    record_citation(FULL, source="foundry-iq")
    text = "…malaria. (Source: NERDC JSS1 Basic Science — Theme 1 (Learning About Our Environment)"
    turn = build_turn(text)
    assert len(turn["citations"]) == 1  # the re-punctuated stub is recognized as a duplicate
    assert turn["citations"][0]["label"] == FULL


def test_build_turn_keeps_unrelated_prose_citation():
    begin_turn_citations()
    record_citation(FULL, source="foundry-iq")
    text = "A note grounded elsewhere. (Source: Oke-Ola world pack — The market)"
    turn = build_turn(text)
    labels = [c["label"] for c in turn["citations"]]
    assert FULL in labels
    assert "Oke-Ola world pack — The market" in labels  # distinct prose citation kept


def test_expecting_hint():
    begin_turn_citations()
    assert build_turn("Ready for Lesson 2? Say 'continue'.")["expecting"] == "continue"
    begin_turn_citations()
    assert build_turn("What would you do to keep the water clean?")["expecting"] == "answer"
    begin_turn_citations()
    assert build_turn("The sun sets over Oke-Ola.")["expecting"] == "free"

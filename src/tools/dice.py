"""Dice tool — NARRATIVE FLAVOUR ONLY.

Never used to decide whether learning succeeds (that is the knowledge check). Used for cosmetic
outcomes: what the player notices, a creature's mood, the weather, etc.
"""
from __future__ import annotations

import json
import random

from agent_framework import ai_function


@ai_function
def roll_dice(sides: int = 20, modifier: int = 0, reason: str = "flourish") -> str:
    """Roll a die for a narrative flourish only (not for knowledge checks).

    Args:
        sides: number of sides on the die (default 20).
        modifier: flat number added to the roll.
        reason: short label for what this roll decides (e.g. "weather", "creature mood").
    Returns:
        JSON string with the roll result.
    """
    raw = random.randint(1, max(2, sides))
    total = raw + modifier
    return json.dumps(
        {"roll": raw, "modifier": modifier, "total": total, "sides": sides, "reason": reason}
    )

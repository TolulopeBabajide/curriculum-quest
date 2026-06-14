"""Curriculum Quest — playable CLI turn loop.

Run:  python -m src.game_loop
Requires:  a filled .env  +  `az login`  +  (ideally) a seeded Foundry IQ knowledge base.
If Foundry IQ isn't ready, set USE_LOCAL_FALLBACK=true in .env to play with local cited retrieval.
"""
from __future__ import annotations

import asyncio

from .agents.characters import build_characters
from .agents.game_master import build_game_master
from .clients import get_chat_client
from .config import settings
from .safety import wrap_learner_input
from .tools.lore import build_lore_tools
from .turn import OPENING

BANNER = r"""
   ____                _           _                   ___                 _
  / ___|   _ _ __ _ __(_) ___ _   _| |_   _ _ __ ___    / _ \ _   _  ___  __| |_
 | |  | | | | '__| '__| |/ __| | | | | | | | '_ ` _ \  | | | | | | |/ _ \/ _` __|
 | |__| |_| | |  | |  | | (__| |_| | | |_| | | | | | | | |_| | |_| |  __/ (_| |_
  \____\__,_|_|  |_|  |_|\___|\__,_|_|\__,_|_| |_| |_|  \__\_\\__,_|\___|\__,_|
   Learn JSS1 Basic Science through everyday life in the community of Oke-Ola.
"""

async def _say(agent, message, thread):
    """Run one turn and return the agent's text, handling preview-SDK return shapes."""
    result = await agent.run(message, thread=thread)
    return getattr(result, "text", None) or str(result)


async def main() -> None:
    print(BANNER)
    print(f"Subject: {settings.grade} {settings.subject}")
    print("Type your action each turn. Commands: 'quit' to exit.\n")

    # `async with` closes the chat client's async transport on exit (no aiohttp "unclosed session").
    async with get_chat_client() as client:
        lore_tools = build_lore_tools()
        characters = build_characters(client, lore_tools)
        gm = build_game_master(client, characters, world_lore_tool=lore_tools["world"])

        # A thread gives the Game Master memory across turns.
        thread = gm.get_new_thread() if hasattr(gm, "get_new_thread") else None

        # Opening scene.
        print("Loreweaver:\n" + await _say(gm, OPENING, thread) + "\n")

        while True:
            try:
                user = input("You > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nThe Lumen dims for now. Farewell, Lumen-Bearer.")
                break
            if not user:
                continue
            if user.lower() in {"quit", "exit"}:
                print("The Lumen dims for now. Farewell, Lumen-Bearer.")
                break
            # Wrap untrusted learner text as data, never instructions (H-02). OPENING above
            # is trusted system text and is sent unwrapped.
            reply = await _say(gm, wrap_learner_input(user), thread)
            print("\nLoreweaver:\n" + reply + "\n")


if __name__ == "__main__":
    asyncio.run(main())

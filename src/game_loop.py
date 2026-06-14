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
from .safety import sanitize_learner_input
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

async def _say(agent, message, thread) -> str:
    """Stream one turn to the console: show a 'thinking' cue, then print tokens as they arrive.

    Streaming is the key UX signal — it tells the learner their input was accepted and a reply is
    being built (a turn orchestrates several agent + retrieval calls, so the first token can take a
    few seconds). Returns the full text once complete.
    """
    print("Loreweaver is thinking…", end="", flush=True)
    parts: list[str] = []
    async for update in agent.run_stream(message, thread=thread):
        chunk = getattr(update, "text", "") or ""
        if not chunk:
            continue
        if not parts:  # first real token — clear the cue and start the reply
            print("\r\033[KLoreweaver:\n", end="", flush=True)
        print(chunk, end="", flush=True)
        parts.append(chunk)
    if not parts:  # nothing streamed (rare) — fall back to a single non-streamed call
        result = await agent.run(message, thread=thread)
        text = getattr(result, "text", None) or str(result)
        print("\r\033[KLoreweaver:\n" + text, end="", flush=True)
        parts.append(text)
    print("\n")
    return "".join(parts)


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

        # Opening scene (OPENING is trusted system text — not sanitized).
        await _say(gm, OPENING, thread)

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
            # Sanitize untrusted learner text server-side (invisible — no markers); the agents'
            # guardrails + the user/system role boundary handle injection (H-02).
            await _say(gm, sanitize_learner_input(user), thread)


if __name__ == "__main__":
    asyncio.run(main())

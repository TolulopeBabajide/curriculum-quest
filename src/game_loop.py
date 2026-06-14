"""Curriculum Quest — playable CLI turn loop.

Run:  python -m src.game_loop
Requires:  a filled .env  +  `az login`  +  (ideally) a seeded Foundry IQ knowledge base.
If Foundry IQ isn't ready, set USE_LOCAL_FALLBACK=true in .env to play with local cited retrieval.
"""
from __future__ import annotations

import asyncio
import logging
import warnings

from .agents.characters import build_characters
from .agents.game_master import build_game_master
from .clients import get_chat_client
from .config import settings
from .observability import configure_logging, turn_span
from .safety import sanitize_learner_input
from .tools.lore import build_lore_tools
from .turn import OPENING

# Keep the player's console clean: preview-SDK experimental warnings are noise, and transient
# per-turn stream errors are caught and recovered in `_say`, so the SDK's error logs needn't surface.
# The real failure detail still lands in the structured turn log (state/logs/turns.jsonl).
warnings.filterwarnings("ignore")
logging.getLogger("agent_framework").setLevel(logging.CRITICAL)

_TURN_ATTEMPTS = 3  # silent retries for a turn before showing a graceful "try again" message

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
    shown: list[str] = []

    def emit(text: str) -> None:
        if not shown:  # first output — clear the cue, start the reply
            print("\r\033[KLoreweaver:\n", end="", flush=True)
        print(text, end="", flush=True)
        shown.append(text)

    # Retry transient turn failures silently while nothing has been displayed yet, so the player
    # only ever sees the "thinking…" cue. First attempt streams (live UX); retries use the
    # non-streamed call, which is more reliable here. Degrade gracefully only if all attempts fail.
    # Every turn — and the real cause of any failure — is logged via turn_span (state/logs/turns.jsonl).
    with turn_span("cli", input_len=len(message)) as rec:
        for attempt in range(_TURN_ATTEMPTS):
            rec.note_attempt()
            try:
                if attempt == 0:  # stream for a live, token-by-token reply
                    got: list[str] = []
                    async for update in agent.run_stream(message, thread=thread):
                        chunk = getattr(update, "text", "") or ""
                        if chunk:
                            emit(chunk)
                            got.append(chunk)
                    if got:
                        print("\n")
                        rec.ok = True
                        return "".join(got)
                # retry path (or an empty first stream): one non-streamed call
                result = await agent.run(message, thread=thread)
                text = getattr(result, "text", None) or str(result)
                if text:
                    emit(text)
                    print("\n")
                    rec.ok = True
                    return text
            except Exception as exc:  # noqa: BLE001 — transient/preview-SDK turn failures degrade, not crash
                rec.note_failure(exc)
                if shown:  # partial already on screen — finalize, don't retry/duplicate
                    print("\n")
                    rec.ok = True
                    return "".join(shown)
                await asyncio.sleep(0.6 * (attempt + 1))  # brief, invisible backoff, then retry
        emit("(The story stumbled for a moment — please try that again.)")
        print("\n")
        return "".join(shown)


async def main() -> None:
    configure_logging()  # structured turn log → state/logs/turns.jsonl (console stays clean)
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

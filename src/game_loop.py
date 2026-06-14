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

# Recovery strategy, informed by instrumented live runs (state/logs/turns.jsonl):
# the failure is Azure's server-side server_error ("Sorry, something went wrong"), and it is NOT
# recoverable client-side — same-thread retries fail identically (turns_retried stays 0) AND a
# fresh-thread retry was observed to fail too (it's deterministic for the runtime's state under load,
# not thread poisoning). So we keep retries minimal and cheap: stream once, one quick same-thread
# retry for a genuinely transient blip, then a single fresh-thread last resort (cheap safety net, not
# a reliable fix). The real lever is reducing per-turn orchestration load + Azure deployment capacity.
_SAME_THREAD_ATTEMPTS = 2
_BACKOFF_S = 0.3

BANNER = r"""
   ____                _           _                   ___                 _
  / ___|   _ _ __ _ __(_) ___ _   _| |_   _ _ __ ___    / _ \ _   _  ___  __| |_
 | |  | | | | '__| '__| |/ __| | | | | | | | '_ ` _ \  | | | | | | |/ _ \/ _` __|
 | |__| |_| | |  | |  | | (__| |_| | | |_| | | | | | | | |_| | |_| |  __/ (_| |_
  \____\__,_|_|  |_|  |_|\___|\__,_|_|\__,_|_| |_| |_|  \__\_\\__,_|\___|\__,_|
   Learn JSS1 Basic Science through everyday life in the community of Oke-Ola.
"""

async def _say(agent, message, thread):
    """Stream one turn to the console: show a 'thinking' cue, then print tokens as they arrive.

    Streaming is the key UX signal — it tells the learner their input was accepted and a reply is
    being built (a turn orchestrates several agent + retrieval calls, so the first token can take a
    few seconds).

    Recovery: a couple of quick same-thread attempts, then one last attempt on a FRESH thread as a
    cheap safety net (live runs show the Azure server_error is deterministic under load and a fresh
    thread usually does NOT recover it either — see the module constants). If a fresh thread does
    succeed it is adopted for the rest of the session (in-thread memory is lost, but campaign progress
    is persisted in state and the Storyteller re-grounds via its state tools).

    Returns ``(full_text, thread_to_use_next)`` — the caller must keep the returned thread.
    """
    print("Loreweaver is thinking…", end="", flush=True)
    shown: list[str] = []

    def emit(text: str) -> None:
        if not shown:  # first output — clear the cue, start the reply
            print("\r\033[KLoreweaver:\n", end="", flush=True)
        print(text, end="", flush=True)
        shown.append(text)

    async def _run_once(thr, *, stream: bool) -> str | None:
        """One attempt on the given thread. Streams (live UX) or uses the non-streamed call."""
        if stream:
            got: list[str] = []
            async for update in agent.run_stream(message, thread=thr):
                chunk = getattr(update, "text", "") or ""
                if chunk:
                    emit(chunk)
                    got.append(chunk)
            return "".join(got) or None
        result = await agent.run(message, thread=thr)
        text = getattr(result, "text", None) or str(result)
        if text:
            emit(text)
        return text or None

    # Every turn — and the real cause of any failure — is logged via turn_span (state/logs/turns.jsonl).
    with turn_span("cli", input_len=len(message)) as rec:
        # Phase 1: same thread (stream first for live UX, then one quick non-streamed retry).
        for attempt in range(_SAME_THREAD_ATTEMPTS):
            rec.note_attempt()
            try:
                text = await _run_once(thread, stream=(attempt == 0))
                if text:
                    print("\n")
                    rec.ok = True
                    return text, thread
            except Exception as exc:  # noqa: BLE001 — turn failures must degrade, not crash
                rec.note_failure(exc)
                if shown:  # partial already on screen — finalize, don't retry/duplicate
                    print("\n")
                    rec.ok = True
                    return "".join(shown), thread
                await asyncio.sleep(_BACKOFF_S * (attempt + 1))  # brief, invisible backoff
        # Phase 2: last resort on a FRESH thread (the same-thread run failure keeps reproducing).
        if hasattr(agent, "get_new_thread") and not shown:
            fresh = agent.get_new_thread()
            rec.note_attempt()
            try:
                text = await _run_once(fresh, stream=False)
                if text:
                    print("\n")
                    rec.ok = True
                    rec.recovered_on_new_thread = True
                    return text, fresh
            except Exception as exc:  # noqa: BLE001
                rec.note_failure(exc)
        emit("(The story stumbled for a moment — please try that again.)")
        print("\n")
        return "".join(shown), thread


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
        _, thread = await _say(gm, OPENING, thread)

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
            # guardrails + the user/system role boundary handle injection (H-02). Keep the returned
            # thread — a fresh-thread recovery adopts a new thread for the rest of the session.
            _, thread = await _say(gm, sanitize_learner_input(user), thread)


if __name__ == "__main__":
    asyncio.run(main())

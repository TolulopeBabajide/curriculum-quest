"""Curriculum Quest backend — drives the game over HTTP/WebSocket for any visual frontend.

This is the same game the CLI plays, exposed as a service. The agents, tools, and Foundry IQ
grounding are reused unchanged; this layer just speaks the structured Turn contract (see turn.py)
so a 2D visual novel or a 3D world can render it.

Endpoints:
  GET  /health        — readiness + which grounding path is active.
  WS   /play          — one play session. The server sends the opening Turn on connect, then a
                        Turn for each text message the client sends. Send "quit" to end.

Run:  uvicorn src.server:app --reload --port 8000
(single-player demo: campaign state is one shared file and is reset at the start of each session)
"""
from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .agents.characters import build_characters
from .agents.game_master import build_game_master
from .clients import get_chat_client
from .config import settings
from .safety import wrap_learner_input
from .tools.lore import build_lore_tools
from .tools.state import begin_session, end_session
from .turn import OPENING, build_turn

# Demo-grade abuse guards on the public /play socket (H-03). Auth and production-grade,
# shared rate limiting are still needed before public deployment (tracked as GRC/H follow-ups).
TURN_TIMEOUT_S = 120.0  # max wall-clock per turn before a graceful error turn
MAX_TURNS = 100  # per-connection message budget before a polite close
MIN_TURN_INTERVAL_S = 0.5  # minimum spacing between learner messages

app = FastAPI(title="Curriculum Quest")


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "subject": settings.subject,
        "grade": settings.grade,
        "grounding": "local-fallback" if settings.use_local_fallback else "foundry-iq",
    }


async def _run(gm, message, thread) -> str:
    result = await gm.run(message, thread=thread)
    return getattr(result, "text", None) or str(result)


async def _close(client) -> None:
    for name in ("aclose", "close"):
        fn = getattr(client, name, None)
        if fn:
            try:
                res = fn()
                if hasattr(res, "__await__"):
                    await res
            except Exception:
                pass
            return


@app.websocket("/play")
async def play(ws: WebSocket) -> None:
    await ws.accept()
    # Private per-connection state file (isolated via a context var) so concurrent sessions
    # don't clobber each other.
    token = begin_session(uuid.uuid4().hex)

    client = get_chat_client()
    lore_tools = build_lore_tools()
    characters = build_characters(client, lore_tools)
    gm = build_game_master(client, characters, world_lore_tool=lore_tools["world"])
    thread = gm.get_new_thread() if hasattr(gm, "get_new_thread") else None

    turns = 0
    last_turn_at = 0.0
    try:
        # OPENING is trusted system text — sent unwrapped, not subject to the per-turn budget.
        await ws.send_json(build_turn(await _run(gm, OPENING, thread)))
        while True:
            user = (await ws.receive_text()).strip()
            if not user:
                continue
            if user.lower() in {"quit", "exit"}:
                await ws.send_json({"speaker": "Storyteller", "text": "Farewell for now.",
                                    "citations": [], "choices": [], "state": {}})
                break
            # Rate limit: ignore messages arriving faster than the minimum interval.
            now = time.monotonic()
            if now - last_turn_at < MIN_TURN_INTERVAL_S:
                continue
            last_turn_at = now
            # Message budget: close politely once the per-connection cap is reached.
            turns += 1
            if turns > MAX_TURNS:
                await ws.send_json({"speaker": "Storyteller",
                                    "text": "We've played a lot today — let's rest. Farewell for now.",
                                    "citations": [], "choices": [], "state": {}})
                break
            # Per-turn timeout: send a graceful error turn instead of crashing on a slow/looping turn.
            try:
                reply = await asyncio.wait_for(
                    _run(gm, wrap_learner_input(user), thread), timeout=TURN_TIMEOUT_S)
            except asyncio.TimeoutError:
                await ws.send_json({"speaker": "Storyteller",
                                    "text": "That took too long — let's try that again.",
                                    "citations": [], "choices": [], "state": {}})
                continue
            await ws.send_json(build_turn(reply))
    except WebSocketDisconnect:
        pass
    finally:
        await _close(client)
        end_session(token)

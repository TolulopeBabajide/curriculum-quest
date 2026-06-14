"""Curriculum Quest backend — drives the game over HTTP/WebSocket for any visual frontend.

This is the same game the CLI plays, exposed as a service. The agents, tools, and Foundry IQ
grounding are reused unchanged; this layer just speaks the structured Turn contract (see turn.py)
so a 2D visual novel or a 3D world can render it.

Endpoints:
  GET  /health        — readiness + which grounding path is active.
  WS   /play          — one play session. For the opening and each learner message, the server
                        streams JSON frames tagged by `type`:
                          {"type":"status","status":"thinking"}      — ack: input accepted, working
                          {"type":"delta","text":"…"}                 — incremental narration tokens
                          {"type":"turn", ...Turn}                    — final structured turn (turn.py)
                        Send "quit" to end. Learner text is sanitized server-side before the model.

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
from .safety import sanitize_learner_input
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


async def _stream_turn(ws: WebSocket, gm, message, thread) -> None:
    """Stream one turn to the client: a 'thinking' ack, incremental deltas, then the final Turn."""
    await ws.send_json({"type": "status", "status": "thinking"})
    parts: list[str] = []
    try:
        async for update in gm.run_stream(message, thread=thread):
            chunk = getattr(update, "text", "") or ""
            if chunk:
                parts.append(chunk)
                await ws.send_json({"type": "delta", "text": chunk})
    except Exception:  # noqa: BLE001 — transient/preview-SDK turn failures must degrade, not crash
        pass
    full = "".join(parts)
    if not full:  # nothing streamed — fall back to one non-streamed call, then a kind message
        try:
            result = await gm.run(message, thread=thread)
            full = getattr(result, "text", None) or str(result)
        except Exception:  # noqa: BLE001
            full = "The story stumbled for a moment — please try that again."
    await ws.send_json({"type": "turn", **build_turn(full)})


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
    def _bye(text: str) -> dict:
        return {"type": "turn", "speaker": "Storyteller", "text": text,
                "citations": [], "choices": [], "state": {}}

    try:
        # OPENING is trusted system text — streamed unwrapped, not subject to the per-turn budget.
        await _stream_turn(ws, gm, OPENING, thread)
        while True:
            user = (await ws.receive_text()).strip()
            if not user:
                continue
            if user.lower() in {"quit", "exit"}:
                await ws.send_json(_bye("Farewell for now."))
                break
            # Rate limit: ignore messages arriving faster than the minimum interval.
            now = time.monotonic()
            if now - last_turn_at < MIN_TURN_INTERVAL_S:
                continue
            last_turn_at = now
            # Message budget: close politely once the per-connection cap is reached.
            turns += 1
            if turns > MAX_TURNS:
                await ws.send_json(_bye("We've played a lot today — let's rest. Farewell for now."))
                break
            # Sanitize untrusted learner text server-side (invisible — no markers); stream the turn
            # under a per-turn timeout so a slow/looping turn degrades gracefully instead of crashing.
            try:
                await asyncio.wait_for(
                    _stream_turn(ws, gm, sanitize_learner_input(user), thread),
                    timeout=TURN_TIMEOUT_S)
            except asyncio.TimeoutError:
                await ws.send_json(_bye("That took too long — let's try that again."))
                continue
    except WebSocketDisconnect:
        pass
    finally:
        await _close(client)
        end_session(token)

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
from .observability import configure_logging, metrics_snapshot, turn_span
from .safety import sanitize_learner_input
from .tools.lore import build_lore_tools
from .tools.state import begin_session, end_session
from .turn import OPENING, build_turn

# Demo-grade abuse guards on the public /play socket (H-03). Auth and production-grade,
# shared rate limiting are still needed before public deployment (tracked as GRC/H follow-ups).
TURN_TIMEOUT_S = 120.0  # max wall-clock per turn before a graceful error turn
MAX_TURNS = 100  # per-connection message budget before a polite close
MIN_TURN_INTERVAL_S = 0.5  # minimum spacing between learner messages
TURN_ATTEMPTS = 3  # silent retries for a turn before sending a graceful "try again" turn

app = FastAPI(title="Curriculum Quest")


@app.on_event("startup")
async def _startup() -> None:
    configure_logging()  # structured turn log → state/logs/turns.jsonl


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "subject": settings.subject,
        "grade": settings.grade,
        "grounding": "local-fallback" if settings.use_local_fallback else "foundry-iq",
    }


@app.get("/metrics")
async def metrics() -> dict:
    """Operational counters for monitoring: turn volume, retry/failure rates, latency, error causes."""
    return metrics_snapshot()


async def _stream_turn(ws: WebSocket, gm, message, thread, session_id: str | None = None) -> None:
    """Stream one turn to the client: a 'thinking' ack, incremental deltas, then the final Turn.

    Every turn — and the real cause of any failure — is logged via turn_span (state/logs/turns.jsonl).
    """
    await ws.send_json({"type": "status", "status": "thinking"})
    shown: list[str] = []
    # Retry transient failures silently while no delta has been sent — the client only sees the
    # 'thinking' ack until real output. First attempt streams; retries use the non-streamed call.
    with turn_span("ws", session_id=session_id, input_len=len(message)) as rec:
        for attempt in range(TURN_ATTEMPTS):
            rec.note_attempt()
            try:
                if attempt == 0:  # stream for live deltas
                    got: list[str] = []
                    async for update in gm.run_stream(message, thread=thread):
                        chunk = getattr(update, "text", "") or ""
                        if chunk:
                            got.append(chunk)
                            shown.append(chunk)
                            await ws.send_json({"type": "delta", "text": chunk})
                    if got:
                        await ws.send_json({"type": "turn", **build_turn("".join(got))})
                        rec.ok = True
                        return
                # retry path (or an empty first stream): one non-streamed call
                result = await gm.run(message, thread=thread)
                text = getattr(result, "text", None) or str(result)
                if text:
                    await ws.send_json({"type": "turn", **build_turn(text)})
                    rec.ok = True
                    return
            except Exception as exc:  # noqa: BLE001 — transient/preview-SDK turn failures degrade, not crash
                rec.note_failure(exc)
                if shown:  # partial deltas already sent — finalize with what we have
                    await ws.send_json({"type": "turn", **build_turn("".join(shown))})
                    rec.ok = True
                    return
                await asyncio.sleep(0.6 * (attempt + 1))  # brief backoff, then retry
        await ws.send_json(
            {"type": "turn", **build_turn("The story stumbled for a moment — please try that again.")})


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
    session_id = uuid.uuid4().hex
    token = begin_session(session_id)

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
        await _stream_turn(ws, gm, OPENING, thread, session_id)
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
                    _stream_turn(ws, gm, sanitize_learner_input(user), thread, session_id),
                    timeout=TURN_TIMEOUT_S)
            except asyncio.TimeoutError:
                await ws.send_json(_bye("That took too long — let's try that again."))
                continue
    except WebSocketDisconnect:
        pass
    finally:
        await _close(client)
        end_session(token)

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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .agents.characters import build_characters
from .agents.game_master import build_game_master
from .clients import get_chat_client
from .config import settings
from .tools.lore import build_lore_tools
from .tools.state import reset_state
from .turn import OPENING, build_turn

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
    reset_state()  # fresh campaign for this session (single-player demo)

    client = get_chat_client()
    lore_tools = build_lore_tools()
    characters = build_characters(client, lore_tools)
    gm = build_game_master(client, characters, world_lore_tool=lore_tools["world"])
    thread = gm.get_new_thread() if hasattr(gm, "get_new_thread") else None

    try:
        await ws.send_json(build_turn(await _run(gm, OPENING, thread)))
        while True:
            user = (await ws.receive_text()).strip()
            if not user:
                continue
            if user.lower() in {"quit", "exit"}:
                await ws.send_json({"speaker": "Storyteller", "text": "Farewell for now.",
                                    "citations": [], "choices": [], "state": {}})
                break
            await ws.send_json(build_turn(await _run(gm, user, thread)))
    except WebSocketDisconnect:
        pass
    finally:
        await _close(client)

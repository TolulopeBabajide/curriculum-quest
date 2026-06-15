"""Structured logging, turn instrumentation, and in-process metrics for Curriculum Quest.

Why this module exists
----------------------
The preview Azure AI Agents (Foundry) runtime occasionally fails a run with a generic
"Sorry, something went wrong." The Agent Framework surfaces only ``last_error.message`` and
*drops* ``last_error.code`` — see ``agent_framework_azure_ai/_chat_client.py``::

    case AgentStreamEvent.THREAD_RUN_FAILED:
        raise ServiceResponseException(event_data.last_error.message)

So the only signal a turn failed server-side is that opaque message. To make these diagnosable
(and to monitor how often retries/fallbacks fire in the demo) we:

  * write one structured JSON line per turn to a JSONL log (``state/logs/turns.jsonl``),
  * record the *real* exception detail we can extract (type, message, any ``code``/``status_code``/
    inner exception), which is the closest we get to the dropped ``last_error.code``,
  * keep cheap in-process counters + latency stats exposed via :func:`metrics_snapshot`
    (the server publishes these at ``GET /metrics``).

Privacy: logs NEVER contain learner free-text or any child-profile data (project rule). We log the
message *length* and outcome, never the content.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Iterator

from .citations import begin_turn_citations

_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = _ROOT / "state" / "logs"
_TURN_LOG = LOG_DIR / "turns.jsonl"

_configured = False
_logger = logging.getLogger("curriculum_quest")


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Set up JSONL turn logging once. Idempotent; safe to call from CLI and server startup.

    Logs go to a rotating file under ``state/logs/`` (gitignored) — never to the player's console,
    which the game keeps clean. Returns the package logger.
    """
    global _configured
    if _configured:
        return _logger
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        _TURN_LOG, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(_JsonFormatter())
    _logger.addHandler(handler)
    _logger.setLevel(level)
    _logger.propagate = False  # keep these structured lines out of the root/console logger
    _configured = True
    return _logger


class _JsonFormatter(logging.Formatter):
    """Render each record as a single JSON line: timestamp, level, message, and any `extra` fields."""

    _RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def describe_exception(exc: BaseException) -> dict[str, Any]:
    """Best-effort extraction of the *real* failure cause from a turn exception.

    The Azure client drops ``last_error.code``, so we surface everything the exception still carries:
    its type, message, and any ``code``/``status_code``/``error_code`` attribute or wrapped
    ``__cause__``. For the common transient run failure the message is Azure's ``last_error.message``
    (e.g. "Sorry, something went wrong"), which maps to a server-side ``server_error``.
    """
    detail: dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error_message": str(exc) or repr(exc),
    }
    for attr in ("code", "status_code", "error_code", "reason"):
        value = getattr(exc, attr, None)
        if value is not None:
            detail[attr] = value
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        detail["caused_by"] = f"{type(cause).__name__}: {cause}"
    # Heuristic classification for the one failure mode we can't get a code for.
    msg = detail["error_message"].lower()
    if "something went wrong" in msg:
        detail["likely_cause"] = "azure_server_error_transient"
    elif "content" in msg and "filter" in msg:
        detail["likely_cause"] = "content_filter"
    elif "rate" in msg and "limit" in msg:
        detail["likely_cause"] = "rate_limit"
    elif "timeout" in msg or "timed out" in msg:
        detail["likely_cause"] = "timeout"
    return detail


# --- in-process metrics (reset per process; good enough for demo monitoring) ------------------

@dataclass
class _Metrics:
    turns_total: int = 0
    turns_ok: int = 0
    turns_retried: int = 0  # turns that needed >1 attempt but still succeeded
    turns_failed: int = 0  # turns that exhausted all attempts (graceful fallback shown)
    attempts_total: int = 0
    error_causes: dict[str, int] = field(default_factory=dict)
    _latencies_ms: list[float] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def record(self, *, attempts: int, ok: bool, latency_ms: float, cause: str | None) -> None:
        with self._lock:
            self.turns_total += 1
            self.attempts_total += attempts
            if ok:
                self.turns_ok += 1
                if attempts > 1:
                    self.turns_retried += 1
            else:
                self.turns_failed += 1
            if cause:
                self.error_causes[cause] = self.error_causes.get(cause, 0) + 1
            self._latencies_ms.append(latency_ms)
            if len(self._latencies_ms) > 500:  # bound memory
                self._latencies_ms = self._latencies_ms[-500:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            lat = sorted(self._latencies_ms)
            def pct(p: float) -> float:
                if not lat:
                    return 0.0
                return round(lat[min(len(lat) - 1, int(p * len(lat)))], 1)
            return {
                "turns_total": self.turns_total,
                "turns_ok": self.turns_ok,
                "turns_retried": self.turns_retried,
                "turns_failed": self.turns_failed,
                "attempts_total": self.attempts_total,
                "success_rate": round(self.turns_ok / self.turns_total, 3) if self.turns_total else None,
                "latency_ms_p50": pct(0.50),
                "latency_ms_p95": pct(0.95),
                "error_causes": dict(self.error_causes),
            }


_metrics = _Metrics()


def metrics_snapshot() -> dict[str, Any]:
    """Current process metrics — published by the server at ``GET /metrics``."""
    return _metrics.snapshot()


@dataclass
class TurnRecord:
    """Mutable per-turn observation, finalized by :func:`turn_span` on exit."""

    interface: str
    session_id: str | None = None
    input_len: int = 0
    attempts: int = 0
    ok: bool = False
    cause: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def note_attempt(self) -> None:
        self.attempts += 1

    def note_failure(self, exc: BaseException) -> None:
        """Capture the real cause of a failed attempt (surfaces the dropped Azure error detail)."""
        self.detail = describe_exception(exc)
        self.cause = self.detail.get("likely_cause", "unknown")


@contextmanager
def turn_span(interface: str, session_id: str | None = None, input_len: int = 0) -> Iterator[TurnRecord]:
    """Time a turn, then log one structured line and update metrics.

    Usage::

        with turn_span("cli", input_len=len(msg)) as rec:
            rec.note_attempt()
            ...                       # set rec.ok = True on success
            rec.note_failure(exc)     # on each failed attempt

    Never raises on its own; logging/metrics failures must not break gameplay.
    """
    rec = TurnRecord(interface=interface, session_id=session_id, input_len=input_len)
    begin_turn_citations()  # fresh citation accumulator for this turn (read by turn.build_turn)
    start = time.monotonic()
    try:
        yield rec
    finally:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        try:
            _metrics.record(
                attempts=max(rec.attempts, 1), ok=rec.ok, latency_ms=latency_ms, cause=rec.cause)
            level = logging.INFO if rec.ok else logging.WARNING
            _logger.log(
                level, "turn",
                extra={
                    "interface": rec.interface,
                    "session_id": rec.session_id,
                    "input_len": rec.input_len,
                    "attempts": rec.attempts,
                    "ok": rec.ok,
                    "latency_ms": latency_ms,
                    "cause": rec.cause,
                    **({"error": rec.detail} if rec.detail else {}),
                },
            )
        except Exception:  # noqa: BLE001 — observability must never break a turn
            pass

"""Tests for src/observability.py — error-cause surfacing, metrics, and turn instrumentation.

Covers the core promise of the module: a turn failure's *real* cause is extracted (the Azure client
drops last_error.code, so we classify from the message), metrics count retries/failures, and
turn_span never raises on its own.
"""
from __future__ import annotations

from agent_framework.exceptions import ServiceResponseException

from src.observability import _Metrics, describe_exception, turn_span


def test_describe_classifies_azure_server_error():
    # The exact generic message the Foundry runtime raises on a transient run failure.
    exc = ServiceResponseException("Sorry, something went wrong.")
    detail = describe_exception(exc)
    assert detail["error_type"] == "ServiceResponseException"
    assert detail["likely_cause"] == "azure_server_error_transient"
    assert "Sorry, something went wrong" in detail["error_message"]


def test_describe_classifies_content_filter_and_rate_limit():
    assert describe_exception(ValueError("Response was blocked by the content filter"))[
        "likely_cause"] == "content_filter"
    assert describe_exception(ValueError("rate limit exceeded, retry later"))[
        "likely_cause"] == "rate_limit"
    assert describe_exception(TimeoutError("request timed out"))["likely_cause"] == "timeout"


def test_describe_surfaces_attrs_and_cause():
    exc = ValueError("boom")
    exc.code = "server_error"  # type: ignore[attr-defined]
    try:
        raise exc from KeyError("upstream")
    except ValueError as raised:
        detail = describe_exception(raised)
    assert detail["code"] == "server_error"
    assert "KeyError" in detail["caused_by"]


def test_metrics_counts_retry_and_failure():
    m = _Metrics()
    m.record(attempts=1, ok=True, latency_ms=100.0, cause=None)  # clean success
    m.record(attempts=2, ok=True, latency_ms=200.0, cause="azure_server_error_transient")  # retried
    m.record(attempts=3, ok=False, latency_ms=300.0, cause="azure_server_error_transient")  # failed
    snap = m.snapshot()
    assert snap["turns_total"] == 3
    assert snap["turns_ok"] == 2
    assert snap["turns_retried"] == 1
    assert snap["turns_failed"] == 1
    assert snap["attempts_total"] == 6
    assert snap["error_causes"]["azure_server_error_transient"] == 2
    assert snap["latency_ms_p50"] > 0


def test_turn_span_records_success_without_raising():
    with turn_span("test", input_len=42) as rec:
        rec.note_attempt()
        rec.ok = True
    assert rec.attempts == 1 and rec.ok is True


def test_turn_span_captures_failure_cause():
    with turn_span("test") as rec:
        rec.note_attempt()
        rec.note_failure(ServiceResponseException("Sorry, something went wrong."))
    assert rec.cause == "azure_server_error_transient"
    assert rec.detail["error_type"] == "ServiceResponseException"

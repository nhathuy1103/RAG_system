"""Unit tests for the provider-neutral Langfuse facade."""

import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

import pytest

from app.infrastructure.telemetry import Telemetry, TelemetryConfig
from app.infrastructure.telemetry.langfuse import _build_mask_otel_spans


def test_disabled_telemetry_redacts_content_and_has_stable_seeded_trace_ids() -> None:
    telemetry = Telemetry()

    assert telemetry.enabled is False
    assert telemetry.content("secret question") == "[REDACTED]"
    assert telemetry.create_trace_id(seed="job-1") == telemetry.create_trace_id(seed="job-1")

    with telemetry.observe("no-op") as observation:
        observation.update(output={"ok": True})
        assert observation.trace_id is None


def test_enabled_configuration_requires_both_credentials() -> None:
    with pytest.raises(ValueError, match="LANGFUSE_PUBLIC_KEY"):
        Telemetry(TelemetryConfig(enabled=True, public_key="pk-lf-test"))


class _FakeObservation:
    trace_id = "a" * 32

    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    def update(self, **kwargs: object) -> None:
        self.updates.append(kwargs)


class _FakeClient:
    def __init__(self, observation: _FakeObservation) -> None:
        self.observation = observation
        self.start_kwargs: dict[str, object] | None = None

    @contextmanager
    def start_as_current_observation(self, **kwargs: object):
        self.start_kwargs = kwargs
        yield self.observation


def test_observe_propagates_trace_attributes_and_records_error() -> None:
    telemetry = Telemetry(TelemetryConfig(capture_content=True))
    raw = _FakeObservation()
    client = _FakeClient(raw)
    propagated: list[dict[str, object]] = []

    @contextmanager
    def propagate(**kwargs: object):
        propagated.append(kwargs)
        yield

    telemetry._client = client
    telemetry._propagate_attributes = propagate

    with (
        pytest.raises(RuntimeError, match="boom"),
        telemetry.observe(
            "rag.chat",
            trace_id="b" * 32,
            user_id="user-1",
            session_id="session-1",
            tags=("rag", "chat"),
            trace_name="rag-chat",
            metadata={"notebook_id": "notebook-1"},
        ) as observation,
    ):
        assert observation.trace_id == "a" * 32
        raise RuntimeError("boom")

    assert client.start_kwargs is not None
    assert client.start_kwargs["trace_context"] == {"trace_id": "b" * 32}
    assert propagated[0]["user_id"] == "user-1"
    assert propagated[0]["session_id"] == "session-1"
    assert propagated[0]["trace_name"] == "rag-chat"
    assert raw.updates[-1]["level"] == "ERROR"
    assert raw.updates[-1]["status_message"] == "boom"


def test_openai_call_attributes_are_only_added_for_enabled_telemetry() -> None:
    disabled = Telemetry()
    assert disabled.openai_call_attributes("generate-answer") == {}

    enabled = Telemetry(TelemetryConfig(capture_content=True))
    enabled._client = object()

    assert enabled.openai_call_attributes(
        "generate-answer",
        metadata={"evidence_count": 2},
    ) == {
        "name": "generate-answer",
        "metadata": {"evidence_count": 2},
    }


def test_mask_otel_spans_preserves_original_span_identifier(monkeypatch: pytest.MonkeyPatch) -> (
    None
):
    class FakeOtelSpanPatch:
        def __init__(self, *, set_attributes: dict[str, object]) -> None:
            self.set_attributes = set_attributes

    class FakeMaskOtelSpansResult:
        def __init__(self, *, span_patches: dict[object, FakeOtelSpanPatch]) -> None:
            self.span_patches = span_patches

    fake_types = ModuleType("langfuse.types")
    fake_types.OtelSpanPatch = FakeOtelSpanPatch
    fake_types.MaskOtelSpansResult = FakeMaskOtelSpansResult
    monkeypatch.setitem(sys.modules, "langfuse.types", fake_types)

    span_identifier = object()
    params = SimpleNamespace(
        spans={
            span_identifier: SimpleNamespace(
                attributes={"gen_ai.prompt.0.content": "sensitive prompt"}
            )
        }
    )

    result = _build_mask_otel_spans(capture_content=False)(params=params)

    assert result is not None
    assert tuple(result.span_patches) == (span_identifier,)
    assert result.span_patches[span_identifier].set_attributes == {
        "gen_ai.prompt.0.content": "[REDACTED]"
    }

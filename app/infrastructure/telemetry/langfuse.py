"""Small, resilient Langfuse v4 facade used by the RAG application.

The facade keeps Langfuse out of domain/port contracts, makes tracing a no-op
when it is not configured, and centralizes content redaction. Export happens
asynchronously in the SDK, so normal application calls do not wait for the
Langfuse API.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

LOGGER = logging.getLogger(__name__)

ObservationType = Literal[
    "event",
    "span",
    "agent",
    "tool",
    "chain",
    "retriever",
    "evaluator",
    "embedding",
    "generation",
    "guardrail",
]


@dataclass(frozen=True)
class TelemetryConfig:
    """Settings required to create a Langfuse client."""

    enabled: bool = False
    public_key: str | None = None
    secret_key: str | None = None
    base_url: str = "https://cloud.langfuse.com"
    environment: str = "development"
    release: str | None = None
    sample_rate: float = 1.0
    capture_content: bool = False


class Observation:
    """Provider-neutral handle for updating the active observation."""

    def __init__(self, raw: Any | None = None) -> None:
        self._raw = raw

    @property
    def trace_id(self) -> str | None:
        value = getattr(self._raw, "trace_id", None)
        return str(value) if value else None

    def update(self, **kwargs: Any) -> None:
        if self._raw is None:
            return
        try:
            self._raw.update(**kwargs)
        except Exception:
            LOGGER.warning("Could not update Langfuse observation", exc_info=True)


class Telemetry:
    """Langfuse-backed telemetry that degrades to a no-op when disabled."""

    def __init__(self, config: TelemetryConfig | None = None) -> None:
        self.config = config or TelemetryConfig()
        self._client: Any | None = None
        self._propagate_attributes: Any | None = None

        if not self.config.enabled:
            return
        if not self.config.public_key or not self.config.secret_key:
            raise ValueError(
                "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required when "
                "LANGFUSE_ENABLED=true."
            )

        try:
            _configure_langfuse_environment(self.config)
            from langfuse import Langfuse, propagate_attributes

            langfuse_kwargs: dict[str, Any] = {
                "public_key": self.config.public_key,
                "secret_key": self.config.secret_key,
                "base_url": self.config.base_url,
                "environment": self.config.environment,
                "release": self.config.release,
                "sample_rate": self.config.sample_rate,
                "tracing_enabled": True,
            }
            mask_otel_spans = _build_mask_otel_spans(
                capture_content=self.config.capture_content
            )
            if mask_otel_spans is not None:
                langfuse_kwargs["mask_otel_spans"] = mask_otel_spans
            self._client = Langfuse(
                **langfuse_kwargs,
            )
            self._propagate_attributes = propagate_attributes
        except Exception:
            # Bad observability configuration must be visible during startup;
            # it must not silently produce a false sense of coverage.
            LOGGER.exception("Could not initialize Langfuse telemetry")
            raise

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def capture_content(self) -> bool:
        return self.enabled and self.config.capture_content

    def openai_call_attributes(
        self,
        name: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return Langfuse-only OpenAI kwargs when the wrapped client is active."""
        if not self.enabled:
            return {}
        attributes: dict[str, Any] = {"name": name}
        if metadata:
            attributes["metadata"] = dict(metadata)
        return attributes

    def content(self, value: Any) -> Any:
        """Return content only when explicitly enabled, otherwise redact it."""
        return value if self.capture_content else "[REDACTED]"

    def create_trace_id(self, *, seed: str | None = None) -> str:
        """Create a W3C-compatible trace id, deterministically when seeded."""
        if self._client is not None:
            return str(self._client.create_trace_id(seed=seed))
        raw = seed or str(uuid4())
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @contextmanager
    def observe(
        self,
        name: str,
        *,
        as_type: ObservationType = "span",
        trace_id: str | None = None,
        input: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
        model: str | None = None,
        model_parameters: Mapping[str, Any] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: Sequence[str] = (),
        trace_name: str | None = None,
    ) -> Iterator[Observation]:
        """Create a current observation and propagate trace-level attributes."""
        if self._client is None or self._propagate_attributes is None:
            yield Observation()
            return

        trace_context = {"trace_id": trace_id} if trace_id else None
        observation_kwargs: dict[str, Any] = {
            "name": name,
            "as_type": as_type,
            "trace_context": trace_context,
            "input": input,
            "metadata": dict(metadata or {}),
        }
        if model is not None:
            observation_kwargs["model"] = model
        if model_parameters is not None:
            observation_kwargs["model_parameters"] = dict(model_parameters)

        propagation_kwargs = {
            "user_id": _bounded(user_id),
            "session_id": _bounded(session_id),
            "metadata": _trace_metadata(metadata),
            "tags": [_bounded(tag) for tag in tags if _bounded(tag)],
            "trace_name": _bounded(trace_name),
            "environment": self.config.environment,
        }

        with (
            self._client.start_as_current_observation(**observation_kwargs) as raw,
            self._propagate_attributes(**propagation_kwargs),
        ):
            observation = Observation(raw)
            try:
                yield observation
            except Exception as exc:
                observation.update(
                    level="ERROR",
                    status_message=_bounded(str(exc) or exc.__class__.__name__),
                )
                raise

    def flush(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception:
            LOGGER.warning("Could not flush Langfuse telemetry", exc_info=True)

    def shutdown(self) -> None:
        if self._client is None:
            return
        try:
            self._client.shutdown()
        except Exception:
            LOGGER.warning("Could not shut down Langfuse telemetry", exc_info=True)


_SECRET_VALUE_PATTERN = re.compile(
    r"\b(?:sk|pk|rk)-(?:lf-|proj-)?[A-Za-z0-9_-]{8,}\b",
    re.IGNORECASE,
)
_SECRET_ATTRIBUTE_MARKERS = (
    "authorization",
    "api_key",
    "apikey",
    "secret",
    "password",
    "access_token",
    "refresh_token",
)
_CONTENT_ATTRIBUTE_MARKERS = (
    "langfuse.observation.input",
    "langfuse.observation.output",
    "gen_ai.prompt",
    "gen_ai.completion",
    "gen_ai.input",
    "gen_ai.output",
    "llm.prompts",
    "llm.completions",
    "message",
    "messages",
    "content",
)
_NON_CONTENT_ATTRIBUTE_MARKERS = (
    "usage",
    "token",
    "cost",
    "model",
    "temperature",
    "max_tokens",
    "max_completion_tokens",
    "response.id",
)


def _configure_langfuse_environment(config: TelemetryConfig) -> None:
    """Make settings loaded by pydantic visible to Langfuse integrations."""
    if config.public_key is not None:
        os.environ["LANGFUSE_PUBLIC_KEY"] = config.public_key
    if config.secret_key is not None:
        os.environ["LANGFUSE_SECRET_KEY"] = config.secret_key
    os.environ["LANGFUSE_BASE_URL"] = config.base_url
    os.environ["LANGFUSE_HOST"] = config.base_url
    os.environ["LANGFUSE_TRACING_ENABLED"] = "true"
    os.environ["LANGFUSE_SAMPLE_RATE"] = str(config.sample_rate)
    os.environ["LANGFUSE_ENVIRONMENT"] = config.environment
    if config.release:
        os.environ["LANGFUSE_RELEASE"] = config.release


def _build_mask_otel_spans(*, capture_content: bool) -> Any:
    def mask_otel_spans(*, params: Any) -> Any | None:
        from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

        patches: dict[Any, Any] = {}
        spans = getattr(params, "spans", {}) or {}
        for identifier, span in spans.items():
            attributes = getattr(span, "attributes", {}) or {}
            replacements: dict[str, Any] = {}
            for key, value in attributes.items():
                key_text = str(key)
                if _should_mask_attribute(
                    key_text,
                    value,
                    capture_content=capture_content,
                ):
                    replacements[key_text] = "[REDACTED]"
            if replacements:
                patches[identifier] = OtelSpanPatch(set_attributes=replacements)
        if not patches:
            return None
        return MaskOtelSpansResult(span_patches=patches)

    return mask_otel_spans


def _should_mask_attribute(
    key: str,
    value: object,
    *,
    capture_content: bool,
) -> bool:
    normalized = key.casefold()
    if any(marker in normalized for marker in _SECRET_ATTRIBUTE_MARKERS):
        return True
    if isinstance(value, str) and _SECRET_VALUE_PATTERN.search(value):
        return True
    if capture_content:
        return False
    if any(marker in normalized for marker in _NON_CONTENT_ATTRIBUTE_MARKERS):
        return False
    return any(marker in normalized for marker in _CONTENT_ATTRIBUTE_MARKERS)


def _bounded(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)[:200]


def _trace_metadata(metadata: Mapping[str, Any] | None) -> dict[str, str]:
    if not metadata:
        return {}
    return {str(key)[:200]: str(value)[:200] for key, value in metadata.items()}


__all__ = ["Observation", "Telemetry", "TelemetryConfig"]

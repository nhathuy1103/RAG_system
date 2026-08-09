"""OpenAI client construction that opts into Langfuse native tracing."""

from __future__ import annotations

from typing import Any

from app.infrastructure.telemetry.langfuse import Telemetry


def create_openai_client(
    *,
    telemetry: Telemetry,
    async_client: bool = False,
    **kwargs: Any,
) -> Any:
    """Create a plain or Langfuse-wrapped OpenAI client based on telemetry state."""
    client_class: Any
    if telemetry.enabled:
        if async_client:
            from langfuse.openai import AsyncOpenAI

            client_class = AsyncOpenAI
        else:
            from langfuse.openai import OpenAI

            client_class = OpenAI
    elif async_client:
        from openai import AsyncOpenAI

        client_class = AsyncOpenAI
    else:
        from openai import OpenAI

        client_class = OpenAI
    return client_class(**kwargs)


__all__ = ["create_openai_client"]

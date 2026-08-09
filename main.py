import os

import uvicorn

from app.bootstrap.settings import get_settings


def main() -> None:
    # Loads and validates the application Settings (env vars / .env file) the
    # same way `create_app()` does, so misconfiguration fails fast on startup.
    get_settings()

    # Settings does not expose host/port fields, so read them directly from
    # the environment (matching the API_HOST / API_PORT documented in
    # .env.example), falling back to sensible local-dev defaults.
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))

    uvicorn.run(
        "app.api.main:create_app",
        factory=True,
        host=host,
        port=port,
        reload=True,
    )


if __name__ == "__main__":
    main()

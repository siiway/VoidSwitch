"""CLI entrypoint: ``voidswitch`` / ``python -m voidswitch``."""

from __future__ import annotations

import uvicorn

from voidswitch.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "voidswitch.main:app",
        host=settings.server.host,
        port=settings.server.port,
        log_level=settings.server.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()

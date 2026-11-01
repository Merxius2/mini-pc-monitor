"""Legacy entrypoint — video download is integrated into src.web.app (port 8080)."""

from __future__ import annotations

from src.web.app import create_app

app = create_app()

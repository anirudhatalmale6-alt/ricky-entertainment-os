"""Passenger entry point for cPanel "Setup Python App".

cPanel/Passenger expects a WSGI callable named ``application`` in this file at
the application root. RICKY's FastAPI app is ASGI, so we bridge it with a2wsgi.

Passenger does not run the ASGI lifespan, so the tables + baseline RBAC/admin
are ensured here at boot (seed is idempotent — it no-ops when data exists).
"""
import asyncio
import os
import sys

# Make the app package importable regardless of Passenger's working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Ensure schema + baseline data exist before serving the first request. Guarded
# so a hiccup here never takes the whole app down on boot.
try:
    from seed import main as seed_main

    asyncio.run(seed_main())
except Exception as exc:  # pragma: no cover - boot-time best effort
    sys.stderr.write(f"[passenger_wsgi] seed skipped: {exc}\n")

from a2wsgi import ASGIMiddleware  # noqa: E402
from app.main import app as asgi_app  # noqa: E402

application = ASGIMiddleware(asgi_app)

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
#
# Passenger preloads this module and then *forks* worker processes. We must leave
# ZERO open DB connections behind: any aiosqlite connection (and its background
# thread) created here would be dead in the forked child and the first request
# would hang. So we dispose the engine at the end of the same event loop that ran
# the seed. NullPool (see db/session.py) already avoids pooling; this is belt-and-
# suspenders.
async def _boot() -> None:
    from seed import main as seed_main
    from app.db.session import engine

    try:
        await seed_main()
    finally:
        await engine.dispose()


try:
    asyncio.run(_boot())
except Exception as exc:  # pragma: no cover - boot-time best effort
    sys.stderr.write(f"[passenger_wsgi] seed skipped: {exc}\n")


# Build the ASGI->WSGI bridge LAZILY, on the first request inside each worker.
# Passenger preloads this module and then forks worker processes; a2wsgi's
# ASGIMiddleware spins up an event loop that would not survive the fork, so
# constructing it here (post-fork, once per worker) is what makes it fork-safe.
_bridge = None


def application(environ, start_response):
    global _bridge
    if _bridge is None:
        from a2wsgi import ASGIMiddleware
        from app.main import app as asgi_app

        _bridge = ASGIMiddleware(asgi_app)
    return _bridge(environ, start_response)

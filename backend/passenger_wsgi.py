"""Passenger entry point for cPanel "Setup Python App".

cPanel/Passenger expects a WSGI callable named ``application`` in this file at
the application root. RICKY's FastAPI app is ASGI, so we bridge it with a2wsgi.

Passenger does not run the ASGI lifespan, so the tables + baseline RBAC/admin
are ensured here at boot (seed is idempotent — it no-ops when data exists).
"""
import asyncio
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Make the app package importable regardless of Passenger's working directory.
sys.path.insert(0, APP_DIR)

# --- Seed AT MOST ONCE per deploy -------------------------------------------
#
# This host runs on LiteSpeed LSAPI, which spawns each worker as a FRESH process
# that re-imports this module — it does NOT fork from a single preload. So the
# seed below would run on EVERY worker cold-start. Under load LSAPI scales
# workers up on demand; if each new worker opens the DB to seed, they contend on
# the SQLite write lock, hang, get killed as "runaway", re-import, re-seed... a
# 503 death-spiral (observed 2026-07-22).
#
# Guard: exactly one worker per deploy claims the seed via an atomic O_EXCL
# sentinel. Every other worker — including ones spawned under load — skips all
# DB work at boot and becomes ready instantly. The sentinel lives beside the DB
# and persists across restarts (the DB is already seeded), so seed only ever
# runs again on a truly fresh deploy. To force a reseed, delete this file:
_SENTINEL = os.path.join(APP_DIR, "tmp", "seeded.marker")


async def _boot() -> None:
    from seed import main as seed_main
    from app.db.session import engine

    # Passenger/LSAPI may fork after this module loads. Leave ZERO open DB
    # connections behind: any aiosqlite connection (and its background thread)
    # would be dead in a forked child and hang the first request. Dispose the
    # engine in the same event loop that ran the seed. NullPool (see
    # db/session.py) already avoids pooling; this is belt-and-suspenders.
    try:
        await seed_main()
    finally:
        await engine.dispose()


def _claim_seed() -> bool:
    """True for exactly one worker per deploy (atomic create); False otherwise."""
    try:
        fd = os.open(_SENTINEL, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        # tmp/ missing or unwritable — fall back to seeding (best effort).
        return True


if _claim_seed():
    try:
        asyncio.run(_boot())
    except Exception as exc:  # pragma: no cover - boot-time best effort
        sys.stderr.write(f"[passenger_wsgi] seed skipped: {exc}\n")
        # Seed failed — release the claim so a later worker can retry.
        try:
            os.remove(_SENTINEL)
        except OSError:
            pass


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

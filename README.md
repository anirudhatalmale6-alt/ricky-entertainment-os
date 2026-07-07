# RICKY Entertainment OS

B2B SaaS platform where hotels and venues manage their entertainment (scheduling,
budgeting, contracting and CFDI invoicing) and artists are the product.

This repository is being built in phases (see the phased development plan). This is
**Phase 1 — Foundations**.

## Phase 1 · Foundations (in progress)

| Checkpoint | Status |
|---|---|
| Project scaffolding & stack | ✅ done |
| Master database (users, roles, artists, companies/venues, bookers) | ✅ done |
| Authentication + roles + permissions (RBAC) | ✅ done |
| Two-factor authentication (TOTP) | ✅ done |
| Infrastructure: encryption, backups | ⏳ next |
| Multi-language / multi-currency | ⏳ next |
| Base notifications & internal messaging | ⏳ next |

## Stack

- **Backend:** FastAPI (Python 3.12) + async SQLAlchemy 2.0
- **Database:** SQLite for development, PostgreSQL (asyncpg) for production
- **Auth:** JWT access tokens, bcrypt password hashing, TOTP 2FA (RFC 6238)

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional; defaults work out of the box
python seed.py                # creates roles/permissions + admin@ricky.os / Admin123!
uvicorn app.main:app --reload
```

Open the interactive API docs at `http://127.0.0.1:8000/docs`.

## API (v1)

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service health check |
| POST | `/api/v1/auth/register` | Register a user (role: booker/artist/admin/finance) |
| POST | `/api/v1/auth/login` | Login → JWT (asks for 2FA code if enabled) |
| POST | `/api/v1/auth/2fa/setup` | Generate TOTP secret + QR (SVG) |
| POST | `/api/v1/auth/2fa/enable` | Activate 2FA with a code |
| POST | `/api/v1/auth/2fa/disable` | Deactivate 2FA with a code |
| GET | `/api/v1/users/me` | Current user profile |
| GET | `/api/v1/users` | List users (requires `user.manage`) |

## RBAC

Roles seeded: `admin` (all permissions), `finance`, `booker`, `artist`.
Permissions are code-based (`user.manage`, `artist.manage`, `invoice.manage`, …)
and checked per-endpoint via a dependency guard.

## Project layout

```
backend/app
├── core/         config + security (hashing, JWT, TOTP)
├── db/           declarative base + async session
├── models/       User, Role, Permission, Artist, Company, Booker
├── schemas/      Pydantic request/response models
├── api/v1/       auth + users routers
└── main.py       FastAPI app
```

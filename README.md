# DesignOS

DesignOS is an AI-controlled, human-supervised design environment. This repository currently implements **BUILD 01**, the backend foundation for persistent structured design state, its recoverable history, user-owned laws, decisions, and design memory. AI execution, Figma, research, and website generation are intentionally outside this build.

## Included

- FastAPI API with project, design state, version, decision, law, and memory endpoints.
- PostgreSQL persistence with SQLAlchemy 2, JSONB snapshots, Alembic migrations, and environment-based configuration.
- Full immutable snapshots on design mutations, recursive version comparison, restoration as a new version, and dot-path surgical edits.
- Explicit decision source and memory trust classifications. Imported and AI-originated content remains distinguished from user-approved information.
- Tests run against isolated in-memory SQLite for fast local feedback. PostgreSQL uses JSONB through a dialect-specific type variant; UUID models remain portable.
- The schema is ready to add pgvector-backed memory embeddings later; this build does not store or query embeddings.

## Quick start

Requires Python 3.11+ and PostgreSQL.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `DATABASE_URL` in `.env` to a PostgreSQL database you can access, then apply migrations and run the API:

```powershell
alembic upgrade head
uvicorn app.main:app --app-dir backend --reload
```

API docs are at `/docs`, and the process health check is at `/health`.

## API outline

All resource routes use the `/api/v1` prefix:

| Method | Path | Purpose |
|---|---|---|
| POST / GET | `/projects` | Create and list projects |
| GET | `/projects/{id}` | Retrieve a project |
| POST / GET / PUT | `/projects/{id}/design` | Initialize, read, and update structured design state |
| PATCH | `/projects/{id}/design/edit` | Apply one path-scoped state edit |
| GET | `/projects/{id}/versions` | List snapshots |
| GET | `/projects/{id}/versions/{version_id}` | Retrieve a snapshot |
| GET | `/projects/{id}/versions/compare/{left_id}/{right_id}` | Compare snapshots |
| POST | `/projects/{id}/versions/{version_id}/restore` | Restore a snapshot as a new version |
| POST / GET | `/projects/{id}/decisions` | Record and list decisions |
| POST / GET / PATCH | `/projects/{id}/laws` | Create, list, and update project design laws |
| POST / GET | `/projects/{id}/memory` | Store and retrieve trust-classified memory |

Design state has the keys `pages`, `components`, `design_tokens`, `ux_navigation`, `assets`, `design_laws`, and `metadata`. A full replacement is a versioned mutation. A surgical edit uses dot-separated keys and list indices, for example `pages.0.title`. A restore does not rewrite history: it applies the selected snapshot and records a new child version.

## Tests

```powershell
pytest
```

Tests use SQLite and do not require a running PostgreSQL server. Apply the included Alembic migration against PostgreSQL to validate the production schema. pgvector extension setup and embedding columns are deferred until a concrete memory-search design is in scope.

# DesignOS

DesignOS is an AI-controlled, human-supervised design environment. **BUILD 01** provides projects, structured state, recoverable versions, decisions, laws, and design memory. **BUILD 02** adds deterministic intent extraction, focused questions, a research-planning and evidence foundation, sourced design requirements, strategic direction hypotheses, and a proposal-only design-operation boundary.

## Included

- FastAPI API with project, design state, version, decision, law, and memory endpoints.
- PostgreSQL persistence with SQLAlchemy 2, JSONB snapshots, Alembic migrations, and environment-based configuration.
- Full immutable snapshots on design mutations, recursive version comparison, restoration as a new version, and dot-path surgical edits.
- Explicit decision source and memory trust classifications. Imported and AI-originated content remains distinguished from user-approved information.
- Tests run against isolated in-memory SQLite for fast local feedback. PostgreSQL uses JSONB through a dialect-specific type variant; UUID models remain portable.
- The schema is ready to add pgvector-backed memory embeddings later; this build does not store or query embeddings.
- Rule-based intent extraction records which fields are user-stated versus inferred, and computes completeness from explicit known fields.
- Question generation is capped to a small set of material gaps and ranks questions with a transparent downstream-impact formula.
- Research plans and evidence are persisted with source, trust, and provenance. No live search or scraping runs.
- Requirements retain `user`, `inferred`, `research`, or `system` source and are not treated as equally authoritative.
- Multiple design directions can be proposed and assessed independently. Assessments retain observations and tradeoffs rather than a universal winner score.
- Only the explicit direction-selection workflow records a user decision, approved memory, intent approval, operation event, and a versioned Design State selection.
- Design operations can be submitted as proposals. There is no generic operation apply endpoint and AI proposals cannot mutate Design State.

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
| POST / GET / PUT | `/projects/{id}/intent` | Create, read, and update structured intent |
| POST | `/projects/{id}/intent/analyze` | Re-run deterministic extraction and generate focused questions |
| GET / POST | `/projects/{id}/questions` | List or add clarification questions |
| GET | `/projects/{id}/questions/open` | List open questions in impact order |
| PATCH | `/projects/{id}/questions/{question_id}` | Skip or supersede an open question |
| POST | `/projects/{id}/questions/{question_id}/answer` | Record an answer and update its targeted intent field |
| GET / POST | `/projects/{id}/research` | List or store provenance-bearing evidence |
| GET / POST | `/projects/{id}/research-plan` | Retrieve or generate an intent-based research plan |
| GET / POST | `/projects/{id}/requirements` | List or create sourced design requirements |
| POST | `/projects/{id}/requirements/generate` | Create requirement candidates from known intent and evidence |
| GET / POST | `/projects/{id}/directions` | List directions; create one or generate three hypotheses |
| GET | `/projects/{id}/directions/{direction_id}` | Retrieve a design direction |
| PATCH | `/projects/{id}/directions/{direction_id}` | Reject or archive a proposal; selection has its own explicit endpoint |
| POST | `/projects/{id}/directions/{direction_id}/assessments` | Record an evidence-bearing criterion assessment |
| POST | `/projects/{id}/directions/{direction_id}/select` | Require `{"confirm": true}` to record an explicit direction selection and state event |
| GET / POST | `/projects/{id}/operations` | List or record proposed design operations (no execution) |

Design state has the keys `pages`, `components`, `design_tokens`, `ux_navigation`, `assets`, `design_laws`, and `metadata`. A full replacement is a versioned mutation. A surgical edit uses dot-separated keys and list indices, for example `pages.0.title`. A restore does not rewrite history: it applies the selected snapshot and records a new child version.

## Tests

```powershell
pytest
```

Tests use SQLite and do not require a running PostgreSQL server. Apply the included Alembic migration against PostgreSQL to validate the production schema. pgvector extension setup and embedding columns are deferred until a concrete memory-search design is in scope.

## BUILD 02 architecture

```text
User Request
↓
Intent Engine
↓
Question Engine
↓
Research Plan
↓
Research Evidence
↓
Design Requirements
↓
Design Directions
↓
Human Selection
↓
Design Decision + Memory
↓
Future Design State
```

BUILD 02 uses deterministic, rule-based extraction and exposes an `IntentExtractor` protocol for a future provider. Unknown information remains unset; inferred values remain marked in field provenance, do not count as confirmed completeness, and can trigger clarification questions. `completeness` is computed from a fixed six-field checklist of user-confirmed information. The question engine asks about missing or inferred goal, project type, action, audience, essential features, and brand guidance, then orders them by deterministic impact factors. Direction generation waits for core intent confirmation and unresolved critical/high-impact questions. It does not ask for low-level styling details prematurely.

Research plans are generated from known intent fields. `ResearchProvider` is an interface only; evidence must be supplied to the API, defaults to untrusted, and never becomes an approved requirement automatically. Inference and research-derived requirements remain labeled and proposed. Multiple direction hypotheses and independent assessments expose strengths, tradeoffs, risks, and evidence without aggregating them into a universal score.

The operation flow is reserved as `Intent → Operation → Validation → Impact Analysis → Preview → Approval → Apply → Version → Memory`. BUILD 02 only persists proposals and records the explicit human direction-selection event. It does not execute arbitrary operation requests.

## BUILD 02 deliberately does not implement

No OpenAI, Anthropic, Gemini, or other LLM calls; no live research search or scraping; no autonomous agent execution; no website or React generation; no Figma integration; no vector database or embeddings; no image generation or browser automation; no collaboration, authentication, or billing. The rule-based extractor is intentionally narrow and leaves unsupported fields unknown. Direction hypotheses are structured backend concepts, not finished visual designs. Since authentication is out of scope, deployments must protect user-only selection and write endpoints at the hosting boundary until authentication is added.

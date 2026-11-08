# KnowBridge

Evidence-linked, permission-aware project handovers. KnowBridge rebuilds the state of a project
from sources the team has authorised, ties every line of the handover to where it came from,
and only asks the person who is leaving about what the evidence can't answer.

The build plan is in [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md).

## Run it locally

You need Docker Desktop, Node 22+ and Python 3.12+.

```bash
cp .env.example .env          # then set GEMINI_API_KEY, API_JWT_SECRET, AUTH_SECRET and SECRETS_KEY
```

### Everything in Docker

```bash
docker compose up --build
```

Open http://localhost:3000 and pick a Project Nimbus persona.

### For development (hot reload)

```bash
# 1. databases
docker compose up -d postgres openfga

# 2. API  (http://localhost:8000/docs)
cd services/api
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"        # macOS/Linux: .venv/bin/pip
.venv/Scripts/alembic upgrade head
.venv/Scripts/uvicorn app.main:app --reload --port 8000

# 3. worker (reads sources in the background)
cd services/api
.venv/Scripts/python -m app.worker

# 4. web  (http://localhost:3000)
cd apps/web
npm install
npm run dev
```

### Demo data

Sign in as any persona and press **Load the Project Nimbus demo**, or from the command line
(no worker needed):

```bash
cd services/api
.venv/Scripts/python -m app.seed nimbus --reset
```

Project Nimbus is a synthetic college fest app (`data/nimbus`): a repository snapshot, meeting
notes, a Trello board, Discord and WhatsApp exports (partly Hinglish), with planted secrets,
contradictions and confidential notes. `data/nimbus/answer_key.yaml` lists everything planted.

On Windows, especially inside a OneDrive folder, `uvicorn --reload` can hang on its first
reload. If API changes don't show up, stop it and start it again (or drop `--reload`). The worker
never reloads by itself: restart it after changing backend code.

### Smart search

Search combines keywords with meaning ("login problems" finds "OTP session lost"). By default
meaning search uses **Gemini embeddings** (`EMBEDDING_PROVIDER=gemini`, needs `GEMINI_API_KEY`).
Gemini's free tier allows 100 embeddings a minute, so a big project is indexed in portions over
a few minutes; keyword search works straight away.

To keep everything on your own server instead (needs ~1.5 GB RAM):
`pip install -e ".[local-search]"` and set `EMBEDDING_PROVIDER=local`. The model (~1 GB)
downloads on first use into `MODEL_CACHE_DIR`.

```bash
cd services/api
.venv/Scripts/python -m app.reindex            # index everything already stored
```

Or press **Build smart search** on a project's overview. New items are indexed during each sync.
Set `EMBEDDING_PROVIDER=off` for keyword-only search.

### Connecting GitHub

Sources → Connect a source → GitHub. Enter `owner/repo` and a
[fine-grained token](https://github.com/settings/personal-access-tokens/new) limited to that
repository with **read-only** Contents, Issues, Pull requests, Metadata and Actions. Public
repositories work without a token (GitHub then allows only 60 API calls an hour). Commit history
is read with `git`, so it costs no API calls; the server needs `git` installed (the Docker image has it).

### Connecting Jira

Sources → Connect a source → Task board → **Connect Jira Cloud**. Enter the site
(`yourteam.atlassian.net`), your Atlassian email, an [API token](https://id.atlassian.com/manage-profile/security/api-tokens),
and a project key (`ROV`) or any JQL. The connection is checked before anything is saved, and
the token is encrypted with `SECRETS_KEY`.

If ports 5432 or 8080 are already in use on your machine, set `POSTGRES_PORT` / `OPENFGA_PORT`
in `.env` and update `DATABASE_URL` / `OPENFGA_API_URL` to match.

## Tests

Database tests use a separate `knowbridge_test` database (created automatically) and check that
no planted secret or confidential item leaks.

```bash
cd services/api && .venv/Scripts/python -m pytest
cd apps/web && npm run typecheck && npm run lint
```

## Layout

| Path | What |
|---|---|
| `apps/web` | Next.js app (UI; calls the API server-side) |
| `services/api` | FastAPI, the agent pipeline, Sentinel, Gatekeeper |
| `infra` | OpenFGA model, Postgres init |
| `data/nimbus` | Synthetic demo project and its answer key |
| `docs` | Build plan and notes |

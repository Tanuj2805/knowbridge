# Disclosures

Required by event rules 5–7. Updated as the build goes.

## AI assistance

| Tool | Used for |
|---|---|
| Claude Code (Anthropic, Claude Opus 5.5) | Planning, scaffolding and writing code alongside me. I review and run everything before it is committed. |
| Gemini API (Google) | Runtime model behind the KnowBridge agents (extraction, verification, interview, composition) and embeddings. |

The Round 1 plan document was drafted with AI assistance and reviewed by me.

## Generated boilerplate

| What | From |
|---|---|
| `apps/web` initial scaffold | `create-next-app@16.4.5` |
| `services/api/alembic/versions/*_initial_schema.py` | `alembic revision --autogenerate`, then edited |

## Third-party components

| Component | Licence | Where |
|---|---|---|
| Next.js, React | MIT | web |
| Auth.js (next-auth) | ISC | web |
| Tailwind CSS | MIT | web |
| Radix UI primitives | MIT | web |
| lucide-react | ISC | web |
| jose | MIT | web |
| dotenv-cli | MIT | web (dev) |
| IBM Plex Sans / Mono, Newsreader (Google Fonts) | OFL 1.1 | web |
| FastAPI, Pydantic | MIT | api |
| SQLAlchemy, Alembic | MIT | api |
| psycopg | LGPL-3.0 | api |
| pgvector (Python + Postgres extension) | MIT / PostgreSQL | api, db |
| LangGraph | MIT | api |
| google-genai SDK | Apache-2.0 | api |
| MCP Python SDK | MIT | api |
| PyJWT, httpx, tenacity, PyYAML | MIT / BSD | api |
| pypdf | BSD-3 | api |
| cryptography (Fernet) | Apache-2.0 / BSD | api (encrypts connector tokens) |
| python-docx | MIT | api |
| PostgreSQL | PostgreSQL | db |
| OpenFGA | Apache-2.0 | permissions |
| git (command-line, called by the GitHub connector) | GPL-2.0 (run as a separate program, not linked) | api |
| GitHub REST API | GitHub terms of service | api (read-only, with the team's own token) |
| Jira Cloud REST API (Atlassian) | Atlassian developer terms | api (read-only issue import with the team's own API token) |
| FastEmbed (Qdrant) | Apache-2.0 | api (runs the local embedding model) |
| ONNX Runtime (Microsoft) | MIT | api (via FastEmbed) |
| paraphrase-multilingual-mpnet-base-v2 (sentence-transformers; ONNX export by Xenova) | Apache-2.0 | api (search model, downloaded from Hugging Face on first use) |
| gitleaks default rules (adapted in `app/sentinel/rules.py`) | MIT | api |

## Data

The demo uses only the synthetic **Project Nimbus** dataset in `data/nimbus`, written for this
project. All names, messages, numbers and "secrets" in it are made up. No real workplace or
personal data is used.

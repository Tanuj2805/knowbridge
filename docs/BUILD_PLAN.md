# KnowBridge — Build Plan

This is the working plan for turning the Round 1 document into a production-ready app.
It follows the Round 1 commitments (9 agents, Claim Ledger, six grades, Gap Interview,
permission-aware handover, human approval) and records every place where the build
deviates from that document and why.

---

## 1. What "done" means for Round 2

One command (`docker compose up`) brings up the full product. A judge can:

1. Sign in as **Admin**, connect the synthetic *Project Nimbus* sources (GitHub repo, notes, task board, chat).
2. Watch a run go through Connect → Reconstruct → Verify, with live per-agent progress.
3. Sign in as **Aarav (leaver)** and answer ~10 Gap Interview questions in under 15 minutes.
4. Sign in as **Priya (approver)**, work the review queue (riskiest first), edit/reject/approve, publish.
5. Sign in as **Meera (successor)**, read a Handover Pack filtered to her role with "withheld" markers,
   follow the 30-day plan, acknowledge each section.
6. Run `make eval` and see the trap-test scorecard (secret leaks = 0, permission leaks = 0, recall numbers).

Everything a user sees links back to evidence in one click.

---

## 2. Stack (final)

| Layer | Choice | Note |
|---|---|---|
| Web | Next.js 16 (App Router, TypeScript, Cache Components off), Tailwind CSS v4, Radix primitives, `@xyflow/react` for graph/timeline | Server components + server actions; API calls happen server-side so tokens never reach the browser |
| Auth | Auth.js v5: GitHub + Google OAuth, plus **demo persona sign-in** when `DEMO_MODE=true` | Next mints a short-lived HS256 JWT per API call; FastAPI verifies it |
| API | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 | |
| Agents | LangGraph with Postgres checkpointer; one versioned skill file per agent (`skills/*.md`) | Run pauses at the Gap Interview via `interrupt()` and resumes on answers |
| LLM | **Gemini** via `google-genai` SDK behind our own `llm/gateway.py` | Native structured output into Pydantic models. Reasoning: `gemini-3.6-flash`; bulk: `gemini-3.5-flash-lite` (both in `.env`) |
| Embeddings | **Gemini** `gemini-embedding-001` (768 dims) by default; local `paraphrase-multilingual-mpnet-base-v2` optional (`EMBEDDING_PROVIDER=local`, `pip install .[local-search]`) | Fits Render's free tier (512 MB); local keeps data on-server where RAM allows |
| Storage | PostgreSQL 17 + pgvector + full-text search; graph as node/edge tables; uploads on local disk volume (S3-compatible later) | |
| Retrieval | Keyword (tsvector) + vector + 1-hop graph neighbourhood, merged with reciprocal-rank fusion, then Gemini rerank for top-k | |
| Permissions | OpenFGA (docker) — **Gatekeeper**, rule-based, never an LLM | Fallback: same rule in a Postgres role table (`AUTHZ_BACKEND=local`) |
| Privacy | **Sentinel**: deterministic secret rules (gitleaks-derived) + India-aware PII rules (phone, Aadhaar, PAN, UPI, IFSC, email); Presidio added as an optional extra recogniser | Runs before any LLM call |
| Connectors | Read-only readers: GitHub (REST or snapshot), Jira Cloud (REST v3, live), documents, task-board and chat exports | MCP wrapping in Round 3 (see deviations) |
| Jobs | Postgres-backed queue (`SELECT … FOR UPDATE SKIP LOCKED`) + separate `worker` process | No Redis needed |
| Observability | Langfuse (optional, via env) + structured JSON logs; every agent step also stored in `run_steps` | |
| Tests | pytest (unit + trap tests), Playwright smoke test for the web, GitHub Actions CI | Any secret or permission leak fails CI |
| Deploy | Docker Compose for judges; Vercel (web) + container host (api/worker) + managed Postgres for the public demo | |

### Deviations from the Round 1 document (to disclose)

| Round 1 said | We do | Why |
|---|---|---|
| LiteLLM gateway, provider chosen by tests | Thin in-house gateway over `google-genai`, Gemini only | One provider decided; fewer dependencies; the gateway keeps the swap point |
| BGE-M3 embeddings + cross-encoder reranker | Local multilingual mpnet embeddings (BGE-M3 isn't packaged for CPU/ONNX in FastEmbed); no reranker yet | Same intent as Round 1: local multilingual model; keeps search private |
| Presidio as the PII engine | Deterministic rules first, Presidio optional | Presidio's defaults miss Indian identifiers; our rules are testable and fast |
| OpenFGA SDK | OpenFGA's HTTP API called directly with `httpx` | Readable requests, no SDK version drift |
| Every connector is an MCP server | Phase 1 connectors are plain read-only Python readers (GitHub REST API or snapshot file, and file importers); MCP wrapping moves to Round 3 with live connectors | Same read-only guarantee and output; MCP adds a moving part we don't need for file exports |

### Decisions log

| Date | Decision | Why |
|---|---|---|
| 8 Nov 2026 | Stay on PostgreSQL (MongoDB considered) | OpenFGA can't use MongoDB, so we'd run two databases; pgvector + full-text search work locally in Docker, while MongoDB vector search needs Atlas or `mongot`; the claim ↔ evidence ↔ permission data is relational; Round 1 commits to Postgres |
| 8 Nov 2026 | Next.js Cache Components turned off | Every screen is per-user and permission-filtered; dynamic rendering is simpler and just as fast here |
| 8 Nov 2026 | Chat stays in the MVP | Chat holds most of the "why" behind decisions |
| 8 Nov 2026 | **Live Jira Cloud connector moved into Round 2** (was "Future" in Round 1) | Team request. Read-only REST v3 (`search/jql`), API token encrypted at rest (Fernet, `SECRETS_KEY`), only `*.atlassian.net` hosts unless `JIRA_ALLOW_ANY_HOST`, credentials checked before saving. Round 3 gets a different feature in its place |
| 8 Nov 2026 | GitHub connector made per-source like Jira; history read with git | Each team connects its own repo with a fine-grained read-only token (encrypted, checked before saving; classic write tokens get a warning). A history-only `git clone --filter=blob:none` gives every commit with its files at no API cost, which powers per-folder code ownership (bots excluded) |
| 8 Nov 2026 | Incremental sync and rate-limit pauses for live sources | Live sources re-read only what changed ("Full re-sync" re-reads everything and detects deletions); a rate limit pauses the job until the reset time instead of failing |
| 8 Nov 2026 | Jira issue history, sub-tasks, components, sprint, story points; Jira keys linked across sources | "Who built it" needs history, not just the current assignee. "ROV-7" in a commit/PR/message links to the Jira issue (only keys that exist, so "UTF-8" never links) |
| 8 Nov 2026 | **Search runs on a local embedding model; agents use Gemini** ("local search + 9 agents") | Measured on this laptop (8 cores): 26 ms to embed a query vs ~150–400 ms for an API round trip; indexing ~4–8 chunks/s (one-time, background). Hybrid search found 9/10 reworded Nimbus questions vs 8/10 keyword-only |
| 8 Nov 2026 | Search precision rules, all from real-data runs | Meaning matches need distance < 0.60 (relevant 0.40–0.59, unrelated 0.64+); in hybrid mode a keyword hit must match most query words; ≤3-letter words match exactly; exact IDs (ROV-15, PR #42, commit hash) rank first; status/sprint/history lines aren't fingerprinted (they made "Setup the dev environment" look unrelated to "set up the local environment") |
| 8 Nov 2026 | **Switched default search embeddings to Gemini** (local stays optional) | Deploying on Render's free tier (512 MB RAM); the local model needs ~1–1.5 GB per process. Gemini's free tier allows 100 embeddings/minute, so indexing runs in quota-sized portions (90/min) and reschedules itself; keyword search works immediately while smart search fills in |
| 8 Nov 2026 | Confidential items are never sent to an external embedding provider (`EMBED_EXTERNAL_MAX_LABEL=restricted`) | Keeps the Round 1 trust promise with Gemini search: they stay keyword-only; vectors are dropped if an item is relabelled later. The UI says plainly what goes to Google |
| 8 Nov 2026 | Scout and Sentinel get real reasoning jobs in Phase 2 | Keeps "9 AI agents" true: Scout plans evidence packets for a handover, Sentinel reviews context and can only raise labels |
| 8 Nov 2026 | Default Gemini models: `gemini-3.6-flash` (reasoning), `gemini-3.5-flash-lite` (bulk), `gemini-embedding-001` | 2.5 models are deprecated; all three are set in `.env` |
| 9 Nov 2026 | Confidential items are never sent to the agents' model either (`LLM_EXTERNAL_MAX_LABEL=restricted`) | Same trust rule as search; they're still shown, with grades, to people cleared to see them |
| 9 Nov 2026 | One gateway for every model call: structured output, pacing (`LLM_RPM_*`), budgets, answer cache | Answers must parse into the agent's schema (one retry); a short "slow down" is waited out, a long or daily one pauses the run; identical calls over unchanged evidence are free |
| 9 Nov 2026 | Agents read evidence packets (a thread, a chat day, a meeting, a week of commits), several per call | Nimbus has 93 small packets; bundling ~9,000 characters per call cuts extraction from ~280 calls to ~6 |
| 9 Nov 2026 | A claim is kept only if its quote really appears in the cited item | Checked by code (`find_quote`), not by the model; invented quotes are dropped |
| 9 Nov 2026 | Sentinel review skill v2 flags rarely | v1 raised 9 Nimbus items (the Railway move, "billing on Aarav's card") and would have hidden them from the successor; v2 matches the rules' meaning of Restricted and raised 1 (a Hinglish "don't forward" message the rules missed) |
| 9 Nov 2026 | Scout skill v2: short is not noise | v1 skipped "confirmation comes through the webhook", "FCM push is in" and "Zentrix wale reply nahi kar rahe"; v2 skips only chatter and bot messages (3 of 92 packets) |
| 9 Nov 2026 | Some claims come straight from system data, with no model: owners from git history (≥5 commits, ≥50%), CI failing since the last success, pull requests idle for 14+ days, overdue open cards | They're facts, so they're cheaper and more reliable than asking a model; marked "system data" so the Skeptic can grade them Verified |
| 9 Nov 2026 | Quote check ignores Markdown emphasis; bundles of ~6,000 characters | First live run dropped 13 real quotes (`**PWA only.**` quoted as `PWA only.`) and the model skimmed 9,000-character bundles. After both fixes, on Nimbus: decisions 24/25 and risks 9/10 of the answer key (rough check), 1 quote dropped, no claim from the injection message |
| 9 Nov 2026 | Dates use the team's time zone (`TIMEZONE`, default Asia/Kolkata) | 01:20 IST on 20 Oct was shown as 19 Oct in UTC |
| 9 Nov 2026 | Extraction stays on `gemini-3.6-flash` | `gemini-3.5-flash-lite` found 1/8 dependencies (vs 4-5/8) and 7/10 risks (vs 9/10). The free tier allows 20 requests a day for 3.6-flash; one Nimbus run uses about 8, so the free tier allows ~2 fresh runs a day (cached re-runs are free) |
| 9 Nov 2026 | **Agents can run on any OpenAI-compatible API** (`LLM_PROVIDER=openai`); local setup uses ASI:One `asi1-mini` | Free plan: 2,000 requests and 100M tokens a day (vs 20 requests on Gemini 3.6 Flash). Two fresh Nimbus runs: decisions 25/25 both times, risks 8/10 both times, ~90 s each; owners and dependencies varied between runs (7 vs 2, 6 vs 2 on the rough check). 4/4 prompt-injection attacks ignored; Hinglish translated well. Weaker than Gemini at exact quotes (more dropped, none let through) and sometimes states more than the evidence; the Skeptic must catch that. `asi1` (the large model) is too slow here: ~40k reasoning tokens and ~2 min per call. ASI:One has no embeddings API, so search stays on Gemini embeddings. Its privacy policy doesn't say whether API prompts are used for training |
| 9 Nov 2026 | The Scout never drops a packet | Both Gemini and asi1-mini called real evidence noise ("third attempt at the double-registration bug", "logos?? … aaj shaam tak, promise"). What it calls noise now still goes to the Risk Detector; the saving from skipping was small |
| 9 Nov 2026 | Sentinel review skill v3 lists what must stay Team | asi1-mini flagged "Railway is on Aarav's card" and similar despite v2; with concrete never-flag examples it raises 0-1 real items and still catches 3/3 planted private items |
| 9 Nov 2026 | Claim ledger page and "Build claims" runs (worker job `run.reconstruct`), ahead of LangGraph | So people can see claims now; a claim is shown only if the viewer can see every item it cites. LangGraph orchestration still comes with the Skeptic and Gap Interview |
| 9 Nov 2026 | Speed: calls run 4 at a time (`LLM_PARALLEL`), pacing set per provider, Jira history shortened for agents | A 145-ticket Jira project took 16 min at Gemini free-tier pacing (8 calls/min) on ASI:One; now ~2 min. History lines were 41% of Jira text: agents get every assignee change plus the 5 latest moves |
| 9 Nov 2026 | **Timeline Builder = merge + timeline + conflicts, in two passes** | A first pass merges duplicates and suggests replacements/conflicts; a second look checks each suggested pair on its own (first passes over-report). Code adds pairs about the same thing with different numbers ("3 events" vs "5 events" was never suggested) and never merges claims with different numbers. On Nimbus: 19 duplicates merged, webhooks → polling linked, all 3 planted number conflicts found (early-bird date, polling interval, free-pass limit), no false ones |
| 9 Nov 2026 | **Skeptic judges passages; code computes grades** (Round 1 rule) | Claims are dealt across calls so similar claims never share one (asi1-mini judged "until 15 Dec" against another claim's "31 Dec"). Removal only when every passage is unrelated; a passage that disagrees makes the claim Conflicting for a person instead. Work written by or assigned to the named owner supports an ownership claim. Grades are recomputed from stored judgements (`regrade`), so the Gap Interview can re-grade without new calls |
| 9 Nov 2026 | Read model answers leniently | asi1-mini wrote `"replaced: b"` for `relation`; strict matching silently dropped 6 correct verdicts |
| 9 Nov 2026 | **Gap Interviewer: code picks the gaps, the model phrases them and reads the answers** | Gaps are ranked in code (disagreeing sources, unanswered questions, doubted claims, big risks with no owner, key decisions with no reason; anything tied to the leaver first), up to 12. Answers are masked by Sentinel and stored as evidence ("Gap Interview: <name>"); the model reads each one as confirms / corrects / picks a side / adds an owner or date; code applies it and re-grades. Live on Nimbus: 12 questions in 11 s, 3 planted contradictions settled by the leaver's answers (early-bird date, polling interval, free-pass limit) |
| 9 Nov 2026 | Grades with the leaver's word: document + leaver = Verified; leaver only = Attested; the leaver saying otherwise = Conflicting | The Round 1 rules; the leaver's confirmation outranks a passage that only seemed to disagree |
| 9 Nov 2026 | **No LangGraph**: runs are a resumable worker job; the interview is a separate step on the handover | Each agent records progress in `runs.state`, so a paused run resumes where it stopped; answers re-grade the ledger as they arrive instead of the run waiting on `interrupt()`. One less framework to deploy; the `langgraph` packages are unused and can be dropped |
| 9 Nov 2026 | Accuracy scoring: `python -m app.eval <project_id>` against `data/nimbus/answer_key.yaml` | asi1-mini on Nimbus: decisions 25/25, owners 12/15, dependencies 6/8, risks 10/10, reversals linked 1/5, contradictions 3/6 (settled or flagged); secrets, confidential and injection checks all 0. Reversals are the weakest area: the agents rarely write the old state as its own claim |
| 9 Nov 2026 | Review happens on the Claim ledger: approve, edit (old wording kept as a version), reject with a note, reopen; bulk-approve by grade | Only the approver role can review (admin is not enough). A claim removed by the Skeptic can be restored by approving it, so a person always has the last word |
| 9 Nov 2026 | **Composer: code picks the content, the model writes the joins** | Only approved, current claims the successor may see go in; the rest become "withheld" notes with the reason (Restricted, or a source they can't open). The model writes the brief, one intro per section and the 30-day plan, and never sees confidential claims. Each plan task must come from a claim; ids written in the text are read too (asi1-mini did that), duplicates are merged |
| 9 Nov 2026 | Packs are versioned snapshots; the successor only sees the published version | A published pack never changes under its reader; the approver previews each new version before publishing. Acknowledgements, flags ("this looks wrong" back to the approver), plan checkboxes, Markdown and calendar (.ics) export, PDF via the browser's print. Every view, export, approval and acknowledgement is in the audit log |
| 9 Nov 2026 | Provider calls time out after 2 minutes, not 5 | A request ASI never answered held the Composer for 5 minutes; asi1-mini answers in 10–20 s, so a hung call now fails fast and is retried |

---

## 3. Repository layout

```
knowbridge/
├─ apps/web/                     Next.js app (UI only, talks to the API server-side)
├─ services/api/
│  ├─ app/
│  │  ├─ main.py                 FastAPI app + routers
│  │  ├─ config.py               settings from env
│  │  ├─ db/                     SQLAlchemy models, session, queries
│  │  ├─ auth.py                 JWT verification, current user
│  │  ├─ gatekeeper/             OpenFGA client + local fallback (same interface)
│  │  ├─ sentinel/               secret + PII rules, redaction, sensitivity labels
│  │  ├─ connectors/             MCP clients + our FastMCP servers + parsers
│  │  ├─ llm/                    Gemini gateway, embeddings, rate-limit + cache
│  │  ├─ retrieval/              hybrid search, permission-filtered
│  │  ├─ agents/                 the 9 agents (one module each)
│  │  ├─ skills/                 versioned prompt/skill files per agent
│  │  ├─ pipeline/               LangGraph graphs (reconstruct+verify, compose)
│  │  ├─ routers/                HTTP endpoints
│  │  └─ worker.py               job runner
│  ├─ alembic/                   migrations
│  └─ tests/                     unit + trap tests
├─ data/nimbus/                  synthetic Project Nimbus dataset + answer key
├─ infra/                        OpenFGA model, Postgres init, seed scripts
├─ compose.yaml                  one-command local stack
├─ docs/                         this plan, architecture notes, demo script
├─ DISCLOSURES.md
└─ README.md
```

---

## 4. Data model

| Table | Key fields |
|---|---|
| `users` | id, email, name, avatar, auth_provider |
| `projects` | id, name, slug, description, retention_days, created_by |
| `memberships` | project_id, user_id, role (`admin`, `approver`, `leaver`, `successor`, `viewer`), role_template (e.g. `backend`, `treasurer`) |
| `sources` | id, project_id, kind (`github`, `document`, `taskboard`, `chat`), config (redacted), status, last_synced_at, scope (date range, channels) |
| `evidence_units` | id, project_id, source_id, kind, permalink, locator (line/message/commit), author, occurred_at, text (redacted), content_hash, sensitivity (`team`, `restricted`, `confidential`), embedding vector(768), tsv |
| `evidence_acl` | evidence_id, principal (`user:…`, `group:…`, `project:…#member`) — mirrored to OpenFGA |
| `redactions` | evidence_id, rule_id, kind, span — never the secret value |
| `entities` | id, project_id, kind (Person, Module, Task, Decision, Risk, Dependency, ExternalContact, Event), name, attrs |
| `edges` | src, dst, kind (owns, decided, depends_on, blocks, supersedes, mentions, assigned_to), valid_from, evidence_id |
| `claims` | id, project_id, type (Decision, Owner, Dependency, Risk, Blocker, OpenQuestion, NextAction, Contact, RecurringProblem), statement, rationale, valid_from/to, grade, confidence, status (Draft, Edited, Approved, Rejected), version, superseded_by, conflicts_with[], effective_sensitivity, created_by_agent |
| `claim_evidence` | claim_id, evidence_id, quote, span_start, span_end, quote_hash, supports (bool from Skeptic) |
| `claim_versions` | claim_id, version, statement, diff, edited_by, edited_at |
| `runs` / `run_steps` | run id, project, status, budgets used; per-agent step with input/output counts, tokens, latency, error |
| `gap_questions` | id, handover_id, claim_id?, question, why_asked, priority, assignee (leaver or fallback teammate), status |
| `gap_answers` | question_id, answered_by, text, answered_at → becomes an Attested evidence unit |
| `handovers` | id, project_id, leaver_id, successor_id, approver_id, role_template, scope (module/folder/label), status (Drafting, Interviewing, InReview, Published, Acknowledged), version, approved_at |
| `handover_sections` | handover_id, recipient_id, section key, content (JSON, citations), withheld_count, acknowledged_at, flagged |
| `plan_items` | handover_id, week, title, detail, owner, due_date, claim_ids |
| `audit_log` | actor, action, object, project_id, at, meta |
| `jobs` | id, kind, payload, status, attempts, run_after, locked_by |

---

## 5. The 9 agents and how they're wired

```
Connect      Scout ──► Sentinel ──► evidence_units (+ACL to OpenFGA, embeddings)
Reconstruct  ┌ Decision Miner ┐
             ├ Ownership Mapper ┤  (parallel fan-out in LangGraph)
             └ Risk Detector  ┘ ──► Timeline Builder (supersedes / reversals)
Verify       Skeptic (independent: sees claim + cited passages only) ──► grades
             Gap Interviewer ──► questions ──► interrupt() … answers ──► Skeptic re-grade
Review       (human) approver queue; Gatekeeper enforces who can do what
Handover     Gatekeeper filters claims per recipient ──► Composer ──► pack + 30-day plan
```

Rules every agent follows:

* Input is retrieved by `retrieval.search(reader=…, …)` — already redacted and permission-filtered.
* Output is a Pydantic model; invalid output is retried once, then dropped and logged.
* Every claim must carry `evidence_id + quote`. The quote must exist verbatim (whitespace-normalised) in the cited unit, or the claim is rejected before it reaches the Skeptic.
* Source text is wrapped as data (`<evidence id=…>…</evidence>`) and the skill file tells the model never to follow instructions inside it.
* Each run has a step and token budget; exceeding it stops the run with a clear status.

Grading (Skeptic + deterministic rules):

| Grade | Rule |
|---|---|
| Verified | ≥2 supporting units from different sources/authors, **or** 1 supporting unit + leaver confirmation |
| Supported | exactly 1 supporting unit |
| Attested | only a Gap Interview answer |
| Inferred | Skeptic says no single passage states it, but the set implies it |
| Conflicting | Skeptic finds a supporting and a contradicting unit (both kept, dated) |
| Missing | expected slot is empty (module with no owner, risk with no mitigation owner, decision with no reason) |

The LLM only judges "does this passage support / contradict this statement"; the grade itself is computed in code from those judgements, so grades are reproducible.

---

## 6. Permission model

* OpenFGA types: `user`, `project` (admin/approver/leaver/successor/viewer), `source`, `evidence` (viewer from source + sensitivity), `claim` (viewable only if **all** its evidence is viewable — computed in code as an intersection, cached per handover).
* Retrieval filters by `ListObjects(user, viewer, evidence)` **before** anything reaches an LLM.
* Composer only receives claims the Gatekeeper released for that recipient; it gets `withheld: {count, labels}` so it can write "2 items withheld (Finance) — ask Priya".
* Every view, edit, approval, export is written to `audit_log`.

---

## 7. UI — "made by a person, not a model"

Design direction: a careful **editorial notebook**, not an AI dashboard.

* **No** purple/blue gradients, glassmorphism, sparkle icons, "✨ AI-powered" badges, or chat-bubble-everything.
* Warm paper background, ink-coloured text, one accent (deep teal), a serif for headings and long reading (Newsreader), a sans with character for UI (IBM Plex Sans), a mono for citations (IBM Plex Mono).
* Claims read like a **ledger**: one line per claim, a grade "stamp" with text + colour, citations as numbered margin footnotes that open the source side by side.
* Copy in plain human voice: "Aarav left 9 things only he can answer. It takes about 12 minutes." — not "AI has generated insights".
* Real empty states, skeleton loading that matches layout, keyboard shortcuts (`j/k` to move, `a` approve, `r` reject, `e` edit, `⌘K` search), visible focus rings, WCAG 2.2 AA contrast, light + dark themes.
* Mobile: the pack and the interview are fully usable on a phone; the review queue is laptop-first.

Screens:

| Who | Screen |
|---|---|
| All | Sign in (OAuth / demo personas), project list |
| Admin | Project overview (readiness, sources, last run), Sources (connect/upload/import), Members & roles, Audit log |
| Admin/Approver | Run view (live agent timeline), Evidence browser, Claim Ledger (filters by type/grade), Timeline (decisions + reversals), Conflict view (side by side) |
| Leaver | Gap Interview (one question at a time, why it's asked, the evidence it came from, "I don't know" / "ask someone else") |
| Approver | Review queue (riskiest first, evidence beside each claim, versions + diff), Publish |
| Successor | Handover Pack (8 sections, withheld markers, acknowledge per section, flag a claim), 30-day plan (week view, .ics export) |

---

## 8. Phases, exit checks and order of work

Each phase ends with a check that must pass before the next one starts.

| Phase | Build | Exit check |
|---|---|---|
| **0. Foundations** ✅ | Repo, compose (Postgres+pgvector, OpenFGA), API skeleton, migrations, auth (OAuth + demo), web shell + design system, CI | `docker compose up` → sign in → empty project list; CI green |
| **1. Evidence** ✅ | Project + membership CRUD, Sentinel, 4 connectors (GitHub, docs upload, task board, chat), embeddings, evidence browser, OpenFGA tuples | Nimbus sources ingested; evidence browsable with permalinks; 3 planted secrets redacted |
| **2. Agents** ✅ | Gemini gateway, skills, LangGraph pipeline, extraction agents, Timeline Builder, Skeptic + grading, Gap Interviewer + resume, Nimbus dataset + answer key | Graded ledger on Nimbus data; run view shows each agent |
| **3. Handover** ✅ | Handover creation, review queue + versions, Gatekeeper filtering, Composer, pack, 30-day plan, acknowledgements, audit log, Markdown/PDF export | **End-to-end run works** for all four personas |
| **4. Test & ship** | Eval harness + trap tests in CI, failure-case tests, Playwright smoke, user test (6 students), deploy, docs, demo video, DISCLOSURES | Round 2 submitted |
| **5. Round 3** | Successor Copilot (10th agent), Knowledge Risk Radar, live Drive/Slack sync, access requests, one new feature to pick (Jira moved to Round 2) | Round 3 submitted |

### Cut order if behind (unchanged from Round 1)
1. PDF export (keep Markdown) 2. Chat importer 3. Second role template 4. Conflict-view polish.
Never cut: evidence links, grades, review/approval, permission filtering.

---

## 9. Extras worth adding (small, low-risk)

The Round 1 doc froze the feature list, so these are clearly marked as extras and only built after Phase 3 passes.

1. **Handover readiness meter** — % of claims Verified/Supported, open gaps, unacknowledged sections. Pure SQL, no AI. (Pulls Future #20 forward in a small form.)
2. **Calendar export of the 30-day plan** (`.ics`) — deadlines like "domain renews 2 Dec" land in the successor's calendar.
3. **Command palette (⌘K)** — jump to any claim, person, module or source.
4. **"Source changed" drift banner** — already promised in §10 of Round 1 (quote hash check); we surface it on the pack and the overview.

---

## 10. Evaluation harness

`data/nimbus/answer_key.yaml` lists every planted item (25 decisions incl. 5 reversals, 15 owners, 8 dependencies, 10 risks, 6 contradictions, 5 omissions, 3 fake secrets, 2 confidential notes, ~20% Hinglish chat, 1 prompt-injection message). `make eval` runs the pipeline against it and prints the Round 1 metrics table. CI runs the cheap deterministic part (Sentinel, Gatekeeper matrix, citation-quote check) on every push; the full LLM eval runs on demand with a cached run as backup.

---

## 11. Environment variables

See `.env.example`. The only required secret for a local demo is `GEMINI_API_KEY`.

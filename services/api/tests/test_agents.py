"""Phase 2 machinery: the Gemini gateway, evidence packets, the Scout, the
Sentinel review, the extraction agents and claims read from system data.
Gemini itself is replaced at the network edge (`gateway._call`), so these tests
check our own logic (cache, retries, limits, routing, labels, quotes) offline;
the live behaviour is checked with a real key in runs on Nimbus."""

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors
from sqlalchemy import delete, func, select

from app import demo, gatekeeper, ingest, retrieval
from app.agents import base, evidence, extract, facts, scout, sentinel_review, skills
from app.connectors.base import RetryLater
from app.db.models import (
    AuditEvent,
    Claim,
    ClaimEvidence,
    ClaimType,
    EvidenceUnit,
    LlmCache,
    Run,
    RunStep,
    Sensitivity,
    Source,
    User,
)
from app.llm import gateway

pytestmark = pytest.mark.db


class Answer(gateway.BaseModel):
    text: str


def _response(parsed, tokens=10):
    return gateway._Reply(parsed=parsed, tokens_in=tokens, tokens_out=2)


def _quota_error(message: str) -> errors.ClientError:
    return errors.ClientError(429, {"error": {"code": 429, "message": message, "status": "RESOURCE_EXHAUSTED"}})


@pytest.fixture
def fake_gemini(monkeypatch):
    """Replaces the network call with a queue of answers; records each prompt."""
    calls: list[str] = []
    answers: list = []

    def call(model, system, prompt, schema, thinking, temperature):
        calls.append(prompt)
        a = answers.pop(0) if answers else _response(None)
        if isinstance(a, Exception):
            raise a
        return a(prompt, schema) if callable(a) else a

    monkeypatch.setattr(gateway, "_call", call)
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    monkeypatch.setattr(gateway.time, "sleep", lambda s: None)
    return SimpleNamespace(calls=calls, answers=answers)


def _gen(db, prompt, **kw):
    return gateway.generate(db, Answer, agent="test", version="1", tier="fast", system="s", prompt=prompt, **kw)


# --- gateway --------------------------------------------------------------


def test_answers_are_cached(db, fake_gemini):
    prompt = f"cache {uuid.uuid4()}"
    fake_gemini.answers.append(_response(Answer(text="hi")))
    usage = gateway.Usage()
    first = _gen(db, prompt, usage=usage)
    second = _gen(db, prompt, usage=usage)
    assert (first.value.text, first.cached, second.value.text, second.cached) == ("hi", False, "hi", True)
    assert len(fake_gemini.calls) == 1
    assert (usage.calls, usage.cached, usage.tokens) == (1, 1, 12)


def test_a_new_skill_version_is_not_served_from_cache(db, fake_gemini):
    prompt = f"version {uuid.uuid4()}"
    fake_gemini.answers += [_response(Answer(text="v1")), _response(Answer(text="v2"))]
    _gen(db, prompt)
    again = gateway.generate(db, Answer, agent="test", version="2", tier="fast", system="s", prompt=prompt)
    assert again.value.text == "v2" and not again.cached


def test_an_answer_that_misses_the_schema_is_retried_once(db, fake_gemini):
    fake_gemini.answers += [_response(None), _response(Answer(text="fixed"))]
    assert _gen(db, f"retry {uuid.uuid4()}").value.text == "fixed"
    assert "did not match" in fake_gemini.calls[1]


def test_two_bad_answers_raise_and_nothing_is_cached(db, fake_gemini):
    rows = db.scalar(select(func.count()).select_from(LlmCache))
    fake_gemini.answers += [_response(None), _response(None)]
    with pytest.raises(gateway.AgentOutputInvalid):
        _gen(db, f"bad {uuid.uuid4()}")
    assert db.scalar(select(func.count()).select_from(LlmCache)) == rows


def test_a_short_slow_down_is_waited_out(db, fake_gemini):
    fake_gemini.answers += [_quota_error("Please retry in 2.5s."), _response(Answer(text="after wait"))]
    assert _gen(db, f"wait {uuid.uuid4()}").value.text == "after wait"
    assert len(fake_gemini.calls) == 2


def test_a_long_or_daily_limit_pauses_the_run(db, fake_gemini):
    fake_gemini.answers.append(_quota_error("Quota exceeded for GenerateRequestsPerDay. Please retry in 30s."))
    with pytest.raises(RetryLater, match="daily"):
        _gen(db, f"daily {uuid.uuid4()}")
    fake_gemini.answers.append(_quota_error("Please retry in 600s."))
    with pytest.raises(RetryLater):
        _gen(db, f"long {uuid.uuid4()}")


def test_server_errors_are_retried(db, fake_gemini):
    fake_gemini.answers += [errors.ServerError(503, {"error": {"message": "overloaded"}}),
                            _response(Answer(text="ok"))]
    assert _gen(db, f"503 {uuid.uuid4()}").value.text == "ok"


def test_the_budget_stops_new_calls_but_not_cached_ones(db, fake_gemini):
    prompt = f"budget {uuid.uuid4()}"
    fake_gemini.answers.append(_response(Answer(text="once")))
    budget = gateway.Budget(max_calls=1, max_tokens=1_000)
    _gen(db, prompt, budget=budget)
    assert _gen(db, prompt, budget=budget).cached
    with pytest.raises(gateway.BudgetExceeded):
        _gen(db, f"over {uuid.uuid4()}", budget=budget)


class _FakeHttp:
    """Stands in for an OpenAI-compatible server (ASI:One, Groq, a local Ollama...)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.bodies = []

    def post(self, url, headers, json):
        self.bodies.append(json)
        status, payload, extra = self.responses.pop(0)
        return httpx.Response(status, json=payload, headers=extra, request=httpx.Request("POST", url))


def _openai(monkeypatch, *responses) -> _FakeHttp:
    from app.config import get_settings

    for k, v in {"LLM_PROVIDER": "openai", "LLM_BASE_URL": "https://llm.example/v1", "LLM_API_KEY": "k",
                 "LLM_MODEL_REASONING": "big", "LLM_MODEL_FAST": "small"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    monkeypatch.setattr(gateway.time, "sleep", lambda s: None)
    fake = _FakeHttp(*responses)
    monkeypatch.setattr(gateway, "_http", lambda: fake)
    return fake


def _chat(content: str) -> tuple[int, dict, dict]:
    return 200, {"choices": [{"message": {"content": content}}],
                 "usage": {"prompt_tokens": 30, "completion_tokens": 5}}, {}


@pytest.fixture
def restore_settings():
    from app.config import get_settings

    yield
    get_settings.cache_clear()


def test_openai_compatible_provider(db, monkeypatch, restore_settings):
    fake = _openai(monkeypatch, _chat('```json\n{"text": "from ASI"}\n```'))
    out = _gen(db, f"openai {uuid.uuid4()}")
    assert out.value.text == "from ASI" and out.tokens == 35
    body = fake.bodies[0]
    assert body["model"] == "small"  # the fast tier
    assert body["messages"][0]["content"].startswith(gateway.SYSTEM_RULES)
    assert body["response_format"]["json_schema"]["schema"] == Answer.model_json_schema()


def test_openai_compatible_retries_and_limits(db, monkeypatch, restore_settings):
    _openai(monkeypatch, _chat("not json"), _chat('{"text": "second try"}'))
    assert _gen(db, f"openai-bad {uuid.uuid4()}").value.text == "second try"

    _openai(monkeypatch, (429, {"error": "slow down"}, {"retry-after": "3"}), _chat('{"text": "waited"}'))
    assert _gen(db, f"openai-429 {uuid.uuid4()}").value.text == "waited"

    _openai(monkeypatch, (429, {"error": "Limit of requests per day reached"}, {}))
    with pytest.raises(RetryLater, match="daily"):
        _gen(db, f"openai-daily {uuid.uuid4()}")


def test_evidence_rules_lead_every_prompt(db, monkeypatch, fake_gemini):
    seen = {}

    def call(model, system, *rest):
        seen["s"] = system
        return _response(Answer(text="x"))

    monkeypatch.setattr(gateway, "_call", call)
    _gen(db, f"rules {uuid.uuid4()}")
    assert seen["s"].startswith(gateway.SYSTEM_RULES)


# --- packets, bundles, quotes ---------------------------------------------


@pytest.fixture(scope="module")
def nimbus(database) -> uuid.UUID:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        project = demo.create_nimbus(db, enqueue=False)
        for source in db.scalars(select(Source).where(Source.project_id == project.id)).all():
            ingest.sync_source(db, source.id)
        return project.id


def _ctx(db, project_id: uuid.UUID, who: str = "priya") -> base.AgentContext:
    agents = ["scout", "sentinel_review", *extract.ALLOWED]
    db.execute(delete(LlmCache).where(LlmCache.agent.in_(agents)))  # fresh answers per test
    uid = db.scalar(select(User.id).where(User.email == f"{who}@nimbus.demo"))
    run = Run(project_id=project_id, kind="test")  # not a "build claims" run the API would see
    db.add(run)
    db.commit()
    return base.context_for(db, run, gatekeeper.principal(db, project_id, uid))


def _packets(db, ctx):
    return evidence.build_packets(evidence.packet_units(db, ctx.principal, ctx.project_id), ctx.source_names)


def test_confidential_items_never_reach_a_packet(db, nimbus):
    ctx = _ctx(db, nimbus)  # priya can see confidential items, but they still aren't sent
    units = [u for pk in _packets(db, ctx) for u in pk.units]
    assert units and all(u.sensitivity != Sensitivity.confidential for u in units)
    assert db.scalar(select(EvidenceUnit.id).where(EvidenceUnit.project_id == nimbus,
                                                   EvidenceUnit.sensitivity == Sensitivity.confidential))


def test_packets_keep_threads_together_and_stay_small(db, nimbus):
    packets = _packets(db, _ctx(db, nimbus))
    assert all(pk.size <= evidence.MAX_PACKET_CHARS or len(pk.units) == 1 for pk in packets)
    threads = [pk for pk in packets if pk.kind == "thread" and len(pk.units) > 1]
    assert threads, "comments should sit with their issue or PR"


def test_bundles_keep_every_packet_once(db, nimbus):
    packets = _packets(db, _ctx(db, nimbus))
    bundles = base.bundles(packets)
    assert sorted(pk.key for b in bundles for pk in b) == sorted(pk.key for pk in packets)
    assert len(bundles) < len(packets)
    assert all(sum(pk.size for pk in b) <= base.BUNDLE_CHARS or len(b) == 1 for b in bundles)


def test_bundle_ids_are_continuous(db, nimbus):
    ctx = _ctx(db, nimbus)
    bundle = base.bundles(_packets(db, ctx))[0]
    text, ids = base.render_bundle(ctx, bundle)
    assert list(ids) == [f"E{n}" for n in range(1, len(ids) + 1)]
    assert all(f'id="{k}"' in text for k in ids)


def test_quotes_must_really_be_in_the_evidence(db, nimbus):
    unit = db.scalars(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus,
                                                 EvidenceUnit.sensitivity == Sensitivity.team)).first()
    words = " ".join(unit.text.split()[:8])
    assert evidence.find_quote(unit, words.upper())
    assert not evidence.find_quote(unit, "we decided to rewrite everything in Rust")
    assert not evidence.find_quote(unit, "the")  # too short to prove anything


# --- Scout ----------------------------------------------------------------


def test_scout_routes_packets_and_never_drops_one(db, nimbus, fake_gemini):
    ctx = _ctx(db, nimbus)
    packets = _packets(db, ctx)

    def answer(prompt, schema):
        lines = [ln for ln in prompt.splitlines() if ln.startswith("P") and " | " in ln]
        routes = [scout.Route(packet=ln.split(" | ")[0], agents=[] if n == 0 else ["decision_miner", "made_up_agent"])
                  for n, ln in enumerate(lines)]
        return _response(scout.ScoutOut(routes=routes))

    fake_gemini.answers += [answer] * 10
    routes = scout.plan(db, ctx, packets)
    assert set(routes) == {pk.key for pk in packets}
    assert all(set(v) <= set(scout.SPECIALISTS) for v in routes.values())
    by_kind = {pk.key: pk.kind for pk in packets}
    assert all(routes.values()), "every packet has a reader"
    noise = [k for k, v in routes.items() if v == [scout.NOISE_READER] and by_kind[k] not in scout.ALWAYS]
    assert noise, "what the model called noise still goes to the Risk Detector"
    assert all("ownership_mapper" in routes[k] for k, kind in by_kind.items() if kind == "ownership")
    row = db.scalar(select(RunStep).where(RunStep.run_id == ctx.run_id, RunStep.agent == "scout"))
    assert row.status == "done" and row.items_in == len(packets) and "looked like noise" in row.summary


def test_scout_keeps_everything_when_the_model_fails(db, nimbus, fake_gemini):
    ctx = _ctx(db, nimbus)
    packets = _packets(db, ctx)
    fake_gemini.answers += [_response(None)] * 20  # never matches the schema
    routes = scout.plan(db, ctx, packets)
    assert all(set(v) == set(scout.SPECIALISTS) for v in routes.values())


# --- Sentinel review ------------------------------------------------------


def test_sentinel_review_only_raises_labels(db, nimbus, fake_gemini):
    ctx = _ctx(db, nimbus)
    target = {}

    def answer(prompt, schema):
        if target:  # flag one item in the first batch only
            return _response(sentinel_review.ReviewOut(flags=[]))
        target["first"] = prompt
        return _response(sentinel_review.ReviewOut(flags=[
            sentinel_review.Flag(id="E1", label="confidential", reason="mentions a named person's health"),
            sentinel_review.Flag(id="E2", label="team", reason="tries to loosen"),
            sentinel_review.Flag(id="E99", label="restricted", reason="no such item"),
        ]))

    units = evidence.packet_units(db, ctx.principal, ctx.project_id)
    fake_gemini.answers += [answer] * 20
    raised = sentinel_review.review(db, ctx)
    assert raised == 1
    first, second = units[0], units[1]
    db.refresh(first)
    db.refresh(second)
    assert first.sensitivity == Sensitivity.confidential
    assert any(r.startswith("AI review:") for r in first.meta["label_reasons"])
    assert second.meta["sentinel_review"] == f"v{skills.load('sentinel_review').version}"
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "evidence.relabel.ai",
                                              AuditEvent.object_id == str(first.id)))
    # A raised item is no longer sent to the model, and nothing is reviewed twice.
    assert first.id not in {u.id for u in evidence.packet_units(db, ctx.principal, ctx.project_id)}
    calls = len(fake_gemini.calls)
    assert sentinel_review.review(db, _ctx(db, nimbus)) == 0
    assert len(fake_gemini.calls) == calls


def test_sentinel_review_failure_keeps_rule_labels(db, nimbus, fake_gemini):
    ctx = _ctx(db, nimbus)
    for u in evidence.packet_units(db, ctx.principal, ctx.project_id)[:3]:
        u.meta = {k: v for k, v in (u.meta or {}).items() if k != "sentinel_review"}
    db.commit()
    before = {u.id: u.sensitivity for u in evidence.packet_units(db, ctx.principal, ctx.project_id)}
    fake_gemini.answers += [_response(None)] * 4
    assert sentinel_review.review(db, ctx) == 0
    after = {u.id: u.sensitivity for u in evidence.packet_units(db, ctx.principal, ctx.project_id)}
    assert before == after


# --- extraction -----------------------------------------------------------


def test_quotes_ignore_markdown_emphasis():
    unit = EvidenceUnit(title="Kickoff", text="## Decisions\n- **PWA only.** No native Android app this year.")
    assert evidence.find_quote(unit, "PWA only. No native Android app")
    assert not evidence.find_quote(unit, "PWA only. A native iOS app")


def test_dates_are_the_teams_local_dates():
    assert evidence.local_date(datetime(2026, 10, 19, 19, 50, tzinfo=UTC)) == date(2026, 10, 20)  # 01:20 IST


def test_handles_resolve_to_one_member():
    names = ["Sneha Kulkarni", "Dev Patel", "Dev Sharma"]
    assert facts.person("sneha-k", names) == "Sneha Kulkarni"
    assert facts.person("Sneha", names) == "Sneha Kulkarni"
    assert facts.person("dev-p", names) == "dev-p"  # two Devs: don't guess
    assert facts.person("ghost", names) == "ghost"


def _first_words(prompt: str, eid: str) -> str:
    lines = prompt.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f'<evidence id="{eid}"'))
    body = next(ln for ln in lines[start + 1 :] if len(ln.strip()) >= 12)  # past a short title like "#dev"
    return " ".join(body.split()[:6])


def test_extraction_keeps_only_claims_with_real_quotes(db, nimbus, fake_gemini):
    ctx = _ctx(db, nimbus)
    packets = _packets(db, ctx)

    def answer(prompt, schema):
        cite = base.Cite(id="E1", quote=_first_words(prompt, "E1"))
        return _response(base.ExtractionOut(claims=[
            base.DraftClaim(type="decision", statement="Real decision.", subject="x", evidence=[cite]),
            base.DraftClaim(type="decision", statement="Invented.", subject="y",
                            evidence=[base.Cite(id="E1", quote="we will rewrite it all in Rust")]),
            base.DraftClaim(type="owner", statement="Wrong type for this agent.", subject="z", evidence=[cite]),
        ]))

    calls = len(base.bundles(packets))
    fake_gemini.answers += [answer] * calls
    kept = extract.extract(db, ctx, "decision_miner", packets, routes={})
    assert kept == calls
    claims = db.scalars(select(Claim).where(Claim.run_id == ctx.run_id)).all()
    assert {c.statement for c in claims} == {"Real decision."}
    assert all(c.evidence and c.created_by_agent == "decision_miner" for c in claims)
    row = db.scalar(select(RunStep).where(RunStep.run_id == ctx.run_id, RunStep.agent == "decision_miner"))
    assert row.status == "done" and f"{2 * calls} dropped" in row.summary

    # Resuming the same run doesn't redo finished bundles.
    before = len(fake_gemini.calls)
    assert extract.extract(db, ctx, "decision_miner", packets, routes={}) == 0
    assert len(fake_gemini.calls) == before


def test_agents_only_read_what_the_scout_sent_them(db, nimbus, fake_gemini):
    ctx = _ctx(db, nimbus)
    packets = _packets(db, ctx)
    routes = {pk.key: [] for pk in packets} | {packets[0].key: ["decision_miner"]}
    fake_gemini.answers.append(_response(base.ExtractionOut(claims=[])))
    extract.extract(db, ctx, "decision_miner", packets, routes)
    assert len(fake_gemini.calls) == 1
    assert f'<packet title="{packets[0].title}">' in fake_gemini.calls[0]


def test_system_data_claims_from_ci_and_pull_requests(db, nimbus, fake_gemini):
    ctx = _ctx(db, nimbus)
    assert facts.risks(db, ctx, "risk_detector") == 2
    db.commit()
    claims = {c.type.value + ": " + c.statement: c
              for c in db.scalars(select(Claim).where(Claim.run_id == ctx.run_id))}
    assert "blocker: CI workflow “build” on main has failed since 28 Oct 2026 (2 runs in a row)." in claims
    assert ("blocker: PR #42 “WIP: nightly payment reconciliation” by Aarav Mehta is still open with no activity "
            "since 20 Oct 2026.") in claims
    assert all(c.grade_reason.startswith(facts.SYSTEM_DATA) and c.evidence for c in claims.values())
    assert not fake_gemini.calls  # no model involved


def test_system_data_claims_from_git_history_and_overdue_cards(db, nimbus):
    sources = {s.kind.value: s for s in db.scalars(select(Source).where(Source.project_id == nimbus))}
    added = [
        EvidenceUnit(project_id=nimbus, source_id=sources["github"].id, external_id="ownership:scanner",
                     kind="code_ownership", title="Who has changed scanner", author="sneha-k",
                     text="Code ownership from git history: scanner\nsneha-k: 8 of 10 commits (80%) · dev-p: 2 (20%)",
                     content_hash="t1", occurred_at=datetime(2026, 10, 30, tzinfo=UTC), locator="git history · scanner",
                     meta={"module": "scanner", "authors": {"sneha-k": 8, "dev-p": 2}, "total_commits": 10}),
        EvidenceUnit(project_id=nimbus, source_id=sources["github"].id, external_id="ownership:docs",
                     kind="code_ownership", title="Who has changed docs", author="dev-p",
                     text="Code ownership from git history: docs\ndev-p: 2 of 2 commits (100%)", content_hash="t2",
                     meta={"module": "docs", "authors": {"dev-p": 2}, "total_commits": 2}),  # too few commits
        EvidenceUnit(project_id=nimbus, source_id=sources["taskboard"].id, external_id="trello:card:test-overdue",
                     kind="card", title="Print volunteer badges", author="",
                     text="Card: Print volunteer badges\nList: This week", content_hash="t3",
                     occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
                     meta={"status": "This week", "assignees": [], "due": "2026-10-20", "closed": False}),
    ]
    db.add_all(added)
    db.commit()
    try:
        ctx = _ctx(db, nimbus)
        facts.ownership(db, ctx, "ownership_mapper")
        facts.risks(db, ctx, "risk_detector")
        db.commit()
        statements = set(db.scalars(select(Claim.statement).where(Claim.run_id == ctx.run_id)))
        assert "Sneha Kulkarni made 80% of the commits to scanner (8 of 10)." in statements
        assert not any(" to docs " in s for s in statements)  # 2 commits are too few to call anyone the owner
        assert "“Print volunteer badges” was due 20 Oct 2026 and is still open, with nobody assigned." in statements
    finally:
        for u in added:
            db.delete(u)
        db.commit()


# --- runs and the claim ledger through the API ------------------------------


def _as(email: str):
    import time

    import jwt
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    now = int(time.time())
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer " + jwt.encode(
        {"sub": email, "provider": "demo", "iss": "knowbridge-web", "aud": "knowbridge-api", "iat": now,
         "exp": now + 300}, get_settings().api_jwt_secret, "HS256")
    return c


def test_build_claims_run_and_ledger(db, nimbus, monkeypatch):
    from app import llm
    from app.agents import pipeline

    def empty_answer(model, system, prompt, schema, thinking, temperature):
        return gateway._Reply(schema.model_validate({f: [] for f in schema.model_fields}), 5, 1)

    monkeypatch.setattr(gateway, "_call", empty_answer)
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    priya, kabir, meera = _as("priya@nimbus.demo"), _as("kabir@nimbus.demo"), _as("meera@nimbus.demo")

    monkeypatch.setattr(llm, "configured", lambda: False)
    assert priya.post(f"/projects/{nimbus}/runs").status_code == 409  # no model set up
    monkeypatch.setattr(llm, "configured", lambda: True)

    started = priya.post(f"/projects/{nimbus}/runs")
    assert started.status_code == 202, started.text
    run_id = uuid.UUID(started.json()["id"])
    assert priya.post(f"/projects/{nimbus}/runs").status_code == 409  # one at a time

    pipeline.reconstruct(db, run_id)  # what the worker does
    run = priya.get(f"/projects/{nimbus}/runs/latest").json()
    assert run["status"] == "done" and {s["agent"] for s in run["steps"]} >= {"scout", *extract.ALLOWED}

    page = priya.get(f"/projects/{nimbus}/claims").json()
    statements = [c["statement"] for c in page["items"]]
    assert any(s.startswith("CI workflow") for s in statements)  # from system data, no model needed
    assert all(c["evidence"] and c["evidence"][0]["quote"] for c in page["items"])
    assert all(c["from_system_data"] for c in page["items"])

    # A claim citing a confidential item: Priya (cleared) sees it, Kabir (admin, not cleared) doesn't.
    secret = db.scalar(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus,
                                                  EvidenceUnit.sensitivity == Sensitivity.confidential))
    claim = Claim(project_id=nimbus, run_id=run_id, type=ClaimType.risk, statement="Private matter.",
                  sensitivity=Sensitivity.confidential, created_by_agent="risk_detector")
    db.add(claim)
    db.flush()
    db.add(ClaimEvidence(claim_id=claim.id, evidence_id=secret.id, quote=secret.text[:20], quote_hash="x"))
    db.commit()
    assert "Private matter." in [c["statement"] for c in priya.get(f"/projects/{nimbus}/claims").json()["items"]]
    k = kabir.get(f"/projects/{nimbus}/claims").json()
    assert "Private matter." not in [c["statement"] for c in k["items"]] and k["hidden"] == 1

    assert priya.get(f"/projects/{nimbus}/claims", params={"type": "risk"}).json()["items"][0]["type"] == "risk"

    # Search reads a question: filler words are dropped and other forms of a word still match.
    found = priya.get(f"/projects/{nimbus}/claims", params={"q": "why are the CI workflows failing?"}).json()
    assert any(c["statement"].startswith("CI workflow") for c in found["items"])
    assert priya.get(f"/projects/{nimbus}/claims", params={"q": "zzqxv"}).json()["total"] == 0

    # Paging: one page of the same order, with the full count alongside.
    every = priya.get(f"/projects/{nimbus}/claims").json()
    second = priya.get(f"/projects/{nimbus}/claims", params={"limit": 1, "offset": 1}).json()
    assert every["total"] == len(every["items"]) >= 2 and second["total"] == every["total"]
    assert [c["id"] for c in second["items"]] == [every["items"][1]["id"]]
    assert meera.get(f"/projects/{nimbus}/claims").status_code == 403  # the successor sees the pack, not drafts


# --- speed: parallel calls, short Jira history, short pauses ----------------


def test_parallel_calls_answer_in_order(db, monkeypatch, restore_settings):
    import threading
    import time

    from app.config import get_settings

    monkeypatch.setenv("LLM_PARALLEL", "4")
    get_settings.cache_clear()
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    lock, live, peak = threading.Lock(), [0], [0]

    def call(model, system, prompt, schema, thinking, temperature):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
        return gateway._Reply(Answer(text=prompt.upper()), 1, 1)

    monkeypatch.setattr(gateway, "_call", call)
    tag = uuid.uuid4().hex[:6]
    prompts = [f"p{i}-{tag}" for i in range(12)]
    ctx = SimpleNamespace(budget=None)
    skill = skills.Skill(name="t", version="1", tier="fast", thinking=None, instructions="s")
    answers = list(base.generate_many(ctx, Answer, prompts, agent="parallel-test", skill=skill,
                                      usage=gateway.Usage()))
    assert [a.text for a in answers] == [p.upper() for p in prompts]
    assert peak[0] > 1, "calls ran at the same time"


def test_jira_history_is_shortened_for_agents_only():
    history = [f"  2026-10-{d:02d}  Aman: status To Do → In Progress" for d in range(1, 13)]
    history.insert(2, "  2026-10-02  Aman: assignee Ravi → Aman")
    text = "KCT-9: Executor\nType: Story · Status: To Do\nHistory:\n" + "\n".join(history) + "\n\nThe description."
    unit = EvidenceUnit(title="KCT-9: Executor", text=text, meta={"provider": "jira"})
    short = evidence.for_agents(unit)
    assert "assignee Ravi → Aman" in short  # who held it is always kept
    assert "2026-10-12" in short and "2026-10-03" not in short  # the latest moves only
    assert "7 other changes not shown" in short and short.endswith("The description.")  # 13 - 5 latest - 1 assignee
    assert evidence.find_quote(unit, "2026-10-03  Aman: status To Do")  # quotes still checked on the full text
    plain = EvidenceUnit(title="x", text=text, meta={})
    assert evidence.for_agents(plain) == text  # only Jira tickets are shortened


def test_slow_down_without_a_hint_pauses_minutes_not_an_hour(db, monkeypatch, restore_settings):
    from datetime import UTC, datetime

    _openai(monkeypatch, (429, {"error": "too many requests"}, {}))
    with pytest.raises(RetryLater) as e:
        _gen(db, f"openai-nohint {uuid.uuid4()}")
    wait = (e.value.retry_at - datetime.now(UTC)).total_seconds()
    assert 240 < wait <= gateway.NO_HINT_PAUSE


# --- Timeline Builder and Skeptic (2.5) -------------------------------------


def _claim(db, run_id, pid, ctype, statement, subject, units, day, *, rationale="", owner=""):
    claim = Claim(project_id=pid, run_id=run_id, type=ctype, statement=statement, subject=subject,
                  rationale=rationale, owner_name=owner, created_by_agent="test",
                  valid_from=datetime(2026, 10, day, tzinfo=UTC))
    db.add(claim)
    db.flush()
    for u in units:
        db.add(ClaimEvidence(claim_id=claim.id, evidence_id=u.id, quote=u.text[:30], quote_hash="t"))
    db.commit()
    return claim


def _ids_by_statement(prompt: str) -> dict[str, str]:
    """'C3 | 2026-10-04 | subject | statement' lines -> {statement: 'C3'}."""
    return {ln.split(" | ")[3]: ln.split(" | ")[0] for ln in prompt.splitlines() if ln.startswith("C") and " | " in ln}


def test_timeline_merges_links_and_keeps_number_conflicts(db, nimbus, monkeypatch):
    from app.agents import timeline

    ctx = _ctx(db, nimbus)
    units = db.scalars(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus,
                                                  EvidenceUnit.sensitivity == Sensitivity.team).limit(6)).all()
    d1 = _claim(db, ctx.run_id, nimbus, ClaimType.decision, "The API moved from Render to Railway.", "API hosting",
                [units[0]], 3)
    d2 = _claim(db, ctx.run_id, nimbus, ClaimType.decision, "API hosting changed from Render to Railway.",
                "API hosting", [units[1]], 4)
    d3 = _claim(db, ctx.run_id, nimbus, ClaimType.decision, "The free pass allows at most 3 events.",
                "free pass limit", [units[2]], 5)
    d4 = _claim(db, ctx.run_id, nimbus, ClaimType.decision, "The free pass allows a maximum of 5 events.",
                "free pass event limit", [units[3]], 6)
    d5 = _claim(db, ctx.run_id, nimbus, ClaimType.decision, "Confirmation uses the payment.captured webhook.",
                "payment confirmation", [units[4]], 7)
    d6 = _claim(db, ctx.run_id, nimbus, ClaimType.decision, "Confirmation switched to polling the Orders API.",
                "payment confirmation", [units[5]], 8)

    def answer(model, system, prompt, schema, thinking, temperature):
        if schema is timeline.TimelineOut:
            ids = _ids_by_statement(prompt)

            def pick(c):
                return ids[c.statement]

            # It wrongly calls the 3- and 5-event claims duplicates, and never suggests them as a conflict.
            return gateway._Reply(timeline.TimelineOut(
                duplicates=[timeline.Group(ids=[pick(d1), pick(d2)]), timeline.Group(ids=[pick(d3), pick(d4)])],
                replaced=[timeline.Replacement(old=pick(d5), new=pick(d6))], conflicts=[]), 5, 1)
        verdicts = []
        for block in prompt.split("\n\n"):
            pair_id = block.split("\n", 1)[0]
            relation = "conflict" if "events" in block else "replaced: b" if "webhook" in block else "unrelated"
            verdicts.append(timeline.PairVerdict(id=pair_id, relation=relation))
        return gateway._Reply(timeline.PairsOut(pairs=verdicts), 5, 1)

    monkeypatch.setattr(gateway, "_call", answer)
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    merged, replaced, conflicts = timeline.build(db, ctx)
    db.expire_all()

    survivors = [c for c in (db.get(Claim, d1.id), db.get(Claim, d2.id)) if c is not None]
    assert merged == 1 and len(survivors) == 1  # a true duplicate is merged…
    assert {ce.evidence_id for ce in survivors[0].evidence} == {units[0].id, units[1].id}  # …keeping all its evidence
    a, b = db.get(Claim, d3.id), db.get(Claim, d4.id)
    assert a and b and b.id in a.conflicts_with and a.id in b.conflicts_with  # different numbers: kept, as a conflict
    assert db.get(Claim, d5.id).superseded_by == d6.id and replaced == 1  # "replaced: b" is understood
    assert conflicts == 1


def test_grading_rules():
    from app.agents.skeptic import Cite, decide
    from app.db.models import Grade

    s1, s2 = Cite("supports", "src-a", "aarav"), Cite("supports", "src-b", "kabir")
    part, against, off = Cite("partial", "src-a", "x"), Cite("contradicts", "src-b", "y"), Cite("unrelated", "s", "z")
    common = {"ctype": ClaimType.decision, "overreach": False, "unanswered": False, "conflicting": False}
    assert decide(**common, cites=[s1, s2])[0] == Grade.verified  # two separate sources
    assert decide(**common, cites=[s1, Cite("supports", "src-a", "Aarav")])[0] == Grade.supported  # same person twice
    assert decide(**common, cites=[s1])[0] == Grade.supported
    assert decide(**common, cites=[part])[0] == Grade.inferred
    assert decide(**(common | {"overreach": True}), cites=[s1, s2])[0] == Grade.inferred
    assert decide(**common, cites=[s1, against])[0] == Grade.conflicting
    assert decide(**(common | {"conflicting": True}), cites=[s1])[0] == Grade.conflicting
    assert decide(**common, cites=[against])[0] == Grade.conflicting  # disagreeing with itself: a person checks
    assert decide(**common, cites=[off])[0] is None  # nothing is about it: removed
    assert decide(**(common | {"ctype": ClaimType.open_question, "unanswered": True}), cites=[s1])[0] == Grade.missing
    assert decide(**common, cites=[off], system="CI runs")[0] == Grade.verified


def test_skeptic_grades_from_its_judgements(db, nimbus, monkeypatch):
    from app.agents import skeptic

    ctx = _ctx(db, nimbus)
    pr = db.scalar(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus, EvidenceUnit.author == "aarav-m",
                                              EvidenceUnit.kind == "pull_request").limit(1))
    msg = db.scalar(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus, EvidenceUnit.kind == "message",
                                               EvidenceUnit.sensitivity == Sensitivity.team).limit(1))
    owner = _claim(db, ctx.run_id, nimbus, ClaimType.owner, "Aarav Mehta owns payments.", "payments", [pr], 3,
                   owner="Aarav Mehta")
    reasoned = _claim(db, ctx.run_id, nimbus, ClaimType.decision, "We use Railway.", "hosting", [msg], 4,
                      rationale="because it is cheaper")
    invented = _claim(db, ctx.run_id, nimbus, ClaimType.risk, "The office floods every June.", "office", [msg], 5)
    a = _claim(db, ctx.run_id, nimbus, ClaimType.decision, "Ends 31 Dec.", "early bird", [msg], 6)
    b = _claim(db, ctx.run_id, nimbus, ClaimType.decision, "Ends 15 Dec.", "early bird", [pr], 7)
    a.conflicts_with, b.conflicts_with = [b.id], [a.id]
    db.commit()

    def answer(model, system, prompt, schema, thinking, temperature):
        checks = []
        for block in prompt.split('<claim id="')[1:]:
            cid = block.split('"', 1)[0]
            stance = "unrelated" if "floods" in block else "partial" if "owns payments" in block else "supports"
            checks.append(skeptic.Check(claim=cid, citations=[skeptic.Stance(id=f"{cid}-E1", stance=stance + ".")],
                                        reason_supported="cheaper" not in block))
        return gateway._Reply(skeptic.SkepticOut(checks=checks), 5, 1)

    monkeypatch.setattr(gateway, "_call", answer)
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    counts = skeptic.grade(db, ctx)
    db.expire_all()

    assert db.get(Claim, owner.id).grade.value == "supported"  # Aarav wrote the PR: that is ownership
    r = db.get(Claim, reasoned.id)
    assert r.grade.value == "supported" and r.rationale == ""  # a reason the evidence doesn't give is dropped
    gone = db.get(Claim, invented.id)
    assert gone.status.value == "rejected" and gone.grade_reason.startswith(skeptic.REMOVED)
    assert db.get(Claim, a.id).grade.value == db.get(Claim, b.id).grade.value == "conflicting"
    assert counts["removed"] == 1


def test_claims_about_different_tickets_are_never_linked():
    from app.agents.timeline import different_tickets, related, same_numbers, tickets

    def c(text):
        return SimpleNamespace(subject="", statement=text)

    a = c("Bug KCT-149 has been carried over through 4 sprints.")
    b = c("Bug KCT-39 has been carried over through 14 sprints.")
    assert different_tickets(a, b) and not related(a, b)  # different bugs, however alike they sound
    assert not different_tickets(c("KCT-96 was due 4 Jun."), c("KCT-96: the score exceeds 100%."))
    assert not different_tickets(c("KCT-96 score exceeds 100%."), c("The score shows 133%."))  # one side unnamed
    assert tickets(c("see PR #42, KCT-7 and UTF-8")) == {"#42", "KCT-7"}
    assert same_numbers(c("PR #42 is half done"), c("PR #17 is half done"))  # ticket numbers are not values


# --- Gap Interview (2.6, 2.7) -----------------------------------------------


def test_gap_interview_end_to_end(db, nimbus, monkeypatch):
    from app import llm
    from app.agents import interviewer
    from app.db.models import GapQuestion, Grade, Handover, RunStatus

    monkeypatch.setattr(llm, "configured", lambda: True)
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    users = {u.email.split("@")[0]: u for u in db.scalars(select(User).where(User.email.like("%@nimbus.demo")))}
    db.execute(delete(Run).where(Run.project_id == nimbus, Run.kind == "reconstruct"))
    run = Run(project_id=nimbus, kind="reconstruct", status=RunStatus.done, started_by=users["priya"].id)
    db.add(run)
    db.commit()
    team = db.scalars(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus,
                                                 EvidenceUnit.sensitivity == Sensitivity.team).limit(3)).all()
    early, late = (_claim(db, run.id, nimbus, ClaimType.decision, s, "early bird", [u], d)
                   for s, u, d in [("Early-bird ends 15 Dec.", team[0], 3), ("Early-bird ends 31 Dec.", team[1], 4)])
    early, late = list((early, late))
    login = _claim(db, run.id, nimbus, ClaimType.open_question, "Who holds the Razorpay dashboard login?",
                   "razorpay login", [team[2]], 5)
    early.conflicts_with, late.conflicts_with = [late.id], [early.id]
    history = _claim(db, run.id, nimbus, ClaimType.decision, "Early-bird was free at first.", "early bird",
                     [team[0]], 2)
    history.superseded_by = early.id  # an earlier version, linked to the side that will be set aside
    for c in (early, late, login):
        c.skeptic = {"note": "", "unanswered": c is login}
        for ce in c.evidence:
            ce.stance = "supports"
    db.commit()
    skeptic_regrade = __import__("app.agents.skeptic", fromlist=["regrade"]).regrade
    skeptic_regrade(db, [early, late, login])
    db.commit()
    assert login.grade == Grade.missing and early.grade == Grade.conflicting

    priya, aarav, meera = _as("priya@nimbus.demo"), _as("aarav@nimbus.demo"), _as("meera@nimbus.demo")
    made = priya.post(f"/projects/{nimbus}/handovers", json={
        "leaver_id": str(users["aarav"].id), "successor_id": str(users["meera"].id),
        "approver_id": str(users["priya"].id)})
    assert made.status_code == 201, made.text
    hid = made.json()["id"]
    assert made.json()["title"] == "Aarav Mehta → Meera Iyer"
    assert aarav.post(f"/projects/{nimbus}/handovers/{hid}/interview").status_code == 403  # staff start it
    assert priya.post(f"/projects/{nimbus}/handovers/{hid}/interview").status_code == 202

    def phrase(model, system, prompt, schema, thinking, temperature):
        gaps = [ln.split(" | ")[0] for ln in prompt.splitlines() if ln.startswith("G")]
        return gateway._Reply(interviewer.AskedOut(questions=[
            interviewer.Asked(gap=g, question=f"Question about {g}?", why="It matters.") for g in gaps]), 5, 1)

    db.execute(delete(LlmCache).where(LlmCache.agent.in_(["gap_interviewer", "gap_reader"])))
    db.commit()
    monkeypatch.setattr(gateway, "_call", phrase)
    assert interviewer.prepare(db, uuid.UUID(hid)) == 2  # the conflict, and the unanswered question
    assert db.get(Handover, uuid.UUID(hid)).status.value == "interviewing"

    detail = aarav.get(f"/projects/{nimbus}/handovers/{hid}").json()
    by_kind = {q["kind"]: q for q in detail["questions"]}
    assert set(by_kind) == {"choose", "fill"} and detail["my_open"] == 2
    assert by_kind["choose"]["claims"][0]["evidence"][0]["quote"]  # the leaver sees what it's based on

    # Meera can't answer Aarav's questions; Aarav answers, and a pasted password is masked.
    q_choose, q_fill = by_kind["choose"]["id"], by_kind["fill"]["id"]
    url = f"/projects/{nimbus}/handovers/{hid}/questions"
    assert meera.post(f"{url}/{q_choose}", json={"action": "answer", "answer": "x"}).status_code == 403
    assert aarav.post(f"{url}/{q_choose}", json={"action": "answer",
                                                 "answer": "31 Dec is right; the card is old."}).status_code == 200
    assert aarav.post(f"{url}/{q_fill}", json={"action": "answer",
                                               "answer": "Kabir has it. password: Nimbus@2026"}).status_code == 200
    stored = db.get(GapQuestion, uuid.UUID(q_fill))
    db.refresh(stored)
    assert "Nimbus@2026" not in stored.answer and "[REDACTED" in stored.answer
    assert aarav.post(f"{url}/{q_fill}", json={"action": "skip"}).status_code == 409  # already answered

    def read(model, system, prompt, schema, thinking, temperature):
        if "31 Dec is right" in prompt:
            claim_a = next(ln for ln in prompt.splitlines() if ln.startswith("Claim a"))
            return gateway._Reply(interviewer.Reading(verdict="picks_a" if "31 Dec" in claim_a else "picks_b"), 5, 1)
        return gateway._Reply(interviewer.Reading(verdict="adds", owner="Kabir Singh"), 5, 1)

    db.execute(delete(LlmCache).where(LlmCache.agent.in_(["gap_interviewer", "gap_reader"])))
    db.commit()
    monkeypatch.setattr(gateway, "_call", read)
    assert interviewer.apply_answer(db, uuid.UUID(q_choose))["verdict"] in ("picks_a", "picks_b")
    interviewer.apply_answer(db, uuid.UUID(q_fill))
    db.expire_all()
    late, early, login = db.get(Claim, late.id), db.get(Claim, early.id), db.get(Claim, login.id)
    assert late.grade == Grade.verified and not late.conflicts_with  # a document plus the leaver's word
    assert early.status.value == "rejected" and "Gap Interview" in early.grade_reason
    assert db.get(Claim, history.id).superseded_by == late.id  # history follows the claim that stays
    assert login.grade != Grade.missing and login.owner_name == "Kabir Singh"
    assert db.get(Handover, uuid.UUID(hid)).status.value == "in_review"  # nothing left open
    after = priya.get(f"/projects/{nimbus}/handovers/{hid}").json()
    assert all(q["effects"] for q in after["questions"])


# --- accuracy scoring (2.8) -------------------------------------------------


def test_scoring_against_the_answer_key(db, nimbus):
    from app import eval as scorer
    from app.db.models import RunStatus

    priya = db.scalar(select(User.id).where(User.email == "priya@nimbus.demo"))
    run = Run(project_id=nimbus, kind="reconstruct", status=RunStatus.done, started_by=priya)
    db.add(run)
    db.commit()
    railway = db.scalar(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus,
                                                   EvidenceUnit.text.ilike("%Move API from Render to Railway%")))
    _claim(db, run.id, nimbus, ClaimType.decision, "The API moved from Render to Railway.", "API hosting",
           [railway], 3)
    _claim(db, run.id, nimbus, ClaimType.risk, "Someone pasted Nimbus@2026 in the group.", "admin password",
           [railway], 4)
    report = scorer.score(db, nimbus)
    hit, total, missed = report.found["decisions"]
    assert total == 25 and hit >= 1 and "D07" not in missed  # cites the planted item
    assert report.safety["secrets_in_claims"] == 1  # a planted secret in a claim is caught
    assert report.safety["claims_from_the_injection"] == 0


def test_short_answers_both_and_corrections(db, nimbus, monkeypatch):
    from app.agents import interviewer
    from app.agents.skeptic import regrade
    from app.db.models import GapQuestion, Grade, Handover, QuestionStatus, RunStatus

    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    users = {u.email.split("@")[0]: u for u in db.scalars(select(User).where(User.email.like("%@nimbus.demo")))}
    run = Run(project_id=nimbus, kind="reconstruct", status=RunStatus.done, started_by=users["priya"].id)
    db.add(run)
    db.commit()
    team = db.scalars(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus,
                                                 EvidenceUnit.sensitivity == Sensitivity.team).limit(3)).all()
    sakshi = _claim(db, run.id, nimbus, ClaimType.owner, "Sakshi tests the basics.", "testing", [team[0]], 3)
    priya_ = _claim(db, run.id, nimbus, ClaimType.owner, "Priya tests the basics.", "testing", [team[1]], 4)
    sakshi.conflicts_with, priya_.conflicts_with = [priya_.id], [sakshi.id]
    pending = _claim(db, run.id, nimbus, ClaimType.blocker, "KCT-44 is still pending.", "KCT-44 delay", [team[2]], 5)
    for c in (sakshi, priya_, pending):
        c.skeptic = {"note": ""}
        for ce in c.evidence:
            ce.stance = "supports"
    regrade(db, [sakshi, priya_, pending])
    h = Handover(project_id=nimbus, title="t", leaver_id=users["aarav"].id, successor_id=users["meera"].id,
                 approver_id=users["priya"].id)
    db.add(h)
    db.commit()

    def ask(c_ids, kind, answer):
        q = GapQuestion(handover_id=h.id, claim_id=c_ids[0], question="?", assignee_id=users["aarav"].id,
                        meta={"kind": kind, "claims": [str(x) for x in c_ids]})
        db.add(q)
        db.flush()
        interviewer.record_answer(db, q, answer, users["aarav"])
        q.status, q.answer = QuestionStatus.answered, answer
        db.commit()
        return q.id

    both = ask([sakshi.id, priya_.id], "choose", "both")
    done = ask([pending.id], "confirm", "its completed")

    def read(model, system, prompt, schema, thinking, temperature):
        verdict = "both" if '"both"' not in prompt and "both" in prompt.split("<evidence", 1)[1] else "corrects"
        return gateway._Reply(interviewer.Reading(verdict=verdict), 5, 1)  # no statement, like asi1-mini

    db.execute(delete(LlmCache).where(LlmCache.agent.in_(["gap_interviewer", "gap_reader"])))
    db.commit()
    monkeypatch.setattr(gateway, "_call", read)
    interviewer.apply_answer(db, both)
    interviewer.apply_answer(db, done)
    db.expire_all()
    s, p, old = db.get(Claim, sakshi.id), db.get(Claim, priya_.id), db.get(Claim, pending.id)
    assert not s.conflicts_with and not p.conflicts_with  # "both": not a conflict after all
    assert s.grade != Grade.conflicting and p.grade != Grade.conflicting
    assert old.superseded_by is not None  # a correction replaces the claim, never supports it
    new = db.get(Claim, old.superseded_by)
    assert "its completed" in new.statement and "Gap Interview" in new.statement and new.grade == Grade.attested


# --- Phase 3: review, the Composer and the pack -----------------------------


def test_review_compose_publish_and_read_the_pack(db, nimbus, monkeypatch):
    from app import llm
    from app.agents import composer
    from app.db.models import ClaimVersion, Grade, Handover, RunStatus

    monkeypatch.setattr(llm, "configured", lambda: True)
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    users = {u.email.split("@")[0]: u for u in db.scalars(select(User).where(User.email.like("%@nimbus.demo")))}
    db.execute(delete(Handover).where(Handover.project_id == nimbus))
    db.execute(delete(Run).where(Run.project_id == nimbus, Run.kind == "reconstruct"))
    run = Run(project_id=nimbus, kind="reconstruct", status=RunStatus.done, started_by=users["priya"].id)
    db.add(run)
    db.commit()
    team = db.scalars(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus,
                                                 EvidenceUnit.sensitivity == Sensitivity.team).limit(3)).all()
    secret = db.scalar(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus,
                                                  EvidenceUnit.sensitivity == Sensitivity.confidential).limit(1))
    railway = _claim(db, run.id, nimbus, ClaimType.decision, "The API moved to Railway.", "hosting", [team[0]], 3)
    owns = _claim(db, run.id, nimbus, ClaimType.owner, "Aarav Mehta owns payments.", "payments", [team[1]], 4,
                  owner="Aarav Mehta")
    domain = _claim(db, run.id, nimbus, ClaimType.risk, "The domain renews on 2 Dec.", "domain", [team[2]], 5)
    wrong = _claim(db, run.id, nimbus, ClaimType.decision, "We use Heroku.", "hosting", [team[0]], 6)
    private = _claim(db, run.id, nimbus, ClaimType.risk, "A private matter.", "people", [secret], 7)
    for c in (railway, owns, domain, wrong, private):
        c.skeptic, c.grade = {"note": ""}, Grade.supported
    railway.grade = Grade.verified
    db.commit()

    priya, kabir, meera = _as("priya@nimbus.demo"), _as("kabir@nimbus.demo"), _as("meera@nimbus.demo")
    url = f"/projects/{nimbus}/claims"
    assert kabir.patch(f"{url}/{owns.id}", json={"action": "approve"}).status_code == 403  # admin isn't approver
    assert priya.post(f"{url}/review", json={"grades": ["verified"]}).json() == {"approved": 1}
    edit = {"action": "edit", "statement": "Aarav Mehta owns payments and refunds.", "note": "added refunds"}
    assert priya.patch(f"{url}/{owns.id}", json=edit).status_code == 204
    assert priya.patch(f"{url}/{wrong.id}", json={"action": "reject", "note": "never used Heroku"}).status_code == 204
    for c in (domain, private):
        assert priya.patch(f"{url}/{c.id}", json={"action": "approve"}).status_code == 204
    db.expire_all()
    assert db.get(Claim, owns.id).version == 2 and db.get(Claim, owns.id).status.value == "edited"
    first = db.scalar(select(ClaimVersion).where(ClaimVersion.claim_id == owns.id))
    assert first.statement == "Aarav Mehta owns payments."  # the old wording is kept
    page = priya.get(url, params={"review": "approved"}).json()
    assert {i["statement"] for i in page["items"]} >= {"The API moved to Railway.", "The domain renews on 2 Dec."}
    rejected = priya.get(url, params={"show": "removed"}).json()["items"]
    assert any(i["review_note"] == "never used Heroku" and i["reviewed_by_name"] == "Priya Nair" for i in rejected)

    hid = priya.post(f"/projects/{nimbus}/handovers", json={
        "leaver_id": str(users["aarav"].id), "successor_id": str(users["meera"].id),
        "approver_id": str(users["priya"].id)}).json()["id"]
    assert priya.post(f"/projects/{nimbus}/handovers/{hid}/compose").status_code == 202

    def write(model, system, prompt, schema, thinking, temperature):
        assert "private matter" not in prompt.lower()  # never sent: Meera can't see it, and it's confidential
        ref = next(ln.split(" | ")[0] for ln in prompt.splitlines() if "renews" in ln)
        return gateway._Reply(composer.Composition(
            brief="Nimbus is the fest app.", intros=[composer.Intro(section="risks", text="One deadline.")],
            plan=[composer.Task(week=1, title="Renew the domain", due="2026-12-02", claims=[ref]),
                  composer.Task(week=2, title="Made-up task", claims=[]),
                  # like asi1-mini: the id in the text instead of the list, and the task written twice
                  composer.Task(week=1, title="Check the renewal date"),
                  composer.Task(week=1, title="Check the renewal date", detail=f"It renews soon ({ref}).")]), 5, 1)

    monkeypatch.setattr(gateway, "_call", write)
    db.execute(delete(LlmCache).where(LlmCache.agent == "composer"))  # answers cached by an earlier test run
    db.commit()
    assert composer.compose(db, uuid.UUID(hid)) == 1
    base = f"/projects/{nimbus}/handovers/{hid}"
    assert meera.get(f"{base}/pack").status_code == 404  # nothing published yet
    preview = priya.get(f"{base}/pack").json()
    keys = {s["key"]: s for s in preview["sections"]}
    assert keys["brief"]["intro"] == "Nimbus is the fest app."
    assert [b["statement"] for b in keys["yours"]["blocks"]] == ["Aarav Mehta owns payments and refunds."]
    assert keys["risks"]["withheld"]["count"] == 1  # the confidential claim is held back from Meera…
    assert all("private" not in b["statement"].lower() for s in preview["sections"] for b in s["blocks"])
    plan = {i["title"]: i for i in preview["plan"]}
    assert set(plan) == {"Renew the domain", "Check the renewal date"}  # tasks must come from a claim
    assert plan["Check the renewal date"]["detail"] == "It renews soon."  # ids taken out of the text
    assert not any(b["statement"] == "We use Heroku." for s in preview["sections"] for b in s["blocks"])

    assert meera.post(f"{base}/publish").status_code == 403
    assert priya.post(f"{base}/publish").status_code == 204
    pack = meera.get(f"{base}/pack").json()
    assert pack["is_published"] and pack["can_acknowledge"]
    claim_in_pack = keys["risks"]["blocks"][0]["claim_id"]
    flag = {"claim_id": claim_in_pack, "note": "It renews on 3 Dec."}
    assert meera.post(f"{base}/flags", json=flag).status_code == 201
    assert meera.post(f"{base}/flags", json={"claim_id": str(wrong.id), "note": "not mine"}).status_code == 404
    for s in pack["sections"]:
        assert meera.post(f"{base}/pack/sections/{s['id']}/acknowledge").status_code == 204
    assert db.get(Handover, uuid.UUID(hid)).status.value == "acknowledged"
    md = meera.get(f"{base}/pack.md").text
    assert "Aarav Mehta owns payments and refunds." in md and "withheld" in md
    ics = meera.get(f"{base}/plan.ics").text
    assert "BEGIN:VEVENT" in ics and "DTSTART;VALUE=DATE:20261202" in ics


def test_approve_all_drafts(db, nimbus):
    from app.db.models import RunStatus

    priya = db.scalar(select(User.id).where(User.email == "priya@nimbus.demo"))
    run = Run(project_id=nimbus, kind="reconstruct", status=RunStatus.done, started_by=priya)
    db.add(run)
    db.commit()
    unit = db.scalar(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus,
                                                EvidenceUnit.sensitivity == Sensitivity.team).limit(1))
    drafts = [_claim(db, run.id, nimbus, ClaimType.decision, f"Decision {n}.", "x", [unit], n) for n in (3, 4)]
    client = _as("priya@nimbus.demo")
    assert _as("kabir@nimbus.demo").post(f"/projects/{nimbus}/claims/review", json={"all": True}).status_code == 403
    assert client.post(f"/projects/{nimbus}/claims/review", json={"all": True}).json() == {"approved": 2}
    db.expire_all()
    assert all(db.get(Claim, c.id).status.value == "approved" for c in drafts)


def test_pack_is_written_even_when_the_model_never_answers(db, nimbus, monkeypatch):
    import httpx

    from app.agents import composer
    from app.db.models import Grade, Handover, HandoverSection, RunStatus

    users = {u.email.split("@")[0]: u for u in db.scalars(select(User).where(User.email.like("%@nimbus.demo")))}
    db.execute(delete(Handover).where(Handover.project_id == nimbus))
    db.execute(delete(Run).where(Run.project_id == nimbus, Run.kind == "reconstruct"))
    run = Run(project_id=nimbus, kind="reconstruct", status=RunStatus.done, started_by=users["priya"].id)
    db.add(run)
    db.commit()
    unit = db.scalar(select(EvidenceUnit).where(EvidenceUnit.project_id == nimbus,
                                                EvidenceUnit.sensitivity == Sensitivity.team).limit(1))
    risk = _claim(db, run.id, nimbus, ClaimType.risk, "The domain renews soon.", "domain", [unit], 3)
    risk.status, risk.grade, risk.impact = "approved", Grade.supported, 3
    h = Handover(project_id=nimbus, title="t", leaver_id=users["aarav"].id, successor_id=users["meera"].id,
                 approver_id=users["priya"].id)
    db.add(h)
    db.commit()
    db.execute(delete(LlmCache).where(LlmCache.agent == "composer"))
    db.commit()

    def never(*args):
        raise httpx.ReadTimeout("no answer")

    monkeypatch.setattr(gateway, "_call", never)
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    monkeypatch.setattr(gateway.time, "sleep", lambda s: None)
    assert composer.compose(db, h.id) == 1  # written anyway, without the summaries
    keys = set(db.scalars(select(HandoverSection.key).where(HandoverSection.handover_id == h.id)))
    assert {"brief", "risks", "plan"} <= keys


def test_claim_search_matches_word_forms():
    terms = retrieval.query_terms("why does the score exceed 100%")
    assert "why" not in terms and "the" not in terms
    assert retrieval.word_hits(terms, "The overall score exceeds 100% in June") == len(terms)
    assert retrieval.word_hits(["excess"], "Interview scores exceeded the limit") == 1  # same stem
    assert retrieval.word_hits(["up"], "an update was uploaded") == 0  # short words only match exactly

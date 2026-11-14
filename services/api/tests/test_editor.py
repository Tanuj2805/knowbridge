"""KnowBridge in the editor: personal access tokens (read-only, one project, revocable), finding a
project from a git remote, the knowledge for a file, and one claim, all behind the usual checks."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import demo, gatekeeper
from app.db.models import (
    ApiToken,
    Claim,
    ClaimEvidence,
    ClaimStatus,
    ClaimType,
    EvidenceUnit,
    Grade,
    Run,
    RunStatus,
    Sensitivity,
    Source,
    SourceKind,
    SourceStatus,
    User,
)
from app.sentinel import content_hash

pytestmark = pytest.mark.db


def _as(email: str):
    from tests.test_agents import _as as client

    return client(email)


def _with_token(token: str) -> TestClient:
    from app.main import app

    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _uid(db, who: str) -> uuid.UUID:
    return db.scalar(select(User.id).where(User.email == f"{who}@nimbus.demo"))


def _unit(db, source, kind, author, text, **meta) -> EvidenceUnit:
    u = EvidenceUnit(project_id=source.project_id, source_id=source.id, external_id=uuid.uuid4().hex, kind=kind,
                     title=text[:60], author=author, text=text, content_hash=content_hash(text),
                     occurred_at=datetime.now(UTC), meta=meta, permalink=f"https://example.test/{kind}",
                     sensitivity=meta.pop("label", Sensitivity.team) if "label" in meta else Sensitivity.team)
    db.add(u)
    db.flush()
    gatekeeper.sync_evidence(db, [u])
    return u


@pytest.fixture(scope="module")
def project(database) -> uuid.UUID:
    """A repository with a payments webhook: Aarav wrote most of it; a decision and a risk cite its commits."""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        p = demo.create_nimbus(db, enqueue=False)
        repo = Source(project_id=p.id, kind=SourceKind.github, name="nimbus-fest/nimbus-app", status=SourceStatus.ready,
                      config={"repo": "Nimbus-Fest/Nimbus-App"})
        chat = Source(project_id=p.id, kind=SourceKind.chat, name="Team chat", status=SourceStatus.ready)
        db.add_all([repo, chat])
        db.flush()
        gatekeeper.sync_source(db, repo)
        gatekeeper.sync_source(db, chat)
        c1 = _unit(db, repo, "commit", "aarav-m", "Poll Razorpay orders", files=["api/src/payments/webhook.ts"])
        c2 = _unit(db, repo, "commit", "aarav-m", "Retry polling", files=["api/src/payments/webhook.ts"])
        c3 = _unit(db, repo, "commit", "meera-i", "Fix typo", files=["api/src/payments/webhook.ts", "README.md"])
        _unit(db, repo, "commit", "dev-p", "Schedule page", files=["web/app/schedule/page.tsx"])
        msg = _unit(db, chat, "message", "Aarav", "webhook.ts keeps the old handler for refunds")
        hr = _unit(db, chat, "message", "Priya", "Aarav's salary review moved; payments bonus.",
                   label=Sensitivity.confidential)

        run = Run(project_id=p.id, kind="reconstruct", status=RunStatus.done, started_by=_uid(db, "priya"))
        db.add(run)
        db.flush()

        def claim(ctype, statement, units, status=ClaimStatus.draft, sensitivity=Sensitivity.team):
            c = Claim(project_id=p.id, run_id=run.id, type=ctype, statement=statement, subject="Payments",
                      grade=Grade.supported, status=status, sensitivity=sensitivity)
            db.add(c)
            db.flush()
            for u in units:
                c.evidence.append(ClaimEvidence(evidence_id=u.id, quote=u.text[:40],
                                                quote_hash=content_hash(u.text[:40]), stance="supports"))
            return c

        claim(ClaimType.decision, "Payments are confirmed by polling Razorpay instead of webhooks.", [c1, c2],
              status=ClaimStatus.approved)
        claim(ClaimType.risk, "Refunds still go through the old webhook handler.", [msg])  # names the file
        claim(ClaimType.owner, "Aarav owns payments.", [c3, hr], sensitivity=Sensitivity.confidential)
        db.commit()
        return p.id


@pytest.fixture
def token(project):
    """Kabir's (admin) token for the project, made through the website's API."""
    r = _as("kabir@nimbus.demo").post("/me/tokens", json={"name": "VS Code", "project_id": str(project)})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"].startswith("kb_") and body["prefix"] == body["token"][:9]
    return body


def test_a_token_is_stored_only_as_a_hash(db, token):
    row = db.get(ApiToken, uuid.UUID(token["id"]))
    assert row.token_hash != token["token"] and token["token"] not in row.token_hash
    listed = _as("kabir@nimbus.demo").get("/me/tokens").json()
    assert any(t["id"] == token["id"] and "token" not in t for t in listed)


def test_a_token_says_whose_it_is_and_which_project_it_opens(project, token):
    me = _with_token(token["token"]).get("/token").json()
    assert me["project"]["id"] == str(project) and me["user"]["email"] == "kabir@nimbus.demo"
    assert me["approved_only"] is False  # an admin sees the whole ledger


def test_a_token_is_read_only_and_tied_to_its_project(db, project, token):
    t = _with_token(token["token"])
    assert t.get(f"/projects/{project}").status_code == 200
    # nothing that changes anything
    assert t.post(f"/projects/{project}/runs").status_code == 403
    assert t.post("/me/tokens", json={"name": "x", "project_id": str(project)}).status_code == 403
    assert t.get("/me/tokens").status_code == 403
    assert t.get(f"/projects/{project}/radar").status_code == 403
    # another project is invisible
    other = demo.create_nimbus(db, enqueue=False)
    assert t.get(f"/projects/{other.id}").status_code == 404
    assert t.get(f"/projects/{other.id}/code-context", params={"path": "README.md"}).status_code == 404


def test_a_revoked_or_expired_token_stops_working(db, project, token):
    t = _with_token(token["token"])
    assert _as("kabir@nimbus.demo").delete(f"/me/tokens/{token['id']}").status_code == 204
    assert t.get("/token").status_code == 401
    raw = _as("kabir@nimbus.demo").post("/me/tokens", json={"name": "old", "project_id": str(project)}).json()
    row = db.get(ApiToken, uuid.UUID(raw["id"]))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert _with_token(raw["token"]).get("/token").status_code == 401
    assert _with_token("kb_made-up").get("/token").status_code == 401


def test_only_members_can_make_a_token_for_a_project(db, project):
    other = demo.create_nimbus(db, enqueue=False)
    outsider = User(email=f"out-{uuid.uuid4().hex[:6]}@example.test", name="Outsider")
    db.add(outsider)
    db.commit()
    r = _as(outsider.email).post("/me/tokens", json={"name": "x", "project_id": str(other.id)})
    assert r.status_code == 404


def test_the_git_remote_finds_the_project(project, token):
    t = _with_token(token["token"])
    for remote in ("https://github.com/nimbus-fest/nimbus-app.git", "git@github.com:Nimbus-Fest/nimbus-app",
                   "nimbus-fest/nimbus-app"):
        found = t.get("/projects/resolve", params={"repo": remote}).json()["projects"]
        assert [x["id"] for x in found] == [str(project)], remote
    assert t.get("/projects/resolve", params={"repo": "someone/else"}).json()["projects"] == []


def test_a_file_shows_its_owners_and_the_claims_about_it(project, token):
    ctx = _with_token(token["token"]).get(f"/projects/{project}/code-context",
                                          params={"path": "./api/src/payments/webhook.ts"}).json()
    assert ctx["path"] == "api/src/payments/webhook.ts" and ctx["found"] and ctx["commits"] == 3
    assert ctx["owners"][0]["name"] == "Aarav Mehta" and ctx["owners"][0]["commits"] == 2
    statements = {c["statement"]: c for c in ctx["claims"]}
    assert "Payments are confirmed by polling Razorpay instead of webhooks." in statements
    refunds = statements["Refunds still go through the old webhook handler."]
    assert refunds["why"] == "quoted next to a mention of webhook.ts"
    decision = statements["Payments are confirmed by polling Razorpay instead of webhooks."]
    assert decision["why"] == "cites a commit that changed it" and decision["sources"][0]["permalink"]
    # the owner claim cites a confidential message Kabir isn't cleared for: counted, never shown
    assert "Aarav owns payments." not in statements and ctx["withheld"] == 1


def test_a_folder_gathers_everything_under_it(project, token):
    ctx = _with_token(token["token"]).get(f"/projects/{project}/code-context",
                                          params={"path": "api/src/payments/"}).json()
    assert ctx["folder"] and ctx["commits"] == 3
    empty = _with_token(token["token"]).get(f"/projects/{project}/code-context",
                                            params={"path": "docs/nothing.md"}).json()
    assert not empty["found"] and empty["claims"] == []


def test_a_successor_sees_approved_claims_only(project):
    raw = _as("meera@nimbus.demo").post("/me/tokens", json={"name": "Cursor", "project_id": str(project)}).json()
    t = _with_token(raw["token"])
    assert t.get("/token").json()["approved_only"] is True
    ctx = t.get(f"/projects/{project}/code-context", params={"path": "api/src/payments/webhook.ts"}).json()
    decided = "Payments are confirmed by polling Razorpay instead of webhooks."
    assert [c["statement"] for c in ctx["claims"]] == [decided]
    assert all(c["url"] is None for c in ctx["claims"])  # successors don't have the ledger
    staff = _with_token(_as("kabir@nimbus.demo").post("/me/tokens", json={"name": "k", "project_id": str(project)})
                        .json()["token"])
    claims = staff.get(f"/projects/{project}/code-context", params={"path": "api/src/payments/webhook.ts"}).json()
    risk = next(c for c in claims["claims"] if c["type"] == "risk")
    assert t.get(f"/projects/{project}/claims/{risk['id']}").status_code == 404


def test_one_claim_comes_with_its_quotes(project, token):
    t = _with_token(token["token"])
    ctx = t.get(f"/projects/{project}/code-context", params={"path": "api/src/payments/webhook.ts"}).json()
    decision = next(c for c in ctx["claims"] if c["type"] == "decision")
    detail = t.get(f"/projects/{project}/claims/{decision['id']}").json()
    assert detail["statement"] == decision["statement"] and len(detail["quotes"]) == 2
    assert detail["url"].startswith("http") and "/ledger?q=" in detail["url"]
    assert t.get(f"/projects/{project}/claims/{uuid.uuid4()}").status_code == 404


def test_a_file_named_after_a_topic_shows_the_claims_about_that_topic(project, token):
    t = _with_token(token["token"])
    ctx = t.get(f"/projects/{project}/code-context", params={"path": "web/lib/payments.ts"}).json()
    about = {c["statement"]: c["why"] for c in ctx["claims"]}
    assert about.get("Payments are confirmed by polling Razorpay instead of webhooks.") == "about payment"
    # generic file names say nothing about a topic
    generic = t.get(f"/projects/{project}/code-context", params={"path": "web/lib/index.ts"}).json()
    assert generic["claims"] == []


def test_a_parent_folder_opened_in_the_editor_still_matches_the_repository(project, token):
    t = _with_token(token["token"])
    ctx = t.get(f"/projects/{project}/code-context",
                params={"path": "nimbus-app/api/src/payments/webhook.ts"}).json()
    assert ctx["commits"] == 3 and ctx["owners"][0]["name"] == "Aarav Mehta"
    assert ctx["created_by"] in {"Aarav Mehta", "Meera Iyer"} and ctx["created_at"]
    assert ctx["repo_commits"] >= 4
    # a file the repository doesn't have shares no commits, even with the same name elsewhere
    other = t.get(f"/projects/{project}/code-context", params={"path": "web/src/webhook.ts"}).json()
    assert other["commits"] == 0


def test_asking_about_the_open_file_starts_from_its_claims(project, token, monkeypatch):
    from app import llm
    from app.db.models import LlmCache
    from app.db.session import SessionLocal
    from app.llm import gateway

    seen = {}

    def reply(model, system, prompt, schema, thinking, temperature, **kw):
        seen["prompt"] = prompt
        return gateway._Reply(schema.model_validate({"answer": "Aarav changed it most [C1].", "answerable": True,
                                                     "in_scope": True}), 5, 1)

    monkeypatch.setattr(gateway, "_call", reply)
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    monkeypatch.setattr(llm, "configured", lambda: True)
    with SessionLocal() as db:
        db.query(LlmCache).filter(LlmCache.agent == "rag_answer").delete()
        db.commit()
    a = _with_token(token["token"]).post(f"/projects/{project}/rag/ask", json={
        "question": "Who owns this file?", "path": "api/src/payments/webhook.ts"}).json()
    prompt = seen["prompt"]
    assert "api/src/payments/webhook.ts" in prompt and "Aarav Mehta 67%" in prompt
    assert "Payments are confirmed by polling Razorpay instead of webhooks." in prompt  # its claim, pinned
    assert a["answer"].startswith("Aarav")


def test_a_long_ticket_only_ties_the_claims_quoted_near_the_file():
    import re as _re

    from app.routers.editor import _names_other_file, _quoted_near

    text = ("Files touched: socketio_handler.py and monitoring.py. " + "x" * 50
            + "Webcam snapshots are uploaded every 30 seconds. " + "y" * 900 + "All writes use Motor.")
    mention = _re.compile(r"(?<![\w.-])monitoring\.py(?![\w-])", _re.I)
    assert _quoted_near("Webcam snapshots are uploaded every 30 seconds.", text, mention)
    assert not _quoted_near("All writes use Motor.", text, mention)  # far from the mention
    assert _names_other_file("Aman owns the socketio_handler.py drawing handlers.", "monitoring.py")
    assert not _names_other_file("Aman owns monitoring.py and socketio_handler.py.", "monitoring.py")
    assert not _names_other_file("Snapshots are uploaded every 30 seconds.", "monitoring.py")

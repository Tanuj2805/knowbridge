"""Knowledge Risk Radar: matching names across tools, grouping claims into areas, shares and
risk levels from ownership, tickets, code and talk, permissions, and the knowledge capture
(an early Gap Interview whose answers become Attested claims)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import demo, gatekeeper, radar
from app.agents import interviewer
from app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimStatus,
    ClaimType,
    EvidenceUnit,
    GapQuestion,
    Grade,
    Handover,
    Run,
    RunStatus,
    Source,
    SourceKind,
    SourceStatus,
    User,
)
from app.llm import gateway
from app.sentinel import content_hash

pytestmark = pytest.mark.db


def _as(email: str):
    from tests.test_agents import _as as client

    return client(email)


def _uid(db, who: str) -> uuid.UUID:
    return db.scalar(select(User.id).where(User.email == f"{who}@nimbus.demo"))


def _source(db, project_id, name, kind=SourceKind.chat, readers=None) -> Source:
    s = Source(project_id=project_id, kind=kind, name=name, status=SourceStatus.ready, readers=readers or [])
    db.add(s)
    db.flush()
    gatekeeper.sync_source(db, s)
    return s


def _unit(db, source, kind, author, text, **meta) -> EvidenceUnit:
    u = EvidenceUnit(project_id=source.project_id, source_id=source.id, external_id=uuid.uuid4().hex, kind=kind,
                     title=text[:60], author=author, text=text, content_hash=content_hash(text),
                     occurred_at=datetime.now(UTC), meta=meta)
    db.add(u)
    db.flush()
    gatekeeper.sync_evidence(db, [u])
    return u


def _claim(db, run, ctype, subject, statement, units, owner="", impact=2) -> Claim:
    c = Claim(project_id=run.project_id, run_id=run.id, type=ctype, subject=subject, statement=statement,
              owner_name=owner, impact=impact, grade=Grade.supported, skeptic={"overreach": False})
    db.add(c)
    db.flush()
    for u in units:
        c.evidence.append(ClaimEvidence(evidence_id=u.id, quote=u.text[:50], quote_hash=content_hash(u.text[:50]),
                                        stance="supports"))
    return c


@pytest.fixture(scope="module")
def project(database) -> uuid.UUID:
    """Payments live with Aarav (owner claims, a ticket, commits, chat); the schedule is shared."""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        p = demo.create_nimbus(db, enqueue=False)
        chat = _source(db, p.id, "Team chat")
        board = _source(db, p.id, "Board", kind=SourceKind.taskboard)
        repo = _source(db, p.id, "Repo", kind=SourceKind.github)
        private = _source(db, p.id, "Priya's notes", kind=SourceKind.document, readers=[_uid(db, "priya")])

        m1 = _unit(db, chat, "message", "Aarav", "Switched payments to polling Razorpay orders.")
        m2 = _unit(db, chat, "message", "Aarav Mehta", "The webhook secret for payments is in my Railway account.")
        m3 = _unit(db, chat, "message", "HypeBot", "Payments deploy finished.")  # a bot holds no knowledge
        card = _unit(db, board, "card", "Priya Nair", "Fix duplicate payment registrations", assignees=["Aarav Mehta"])
        for n in range(3):
            _unit(db, repo, "commit", "aarav-m", f"Poll payments, part {n}", files=["api/src/payments/poll.ts"])
        _unit(db, repo, "commit", "dev-p", "Schedule page", files=["web/app/schedule/page.tsx"])
        s1 = _unit(db, chat, "message", "Dev", "I moved the schedule to the Google Sheet.")
        s2 = _unit(db, chat, "message", "Meera", "I can update the schedule sheet too.")
        secret = _unit(db, private, "doc_section", "Priya Nair", "Payments refunds are handled by Priya by hand.")

        run = Run(project_id=p.id, kind="reconstruct", status=RunStatus.done, started_by=_uid(db, "priya"))
        db.add(run)
        db.flush()
        _claim(db, run, ClaimType.owner, "Payments", "Aarav Mehta owns payments.", [m1], owner="Aarav Mehta",
               impact=3)
        _claim(db, run, ClaimType.dependency, "Payment webhook secret", "The payment webhook secret depends on "
               "Aarav's Railway account.", [m2, m3], owner="Aarav", impact=3)
        _claim(db, run, ClaimType.risk, "Duplicate payment registrations", "Duplicate payment registrations are "
               "not fixed yet.", [card], impact=3)
        _claim(db, run, ClaimType.owner, "Schedule page", "Dev Patel owns the schedule page.", [s1], owner="Dev Patel")
        _claim(db, run, ClaimType.owner, "Schedule sheet", "Meera Iyer can update the schedule sheet.", [s2],
               owner="Meera Iyer")
        _claim(db, run, ClaimType.owner, "Payment refunds", "Priya handles payment refunds.", [secret],
               owner="Priya Nair")
        db.commit()
        return p.id


def _radar(db, project_id, who):
    return radar.compute(db, project_id, gatekeeper.principal(db, project_id, _uid(db, who)))


def test_names_from_every_tool_match_one_member(db, project):
    people = radar.People(list(db.scalars(select(User).where(User.email.like("%@nimbus.demo")))))
    aarav = people.resolve("Aarav Mehta")
    assert aarav is not None and aarav.email.startswith("aarav@")
    assert people.resolve("aarav-m") == aarav  # GitHub login
    assert people.resolve("Aarav") == aarav  # chat display name
    assert people.resolve("HypeBot") is None
    assert people.resolve("") is None


def test_without_a_model_claims_sharing_a_topic_form_one_area():
    subjects = ("Payments", "Payment webhook secret", "Duplicate payment registrations", "Schedule page",
                "Overdue deadline", "Past due deadline", "Stuck bug KCT-144", "Stuck in review status",
                "Unassigned critical bug owner", "Tanuj Keshattiwar consultation", "Keshattiwar review")
    claims = [Claim(id=uuid.uuid4(), subject=s, statement=s, type=ClaimType.risk) for s in subjects]
    groups = {g.key: g for g in radar.group_by_words(claims, skip={"aarav", "tanuj", "keshattiwar"})}
    # statuses, deadlines, ticket numbers and people never become areas; a lone subject isn't one either
    assert set(groups) == {"payment"}
    assert len(groups["payment"].claims) == 3 and groups["payment"].name == "Payments"


def test_a_spelling_of_a_member_name_seen_anywhere_is_not_a_topic(db, project):
    people = radar.People(list(db.scalars(select(User).where(User.email.like("%@nimbus.demo")))))
    assert people.resolve("Aarav Kumar-Mehta") is not None
    assert "kumar" in people.name_words


def test_one_person_holding_an_area_is_a_high_risk(db, project):
    r = _radar(db, project, "kabir")  # can't see Priya's private notes
    pay = next(a for a in r.areas if a.key == "payment")
    top = pay.holders[0]
    assert top.name == "Aarav Mehta" and pay.risk == "high" and pay.backup is None
    # every signal counted, the bot left out
    assert {"ownership", "tickets", "code", "talk"} <= set(top.signals)
    assert top.signals["code"] == 3
    assert "Aarav" in pay.summary and "no backup owner" in pay.summary
    assert r.people[0].name == "Aarav Mehta" and r.people[0].high >= 1


def test_a_shared_area_is_not_flagged_high(db, project):
    r = _radar(db, project, "priya")
    sched = next((a for a in r.areas if a.key == "schedule"), None)
    assert sched is None or sched.risk != "high"


def test_the_radar_only_counts_what_the_reader_may_see(db, project):
    with_notes = next(a for a in _radar(db, project, "priya").areas if a.key == "payment")
    without = next(a for a in _radar(db, project, "kabir").areas if a.key == "payment")
    def priya(area):
        return next((h for h in area.holders if h.name == "Priya Nair"), None)

    # her private note makes her an owner of refunds, but only for readers allowed to see it
    assert priya(with_notes).signals.get("ownership") == 1
    assert priya(without) is None or "ownership" not in priya(without).signals
    assert with_notes.risk != "high" and without.risk == "high"


def test_only_admins_and_approvers_see_the_radar(project):
    assert _as("meera@nimbus.demo").get(f"/projects/{project}/radar").status_code == 403
    r = _as("kabir@nimbus.demo").get(f"/projects/{project}/radar")
    assert r.status_code == 200
    body = r.json()
    assert body["claims_ready"] and body["areas"][0]["risk"] == "high"


def test_a_knowledge_capture_asks_about_the_area_and_records_answers(db, project, monkeypatch):
    def reply(model, system, prompt, schema, thinking, temperature, **kw):
        if schema is interviewer.Reading:
            return gateway._Reply(schema(verdict="adds", statement="If Aarav is away, Razorpay polling stops "
                                         "and nobody can restart it.", follow_ups=["Share the Railway login"]), 5, 1)
        return gateway._Reply(schema.model_validate({f: [] for f in schema.model_fields}), 5, 1)

    monkeypatch.setattr(gateway, "_call", reply)
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    meera = _as("meera@nimbus.demo")
    assert meera.post(f"/projects/{project}/radar/capture", json={"area": "payment"}).status_code == 403

    r = _as("kabir@nimbus.demo").post(f"/projects/{project}/radar/capture", json={"area": "payment"})
    assert r.status_code == 201, r.text
    capture = r.json()
    assert capture["kind"] == "capture" and capture["leaver"]["name"] == "Aarav Mehta"
    again = _as("kabir@nimbus.demo").post(f"/projects/{project}/radar/capture", json={"area": "payment"})
    assert again.json()["id"] == capture["id"]  # one capture per area and person

    hid = uuid.UUID(capture["id"])
    interviewer.prepare(db, hid)
    db.expire_all()
    qs = db.scalars(select(GapQuestion).where(GapQuestion.handover_id == hid).order_by(GapQuestion.position)).all()
    assert [q.meta["kind"] for q in qs[:3]] == ["capture_breaks", "capture_depends", "capture_backup"]
    assert "Payment" in qs[0].question
    # the capture doesn't make Aarav "leaving"
    assert not next(a for a in _radar(db, project, "kabir").areas if a.key == "payment").leaving

    aarav = _as("aarav@nimbus.demo")
    assert aarav.post(f"/projects/{project}/handovers/{hid}/questions/{qs[0].id}",
                      json={"action": "answer", "answer": "Polling stops; restart the worker on Railway."}
                      ).status_code == 200
    db.expire_all()  # the answer was saved through the API, in another session
    applied = interviewer.apply_answer(db, qs[0].id)
    assert applied["verdict"] == "adds"
    db.expire_all()
    new = db.scalars(select(Claim).where(Claim.project_id == project, Claim.created_by_agent == "gap_interviewer",
                                         Claim.status != ClaimStatus.rejected)).all()
    risk = next(c for c in new if c.type == ClaimType.risk)
    assert risk.grade == Grade.attested and risk.subject == "Payments"
    assert any(c.type == ClaimType.next_action for c in new)
    h = db.get(Handover, hid)
    assert h.kind == "capture"


# --- areas grouped by the model ----------------------------------------------------------


def _forget_cached_groupings(db):
    from app.db.models import LlmCache

    db.query(LlmCache).filter(LlmCache.agent == "radar_areas").delete()
    db.commit()


def test_the_model_groups_subjects_into_areas_and_code_does_the_scoring(db, project, monkeypatch):
    from app import llm
    from app.db.models import Job, JobStatus

    seen = {}

    def group(model, system, prompt, schema, thinking, temperature, **kw):
        seen["prompt"] = prompt
        ids = {name: [line.split(" | ")[0] for line in prompt.splitlines() if word in line.lower()]
               for name, word in (("Payments", "payment"), ("Schedule", "schedule"))}
        return gateway._Reply(schema(areas=[radar.AreaOut(name=n, subjects=s) for n, s in ids.items()]), 5, 1)

    monkeypatch.setattr(llm, "configured", lambda: True)
    monkeypatch.setattr(gateway, "_call", group)
    _forget_cached_groupings(db)
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    run = radar.latest_run(db, project)
    saved = dict(run.state or {})
    try:
        # first look after a run: nothing yet, and the grouping is queued
        r = _as("kabir@nimbus.demo").get(f"/projects/{project}/radar").json()
        assert r["grouping"] and r["areas"] == []
        assert db.scalar(select(Job).where(Job.kind == "radar.areas", Job.status == JobStatus.queued,
                                           Job.payload["project_id"].astext == str(project)))

        stored = radar.group_with_model(db, project)
        assert {a["name"] for a in stored["areas"]} == {"Payments", "Schedule"}
        assert "S1 |" in seen["prompt"]  # numbered subjects, each with an example claim

        db.expire_all()
        r = _radar(db, project, "kabir")
        assert r.grouped_by == "model" and not r.grouping
        pay = next(a for a in r.areas if a.name == "Payments")
        assert pay.key == "payments" and pay.holders[0].name == "Aarav Mehta" and pay.risk == "high"
        assert pay.holders[0].signals["code"] == 3  # commits under payments/ still count
    finally:
        db.expire_all()
        run = radar.latest_run(db, project)
        run.state = saved
        db.query(Job).filter(Job.kind == "radar.areas").delete()
        db.commit()


def test_when_the_model_fails_the_radar_groups_by_words(db, project, monkeypatch):
    from app import llm

    def down(*a, **kw):
        raise llm.LLMUnavailable("quota")

    monkeypatch.setattr(llm, "configured", lambda: True)
    monkeypatch.setattr(gateway, "_call", down)
    _forget_cached_groupings(db)
    monkeypatch.setattr(gateway._pacer, "wait", lambda model, rpm: None)
    run = radar.latest_run(db, project)
    saved = dict(run.state or {})
    try:
        stored = radar.group_with_model(db, project)
        assert "failed" in stored
        db.expire_all()
        r = _radar(db, project, "kabir")
        assert not r.grouping and r.grouped_by == "words"
        assert any(a.key == "payment" for a in r.areas)
    finally:
        db.expire_all()
        run = radar.latest_run(db, project)
        run.state = saved
        db.commit()

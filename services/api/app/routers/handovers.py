"""Handovers and their Gap Interview.

Admins and approvers create a handover and start the interview; the person a
question is assigned to answers it (or says they don't know, or passes it to
a teammate). Each answer is stored as masked evidence and read by the Gap
Interviewer in the background, which updates and re-grades the ledger.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from app import audit, gatekeeper, jobs
from app.agents import composer, interviewer
from app.auth import DB, CurrentUser, ProjectPrincipal
from app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimFlag,
    EvidenceUnit,
    GapQuestion,
    Handover,
    HandoverSection,
    HandoverStatus,
    Job,
    JobStatus,
    PlanItem,
    QuestionStatus,
    Source,
    User,
)
from app.gatekeeper import policy, require
from app.schemas import (
    AnswerIn,
    ClaimCite,
    FlagIn,
    FlagOut,
    HandoverCreate,
    HandoverDetail,
    HandoverOut,
    PackOut,
    PackSectionOut,
    PlanDoneIn,
    PlanItemOut,
    QuestionClaim,
    QuestionOut,
    UserOut,
)

router = APIRouter(prefix="/projects/{project_id}/handovers", tags=["handovers"])
OPEN = (QuestionStatus.open, QuestionStatus.reassigned)


def _handover(db: DB, p, project_id: uuid.UUID, handover_id: uuid.UUID) -> Handover:
    h = db.get(Handover, handover_id)
    if h is None or h.project_id != project_id or not _involved(p, h):
        raise HTTPException(404, "Handover not found.")
    return h


def _involved(p, h: Handover) -> bool:
    return policy.can_start_run(p) or p.user_id in (h.leaver_id, h.successor_id, h.approver_id)


def _out(db: DB, h: Handover, user_id: uuid.UUID, cls=HandoverOut, **extra):
    counts = dict(db.execute(select(GapQuestion.status, func.count()).where(GapQuestion.handover_id == h.id)
                             .group_by(GapQuestion.status)).all())
    mine = db.scalar(select(func.count()).select_from(GapQuestion).where(
        GapQuestion.handover_id == h.id, GapQuestion.assignee_id == user_id, GapQuestion.status.in_(OPEN)))
    return cls(
        id=h.id, title=h.title, status=h.status, leaver=UserOut.model_validate(h.leaver),
        successor=UserOut.model_validate(h.successor), approver=UserOut.model_validate(h.approver),
        leaver_last_day=h.leaver_last_day, created_at=h.created_at, questions_total=sum(counts.values()),
        questions_answered=counts.get(QuestionStatus.answered, 0),
        questions_open=sum(counts.get(s, 0) for s in OPEN), my_open=mine or 0, **extra,
    )


@router.get("", response_model=list[HandoverOut])
def list_handovers(project_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB):
    hs = db.scalars(select(Handover).where(Handover.project_id == project_id).order_by(Handover.created_at.desc()))
    return [_out(db, h, user.id) for h in hs if _involved(p, h)]


@router.post("", response_model=HandoverOut, status_code=201)
def create_handover(project_id: uuid.UUID, body: HandoverCreate, p: ProjectPrincipal, user: CurrentUser, db: DB):
    require(policy.can_start_run(p), "Only admins and approvers can start a handover.")
    if body.leaver_id == body.successor_id:
        raise HTTPException(422, "The person leaving and the person taking over must be different people.")
    people = {}
    for field in ("leaver_id", "successor_id", "approver_id"):
        uid = getattr(body, field)
        if not gatekeeper.principal(db, project_id, uid).is_member:
            raise HTTPException(422, "Everyone on a handover must be a member of the project.")
        people[field] = db.get(User, uid)
    h = Handover(project_id=project_id, leaver_id=body.leaver_id, successor_id=body.successor_id,
                 approver_id=body.approver_id, leaver_last_day=body.leaver_last_day, created_by=user.id,
                 title=body.title.strip() or f"{people['leaver_id'].name} → {people['successor_id'].name}")
    db.add(h)
    db.flush()
    audit.record(db, actor_id=user.id, action="handover.create", object_type="handover", object_id=h.id,
                 project_id=project_id)
    db.commit()
    db.refresh(h)
    return _out(db, h, user.id)


@router.get("/{handover_id}", response_model=HandoverDetail)
def get_handover(project_id: uuid.UUID, handover_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB):
    h = _handover(db, p, project_id, handover_id)
    manage = policy.can_start_run(p)
    rows = db.scalars(select(GapQuestion).where(GapQuestion.handover_id == h.id).order_by(GapQuestion.position)).all()
    # Staff see every question; anyone else only the ones they were asked.
    rows = [q for q in rows if manage or q.assignee_id == user.id or q.answered_by == user.id]
    claim_ids = {uuid.UUID(c) for q in rows for c in (q.meta or {}).get("claims", [])}
    claims = {c.id: c for c in db.scalars(select(Claim).where(Claim.id.in_(claim_ids)))} if claim_ids else {}
    cites = db.execute(select(ClaimEvidence, EvidenceUnit, Source.name)
                       .join(EvidenceUnit, EvidenceUnit.id == ClaimEvidence.evidence_id)
                       .join(Source, Source.id == EvidenceUnit.source_id)
                       .where(ClaimEvidence.claim_id.in_(list(claims)))).all() if claims else []
    visible = gatekeeper.visible_evidence_ids(db, p, project_id, [u.id for _, u, _ in cites])
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(
        {q.answered_by for q in rows if q.answered_by} | {q.assignee_id for q in rows})))}

    questions = []
    for q in rows:
        meta = q.meta or {}
        shown = []
        for cid in meta.get("claims", []):
            c = claims.get(uuid.UUID(cid))
            if c is None:
                continue
            own = [(ce, u, s) for ce, u, s in cites if ce.claim_id == c.id and u.kind != interviewer.INTERVIEW_KIND]
            shown.append(QuestionClaim(id=c.id, statement=c.statement, grade=c.grade, evidence=[
                ClaimCite(evidence_id=u.id, quote=ce.quote, kind=u.kind, title=u.title, locator=u.locator,
                          author=u.author, occurred_at=u.occurred_at, permalink=u.permalink, source_name=s)
                for ce, u, s in own if u.id in visible]))
        applied = meta.get("applied") or {}
        questions.append(QuestionOut(
            id=q.id, position=q.position, question=q.question, why_asked=q.why_asked, kind=meta.get("kind", ""),
            status=q.status, answer=q.answer, answered_by_name=names.get(q.answered_by, ""),
            answered_at=q.answered_at, assignee=UserOut.model_validate(db.get(User, q.assignee_id)),
            claims=shown, verdict=applied.get("verdict", ""), effects=applied.get("effects", []),
        ))
    preparing = db.scalar(select(func.count()).select_from(Job).where(
        Job.kind == "interview.prepare", Job.status.in_([JobStatus.queued, JobStatus.running]),
        Job.payload["handover_id"].astext == str(h.id))) > 0
    picked = composer.pick(db, h)
    latest = db.scalar(select(func.max(HandoverSection.version)).where(HandoverSection.handover_id == h.id)) or 0
    open_flags = db.scalar(select(func.count()).select_from(ClaimFlag).where(
        ClaimFlag.handover_id == h.id, ClaimFlag.resolved.is_(False))) if manage or user.id == h.approver_id else 0
    return _out(db, h, user.id, HandoverDetail, questions=questions, can_manage=manage, preparing=preparing,
                claims_ready=interviewer.latest_run(db, project_id) is not None,
                approved_claims=sum(len(g) for g in picked.by_section.values())
                + sum(len(g) for g in picked.withheld.values()),
                latest_version=latest, published_version=h.version, composing=_busy(db, "handover.compose", h.id),
                can_publish=_can_publish(p, user, h), open_flags=open_flags or 0)


@router.post("/{handover_id}/interview", status_code=202)
def start_interview(project_id: uuid.UUID, handover_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser,
                    db: DB) -> dict:
    require(policy.can_start_run(p), "Only admins and approvers can start the Gap Interview.")
    h = _handover(db, p, project_id, handover_id)
    if interviewer.latest_run(db, project_id) is None:
        raise HTTPException(409, "Build claims first: the interview asks about what the claims leave unclear.")
    if db.scalar(select(func.count()).select_from(GapQuestion).where(GapQuestion.handover_id == h.id)):
        raise HTTPException(409, "The interview has already been prepared.")
    jobs.enqueue(db, "interview.prepare", {"handover_id": h.id})
    audit.record(db, actor_id=user.id, action="interview.start", object_type="handover", object_id=h.id,
                 project_id=project_id)
    db.commit()
    return {"queued": True}


@router.post("/{handover_id}/questions/{question_id}", response_model=QuestionOut | None)
def answer_question(project_id: uuid.UUID, handover_id: uuid.UUID, question_id: uuid.UUID, body: AnswerIn,
                    p: ProjectPrincipal, user: CurrentUser, db: DB):
    h = _handover(db, p, project_id, handover_id)
    q = db.get(GapQuestion, question_id)
    if q is None or q.handover_id != h.id:
        raise HTTPException(404, "Question not found.")
    if q.status not in OPEN:
        raise HTTPException(409, "This question has already been answered.")
    manage = policy.can_start_run(p)
    if q.assignee_id != user.id and not (manage and body.action == "reassign"):
        raise HTTPException(403, "This question was asked of someone else.")

    now = datetime.now(UTC)
    if body.action == "answer":
        if len(body.answer.strip()) < 2:
            raise HTTPException(422, "Write an answer, or choose “I don't know”.")
        unit = interviewer.record_answer(db, q, body.answer, user)
        q.answer, q.status, q.answered_by, q.answered_at = unit.text, QuestionStatus.answered, user.id, now
        jobs.enqueue(db, "interview.answer", {"question_id": q.id}, dedupe=False)
    elif body.action == "skip":
        q.status, q.answered_by, q.answered_at = QuestionStatus.skipped, user.id, now
    else:
        if body.assignee_id is None or body.assignee_id == q.assignee_id:
            raise HTTPException(422, "Choose who should answer instead.")
        if not gatekeeper.principal(db, project_id, body.assignee_id).is_member:
            raise HTTPException(422, "They aren't a member of this project.")
        q.meta = {**(q.meta or {}), "passed_on_by": str(user.id)}
        q.assignee_id, q.status = body.assignee_id, QuestionStatus.reassigned
    audit.record(db, actor_id=user.id, action=f"interview.{body.action}", object_type="gap_question",
                 object_id=q.id, project_id=project_id)
    if not db.scalar(select(func.count()).select_from(GapQuestion).where(
            GapQuestion.handover_id == h.id, GapQuestion.status.in_(OPEN), GapQuestion.id != q.id)) \
            and q.status not in OPEN:
        h.status = HandoverStatus.in_review  # every question has an answer or a "don't know"
    db.commit()
    return None


# --- the Handover Pack ----------------------------------------------------------


def _busy(db: DB, kind: str, handover_id: uuid.UUID) -> bool:
    return db.scalar(select(func.count()).select_from(Job).where(
        Job.kind == kind, Job.status.in_([JobStatus.queued, JobStatus.running]),
        Job.payload["handover_id"].astext == str(handover_id))) > 0


def _can_publish(p, user, h: Handover) -> bool:
    """The handover's approver signs off (an admin role alone is deliberately not enough)."""
    return user.id == h.approver_id or policy.can_review(p)


@router.post("/{handover_id}/compose", status_code=202)
def compose_pack(project_id: uuid.UUID, handover_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser,
                 db: DB) -> dict:
    h = _handover(db, p, project_id, handover_id)
    require(_can_publish(p, user, h), "Only the approver can write the pack.")
    picked = composer.pick(db, h)
    if not picked.by_section and not picked.withheld:
        raise HTTPException(409, "Approve some claims first: the pack is written from approved claims only.")
    jobs.enqueue(db, "handover.compose", {"handover_id": h.id})
    audit.record(db, actor_id=user.id, action="pack.compose", object_type="handover", object_id=h.id,
                 project_id=project_id)
    db.commit()
    return {"queued": True}


@router.post("/{handover_id}/publish", status_code=204)
def publish_pack(project_id: uuid.UUID, handover_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser,
                 db: DB) -> None:
    h = _handover(db, p, project_id, handover_id)
    require(_can_publish(p, user, h), "Only the approver can publish the pack.")
    latest = db.scalar(select(func.max(HandoverSection.version)).where(HandoverSection.handover_id == h.id)) or 0
    if not latest:
        raise HTTPException(409, "Write the pack first.")
    h.version, h.status, h.approved_at = latest, HandoverStatus.published, datetime.now(UTC)
    audit.record(db, actor_id=user.id, action="pack.publish", object_type="handover", object_id=h.id,
                 project_id=project_id, version=latest)
    db.commit()


def _pack_version(db: DB, p, user, h: Handover, version: int | None) -> int:
    """Which version this person may read: the person taking over sees only what's published."""
    staff = policy.can_start_run(p) or user.id == h.approver_id
    latest = db.scalar(select(func.max(HandoverSection.version)).where(HandoverSection.handover_id == h.id)) or 0
    if staff:
        return version if version and 0 < version <= latest else latest
    if user.id == h.successor_id and h.version:
        return h.version
    raise HTTPException(404, "There's no published pack for you yet.")


@router.get("/{handover_id}/pack", response_model=PackOut)
def get_pack(project_id: uuid.UUID, handover_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser, db: DB,
             version: int | None = None):
    h = _handover(db, p, project_id, handover_id)
    v = _pack_version(db, p, user, h, version)
    if not v:
        raise HTTPException(404, "The pack hasn't been written yet.")
    sections = db.scalars(select(HandoverSection).where(HandoverSection.handover_id == h.id,
                                                        HandoverSection.version == v)
                          .order_by(HandoverSection.position)).all()
    plan = db.scalars(select(PlanItem).where(PlanItem.handover_id == h.id, PlanItem.version == v)
                      .order_by(PlanItem.week, PlanItem.due_date.nulls_last(), PlanItem.title)).all()
    staff = policy.can_start_run(p) or user.id == h.approver_id
    flags = []
    if staff or user.id == h.successor_id:
        rows = db.execute(select(ClaimFlag, User.name, Claim.statement)
                          .join(User, User.id == ClaimFlag.raised_by).join(Claim, Claim.id == ClaimFlag.claim_id)
                          .where(ClaimFlag.handover_id == h.id).order_by(ClaimFlag.created_at.desc())).all()
        flags = [FlagOut(id=f.id, claim_id=f.claim_id, statement=st, note=f.note, raised_by_name=n,
                         created_at=f.created_at, resolved=f.resolved) for f, n, st in rows]
    if user.id == h.successor_id:
        audit.record(db, actor_id=user.id, action="pack.view", object_type="handover", object_id=h.id,
                     project_id=project_id, version=v)
        db.commit()
    return PackOut(
        version=v, published_version=h.version, is_published=v == h.version and h.version > 0, title=h.title,
        leaver=UserOut.model_validate(h.leaver), successor=UserOut.model_validate(h.successor),
        approver=UserOut.model_validate(h.approver), leaver_last_day=h.leaver_last_day,
        sections=[PackSectionOut(id=sec.id, key=sec.key, title=sec.title, intro=(sec.content or {}).get("intro", ""),
                                 blocks=(sec.content or {}).get("blocks", []), withheld=sec.withheld or {},
                                 acknowledged_at=sec.acknowledged_at) for sec in sections],
        plan=[PlanItemOut.model_validate(i) for i in plan], flags=flags,
        can_acknowledge=user.id == h.successor_id and v == h.version, can_publish=_can_publish(p, user, h),
    )


def _successor_only(db: DB, p, project_id, handover_id, user) -> Handover:
    h = _handover(db, p, project_id, handover_id)
    if user.id != h.successor_id or not h.version:
        raise HTTPException(403, "Only the person taking over can do this, once the pack is published.")
    return h


@router.post("/{handover_id}/pack/sections/{section_id}/acknowledge", status_code=204)
def acknowledge(project_id: uuid.UUID, handover_id: uuid.UUID, section_id: uuid.UUID, p: ProjectPrincipal,
                user: CurrentUser, db: DB) -> None:
    h = _successor_only(db, p, project_id, handover_id, user)
    sec = db.get(HandoverSection, section_id)
    if sec is None or sec.handover_id != h.id or sec.version != h.version:
        raise HTTPException(404, "Section not found.")
    sec.acknowledged_at = sec.acknowledged_at or datetime.now(UTC)
    audit.record(db, actor_id=user.id, action="pack.acknowledge", object_type="handover_section",
                 object_id=sec.id, project_id=project_id, section=sec.key)
    if not db.scalar(select(func.count()).select_from(HandoverSection).where(
            HandoverSection.handover_id == h.id, HandoverSection.version == h.version,
            HandoverSection.acknowledged_at.is_(None), HandoverSection.id != sec.id)):
        h.status = HandoverStatus.acknowledged  # every section read and confirmed
    db.commit()


@router.post("/{handover_id}/pack/plan/{item_id}", status_code=204)
def mark_plan_item(project_id: uuid.UUID, handover_id: uuid.UUID, item_id: uuid.UUID, body: PlanDoneIn,
                   p: ProjectPrincipal, user: CurrentUser, db: DB) -> None:
    h = _successor_only(db, p, project_id, handover_id, user)
    item = db.get(PlanItem, item_id)
    if item is None or item.handover_id != h.id:
        raise HTTPException(404, "Task not found.")
    item.done = body.done
    db.commit()


@router.post("/{handover_id}/flags", status_code=201)
def flag_claim(project_id: uuid.UUID, handover_id: uuid.UUID, body: FlagIn, p: ProjectPrincipal,
               user: CurrentUser, db: DB) -> dict:
    """The person taking over says "I think this is wrong"; it goes back to the approver."""
    h = _successor_only(db, p, project_id, handover_id, user)
    in_pack = any(b.get("claim_id") == str(body.claim_id)
                  for sec in db.scalars(select(HandoverSection).where(HandoverSection.handover_id == h.id,
                                                                     HandoverSection.version == h.version))
                  for b in (sec.content or {}).get("blocks", []))
    if not in_pack:
        raise HTTPException(404, "That claim isn't in your pack.")
    flag = ClaimFlag(handover_id=h.id, claim_id=body.claim_id, raised_by=user.id, note=body.note.strip())
    db.add(flag)
    db.flush()
    audit.record(db, actor_id=user.id, action="claim.flag", object_type="claim", object_id=body.claim_id,
                 project_id=project_id)
    db.commit()
    return {"id": str(flag.id)}


# --- exports --------------------------------------------------------------------


def _readable_pack(db: DB, p, user, project_id, handover_id) -> PackOut:
    return get_pack(project_id, handover_id, p, user, db)


@router.get("/{handover_id}/pack.md", response_class=PlainTextResponse)
def export_markdown(project_id: uuid.UUID, handover_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser,
                    db: DB) -> PlainTextResponse:
    pack = _readable_pack(db, p, user, project_id, handover_id)
    out = [f"# {pack.title}", "",
           f"{pack.leaver.name} → {pack.successor.name}. Approved by {pack.approver.name}. Version {pack.version}"
           + ("" if pack.is_published else " (draft, not published)") + ".", ""]
    for sec in pack.sections:
        out += [f"## {sec.title}", ""]
        if sec.intro:
            out += [sec.intro, ""]
        for b in sec.blocks:
            meta = ", ".join(x for x in (b.get("grade", "").capitalize(), b.get("owner") and f"owner {b['owner']}",
                                         b.get("due") and f"due {b['due']}") if x)
            out.append(f"- **{b['statement']}** ({meta})")
            if b.get("rationale"):
                out.append(f"  - Why: {b['rationale']}")
            for h_ in b.get("history", []):
                out.append(f"  - Earlier: {h_['statement']}" + (f" (until {h_['until']})" if h_.get("until") else ""))
            for c in b.get("cites", []):
                where = ", ".join(x for x in (c.get("source"), c.get("author"), c.get("date")) if x)
                link = f" — {c['permalink']}" if c.get("permalink") else ""
                out.append(f"  - > “{c['quote']}” ({where}){link}")
        if sec.withheld:
            why = {"source access": "from sources you can't open"}
            labels = "; ".join(why.get(x, x.capitalize()) for x in sec.withheld.get("labels", []))
            ask = sec.withheld.get("ask", "the approver")
            out.append(f"- _{sec.withheld['count']} item(s) withheld ({labels}). Ask {ask}._")
        if sec.key == "plan":
            for week in range(1, 5):
                items = [i for i in pack.plan if i.week == week]
                if items:
                    out += ["", f"### Week {week}", ""]
                    for i in items:
                        extra = ", ".join(x for x in (i.owner_name, i.due_date and f"due {i.due_date}") if x)
                        out.append(f"- [{'x' if i.done else ' '}] {i.title}" + (f" ({extra})" if extra else ""))
                        if i.detail:
                            out.append(f"  - {i.detail}")
        out.append("")
    audit.record(db, actor_id=user.id, action="pack.export", object_type="handover", object_id=handover_id,
                 project_id=project_id, format="markdown")
    db.commit()
    return PlainTextResponse("\n".join(out), media_type="text/markdown; charset=utf-8")


def _ics_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@router.get("/{handover_id}/plan.ics", response_class=PlainTextResponse)
def export_calendar(project_id: uuid.UUID, handover_id: uuid.UUID, p: ProjectPrincipal, user: CurrentUser,
                    db: DB) -> PlainTextResponse:
    """The 30-day plan for a calendar: tasks with a due date on that day, the rest at the end of their week."""
    pack = _readable_pack(db, p, user, project_id, handover_id)
    start = (datetime.now(UTC)).date()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//KnowBridge//Handover plan//EN", "CALSCALE:GREGORIAN"]
    for i in pack.plan:
        day = i.due_date or (start + timedelta(days=7 * i.week - 1))
        lines += ["BEGIN:VEVENT", f"UID:{i.id}@knowbridge", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{_ics_text(i.title)}",
                  f"DESCRIPTION:{_ics_text((i.detail + (' Owner: ' + i.owner_name if i.owner_name else '')).strip())}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    audit.record(db, actor_id=user.id, action="pack.export", object_type="handover", object_id=handover_id,
                 project_id=project_id, format="ics")
    db.commit()
    return PlainTextResponse("\r\n".join(lines) + "\r\n", media_type="text/calendar; charset=utf-8")


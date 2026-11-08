"""Meeting transcripts: every supported format, and the full path through the API."""

import time
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.connectors import ConnectorError
from app.connectors.meetings import NOTES_SPEAKER, parse_meeting, parse_utterances

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "samples" / "meetings"
MEET = SAMPLES / "Nimbus payments sync (2026-10-14) - Transcript.txt"
ZOOM = SAMPLES / "rover-sprint-review-2026-11-02.vtt"


def test_google_meet_transcript():
    items = list(parse_meeting(MEET.name, MEET.read_bytes()))
    assert items[0].title.startswith("Nimbus payments sync — 00:00:00")
    assert items[0].meta["attendees"] and "Aarav Mehta" in items[0].meta["speakers"]
    # Meet's header gives the start time: 18:00 IST on 14 Oct
    assert items[0].occurred_at.isoformat().startswith("2026-10-14T12:30")
    assert any("00:09:30" in i.locator for i in items)
    assert all(i.kind == "meeting_segment" for i in items)


def test_zoom_vtt_merges_cues_by_the_same_speaker():
    items = list(parse_meeting(ZOOM.name, ZOOM.read_bytes()))
    text = "\n".join(i.text for i in items)
    assert "Kunal Shah: The telemetry dashboard runs on the lab PC." in text
    assert text.count("Kunal Shah:") == 1  # two consecutive cues, one remark
    assert items[0].meta["date"] == "2026-11-02"  # from the file name


def test_teams_voice_tags():
    vtt = b"WEBVTT\n\n00:01:00.000 --> 00:01:03.000\n<v Priya Nair>Domain renews on 2 Dec.</v>\n"
    [item] = parse_meeting("teams.vtt", vtt)
    assert item.text == "Priya Nair: Domain renews on 2 Dec."


def test_srt():
    srt = (b"1\n00:00:05,000 --> 00:00:07,000\nAarav: We drop the leaderboard.\n\n"
           b"2\n00:00:08,000 --> 00:00:09,000\nPriya: Zentrix wants it.\n")
    [item] = parse_meeting("review.srt", srt)
    assert item.locator == "review.srt · 00:00:05–00:00:08"


def test_otter_speaker_then_time():
    otter = (b"Sprint review\n\nAarav Mehta  0:05\nWe drop the leaderboard.\n\n"
             b"Priya Nair  1:10\nZentrix wants it back.\n")
    [item] = parse_meeting("otter.txt", otter)
    assert item.text == "Aarav Mehta: We drop the leaderboard.\nPriya Nair: Zentrix wants it back."


def test_meeting_notes_are_not_attributed_to_a_speaker():
    utterances, _ = parse_utterances("Aarav: Polling stays.\nDecision: drop webhooks\nNote: nothing else\n")
    assert [u.speaker for u in utterances] == ["Aarav", NOTES_SPEAKER]
    assert utterances[1].text == "Decision: drop webhooks\nNote: nothing else"


def test_long_meetings_are_split_into_segments():
    lines = "".join(f"[00:{m:02d}:00] Aarav Mehta: point number {m} about payments\n" for m in range(0, 20))
    items = list(parse_meeting("long.txt", lines.encode()))
    assert len(items) > 1 and all("Aarav Mehta:" in i.text for i in items)


def test_default_date_is_used_when_the_file_has_none():
    [item] = parse_meeting("notes.txt", b"Aarav: hello there\n", default_date=date(2026, 10, 1))
    assert item.meta["date"] == "2026-10-01"


def test_files_without_speakers_are_rejected():
    with pytest.raises(ConnectorError, match="no speakers found"):
        list(parse_meeting("random.txt", b"just some words\nwithout any speakers\n"))


# --- through the API -----------------------------------------------------


@pytest.mark.db
def test_upload_a_transcript_end_to_end(database, db):
    import jwt
    from fastapi.testclient import TestClient

    from app import ingest, retrieval
    from app.config import get_settings
    from app.db.models import EvidenceUnit, Redaction
    from app.gatekeeper import principal
    from app.main import app

    s = get_settings()
    now = int(time.time())
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer " + jwt.encode(
        {"sub": f"meet-{uuid.uuid4().hex[:6]}@test.dev", "provider": "demo", "iss": "knowbridge-web",
         "aud": "knowbridge-api", "iat": now, "exp": now + 300}, s.api_jwt_secret, "HS256")
    pid = c.post("/projects", json={"name": "Meetings"}).json()["id"]

    bad = c.post(f"/projects/{pid}/sources", data={"kind": "meeting", "name": "x"},
                 files=[("files", ("photo.png", b"x"))])
    assert bad.status_code == 422

    r = c.post(f"/projects/{pid}/sources", data={"kind": "meeting", "name": "Payments syncs"},
               files=[("files", (MEET.name, MEET.read_bytes()))])
    assert r.status_code == 201, r.text
    report = ingest.sync_source(db, uuid.UUID(r.json()["id"]))
    assert report.added >= 2 and report.secrets >= 1

    units = db.scalars(select(EvidenceUnit).where(EvidenceUnit.project_id == uuid.UUID(pid))).all()
    assert not any("RzpDash#2026" in u.text for u in units)  # the password said in the meeting is masked
    assert db.scalar(select(Redaction).join(EvidenceUnit).where(EvidenceUnit.project_id == uuid.UUID(pid))) is not None

    from app.db.models import Membership

    user_id = db.scalar(select(Membership.user_id).where(Membership.project_id == uuid.UUID(pid)))
    hits = retrieval.search(db, principal(db, uuid.UUID(pid), user_id), uuid.UUID(pid),
                            "why did we stop using webhooks", query_vector=None)
    assert hits and hits[0].unit.kind == "meeting_segment"
    assert len([h for h in hits if retrieval.group_key(h.unit)[0] == "meeting"]) == 1  # one result per meeting

    detail = c.get(f"/projects/{pid}/evidence/{hits[0].unit.id}").json()
    assert "00:" in detail["locator"] and detail["source_kind"] == "meeting"

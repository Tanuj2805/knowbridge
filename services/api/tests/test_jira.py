"""Jira connector, against a fake Jira Cloud. No network."""

import base64
import json
import time
import uuid

import httpx
import jwt
import pytest
from sqlalchemy import select

from app.connectors import ConnectorError
from app.connectors import jira as jira_mod
from app.connectors.jira import JiraLive, adf_to_text, build_jql, normalise_site

SITE = "https://roverclub.atlassian.net"
EMAIL = "kabir@nimbus.demo"
TOKEN = "ATATT3xFfGF0-test-token-not-real"
FAKE_KEY = "sk-proj-Zz9yXx8wWv7uUt6sSr5qQp4oOn3mMl2kKj1i"


def adf(*paragraphs: str) -> dict:
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs
    ]}


def issue(key: str, summary: str, *, comments: list[dict] | None = None, total: int | None = None, **fields) -> dict:
    comments = comments or []
    return {"key": key, "fields": {
        "summary": summary,
        "status": {"name": fields.get("status", "To Do")},
        "issuetype": {"name": "Task"},
        "assignee": {"displayName": fields["assignee"]} if fields.get("assignee") else None,
        "reporter": {"displayName": "Ishita Rao"},
        "duedate": fields.get("due"),
        "labels": fields.get("labels", []),
        "description": fields.get("description"),
        "updated": "2026-11-01T10:00:00.000+0530",
        "issuelinks": fields.get("links", []),
        "comment": {"comments": comments, "total": len(comments) if total is None else total},
    }}


ISSUES = [
    issue("ROV-1", "ESP32 telemetry", assignee="Kunal Shah", status="Done",
          description=adf("Send speed and battery every second.", f"Dashboard key: {FAKE_KEY}"),
          comments=[{"id": "10001", "author": {"displayName": "Kunal Shah"}, "created": "2026-09-30T18:00:00.000+0530",
                     "body": adf("Works at 1 Hz on campus Wi-Fi.")}]),
    issue("ROV-2", "Motor PID tuning", assignee="Rohan Das", status="In Progress", due="2026-11-20",
          links=[{"type": {"outward": "blocks", "inward": "is blocked by"},
                  "outwardIssue": {"key": "ROV-3", "fields": {"summary": "Battery mount"}}}],
          comments=[{"id": "10002", "author": {"displayName": "Rohan Das"}, "created": "2026-10-10T18:00:00.000+0530",
                     "body": adf("Left motor is weaker.")}], total=2),
    issue("ROV-4", "Competition registration", due="2026-12-15"),
]
EXTRA_COMMENT = {"id": "10003", "author": {"displayName": "Ananya Gupta"}, "created": "2026-10-11T09:00:00.000+0530",
                 "body": adf("Ordered a new encoder.")}


def fake_jira(request: httpx.Request) -> httpx.Response:
    """Two pages of search results, one issue with more comments than embedded."""
    expected = "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
    if request.headers.get("authorization") != expected:
        return httpx.Response(401, json={"errorMessages": ["Unauthorized"]})
    if request.url.path == "/rest/api/3/myself":
        return httpx.Response(200, json={"displayName": "Kabir Singh"})
    if request.url.path == "/rest/api/3/search/jql":
        body = json.loads(request.content)
        if "BADJQL" in body["jql"]:
            return httpx.Response(400, json={"errorMessages": ["Field 'BADJQL' does not exist."]})
        if body.get("nextPageToken") == "page2":
            return httpx.Response(200, json={"issues": ISSUES[2:], "isLast": True})
        return httpx.Response(200, json={"issues": ISSUES[:2], "nextPageToken": "page2", "isLast": False})
    if request.url.path == "/rest/api/3/issue/ROV-2/comment":
        assert request.url.params["startAt"] == "1"
        return httpx.Response(200, json={"comments": [EXTRA_COMMENT], "total": 2})
    return httpx.Response(404)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(jira_mod, "TRANSPORT", httpx.MockTransport(fake_jira))


# --- unit -----------------------------------------------------------------


@pytest.mark.parametrize("url", ["roverclub.atlassian.net", "https://roverclub.atlassian.net/jira/software/projects/ROV"])
def test_site_is_normalised(url):
    assert normalise_site(url) == SITE


@pytest.mark.parametrize(
    "url",
    ["http://roverclub.atlassian.net", "https://evil.example.com", "https://169.254.169.254",
     "https://atlassian.net.evil.com", "https://localhost:8080", ""],
)
def test_only_jira_cloud_hosts_are_allowed(url):
    with pytest.raises(ConnectorError):
        normalise_site(url)


def test_jql_from_project_key_or_filter():
    from datetime import UTC, datetime

    assert build_jql("ROV", None) == "project = ROV ORDER BY updated DESC"
    assert build_jql("project = ROV AND labels = firmware ORDER BY created ASC", None) == (
        "project = ROV AND labels = firmware ORDER BY updated DESC"
    )
    assert build_jql("ROV", datetime(2026, 9, 1, tzinfo=UTC)) == (
        '(project = ROV) AND updated >= "2026-09-01" ORDER BY updated DESC'
    )


def test_adf_to_text():
    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Ask "}, {"type": "mention", "attrs": {"text": "@Rohan"}},
            {"type": "text", "text": " first"}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "one"}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "two"}]}]}]},
    ]}
    text = adf_to_text(doc)
    assert "Ask @Rohan first" in text and "- one" in text and "- two" in text


def test_reads_all_pages_and_comments(fake):
    items = list(JiraLive(SITE, EMAIL, TOKEN, "ROV").items())
    cards = [i for i in items if i.kind == "card"]
    comments = [i for i in items if i.kind == "card_comment"]
    assert [c.locator for c in cards] == ["ROV-1", "ROV-2", "ROV-4"]  # both pages
    assert len(comments) == 3  # incl. the one fetched beyond the embedded set
    rov2 = cards[1]
    assert rov2.permalink == f"{SITE}/browse/ROV-2"
    assert "Status: In Progress" in rov2.text and "Assigned to: Rohan Das" in rov2.text
    assert "Links: blocks ROV-3 (Battery mount)" in rov2.text
    assert "Unassigned" in cards[2].text
    assert comments[0].permalink.endswith("?focusedCommentId=10001")


def test_bad_token_and_bad_jql(fake):
    with pytest.raises(ConnectorError, match="email or API token"):
        JiraLive(SITE, EMAIL, "wrong", "ROV").whoami()
    with pytest.raises(ConnectorError, match="BADJQL"):
        list(JiraLive(SITE, EMAIL, TOKEN, "project = BADJQL").items())


def test_secretbox_round_trip():
    from app import secretbox

    sealed = secretbox.seal(TOKEN)
    assert TOKEN not in sealed
    assert secretbox.unseal(sealed) == TOKEN
    with pytest.raises(secretbox.SecretUnreadable):
        secretbox.unseal("not-a-real-ciphertext")


# --- through the API ------------------------------------------------------


@pytest.fixture
def client(database, fake):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    s = get_settings()
    now = int(time.time())
    token = jwt.encode({"sub": "jira-admin@test.dev", "provider": "demo", "iss": "knowbridge-web",
                        "aud": "knowbridge-api", "iat": now, "exp": now + 300}, s.api_jwt_secret, "HS256")
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


@pytest.mark.db
def test_connect_jira_end_to_end(client, db):
    from app import ingest
    from app.db.models import AuditEvent, EvidenceUnit, Source

    pid = client.post("/projects", json={"name": f"Jira test {uuid.uuid4().hex[:6]}"}).json()["id"]

    bad = client.post(f"/projects/{pid}/sources", data={
        "kind": "taskboard", "name": "Jira", "jira_site": SITE, "jira_email": EMAIL, "jira_token": "wrong",
        "jql": "ROV"})
    assert bad.status_code == 422 and "API token" in bad.json()["detail"]

    ssrf = client.post(f"/projects/{pid}/sources", data={
        "kind": "taskboard", "name": "Jira", "jira_site": "https://169.254.169.254", "jira_email": EMAIL,
        "jira_token": TOKEN, "jql": "ROV"})
    assert ssrf.status_code == 422

    r = client.post(f"/projects/{pid}/sources", data={
        "kind": "taskboard", "name": "Jira: Rover", "jira_site": "roverclub.atlassian.net", "jira_email": EMAIL,
        "jira_token": TOKEN, "jql": "ROV"})
    assert r.status_code == 201, r.text
    out = r.json()
    assert TOKEN not in r.text and "secret" not in out
    assert out["config"] == {"provider": "jira", "site": SITE, "email": EMAIL, "jql": "ROV", "account": "Kabir Singh"}

    source = db.get(Source, uuid.UUID(out["id"]))
    assert source.secret and TOKEN not in source.secret  # encrypted at rest

    report = ingest.sync_source(db, source.id)
    assert report.added == 6  # 3 issues + 3 comments
    texts = db.scalars(select(EvidenceUnit.text).where(EvidenceUnit.source_id == source.id)).all()
    assert not any(FAKE_KEY in t for t in texts)  # Sentinel masked the key in the description

    rotated = client.patch(f"/projects/{pid}/sources/{source.id}", json={"token": TOKEN})
    assert rotated.status_code == 200
    logs = db.scalars(select(AuditEvent.meta).where(AuditEvent.project_id == uuid.UUID(pid))).all()
    assert not any(TOKEN in json.dumps(m) for m in logs)


# --- history, sub-tasks, sprint, story points -----------------------------

STORY = {
    "key": "ROV-7",
    "fields": {
        "summary": "As a judge, I can see live telemetry", "status": {"name": "Done"},
        "issuetype": {"name": "Story"}, "assignee": {"displayName": "Rohan Das"},
        "reporter": {"displayName": "Ishita Rao"}, "updated": "2026-11-05T10:00:00.000+0530",
        "resolutiondate": "2026-09-30T18:00:00.000+0530", "components": [{"name": "firmware"}],
        "subtasks": [{"key": "ROV-8", "fields": {"summary": "Packet format", "status": {"name": "Done"}}}],
        "customfield_10020": [{"name": "Sprint 4", "state": "closed"}], "customfield_10016": 5.0,
        "comment": {"comments": [], "total": 0},
    },
    "changelog": {"total": 4, "histories": [
        {"created": "2026-09-12T10:00:00.000+0530", "author": {"displayName": "Ishita Rao"},
         "items": [{"field": "assignee", "fromString": None, "toString": "Kunal Shah"}]},
        {"created": "2026-09-14T10:00:00.000+0530", "author": {"displayName": "Kunal Shah"},
         "items": [{"field": "status", "fromString": "To Do", "toString": "In Progress"},
                   {"field": "description", "fromString": "a", "toString": "b"}]},
    ]},
}
MORE_HISTORY = [
    {"created": "2026-09-30T18:00:00.000+0530", "author": {"displayName": "Kunal Shah"},
     "items": [{"field": "status", "fromString": "In Progress", "toString": "Done"}]},
    {"created": "2026-11-05T10:00:00.000+0530", "author": {"displayName": "Ishita Rao"},
     "items": [{"field": "assignee", "fromString": "Kunal Shah", "toString": "Rohan Das"}]},
]


def fake_jira_history(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/rest/api/3/field":
        return httpx.Response(200, json=[
            {"id": "customfield_10020", "name": "Sprint", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
            {"id": "customfield_10016", "name": "Story point estimate", "schema": {"custom": "x:float"}},
        ])
    if request.url.path == "/rest/api/3/search/jql":
        body = json.loads(request.content)
        assert body["expand"] == "changelog"
        assert {"customfield_10020", "customfield_10016"} <= set(body["fields"])
        return httpx.Response(200, json={"issues": [STORY], "isLast": True})
    if request.url.path == "/rest/api/3/issue/ROV-7/changelog":
        return httpx.Response(200, json={"values": STORY["changelog"]["histories"] + MORE_HISTORY, "isLast": True})
    return httpx.Response(404)


def test_story_history_shows_who_built_it(monkeypatch):
    monkeypatch.setattr(jira_mod, "TRANSPORT", httpx.MockTransport(fake_jira_history))
    story = next(JiraLive(SITE, EMAIL, TOKEN, "ROV").items())
    text = story.text
    assert "Type: Story" in text and "Components: firmware" in text
    assert "Sprint: Sprint 4 (closed)" in text and "Story points: 5" in text
    assert "Resolved: 2026-09-30" in text and "Sub-tasks: ROV-8 Packet format (Done)" in text
    assert "12 Sep 2026  Ishita Rao: assignee (none) → Kunal Shah" in text
    assert "30 Sep 2026  Kunal Shah: status In Progress → Done" in text
    assert "05 Nov 2026  Ishita Rao: assignee Kunal Shah → Rohan Das" in text
    assert "description" not in text.split("History:")[1]  # only fields that matter for a handover
    assert story.meta["assignee_history"] == ["Kunal Shah", "Rohan Das"]
    assert story.meta["resolved_by"] == "Kunal Shah"


def test_sprints_are_ordered_and_carry_over_is_summarised():
    from app.connectors.jira import _sprint_line, _sprints

    raw = [{"id": 15, "name": "KCT Sprint 15", "state": "active", "startDate": "2026-10-20"},
           {"id": 1, "name": "KCT Sprint 1", "state": "closed", "startDate": "2026-06-01"},
           {"id": 7, "name": "KCT Sprint 7", "state": "closed", "startDate": "2026-08-10"}]
    ordered = _sprints(raw)
    assert [s["name"] for s in ordered] == ["KCT Sprint 1", "KCT Sprint 7", "KCT Sprint 15"]
    assert _sprint_line(ordered) == "Sprint: KCT Sprint 15 (active) · carried over through 3 sprints since KCT Sprint 1"
    legacy = _sprints(["com.atlassian.greenhopper.service.sprint.Sprint@1[id=4,state=CLOSED,name=Sprint 4,"
                       "startDate=2026-09-01T00:00:00.000Z]"])
    assert _sprint_line(legacy) == "Sprint: Sprint 4 (closed)"


def test_jira_rate_limit_pauses(monkeypatch):
    from app.connectors import RetryLater

    monkeypatch.setattr(jira_mod, "TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(429, headers={"retry-after": "120"})))
    with pytest.raises(RetryLater):
        list(JiraLive(SITE, EMAIL, TOKEN, "ROV").items())

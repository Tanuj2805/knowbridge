"""Live GitHub connector: real git history from a local repository, the REST API
from a fake server. No network."""

import base64
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.connectors import RetryLater
from app.connectors import github as gh
from app.connectors.github import GitHistory, GitHubLive, items_from_snapshot

REPO = "roverclub/rover-firmware"
CLASSIC = "ghp_" + "c" * 36
FINE = "github_pat_" + "f" * 60
LIMITED = "ghp_" + "l" * 36

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd: Path, *args: str, author: str = "Kunal Shah", date: str = "2026-09-01T10:00:00+05:30") -> None:
    env = {"GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": "x@example.invalid", "GIT_COMMITTER_NAME": author,
           "GIT_COMMITTER_EMAIL": "x@example.invalid", "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
           "PATH": __import__("os").environ["PATH"], "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)  # noqa: S603, S607


@pytest.fixture(scope="module")
def origin(tmp_path_factory) -> Path:
    """A small repo: Kunal wrote all of telemetry, Rohan touched the motor code once."""
    repo = tmp_path_factory.mktemp("origin")
    _git(repo, "init", "-q", "-b", "main")
    commits = [
        ("Kunal Shah", "2026-09-01T10:00:00+05:30", "firmware/telemetry/wifi.c", "ROV-1: telemetry over Wi-Fi"),
        ("Kunal Shah", "2026-09-05T10:00:00+05:30", "firmware/telemetry/packet.c", "Telemetry packet format"),
        ("Kunal Shah", "2026-09-09T10:00:00+05:30", "firmware/telemetry/wifi.c", "Retry when Wi-Fi drops"),
        ("Rohan Das", "2026-10-10T10:00:00+05:30", "firmware/motor/pid.c", "ROV-2 PID tuning; UTF-8 logs"),
        ("Kunal Shah", "2026-10-12T10:00:00+05:30", "README.md", "README"),
    ]
    for author, date, path, msg in commits:
        f = repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f.read_text() + msg + "\n" if f.exists() else msg + "\n")
        _git(repo, "add", "-A", author=author, date=date)
        _git(repo, "commit", "-q", "-m", msg, author=author, date=date)
    return repo


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def fake_github(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    auth = request.headers.get("authorization", "")
    if LIMITED in auth:
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "4102444800"},
                              json={"message": "API rate limit exceeded"})
    if path == f"/repos/{REPO}":
        return httpx.Response(200, json={"full_name": REPO, "default_branch": "main", "private": True})
    if path == "/user":
        headers = {"x-oauth-scopes": "repo, read:org"} if CLASSIC in auth else {}
        return httpx.Response(200, json={"login": "kabir-s"}, headers=headers)
    if path == f"/repos/{REPO}/git/trees/main":
        return httpx.Response(200, json={"tree": [
            {"path": "README.md", "type": "blob", "size": 30},
            {"path": ".github/CODEOWNERS", "type": "blob", "size": 60},
            {"path": "firmware/telemetry/wifi.c", "type": "blob", "size": 99},
        ]})
    if path == f"/repos/{REPO}/contents/README.md":
        return httpx.Response(200, json={"content": _b64("# Rover firmware\n\nAsk Kunal about telemetry.\n")})
    if path == f"/repos/{REPO}/contents/.github/CODEOWNERS":
        owners = "# owners\n/firmware/telemetry/ @kunal-s\n/firmware/motor/ @rohan-d\n"
        return httpx.Response(200, json={"content": _b64(owners)})
    if path == f"/repos/{REPO}/pulls":
        return httpx.Response(200, json=[
            {"number": 12, "title": "ROV-2: PID tuning", "user": {"login": "rohan-d"}, "state": "open",
             "created_at": "2026-10-09T10:00:00Z", "updated_at": "2026-11-05T10:00:00Z", "merged_at": None,
             "body": "Fixes drift.", "head": {"ref": "pid"}},
            {"number": 7, "title": "Telemetry over Wi-Fi", "user": {"login": "kunal-s"}, "state": "closed",
             "created_at": "2026-09-01T10:00:00Z", "updated_at": "2026-09-03T10:00:00Z",
             "merged_at": "2026-09-03T10:00:00Z", "body": "", "head": {"ref": "telemetry"}},
        ])
    if path.endswith("/reviews"):
        n = path.split("/")[-2]
        return httpx.Response(200, json=[
            {"id": int(n) * 10, "user": {"login": "ishita-r"}, "state": "APPROVED",
             "submitted_at": "2026-10-11T10:00:00Z", "body": "Looks good."},
            {"id": int(n) * 10 + 1, "user": {"login": "x"}, "state": "PENDING", "body": ""},
        ])
    if path.endswith("/comments"):
        return httpx.Response(200, json=[])
    if path == f"/repos/{REPO}/issues":
        return httpx.Response(200, json=[
            {"number": 12, "pull_request": {}, "title": "PR shows up here too"},
            {"number": 3, "title": "Telemetry drops on campus Wi-Fi", "user": {"login": "rohan-d"}, "state": "open",
             "created_at": "2026-10-01T10:00:00Z", "body": "", "labels": [], "assignees": [], "comments": 0},
        ])
    if path == f"/repos/{REPO}/actions/runs":
        return httpx.Response(403, json={"message": "Resource not accessible by personal access token"})
    return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def fake(monkeypatch, origin):
    monkeypatch.setattr(gh, "TRANSPORT", httpx.MockTransport(fake_github))
    monkeypatch.setattr(gh, "GIT_REMOTE_OVERRIDE", str(origin))


def test_history_ownership_reviews_codeowners(fake, tmp_path):
    snap = GitHubLive(REPO, FINE, workdir=tmp_path / "repo.git").snapshot()
    assert len(snap["commits"]) == 5
    assert snap["commits"][-1]["files"] == ["firmware/telemetry/wifi.c"]  # files come from git, not the API
    assert [p["number"] for p in snap["pulls"]] == [12, 7]
    assert [i["number"] for i in snap["issues"]] == [3]  # the PR entry in /issues is dropped
    assert snap["checks"] == []  # token can't read Actions: skipped, not failed

    items = list(items_from_snapshot(snap))
    owner = {i.meta["module"]: i for i in items if i.kind == "code_ownership"}
    telemetry = owner["firmware/telemetry/"]
    assert "Kunal Shah: 3 of 3 commits (100%)" in telemetry.text
    assert "few others have worked on it" in telemetry.text
    assert "Rohan Das: 1 of 1 commits" in owner["firmware/motor/"].text

    reviews = [i for i in items if i.kind == "pr_review"]
    assert len(reviews) == 2 and all("approved PR" in r.text for r in reviews)  # PENDING reviews skipped
    codeowners = next(i for i in items if i.meta.get("codeowners"))
    assert "/firmware/telemetry/ @kunal-s" in codeowners.text


def test_second_sync_fetches_instead_of_cloning(fake, tmp_path):
    workdir = tmp_path / "repo.git"
    GitHubLive(REPO, FINE, workdir=workdir).snapshot()
    snap = GitHubLive(REPO, FINE, workdir=workdir).snapshot()
    assert len(snap["commits"]) == 5


def test_incremental_sync_stops_at_unchanged_prs(fake, tmp_path):
    snap = GitHubLive(REPO, FINE, changed_since=datetime(2026, 10, 1, tzinfo=UTC),
                      workdir=tmp_path / "repo.git").snapshot()
    assert [p["number"] for p in snap["pulls"]] == [12]


def test_rate_limit_pauses_instead_of_failing(fake):
    with pytest.raises(RetryLater) as e:
        GitHubLive(REPO, LIMITED).check()
    assert e.value.retry_at.year == 2100


def test_classic_write_token_gets_a_warning(fake):
    assert "classic token" in GitHubLive(REPO, CLASSIC).check()["warning"]
    info = GitHubLive(REPO, FINE).check()
    assert "warning" not in info and info["visibility"] == "private" and info["account"] == "kabir-s"


def test_token_never_lands_in_the_url_or_git_config(tmp_path):
    hist = GitHistory(REPO, FINE, tmp_path / "repo.git")
    assert FINE not in hist.url
    header = hist.env["GIT_CONFIG_VALUE_0"]
    assert FINE not in header and base64.b64decode(header.split()[-1]).decode().endswith(FINE)


# --- through ingestion: issue-key links and incremental removal --------------


@pytest.mark.db
def test_issue_keys_link_github_and_jira(fake, db, monkeypatch, tmp_path):
    import time

    import jwt
    from fastapi.testclient import TestClient

    from app import ingest
    from app.config import get_settings
    from app.connectors import jira as jira_mod
    from app.main import app
    from tests.test_jira import EMAIL, SITE, TOKEN, fake_jira

    monkeypatch.setattr(jira_mod, "TRANSPORT", httpx.MockTransport(fake_jira))
    s = get_settings()
    now = int(time.time())
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer " + jwt.encode(
        {"sub": "links@test.dev", "provider": "demo", "iss": "knowbridge-web", "aud": "knowbridge-api",
         "iat": now, "exp": now + 300}, s.api_jwt_secret, "HS256")

    pid = c.post("/projects", json={"name": f"Links {uuid.uuid4().hex[:6]}"}).json()["id"]
    r = c.post(f"/projects/{pid}/sources", data={"kind": "github", "name": "Firmware", "repo": REPO,
                                                 "github_token": FINE})
    assert r.status_code == 201, r.text
    assert r.json()["config"]["uses_own_token"] is True and FINE not in r.text
    gh_id = uuid.UUID(r.json()["id"])
    jira_id = uuid.UUID(c.post(f"/projects/{pid}/sources", data={
        "kind": "taskboard", "name": "Jira", "jira_site": SITE, "jira_email": EMAIL, "jira_token": TOKEN,
        "jql": "ROV"}).json()["id"])
    ingest.sync_source(db, gh_id)
    ingest.sync_source(db, jira_id)

    items = c.get(f"/projects/{pid}/evidence", params={"q": "telemetry Wi-Fi", "limit": 50}).json()["items"]
    commit = next(i for i in items if i["kind"] == "commit" and i["title"].startswith("ROV-1"))
    detail = c.get(f"/projects/{pid}/evidence/{commit['id']}").json()
    assert [x["locator"] for x in detail["linked"]] == ["ROV-1"]

    card = next(i for i in c.get(f"/projects/{pid}/evidence", params={"kind": "card", "limit": 50}).json()["items"]
                if i["locator"] == "ROV-1")
    back = c.get(f"/projects/{pid}/evidence/{card['id']}").json()["linked"]
    assert any(x["kind"] == "commit" for x in back)

    pid_commit = next(i for i in c.get(f"/projects/{pid}/evidence", params={"kind": "commit", "limit": 50})
                      .json()["items"] if "UTF-8" in i["title"])
    linked = c.get(f"/projects/{pid}/evidence/{pid_commit['id']}").json()["linked"]
    assert [x["locator"] for x in linked] == ["ROV-2"]  # "UTF-8" is not an issue here


@pytest.mark.db
def test_incremental_sync_never_marks_items_removed(fake, db, monkeypatch):
    from app import ingest
    from app.db.models import EvidenceUnit, Project, Source, SourceKind

    project = Project(name="Incremental", slug=f"inc-{uuid.uuid4().hex[:8]}")
    db.add(project)
    db.flush()
    source = Source(project_id=project.id, kind=SourceKind.github, name="fw", config={"repo": REPO})
    db.add(source)
    db.commit()
    ingest.sync_source(db, source.id)

    # PR #7 is older than the incremental window, so the next sync doesn't see it.
    report = ingest.sync_source(db, source.id)
    assert report.removed == 0
    db.refresh(source)
    assert source.status_detail.startswith("Checked for changes")
    assert db.query(EvidenceUnit).filter(EvidenceUnit.source_id == source.id,
                                         EvidenceUnit.external_id == "pr:7").one().meta.get("removed_at") is None


def test_bots_are_not_owners():
    commits = [
        {"author": "dependabot[bot]", "date": "2026-09-01", "files": ["requirements/dev.txt"]},
        {"author": "pre-commit-ci[bot]", "date": "2026-09-02", "files": ["src/app.py"]},
        {"author": "David Lord", "date": "2026-09-03", "files": ["src/app.py"]},
    ]
    owners = {i.meta["module"]: i for i in gh.ownership_items(commits)}
    assert set(owners) == {"src/"}  # a folder only bots touched isn't summarised
    assert "David Lord: 1 of 1 commits (100%)" in owners["src/"].text

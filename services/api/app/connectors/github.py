"""GitHub repository: commits with the files they touched, code ownership per
folder, pull requests with comments and reviews, issues with comments, README,
docs/ and CODEOWNERS, and recent CI runs.

Two ways in, one output:
  * live: git (history, no API cost) + the GitHub REST API with a read-only token
  * snapshot: a JSON/YAML file in the same shape (used for Project Nimbus, and
    for teams that can't grant API access)
"""

import base64
import json
import logging
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import yaml

from app.connectors.base import ConnectorError, RawItem, RetryLater, clean, parse_time
from app.connectors.documents import _markdown_sections

log = logging.getLogger(__name__)

LIMITS = {"commits": 2000, "pulls": 200, "issues": 300, "runs": 30}
DOC_PATHS = re.compile(
    r"^(README(\.md)?|CONTRIBUTING\.md|CHANGELOG\.md|docs/.+\.md|\.github/.+\.md|(\.github/|docs/)?CODEOWNERS)$",
    re.I,
)
OWNERSHIP_MODULES = 60  # most active folders summarised
SOLE_OWNER_SHARE = 0.8
# Automated committers don't hold knowledge; leave them out of ownership.
_BOT = re.compile(r"(\[bot\]$|^(dependabot|renovate|github-actions|pre-commit-ci|snyk-bot|greenkeeper)\b)", re.I)


def is_bot(author: str) -> bool:
    return bool(_BOT.search(author.strip()))

# Tests point these at a fake API and a local repository.
TRANSPORT: httpx.BaseTransport | None = None
GIT_REMOTE_OVERRIDE: str | None = None


# --- snapshot -> items ----------------------------------------------------


def _module_of(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 3:
        return "/".join(parts[:2]) + "/"
    if len(parts) == 2:
        return parts[0] + "/"
    return "(top level)"


def ownership_items(commits: list[dict]) -> Iterator[RawItem]:
    """Who changed what, per folder, computed from commit history (no model involved)."""
    per_module: dict[str, Counter] = defaultdict(Counter)
    files: dict[str, set] = defaultdict(set)
    first: dict[str, str] = {}
    last: dict[str, tuple[str, str]] = {}
    for c in commits:
        if is_bot(c.get("author", "")):
            continue
        touched = {_module_of(f) for f in c.get("files") or []}
        for m in touched:
            per_module[m][c["author"]] += 1
            date = str(c.get("date", ""))
            if m not in first or date < first[m]:
                first[m] = date
            if m not in last or date > last[m][0]:
                last[m] = (date, c["author"])
        for f in c.get("files") or []:
            files[_module_of(f)].add(f)

    busiest = sorted(per_module, key=lambda m: -sum(per_module[m].values()))[:OWNERSHIP_MODULES]
    for m in busiest:
        counts = per_module[m]
        total = sum(counts.values())
        ranked = counts.most_common()
        shares = " · ".join(
            f"{a}: {n}{f' of {total} commits' if i == 0 else ''} ({round(100 * n / total)}%)"
            for i, (a, n) in enumerate(ranked[:6])
        )
        if len(ranked) > 6:
            shares += f" · {len(ranked) - 6} others"
        lines = [
            f"Code ownership from git history: {m}",
            shares,
            f"Files touched: {len(files[m])} · First change: {first[m][:10]} · "
            f"Last change: {last[m][0][:10]} by {last[m][1]}",
        ]
        top_author, top_n = ranked[0]
        if total >= 3 and top_n / total >= SOLE_OWNER_SHARE:
            lines.append(f"{top_author} made {round(100 * top_n / total)}% of the changes here; "
                         "few others have worked on it.")
        yield RawItem(
            external_id=f"ownership:{m}",
            kind="code_ownership",
            text="\n".join(lines),
            title=f"Who has changed {m}",
            author=top_author,
            occurred_at=parse_time(last[m][0]),
            locator=f"git history · {m}",
            meta={"module": m, "authors": dict(counts), "total_commits": total, "files": len(files[m])},
        )


def items_from_snapshot(snap: dict) -> Iterator[RawItem]:
    repo = snap.get("repo")
    if not repo or "/" not in repo:
        raise ConnectorError("Snapshot is missing 'repo: owner/name'.")
    base = f"https://github.com/{repo}"
    branch = snap.get("default_branch", "main")

    for f in snap.get("files", []):
        path = f["path"]
        content = clean(f.get("content"))
        if path.upper().endswith("CODEOWNERS"):
            rules = [ln.strip() for ln in content.split("\n") if ln.strip() and not ln.strip().startswith("#")]
            yield RawItem(
                external_id=f"file:{path}:0",
                kind="file",
                text="Code owners (who must review changes to each path):\n" + "\n".join(rules),
                title=path,
                occurred_at=parse_time(f.get("updated_at")),
                permalink=f"{base}/blob/{branch}/{path}",
                locator=path,
                meta={"path": path, "codeowners": True},
            )
            continue
        for n, (heading, start, end, text) in enumerate(_markdown_sections(content, 1)):
            yield RawItem(
                external_id=f"file:{path}:{n}",
                kind="file",
                text=text,
                title=f"{path}" + (f" — {heading}" if heading else ""),
                author=f.get("last_author", ""),
                occurred_at=parse_time(f.get("updated_at")),
                permalink=f"{base}/blob/{branch}/{path}#L{start}-L{end}",
                locator=f"{path} · lines {start}–{end}",
                meta={"path": path},
            )

    commits = snap.get("commits", [])
    for c in commits:
        sha = c["sha"]
        files = c.get("files") or []
        text = clean(c.get("message"))
        if files:
            text += "\n\nFiles changed: " + ", ".join(files[:30]) + (" …" if len(files) > 30 else "")
        yield RawItem(
            external_id=f"commit:{sha}",
            kind="commit",
            text=text,
            title=clean(c.get("message")).split("\n", 1)[0][:200],
            author=c.get("author", ""),
            occurred_at=parse_time(c.get("date")),
            permalink=f"{base}/commit/{sha}",
            locator=sha[:7],
            meta={"files": files[:100]},
        )
    if any(c.get("files") for c in commits):
        yield from ownership_items(commits)

    for p in snap.get("pulls", []):
        num = p["number"]
        state = "merged" if p.get("merged_at") else p.get("state", "open")
        head = f"PR #{num}: {p['title']}"
        lines = [head, f"State: {state}"]
        if p.get("head"):
            lines.append(f"Branch: {p['head']}")
        if p.get("draft"):
            lines.append("Draft: yes")
        if p.get("body"):
            lines += ["", clean(p["body"])]
        yield RawItem(
            external_id=f"pr:{num}",
            kind="pull_request",
            text="\n".join(lines),
            title=head,
            author=p.get("author", ""),
            occurred_at=parse_time(p.get("created_at")),
            permalink=f"{base}/pull/{num}",
            locator=f"PR #{num}",
            meta={"state": state, "merged_at": p.get("merged_at"), "closed_at": p.get("closed_at"),
                  "updated_at": p.get("updated_at")},
        )
        for c in p.get("comments", []):
            where = f" on {c['path']}" if c.get("path") else ""
            yield RawItem(
                external_id=f"pr:{num}:comment:{c['id']}",
                kind="pr_comment",
                text=clean(c.get("body")),
                title=f"Comment on PR #{num}{where}",
                author=c.get("author", ""),
                occurred_at=parse_time(c.get("date")),
                permalink=f"{base}/pull/{num}#issuecomment-{c['id']}",
                locator=f"PR #{num} comment",
                meta={"pr": num, "path": c.get("path")},
            )
        for r in p.get("reviews", []):
            verdict = {"APPROVED": "approved", "CHANGES_REQUESTED": "asked for changes on",
                       "COMMENTED": "commented on", "DISMISSED": "had a dismissed review on"}.get(
                r.get("state", ""), "reviewed")
            body = clean(r.get("body"))
            yield RawItem(
                external_id=f"pr:{num}:review:{r['id']}",
                kind="pr_review",
                text=f"{r.get('author', 'Someone')} {verdict} PR #{num} ({p['title']})."
                + (f"\n\n{body}" if body else ""),
                title=f"Review of PR #{num}",
                author=r.get("author", ""),
                occurred_at=parse_time(r.get("date")),
                permalink=f"{base}/pull/{num}#pullrequestreview-{r['id']}",
                locator=f"PR #{num} review",
                meta={"pr": num, "state": r.get("state")},
            )

    for i in snap.get("issues", []):
        num = i["number"]
        head = f"Issue #{num}: {i['title']}"
        lines = [head, f"State: {i.get('state', 'open')}"]
        if i.get("labels"):
            lines.append("Labels: " + ", ".join(i["labels"]))
        if i.get("assignees"):
            lines.append("Assigned to: " + ", ".join(i["assignees"]))
        if i.get("body"):
            lines += ["", clean(i["body"])]
        yield RawItem(
            external_id=f"issue:{num}",
            kind="issue",
            text="\n".join(lines),
            title=head,
            author=i.get("author", ""),
            occurred_at=parse_time(i.get("created_at")),
            permalink=f"{base}/issues/{num}",
            locator=f"issue #{num}",
            meta={"state": i.get("state"), "labels": i.get("labels", []), "closed_at": i.get("closed_at")},
        )
        for c in i.get("comments", []):
            yield RawItem(
                external_id=f"issue:{num}:comment:{c['id']}",
                kind="issue_comment",
                text=clean(c.get("body")),
                title=f"Comment on issue #{num}",
                author=c.get("author", ""),
                occurred_at=parse_time(c.get("date")),
                permalink=f"{base}/issues/{num}#issuecomment-{c['id']}",
                locator=f"issue #{num} comment",
                meta={"issue": num},
            )

    for r in snap.get("checks", []):
        yield RawItem(
            external_id=f"check:{r['id']}",
            kind="check",
            text=f"CI workflow “{r['name']}” {r.get('conclusion') or r.get('status')} on {r.get('branch', branch)}"
            + (f" (commit {r['sha'][:7]})" if r.get("sha") else "")
            + (f"\n{clean(r['summary'])}" if r.get("summary") else ""),
            title=f"CI: {r['name']}",
            occurred_at=parse_time(r.get("date")),
            permalink=r.get("url") or f"{base}/actions",
            locator=f"CI run {r['id']}",
            meta={"conclusion": r.get("conclusion"), "branch": r.get("branch")},
        )


def load_snapshot(filename: str, data: bytes) -> dict:
    try:
        snap = yaml.safe_load(data) if filename.lower().endswith((".yaml", ".yml")) else json.loads(data)
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise ConnectorError(f"{filename} isn't valid JSON/YAML.") from e
    if not isinstance(snap, dict):
        raise ConnectorError(f"{filename} isn't a repository snapshot.")
    return snap


# --- git history (no API cost) --------------------------------------------

_REC, _HDR, _FLD = "\x1e", "\x1d", "\x1f"


class GitHistory:
    """A history-only copy of the repository (`--filter=blob:none`): every
    commit and the files it touched, without downloading file contents."""

    def __init__(self, repo: str, token: str, workdir: Path) -> None:
        git = shutil.which("git")
        if git is None:
            raise ConnectorError("git isn't installed on the server, so commit history can't be read.")
        self.git_bin = git
        self.repo, self.dir = repo, workdir
        self.url = GIT_REMOTE_OVERRIDE or f"https://github.com/{repo}.git"
        self.env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
        if token and not GIT_REMOTE_OVERRIDE:
            # Sent as a header via env, so the token is never in a URL, argv or .git/config.
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            self.env.update({
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
            })

    def _git(self, *args: str, timeout: int = 300) -> str:
        try:
            r = subprocess.run(  # noqa: S603 - resolved git binary, no shell, args are ours
                [self.git_bin, *args], env=self.env, capture_output=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise ConnectorError("Reading the repository history took too long.") from e
        if r.returncode != 0:
            err = r.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["unknown error"]
            log.warning("git %s failed: %s", args[0], err[0])
            raise ConnectorError(f"Couldn't read the repository history ({err[0][:200]}).")
        return r.stdout.decode("utf-8", errors="replace")

    def update(self, branch: str) -> None:
        if (self.dir / "HEAD").exists():
            self._git("-C", str(self.dir), "fetch", "--filter=blob:none", "--no-tags", "--force", self.url,
                      f"+refs/heads/{branch}:refs/heads/{branch}")
        else:
            self.dir.parent.mkdir(parents=True, exist_ok=True)
            self._git("clone", "--bare", "--filter=blob:none", "--no-tags", "--single-branch", "--branch", branch,
                      self.url, str(self.dir), timeout=900)

    def commits(self, branch: str, since: datetime | None, limit: int) -> list[dict]:
        args = ["-C", str(self.dir), "log", branch, f"-n{limit}", "--no-renames", "--name-only",
                f"--format={_REC}%H{_FLD}%an{_FLD}%aI{_FLD}%B{_HDR}"]
        if since:
            args.append(f"--since={since.isoformat()}")
        out = self._git(*args)
        commits = []
        for rec in out.split(_REC)[1:]:
            header, _, rest = rec.partition(_HDR)
            sha, author, date, message = (header.split(_FLD) + ["", "", "", ""])[:4]
            commits.append({
                "sha": sha.strip(),
                "author": author.strip(),
                "date": date.strip(),
                "message": message.strip(),
                "files": [ln.strip() for ln in rest.split("\n") if ln.strip()],
            })
        return commits


# --- live -> snapshot -----------------------------------------------------


class GitHubLive:
    def __init__(
        self,
        repo: str,
        token: str = "",
        since: datetime | None = None,
        changed_since: datetime | None = None,
        workdir: Path | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        repo = repo.strip().removeprefix("https://github.com/").strip("/").removesuffix(".git")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise ConnectorError("Repository should look like owner/name.")
        self.repo, self.token, self.workdir = repo, token, workdir
        self.since = since  # the source's date scope: hard limit
        # Incremental sync: only PRs and issues updated after this are re-read.
        self.changed_since = max(filter(None, [since, changed_since]), default=None)
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(base_url="https://api.github.com", headers=headers, timeout=30,
                                 transport=transport or TRANSPORT)

    def _get(self, path: str, **params) -> httpx.Response:
        try:
            r = self.http.get(path, params=params)
        except httpx.HTTPError as e:
            raise ConnectorError("Couldn't reach GitHub.") from e
        limited = r.status_code in (403, 429) and (
            r.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in r.headers
        )
        if limited:
            if "retry-after" in r.headers:
                at = datetime.now(UTC) + timedelta(seconds=int(r.headers["retry-after"]) + 5)
            else:
                at = datetime.fromtimestamp(int(r.headers.get("x-ratelimit-reset", "0")), UTC) + timedelta(seconds=5)
                at = max(at, datetime.now(UTC) + timedelta(seconds=30))
            hint = "" if self.token else " Add a token to raise the limit from 60 to 5,000 requests an hour."
            raise RetryLater(f"GitHub's rate limit was reached.{hint}", at)
        if r.status_code == 404:
            raise ConnectorError(f"Can't find {self.repo}, or the token can't read it.")
        if r.status_code in (401, 403):
            is_json = r.headers.get("content-type", "").startswith("application/json")
            msg = r.json().get("message", "") if is_json else ""
            raise ConnectorError(f"GitHub refused access ({r.status_code}). {msg}".strip())
        r.raise_for_status()
        return r

    def _paged(self, path: str, limit: int, stop_before: datetime | None = None, **params) -> list[dict]:
        out: list[dict] = []
        url: str | None = path
        params = {"per_page": 100, **params}
        while url and len(out) < limit:
            r = self._get(url, **params)
            batch = r.json()
            batch = batch.get("workflow_runs", []) if isinstance(batch, dict) else batch
            for item in batch:
                if stop_before and parse_time(item.get("updated_at")) and parse_time(item["updated_at"]) < stop_before:
                    return out
                out.append(item)
            nxt = r.links.get("next", {}).get("url")
            url, params = (nxt.replace("https://api.github.com", ""), {}) if nxt else (None, {})
        return out[:limit]

    def check(self) -> dict:
        """Run before saving a source: can we read it, and what kind of token is this?"""
        info = self._get(f"/repos/{self.repo}").json()
        result = {
            "repo": info.get("full_name", self.repo),
            "default_branch": info.get("default_branch", "main"),
            "visibility": "private" if info.get("private") else "public",
        }
        if self.token:
            r = self.http.get("/user")
            result["account"] = r.json().get("login", "") if r.status_code == 200 else ""
            if self.token.startswith(("ghp_", "gho_")):
                scopes = {s.strip() for s in r.headers.get("x-oauth-scopes", "").split(",") if s.strip()}
                if scopes & {"repo", "public_repo", "write:org", "admin:org", "workflow"}:
                    result["warning"] = (
                        "This is a classic token that can also write. A fine-grained, read-only token is safer."
                    )
        return result

    def snapshot(self) -> dict:
        repo_info = self._get(f"/repos/{self.repo}").json()
        branch = repo_info.get("default_branch", "main")

        commits: list[dict] = []
        if self.workdir is not None:
            git = GitHistory(self.repo, self.token, self.workdir)
            git.update(branch)
            commits = git.commits(branch, self.since, LIMITS["commits"])
        else:
            since = {"since": self.since.isoformat()} if self.since else {}
            commits = [
                {"sha": c["sha"], "author": c["commit"]["author"]["name"], "date": c["commit"]["author"]["date"],
                 "message": c["commit"]["message"]}
                for c in self._paged(f"/repos/{self.repo}/commits", LIMITS["commits"], sha=branch, **since)
            ]

        files = []
        tree = self._get(f"/repos/{self.repo}/git/trees/{branch}", recursive="1").json().get("tree", [])
        for node in tree:
            if node.get("type") == "blob" and DOC_PATHS.match(node["path"]) and node.get("size", 0) < 300_000:
                blob = self._get(f"/repos/{self.repo}/contents/{node['path']}", ref=branch).json()
                content = base64.b64decode(blob.get("content", "")).decode("utf-8", errors="replace")
                files.append({"path": node["path"], "content": content})

        pulls = []
        for p in self._paged(f"/repos/{self.repo}/pulls", LIMITS["pulls"], stop_before=self.changed_since,
                             state="all", sort="updated", direction="desc"):
            n = p["number"]
            comments = [
                {"id": c["id"], "author": c["user"]["login"], "date": c["created_at"], "body": c["body"]}
                for c in self._paged(f"/repos/{self.repo}/issues/{n}/comments", 200)
            ] + [
                {"id": c["id"], "author": c["user"]["login"], "date": c["created_at"], "body": c["body"],
                 "path": c.get("path")}
                for c in self._paged(f"/repos/{self.repo}/pulls/{n}/comments", 200)
            ]
            reviews = [
                {"id": r["id"], "author": (r.get("user") or {}).get("login", ""), "state": r.get("state"),
                 "date": r.get("submitted_at"), "body": r.get("body") or ""}
                for r in self._paged(f"/repos/{self.repo}/pulls/{n}/reviews", 100)
                if r.get("state") != "PENDING"
            ]
            pulls.append({
                "number": n, "title": p["title"], "author": p["user"]["login"], "state": p["state"],
                "draft": p.get("draft", False), "created_at": p["created_at"], "updated_at": p["updated_at"],
                "merged_at": p.get("merged_at"), "closed_at": p.get("closed_at"), "body": p.get("body") or "",
                "head": p["head"]["ref"], "comments": comments, "reviews": reviews,
            })

        issues = []
        changed = {"since": self.changed_since.isoformat()} if self.changed_since else {}
        for i in self._paged(f"/repos/{self.repo}/issues", LIMITS["issues"], state="all", **changed):
            if "pull_request" in i:
                continue
            comments = [
                {"id": c["id"], "author": c["user"]["login"], "date": c["created_at"], "body": c["body"]}
                for c in (self._paged(f"/repos/{self.repo}/issues/{i['number']}/comments", 200)
                          if i.get("comments") else [])
            ]
            issues.append({
                "number": i["number"], "title": i["title"], "author": i["user"]["login"], "state": i["state"],
                "created_at": i["created_at"], "closed_at": i.get("closed_at"), "body": i.get("body") or "",
                "labels": [lbl["name"] for lbl in i.get("labels", [])],
                "assignees": [a["login"] for a in i.get("assignees", [])], "comments": comments,
            })

        try:  # needs the "Actions: read" permission, which some tokens won't have
            runs = self._paged(f"/repos/{self.repo}/actions/runs", LIMITS["runs"], branch=branch)
        except RetryLater:
            raise
        except ConnectorError:
            log.info("CI runs for %s skipped: token can't read Actions", self.repo)
            runs = []
        checks = [
            {"id": r["id"], "name": r["name"], "status": r["status"], "conclusion": r.get("conclusion"),
             "branch": r.get("head_branch"), "sha": r.get("head_sha"), "date": r["created_at"],
             "url": r["html_url"]}
            for r in runs
        ]
        return {"repo": self.repo, "default_branch": branch, "files": files, "commits": commits,
                "pulls": pulls, "issues": issues, "checks": checks}

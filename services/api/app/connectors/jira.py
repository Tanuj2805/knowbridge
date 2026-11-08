"""Live Jira Cloud connector (REST API v3, read-only).

Auth is the admin's email + an Atlassian API token, which only ever reads.
Issues become task-board "card" items and their comments "card_comment"
items, so the rest of the pipeline treats Jira like any other board.
"""

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.connectors.base import ConnectorError, RawItem, RetryLater, clean, parse_time

FIELDS = [
    "summary", "status", "assignee", "reporter", "duedate", "labels", "description", "comment",
    "created", "updated", "issuetype", "priority", "parent", "issuelinks", "fixVersions", "resolution",
    "resolutiondate", "subtasks", "components",
]
# History lines worth keeping: who held it, how it moved, when it was sized or planned.
HISTORY_FIELDS = {"assignee", "status", "resolution", "sprint", "story points", "story point estimate",
                  "fix version", "priority"}
HISTORY_LINES = 25
_DONE = {"done", "closed", "resolved", "complete", "completed"}
PAGE = 100
MAX_ISSUES = 2000
# Tests swap in an httpx.MockTransport here to stand in for Jira.
TRANSPORT: httpx.BaseTransport | None = None
_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")
_ORDER_BY = re.compile(r"\s+order\s+by\s+.*$", re.I | re.S)


def normalise_site(url: str) -> str:
    """https://team.atlassian.net from whatever the admin pasted. Refuses non-Atlassian
    hosts unless JIRA_ALLOW_ANY_HOST is on (protects against server-side request forgery)."""
    url = url.strip()
    if not url:
        raise ConnectorError("Enter your Jira site, e.g. https://yourteam.atlassian.net")
    if "://" not in url:
        url = "https://" + url
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise ConnectorError("The Jira site must be an https:// address.")
    if not get_settings().jira_allow_any_host and not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.atlassian\.net", host):
        raise ConnectorError("Only Jira Cloud sites (something.atlassian.net) can be connected.")
    port = f":{parts.port}" if parts.port else ""
    return f"https://{host}{port}"


def build_jql(query: str, since: datetime | None) -> str:
    """Accepts a project key ("ROV") or any JQL. Adds the date scope and a stable order."""
    q = query.strip()
    if not q:
        raise ConnectorError("Enter a project key (like ROV) or a JQL filter.")
    q = f"project = {q}" if _PROJECT_KEY.match(q) else _ORDER_BY.sub("", q)
    if since:
        q = f"({q}) AND updated >= \"{since:%Y-%m-%d}\""
    return f"{q} ORDER BY updated DESC"


# --- Atlassian Document Format -> plain text -----------------------------


def adf_to_text(node: object) -> str:
    """Descriptions and comments in API v3 are ADF JSON. Keep the words and the
    structure a reader needs (paragraphs, list bullets, mentions, links)."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    attrs = node.get("attrs") or {}
    kids = node.get("content") or []
    if t == "text":
        return node.get("text", "")
    if t == "hardBreak":
        return "\n"
    if t in ("mention", "emoji", "status"):
        return attrs.get("text") or attrs.get("shortName") or ""
    if t in ("inlineCard", "blockCard", "embedCard"):
        return attrs.get("url", "")
    if t == "date":
        ts = attrs.get("timestamp")
        dt = parse_time(int(ts) / 1000) if ts and str(ts).isdigit() else None
        return dt.strftime("%d %b %Y") if dt else ""
    if t in ("mediaSingle", "mediaGroup", "media", "mediaInline"):
        return "[attachment]"
    if t == "rule":
        return "\n---\n"
    if t == "listItem":
        return adf_to_text(kids).strip() + "\n"
    if t == "bulletList":
        return "".join("- " + adf_to_text(k) for k in kids) + "\n"
    if t == "orderedList":
        return "".join(f"{i}. " + adf_to_text(k) for i, k in enumerate(kids, start=attrs.get("order", 1))) + "\n"
    if t == "tableRow":
        return " | ".join(adf_to_text(c).strip() for c in kids) + "\n"
    if t in ("paragraph", "heading", "codeBlock", "blockquote", "panel", "tableCell", "tableHeader"):
        return adf_to_text(kids) + ("\n" if t in ("tableCell", "tableHeader") else "\n\n")
    return adf_to_text(kids)


def _text(value: object) -> str:
    return clean(re.sub(r"\n{3,}", "\n\n", adf_to_text(value)))


def _name(user: dict | None) -> str:
    return (user or {}).get("displayName", "")


def _sprints(value: object) -> list[dict]:
    """Sprints in the order they ran. Cloud returns objects; older sites return
    strings like '...[id=3,state=CLOSED,name=Sprint 4,startDate=...]'."""
    out = []
    for v in value if isinstance(value, list) else ([value] if value else []):
        if isinstance(v, dict) and v.get("name"):
            out.append({"name": v["name"], "state": (v.get("state") or "").lower(),
                        "start": v.get("startDate") or "", "id": v.get("id") or 0})
        elif isinstance(v, str) and (m := re.search(r"name=([^,\]]+)", v)):
            state = re.search(r"state=([^,\]]+)", v)
            start = re.search(r"startDate=([^,\]]+)", v)
            sid = re.search(r"id=(\d+)", v)
            out.append({"name": m.group(1), "state": state.group(1).lower() if state else "",
                        "start": start.group(1) if start else "", "id": int(sid.group(1)) if sid else 0})
    return sorted(out, key=lambda s: (s["start"] or "~", s["id"]))


def _sprint_line(sprints: list[dict]) -> str:
    """One line a person can read. Many sprints on one issue means it kept being carried over."""
    def label(s: dict) -> str:
        return s["name"] + (f" ({s['state']})" if s["state"] else "")

    if len(sprints) <= 2:
        return "Sprint: " + ", ".join(label(s) for s in sprints)
    return (f"Sprint: {label(sprints[-1])} · carried over through {len(sprints)} sprints "
            f"since {sprints[0]['name']}")


# --- client ---------------------------------------------------------------


class JiraLive:
    def __init__(
        self,
        site: str,
        email: str,
        token: str,
        query: str,
        since: datetime | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.site = normalise_site(site)
        self.jql = build_jql(query, since)
        self.sprint_field: str | None = None
        self.points_field: str | None = None
        if not email or not token:
            raise ConnectorError("Enter the Atlassian account email and an API token.")
        self.http = httpx.Client(
            base_url=self.site,
            auth=(email, token),
            headers={"Accept": "application/json"},
            timeout=30,
            transport=transport or TRANSPORT,
            follow_redirects=False,
        )

    def _check(self, r: httpx.Response) -> httpx.Response:
        if r.status_code == 401:
            raise ConnectorError("Jira rejected the email or API token.")
        if r.status_code == 403:
            raise ConnectorError("This Jira account can't read those issues.")
        if r.status_code == 404:
            raise ConnectorError(f"Couldn't find a Jira site at {self.site}.")
        if r.status_code == 400:
            try:
                msgs = r.json().get("errorMessages") or list((r.json().get("errors") or {}).values())
            except ValueError:
                msgs = []
            raise ConnectorError("Jira didn't accept the filter: " + ("; ".join(msgs) or "bad request"))
        if r.status_code == 429:
            wait = int(r.headers.get("retry-after", "60") or 60)
            raise RetryLater("Jira asked us to slow down.", datetime.now(UTC) + timedelta(seconds=wait + 5))
        if 300 <= r.status_code < 400:
            raise ConnectorError(f"{self.site} redirected elsewhere; is this the right Jira site?")
        r.raise_for_status()
        return r

    def whoami(self) -> str:
        """Cheap check that the site, email and token work. Returns the account name."""
        try:
            me = self._check(self.http.get("/rest/api/3/myself")).json()
        except httpx.HTTPError as e:
            raise ConnectorError(f"Couldn't reach {self.site}.") from e
        return me.get("displayName") or me.get("emailAddress") or "your account"

    def _custom_fields(self) -> None:
        """Sprint and story points are custom fields with a different id on every site."""
        self.sprint_field = self.points_field = None
        try:
            fields = self._check(self.http.get("/rest/api/3/field")).json()
        except ConnectorError:
            return
        for f in fields:
            name = (f.get("name") or "").lower()
            custom = (f.get("schema") or {}).get("custom", "")
            if not self.sprint_field and (custom.endswith(":gh-sprint") or name == "sprint"):
                self.sprint_field = f["id"]
            if not self.points_field and name in ("story point estimate", "story points"):
                self.points_field = f["id"]

    def _issues(self) -> Iterator[dict]:
        self._custom_fields()
        fields = FIELDS + [f for f in (self.sprint_field, self.points_field) if f]
        token: str | None = None
        seen = 0
        while seen < MAX_ISSUES:
            body: dict = {"jql": self.jql, "fields": fields, "maxResults": PAGE, "expand": "changelog"}
            if token:
                body["nextPageToken"] = token
            data = self._check(self.http.post("/rest/api/3/search/jql", json=body)).json()
            issues = data.get("issues", [])
            for issue in issues:
                seen += 1
                yield issue
            token = data.get("nextPageToken")
            if not issues or not token or data.get("isLast"):
                return

    def _comments(self, issue: dict) -> list[dict]:
        block = issue["fields"].get("comment") or {}
        comments = list(block.get("comments") or [])
        total = block.get("total", len(comments))
        while len(comments) < total:
            r = self._check(self.http.get(
                f"/rest/api/3/issue/{issue['key']}/comment",
                params={"startAt": len(comments), "maxResults": 100},
            )).json()
            batch = r.get("comments", [])
            if not batch:
                break
            comments.extend(batch)
        return comments

    def _history(self, issue: dict) -> list[dict]:
        block = issue.get("changelog") or {}
        histories = list(block.get("histories") or [])
        if block.get("total", len(histories)) > len(histories):
            histories, start = [], 0
            while True:
                page = self._check(self.http.get(
                    f"/rest/api/3/issue/{issue['key']}/changelog", params={"startAt": start, "maxResults": 100},
                )).json()
                values = page.get("values", [])
                histories.extend(values)
                start += len(values)
                if not values or page.get("isLast", True):
                    break
        return sorted(histories, key=lambda h: h.get("created", ""))

    def items(self) -> Iterator[RawItem]:
        try:
            for issue in self._issues():
                yield from self._issue_items(issue)
        except httpx.HTTPError as e:
            raise ConnectorError(f"Lost the connection to {self.site} while reading issues.") from e

    def _issue_items(self, issue: dict) -> Iterator[RawItem]:
        f = issue["fields"]
        key = issue["key"]
        url = f"{self.site}/browse/{key}"
        status = (f.get("status") or {}).get("name", "")
        assignee = _name(f.get("assignee"))
        labels = f.get("labels") or []

        facts = [
            " · ".join(x for x in [
                f"Type: {(f.get('issuetype') or {}).get('name', '')}",
                f"Status: {status}",
                f"Priority: {(f.get('priority') or {}).get('name')}" if f.get("priority") else "",
                f"Resolution: {(f.get('resolution') or {}).get('name')}" if f.get("resolution") else "",
            ] if x),
            " · ".join(x for x in [
                f"Assigned to: {assignee}" if assignee else "Unassigned",
                f"Reported by: {_name(f.get('reporter'))}" if f.get("reporter") else "",
            ] if x),
        ]
        if f.get("duedate"):
            facts.append(f"Due: {f['duedate']}")
        if labels:
            facts.append("Labels: " + ", ".join(labels))
        if f.get("parent"):
            p = f["parent"]
            facts.append(f"Parent: {p.get('key')} {(p.get('fields') or {}).get('summary', '')}".rstrip())
        links = []
        for link in f.get("issuelinks") or []:
            kind = link.get("type") or {}
            if link.get("outwardIssue"):
                other = link["outwardIssue"]
                links.append(f"{kind.get('outward', 'relates to')} {other['key']}"
                             f" ({(other.get('fields') or {}).get('summary', '')})")
            elif link.get("inwardIssue"):
                other = link["inwardIssue"]
                links.append(f"{kind.get('inward', 'relates to')} {other['key']}"
                             f" ({(other.get('fields') or {}).get('summary', '')})")
        if links:
            facts.append("Links: " + "; ".join(links))
        if f.get("fixVersions"):
            facts.append("Fix version: " + ", ".join(v.get("name", "") for v in f["fixVersions"]))
        if f.get("components"):
            facts.append("Components: " + ", ".join(c.get("name", "") for c in f["components"]))
        sprints = _sprints(f.get(self.sprint_field)) if self.sprint_field else []
        if sprints:
            facts.append(_sprint_line(sprints))
        points = f.get(self.points_field) if self.points_field else None
        if points is not None:
            facts.append(f"Story points: {points:g}" if isinstance(points, int | float) else f"Story points: {points}")
        if f.get("resolutiondate"):
            facts.append(f"Resolved: {f['resolutiondate'][:10]}")
        if f.get("subtasks"):
            facts.append("Sub-tasks: " + "; ".join(
                f"{t['key']} {(t.get('fields') or {}).get('summary', '')} "
                f"({((t.get('fields') or {}).get('status') or {}).get('name', '?')})"
                for t in f["subtasks"]
            ))

        history_lines, assignees_over_time, resolved_by = [], [], ""
        for h in self._history(issue):
            who = _name(h.get("author")) or "Someone"
            when = (parse_time(h.get("created")) or datetime.now(UTC)).strftime("%d %b %Y")
            for it in h.get("items") or []:
                field = (it.get("field") or "").lower()
                if field not in HISTORY_FIELDS:
                    continue
                old, new = it.get("fromString") or "(none)", it.get("toString") or "(none)"
                history_lines.append(f"  {when}  {who}: {it.get('field')} {old} → {new}")
                if field == "assignee" and it.get("toString"):
                    assignees_over_time.append(it["toString"])
                if field == "status" and new.lower() in _DONE:
                    resolved_by = who
        if history_lines:
            facts.append("History:")
            if len(history_lines) > HISTORY_LINES:
                earlier = len(history_lines) - HISTORY_LINES
                facts.append(f"  … {earlier} earlier change{'' if earlier == 1 else 's'}")
            facts.extend(history_lines[-HISTORY_LINES:])
        description = _text(f.get("description"))

        yield RawItem(
            external_id=f"jira:{key}",
            kind="card",
            text="\n".join([f"{key}: {f.get('summary', '')}", *facts] + (["", description] if description else [])),
            title=f"{key}: {f.get('summary', '')}",
            author=assignee or _name(f.get("reporter")),
            occurred_at=parse_time(f.get("updated") or f.get("created")),
            permalink=url,
            locator=key,
            meta={"provider": "jira", "key": key, "status": status, "assignees": [assignee] if assignee else [],
                  "assignee_history": list(dict.fromkeys(assignees_over_time)), "resolved_by": resolved_by,
                  "type": (f.get("issuetype") or {}).get("name", ""), "due": f.get("duedate"), "labels": labels,
                  "sprint_count": len(sprints),
                  "created": f.get("created"), "resolved": f.get("resolutiondate")},
        )
        for c in self._comments(issue):
            body = _text(c.get("body"))
            if not body:
                continue
            yield RawItem(
                external_id=f"jira:{key}:comment:{c['id']}",
                kind="card_comment",
                text=body,
                title=f"Comment on {key}: {f.get('summary', '')}",
                author=_name(c.get("author")),
                occurred_at=parse_time(c.get("created")),
                permalink=f"{url}?focusedCommentId={c['id']}",
                locator=f"{key} comment",
                meta={"provider": "jira", "key": key},
            )

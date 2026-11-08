"""Task-board exports: Trello board JSON, and CSV from Jira, GitHub Projects or
anything with recognisable column names.

Each card is one item; each comment on a card is its own item so it can be
cited on its own.
"""

import csv
import io
import json
from collections.abc import Iterator

from app.connectors.base import ConnectorError, RawItem, clean, parse_time


def parse_trello(data: bytes) -> Iterator[RawItem]:
    board = json.loads(data)
    if not isinstance(board, dict) or "cards" not in board:
        raise ConnectorError("This doesn't look like a Trello board export.")
    lists = {lst["id"]: lst["name"] for lst in board.get("lists", [])}
    members = {m["id"]: m.get("fullName") or m.get("username", "") for m in board.get("members", [])}
    checklists: dict[str, list[str]] = {}
    for cl in board.get("checklists", []):
        items = [f"[{'x' if i.get('state') == 'complete' else ' '}] {i['name']}" for i in cl.get("checkItems", [])]
        checklists.setdefault(cl["idCard"], []).append(f"{cl.get('name', 'Checklist')}:\n" + "\n".join(items))

    cards = {c["id"]: c for c in board["cards"]}
    for c in board["cards"]:
        status = lists.get(c.get("idList", ""), "")
        assignees = [members.get(i, i) for i in c.get("idMembers", [])]
        labels = [lbl.get("name") for lbl in c.get("labels", []) if lbl.get("name")]
        lines = [
            f"Card: {c['name']}",
            f"List: {status}" + (" (archived)" if c.get("closed") else ""),
        ]
        if assignees:
            lines.append("Assigned to: " + ", ".join(assignees))
        if c.get("due"):
            lines.append(f"Due: {c['due'][:10]}" + (" (done)" if c.get("dueComplete") else ""))
        if labels:
            lines.append("Labels: " + ", ".join(labels))
        if c.get("desc"):
            lines += ["", clean(c["desc"])]
        for cl in checklists.get(c["id"], []):
            lines += ["", cl]
        yield RawItem(
            external_id=f"trello:card:{c['id']}",
            kind="card",
            text="\n".join(lines),
            title=c["name"],
            author=assignees[0] if assignees else "",
            occurred_at=parse_time(c.get("dateLastActivity")),
            permalink=c.get("shortUrl") or c.get("url", ""),
            locator=f"card “{c['name']}”",
            meta={"status": status, "assignees": assignees, "labels": labels, "due": c.get("due"),
                  "closed": bool(c.get("closed"))},
        )

    for a in board.get("actions", []):
        if a.get("type") != "commentCard":
            continue
        card_id = a.get("data", {}).get("card", {}).get("id", "")
        card = cards.get(card_id, {})
        yield RawItem(
            external_id=f"trello:comment:{a['id']}",
            kind="card_comment",
            text=clean(a.get("data", {}).get("text")),
            title=f"Comment on “{card.get('name', 'card')}”",
            author=a.get("memberCreator", {}).get("fullName", ""),
            occurred_at=parse_time(a.get("date")),
            permalink=card.get("shortUrl", ""),
            locator=f"comment on “{card.get('name', 'card')}”",
            meta={"card_id": card_id},
        )


# Column names seen in Jira, GitHub Projects, Asana, Linear and Notion exports.
_COLUMNS = {
    "title": ["summary", "title", "name", "task name", "task"],
    "status": ["status", "state", "column", "section/column", "list"],
    "assignee": ["assignee", "assignees", "owner", "assigned to"],
    "due": ["due date", "due", "due on", "target date"],
    "labels": ["labels", "tags", "label"],
    "description": ["description", "body", "notes", "details"],
    "id": ["issue key", "key", "id", "issue id", "number", "task id"],
    "url": ["url", "link", "issue url"],
    "updated": ["updated", "last modified", "modified", "updated at"],
    "comments": ["comment", "comments"],
}


def parse_task_csv(filename: str, data: bytes) -> Iterator[RawItem]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as e:
        raise ConnectorError(f"{filename} is empty.") from e
    norm = [h.strip().lower() for h in header]

    def cols(field: str) -> list[int]:
        return [i for i, h in enumerate(norm) if h in _COLUMNS[field]]

    idx = {f: cols(f) for f in _COLUMNS}
    if not idx["title"]:
        raise ConnectorError(f"{filename} has no Title/Summary/Name column.")

    for n, row in enumerate(reader, start=2):
        def get(field: str, row: list[str] = row) -> str:
            # Jira repeats columns (several "Comment" or "Labels" columns); join them.
            return "; ".join(row[i].strip() for i in idx[field] if i < len(row) and row[i].strip())

        title = get("title")
        if not title:
            continue
        lines = [f"Card: {title}"]
        for label, field in [("Status", "status"), ("Assigned to", "assignee"), ("Due", "due"), ("Labels", "labels")]:
            if get(field):
                lines.append(f"{label}: {get(field)}")
        if get("description"):
            lines += ["", get("description")]
        if get("comments"):
            lines += ["", "Comments: " + get("comments")]
        key = get("id") or f"row{n}"
        yield RawItem(
            external_id=f"csv:{filename}:{key}",
            kind="card",
            text="\n".join(lines),
            title=title,
            author=get("assignee").split(";")[0].strip(),
            occurred_at=parse_time(get("updated")),
            permalink=get("url"),
            locator=f"{filename} · row {n}" + (f" ({key})" if get("id") else ""),
            meta={"status": get("status"), "assignees": [a.strip() for a in get("assignee").split(",") if a.strip()],
                  "due": get("due"), "labels": get("labels")},
        )


def parse_taskboard(filename: str, data: bytes) -> Iterator[RawItem]:
    lower = filename.lower()
    if lower.endswith(".json"):
        return parse_trello(data)
    if lower.endswith(".csv"):
        return parse_task_csv(filename, data)
    raise ConnectorError(f"Can't read {filename}: upload a Trello .json or a .csv export.")

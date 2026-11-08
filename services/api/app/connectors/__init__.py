"""Connectors turn a source into RawItems. They only ever read."""

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

from app.connectors.base import ISSUE_KEY, ConnectorError, RawItem, RetryLater
from app.connectors.chat import parse_chat
from app.connectors.documents import parse_document
from app.connectors.github import GitHubLive, items_from_snapshot, load_snapshot
from app.connectors.jira import JiraLive
from app.connectors.meetings import parse_meeting
from app.connectors.taskboard import parse_taskboard
from app.db.models import SourceKind

__all__ = ["ISSUE_KEY", "ConnectorError", "RawItem", "RetryLater", "is_live", "read_source"]


def is_live(kind: SourceKind, config: dict) -> bool:
    """Live sources read from the tool on every sync; the rest re-read uploaded files."""
    return (kind == SourceKind.github and bool(config.get("repo"))) or config.get("provider") == "jira"


def read_source(
    kind: SourceKind,
    config: dict,
    files: list[Path],
    github_token: str = "",
    since: datetime | None = None,
    secret: str | None = None,
    changed_since: datetime | None = None,
    workdir: Path | None = None,
) -> Iterator[RawItem]:
    """All items in a source.

    files:         stored uploads, for upload-based sources
    since:         the source's date scope (hard limit)
    changed_since: incremental sync; live sources only re-read what changed after this
    secret:        the source's decrypted credential (Jira token, GitHub token)
    workdir:       where a live GitHub source keeps its history-only git copy
    """
    if kind == SourceKind.taskboard and config.get("provider") == "jira":
        if not secret:
            raise ConnectorError("This Jira source has no saved API token. Add one under Sources.")
        newest = max(filter(None, [since, changed_since]), default=None)
        yield from JiraLive(config["site"], config["email"], secret, config["jql"], newest).items()
        return
    if kind == SourceKind.github and config.get("repo") and not files:
        live = GitHubLive(config["repo"], secret or github_token, since, changed_since, workdir)
        yield from items_from_snapshot(live.snapshot())
        return
    if not files:
        raise ConnectorError("No files uploaded for this source.")
    for path in files:
        data = path.read_bytes()
        name = path.name
        if kind == SourceKind.github:
            yield from items_from_snapshot(load_snapshot(name, data))
        elif kind == SourceKind.document:
            yield from parse_document(name, data)
        elif kind == SourceKind.taskboard:
            yield from parse_taskboard(name, data)
        elif kind == SourceKind.chat:
            yield from parse_chat(name, data)
        elif kind == SourceKind.meeting:
            default = date.fromisoformat(config["meeting_date"]) if config.get("meeting_date") else None
            yield from parse_meeting(name, data, default)
        else:
            raise ConnectorError(f"Sources of type {kind.value} can't be imported from files.")

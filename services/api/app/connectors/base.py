"""What every connector produces: plain items with enough context to cite."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class RawItem:
    external_id: str  # stable inside the source, so re-syncs update instead of duplicating
    kind: str  # commit, pull_request, pr_comment, issue, issue_comment, file, check,
    #            doc_section, card, card_comment, message
    text: str
    title: str = ""
    author: str = ""
    occurred_at: datetime | None = None
    permalink: str = ""
    locator: str = ""  # human-readable position: "lines 12–30", "message 418", "a1b2c3d"
    meta: dict = field(default_factory=dict)
    # A label the source itself asserts (e.g. front matter "sensitivity: confidential").
    sensitivity_hint: str | None = None


class ConnectorError(Exception):
    """A problem with the input the user can fix (bad file, wrong format)."""


class RetryLater(ConnectorError):
    """The tool asked us to slow down (rate limit). The sync resumes at `retry_at`."""

    def __init__(self, message: str, retry_at: datetime) -> None:
        super().__init__(message)
        self.retry_at = retry_at


# Jira-style issue keys ("ROV-7") mentioned in commits, PRs, chats. Candidates only:
# "UTF-8" matches too, so links are resolved against keys that really exist.
ISSUE_KEY = re.compile(r"(?<![A-Za-z0-9-])([A-Z][A-Z0-9]{1,9}-[1-9]\d{0,5})(?![A-Za-z0-9-])")


def parse_time(value: str | int | float | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    s = str(value).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return datetime.fromtimestamp(float(s), tz=UTC)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def clean(text: str | None) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()

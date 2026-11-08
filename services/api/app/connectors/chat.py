"""Chat exports: Slack (export zip or channel JSON), Discord (DiscordChatExporter
JSON) and WhatsApp (the "Export chat" text file).

One message becomes one item, so a citation can point at the exact message.
Thread / reply links are kept in meta so later steps can pull in context.
"""

import io
import json
import re
import zipfile
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from app.connectors.base import ConnectorError, RawItem, clean, parse_time

IST = timezone(timedelta(hours=5, minutes=30))


# --- Slack ----------------------------------------------------------------


def _slack_messages(channel: str, messages: list[dict], users: dict[str, str], workspace: str) -> Iterator[RawItem]:
    for m in messages:
        if m.get("subtype") in {"channel_join", "channel_leave", "bot_add", "channel_purpose"}:
            continue
        text = clean(m.get("text"))
        for f in m.get("files") or []:
            text += f"\n[attachment: {f.get('name') or f.get('title') or 'file'}]"
        if not text:
            continue
        ts = str(m.get("ts", ""))
        author = m.get("user_profile", {}).get("real_name") or users.get(m.get("user", ""), m.get("user", ""))
        yield RawItem(
            external_id=f"slack:{channel}:{ts}",
            kind="message",
            text=text,
            title=f"#{channel}",
            author=author or "unknown",
            occurred_at=parse_time(ts),
            permalink=f"https://{workspace}.slack.com/archives/{channel}/p{ts.replace('.', '')}" if workspace else "",
            locator=f"#{channel} · {ts}",
            meta={
                "channel": channel,
                "thread_ts": m.get("thread_ts"),
                "reply_count": m.get("reply_count", 0),
                "pinned": bool(m.get("pinned_to")),
            },
        )


def parse_slack(filename: str, data: bytes, workspace: str = "") -> Iterator[RawItem]:
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            users: dict[str, str] = {}
            if "users.json" in names:
                for u in json.loads(z.read("users.json")):
                    users[u["id"]] = u.get("real_name") or u.get("name", u["id"])
            for name in sorted(names):
                parts = name.split("/")
                if len(parts) == 2 and parts[1].endswith(".json"):
                    yield from _slack_messages(parts[0], json.loads(z.read(name)), users, workspace)
        return
    payload = json.loads(data)
    if isinstance(payload, dict) and "messages" in payload:
        yield from _slack_messages(payload.get("channel", "channel"), payload["messages"], {}, workspace)
    elif isinstance(payload, list):
        yield from _slack_messages(filename.rsplit(".", 1)[0], payload, {}, workspace)
    else:
        raise ConnectorError("This doesn't look like a Slack export.")


# --- Discord (DiscordChatExporter JSON) ----------------------------------


def parse_discord(data: bytes) -> Iterator[RawItem]:
    payload = json.loads(data)
    if not isinstance(payload, dict) or "messages" not in payload:
        raise ConnectorError("This doesn't look like a DiscordChatExporter JSON file.")
    guild = payload.get("guild", {})
    channel = payload.get("channel", {})
    cname = channel.get("name", "channel")
    for i, m in enumerate(payload["messages"], start=1):
        if m.get("type") not in (None, "Default", "Reply"):
            continue
        text = clean(m.get("content"))
        for a in m.get("attachments") or []:
            text += f"\n[attachment: {a.get('fileName', 'file')}]"
        if not text:
            continue
        author = m.get("author", {})
        ref = m.get("reference") or {}
        yield RawItem(
            external_id=f"discord:{channel.get('id', cname)}:{m['id']}",
            kind="message",
            text=text,
            title=f"#{cname}",
            author=author.get("nickname") or author.get("name") or "unknown",
            occurred_at=parse_time(m.get("timestamp")),
            permalink=(
                f"https://discord.com/channels/{guild.get('id')}/{channel.get('id')}/{m['id']}"
                if guild.get("id") and channel.get("id")
                else ""
            ),
            locator=f"#{cname} · message {i}",
            meta={"channel": cname, "reply_to": ref.get("messageId"), "pinned": bool(m.get("isPinned"))},
        )


# --- WhatsApp -------------------------------------------------------------

# Android: "12/10/24, 9:41 pm - Aarav: text"   iOS: "[12/10/24, 9:41:05 PM] Aarav: text"
_WA_LINE = re.compile(
    r"^‎?\[?(?P<date>\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}),?\s+"
    r"(?P<time>\d{1,2}[:.]\d{2}(?:[:.]\d{2})?)\s*(?P<ampm>[aApP]\.?\s?[mM]\.?)?\]?"
    r"\s*(?:-|–)?\s*(?P<rest>.*)$"
)
# System lines ("Aarav added Meera") have no "Name: " part and are skipped structurally;
# these are placeholders WhatsApp puts *inside* real messages.
_WA_PLACEHOLDER = re.compile(
    r"^(<Media omitted>|<attached: [^>]+>|This message was deleted|You deleted this message|null)$", re.I
)


def _wa_datetime(date: str, time: str, ampm: str | None, day_first: bool) -> datetime | None:
    d = re.split(r"[/.-]", date)
    a, b, y = int(d[0]), int(d[1]), int(d[2])
    day, month = (a, b) if day_first else (b, a)
    if y < 100:
        y += 2000
    t = re.split(r"[:.]", time)
    hour, minute = int(t[0]), int(t[1])
    second = int(t[2]) if len(t) > 2 else 0
    if ampm:
        pm = ampm.strip().lower().startswith("p")
        hour = hour % 12 + (12 if pm else 0)
    try:
        return datetime(y, month, day, hour, minute, second, tzinfo=IST)
    except ValueError:
        return None


def parse_whatsapp(filename: str, data: bytes) -> Iterator[RawItem]:
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.replace("\r\n", "\n").split("\n")

    # Indian exports are day-first; switch only if a first field exceeds 12.
    day_first = True
    for line in lines[:500]:
        m = _WA_LINE.match(line)
        if m:
            parts = re.split(r"[/.-]", m["date"])
            if int(parts[1]) > 12:
                day_first = False
                break

    chat = re.sub(r"^WhatsApp Chat with |\.txt$", "", filename)
    current: dict | None = None
    n = 0

    def flush() -> Iterator[RawItem]:
        nonlocal n
        if not current:
            return
        body = clean(current["text"])
        if not body or _WA_PLACEHOLDER.match(body):
            return
        n += 1
        yield RawItem(
            external_id=f"whatsapp:{chat}:{current['line']}",
            kind="message",
            text=body,
            title=chat,
            author=current["author"],
            occurred_at=current["at"],
            locator=f"line {current['line']}",
            meta={"chat": chat},
        )

    for lineno, line in enumerate(lines, start=1):
        m = _WA_LINE.match(line)
        if m and ":" in m["rest"]:
            author, _, body = m["rest"].partition(": ")
            if not body and author.endswith(":"):
                author, body = author[:-1], ""
            yield from flush()
            current = {
                "author": author.strip().lstrip("~").strip(),
                "text": body,
                "at": _wa_datetime(m["date"], m["time"], m["ampm"], day_first),
                "line": lineno,
            }
        elif m:
            # System line with a timestamp ("Aarav added Meera") — ends the previous message.
            yield from flush()
            current = None
        elif current is not None:
            current["text"] += "\n" + line
    yield from flush()
    if n == 0:
        raise ConnectorError("No messages found. Is this a WhatsApp 'Export chat' text file?")


def parse_chat(filename: str, data: bytes) -> Iterator[RawItem]:
    """Pick the right parser from the file's name and content."""
    lower = filename.lower()
    if lower.endswith(".txt"):
        return parse_whatsapp(filename, data)
    if lower.endswith(".zip"):
        return parse_slack(filename, data)
    if lower.endswith(".json"):
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as e:
            raise ConnectorError(f"{filename} isn't valid JSON.") from e
        if isinstance(payload, dict) and "guild" in payload and "messages" in payload:
            return parse_discord(data)
        return parse_slack(filename, data)
    raise ConnectorError(f"Can't read {filename}: use a WhatsApp .txt, Slack .zip/.json or Discord .json export.")

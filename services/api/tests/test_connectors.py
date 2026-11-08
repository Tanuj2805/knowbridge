import io
import json
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from app.connectors import ConnectorError
from app.connectors.chat import parse_chat, parse_discord, parse_slack, parse_whatsapp
from app.connectors.documents import parse_markdown
from app.connectors.github import items_from_snapshot
from app.connectors.taskboard import parse_task_csv, parse_trello
from app.lang import detect
from tests.conftest import DATA

IST = timezone(timedelta(hours=5, minutes=30))


# --- WhatsApp -------------------------------------------------------------


def test_whatsapp_nimbus_export():
    path = DATA / "chat" / "WhatsApp Chat with Nimbus Tech.txt"
    items = list(parse_whatsapp(path.name, path.read_bytes()))
    assert len(items) == 23  # system lines ("created group", "added …") are skipped
    first = items[0]
    assert first.author == "Priya Nair"
    assert first.occurred_at == datetime(2026, 7, 20, 18, 5, tzinfo=IST)
    assert first.title == "Nimbus Tech"
    assert first.locator.startswith("line ")


def test_whatsapp_multiline_and_ios_format():
    text = (
        "[05/11/26, 9:41:05 PM] Aarav: first line\n"
        "second line\n"
        "[05/11/26, 9:42:00 PM] Meera: <Media omitted>\n"
        "[05/11/26, 9:43:00 PM] Meera: ok\n"
    )
    items = list(parse_whatsapp("chat.txt", text.encode()))
    assert [i.text for i in items] == ["first line\nsecond line", "ok"]
    assert items[0].occurred_at == datetime(2026, 11, 5, 21, 41, 5, tzinfo=IST)


def test_whatsapp_month_first_is_detected():
    text = "11/25/26, 10:00 am - Sam: hello there\n11/26/26, 10:00 am - Sam: again\n"
    items = list(parse_whatsapp("chat.txt", text.encode()))
    assert items[0].occurred_at.month == 11 and items[0].occurred_at.day == 25


def test_whatsapp_rejects_other_text():
    with pytest.raises(ConnectorError):
        list(parse_whatsapp("notes.txt", b"just some notes\nnothing else"))


# --- Discord / Slack ------------------------------------------------------


def test_discord_export():
    items = list(parse_discord((DATA / "chat" / "discord-dev.json").read_bytes()))
    assert len(items) == 19
    reply = next(i for i in items if i.meta.get("reply_to"))
    assert reply.permalink.startswith("https://discord.com/channels/")
    assert items[0].author == "Aarav"


def test_slack_zip_export():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("users.json", json.dumps([{"id": "U1", "real_name": "Aarav Mehta"}]))
        z.writestr("general/2026-10-01.json", json.dumps([
            {"type": "message", "user": "U1", "text": "We moved to Railway", "ts": "1696150800.000100"},
            {"type": "message", "subtype": "channel_join", "user": "U1", "text": "joined", "ts": "1696150900.0"},
        ]))
    items = list(parse_slack("export.zip", buf.getvalue(), workspace="nimbus"))
    assert len(items) == 1
    assert items[0].author == "Aarav Mehta"
    assert items[0].permalink == "https://nimbus.slack.com/archives/general/p1696150800000100"


def test_chat_dispatch_by_content():
    assert next(iter(parse_chat("x.json", (DATA / "chat" / "discord-dev.json").read_bytes()))).kind == "message"
    with pytest.raises(ConnectorError):
        parse_chat("x.pdf", b"")


# --- Task boards ----------------------------------------------------------


def test_trello_export():
    items = list(parse_trello((DATA / "taskboard" / "trello-nimbus-2027.json").read_bytes()))
    kinds = Counter(i.kind for i in items)
    assert kinds == {"card": 16, "card_comment": 4}
    recon = next(i for i in items if i.title == "Payment reconciliation job")
    assert "List: In progress" in recon.text
    assert "[x] Fetch settlements" in recon.text and "[ ] Email receipts" in recon.text
    archived = next(i for i in items if i.title == "Accommodation form")
    assert "(archived)" in archived.text


def test_jira_csv_with_repeated_columns():
    csv_text = (
        "Summary,Issue key,Status,Assignee,Due date,Comment,Comment\n"
        "Fix spam emails,NIM-7,In Progress,Dev Patel,2026-11-10,Needs DKIM,GoDaddy login is with Aarav\n"
        ",NIM-8,Done,,,,\n"
    )
    items = list(parse_task_csv("jira.csv", csv_text.encode()))
    assert len(items) == 1
    assert "Needs DKIM; GoDaddy login is with Aarav" in items[0].text
    assert items[0].locator == "jira.csv · row 2 (NIM-7)"


def test_csv_without_title_column_is_rejected():
    with pytest.raises(ConnectorError):
        list(parse_task_csv("x.csv", b"foo,bar\n1,2\n"))


# --- Documents ------------------------------------------------------------


def test_markdown_sections_and_front_matter():
    path = DATA / "docs" / "committee" / "volunteer-stipends.md"
    items = list(parse_markdown(path.name, path.read_bytes()))
    assert items and all(i.sensitivity_hint == "confidential" for i in items)
    assert items[0].author == "Priya Nair"


def test_markdown_line_numbers_point_at_the_original_file():
    path = DATA / "docs" / "team" / "2026-08-30-weekly-sync.md"
    raw = path.read_text(encoding="utf-8").split("\n")
    for item in parse_markdown(path.name, path.read_bytes()):
        start, end = item.meta["line_start"], item.meta["line_end"]
        assert raw[start - 1].strip() == item.text.split("\n")[0].strip()
        assert end >= start


# --- GitHub snapshot ------------------------------------------------------


def test_github_snapshot():
    snap = yaml.safe_load((DATA / "github" / "snapshot.yaml").read_text(encoding="utf-8"))
    items = list(items_from_snapshot(snap))
    kinds = Counter(i.kind for i in items)
    assert kinds["commit"] == 28
    assert kinds["pull_request"] == 12
    assert kinds["issue"] == 10
    assert kinds["check"] == 3
    pr42 = next(i for i in items if i.external_id == "pr:42")
    assert pr42.permalink == "https://github.com/nimbus-fest/nimbus-app/pull/42"
    assert "State: open" in pr42.text and "Draft: yes" in pr42.text
    readme = next(i for i in items if i.kind == "file" and "README" in i.title)
    assert "#L" in readme.permalink
    assert len({i.external_id for i in items}) == len(items)


def test_snapshot_needs_repo():
    with pytest.raises(ConnectorError):
        list(items_from_snapshot({"commits": []}))


# --- language -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Guys fest dates shift ho gayi hai, ab 23-25 Jan hai", "hi-en"),
        ("haan dekhta hoon kal, abhi exams chal rahe hai", "hi-en"),
        ("We moved the API to Railway because Render cold starts were slow", "en"),
        ("ok", "en"),
        ("यह हिंदी में लिखा गया एक वाक्य है", "hi"),
    ],
)
def test_language_detection(text, lang):
    assert detect(text) == lang

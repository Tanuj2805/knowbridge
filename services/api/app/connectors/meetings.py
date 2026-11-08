"""Meeting transcripts: Zoom / Teams WebVTT, SRT, Google Meet transcripts (txt or
docx), Otter / Fireflies exports, and plain "Name: what they said" notes.

A transcript becomes a series of segments (a few minutes or ~1,200 characters
each), so a claim can cite the exact moment: "Payments sync, 00:12:30–00:14:10".
Each segment keeps who said what, line by line.
"""

import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone

from app.connectors.base import ConnectorError, RawItem, clean

IST = timezone(timedelta(hours=5, minutes=30))
SEGMENT_CHARS = 1200
SEGMENT_SECONDS = 180

_TIMING = re.compile(r"^(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}")
_TIMESTAMP = r"(?:\d{1,2}:)?\d{1,2}:\d{2}"
_ONLY_TIME = re.compile(rf"^[\[(]?({_TIMESTAMP})[\])]?$")
_TIME_THEN_SPEAKER = re.compile(rf"^[\[(]?({_TIMESTAMP})[\])]?\s*[-–]?\s*(.+)$")
_VOICE = re.compile(r"^<v\s+([^>]+)>(.*?)(?:</v>)?$")
# Otter style: "Aarav Mehta  12:34" on its own line, then what they said.
_SPEAKER_THEN_TIME = re.compile(rf"^([A-Z][\w.'’-]*(?: [A-Z][\w.'’-]*){{0,3}})\s{{2,}}({_TIMESTAMP})$")
_SPEAKER = re.compile(r"^([A-Z][\w.'’-]*(?:\s[A-Z][\w.'’-]*){0,3}|[a-z][\w.'’-]+(?:\s[a-z][\w.'’-]+){0,2})\s*:\s+(.+)$")
_NOT_A_SPEAKER = {
    "note", "notes", "action items", "agenda", "summary", "decision", "decisions", "todo", "http", "https",
}
NOTES_SPEAKER = "Meeting notes"
_START = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T,]+(\d{1,2}):(\d{2})")

_DATE_PATTERNS = [
    (re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})"), lambda m: date(int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+(\d{4})", re.I),
     lambda m: datetime.strptime(f"{m[1]} {m[2][:3]} {m[3]}", "%d %b %Y").date()),
    (re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", re.I),
     lambda m: datetime.strptime(f"{m[2]} {m[1][:3]} {m[3]}", "%d %b %Y").date()),
]


@dataclass
class Utterance:
    speaker: str
    text: str
    at: int | None  # seconds from the start of the meeting
    until: int | None = None  # when the (merged) remark ended

    def __post_init__(self) -> None:
        if self.until is None:
            self.until = self.at


MERGE_GAP_SECONDS = 30  # subtitle cues split one remark into many lines; rejoin them


def _seconds(ts: str) -> int:
    parts = [int(p) for p in re.split(r"[:.,]", ts)[:3]]
    if ts.count(":") == 2:
        h, m, s = parts
    else:
        h, (m, s) = 0, parts[:2]
    return h * 3600 + m * 60 + s


def hhmmss(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def find_date(text: str) -> date | None:
    for pattern, build in _DATE_PATTERNS:
        if m := pattern.search(text):
            try:
                return build(m)
            except ValueError:
                continue
    return None


def _is_speaker(name: str) -> bool:
    n = name.strip().lower()
    return bool(n) and n not in _NOT_A_SPEAKER and not n.startswith("http") and len(n) <= 40


def parse_utterances(text: str) -> tuple[list[Utterance], list[str]]:
    """Returns (utterances, header lines before the conversation starts)."""
    out: list[Utterance] = []
    header: list[str] = []
    now: int | None = None
    pending_speaker: str | None = None
    in_attendees = False

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip().lstrip("﻿")
        if not line or line == "WEBVTT" or line.startswith("NOTE") or line.isdigit():
            pending_speaker = None if not line else pending_speaker
            continue
        if line.lower() in ("attendees", "participants"):
            in_attendees = True
            header.append(line)
            continue
        if line.lower() in ("transcript", "transcription"):
            in_attendees = False
            continue
        if _TIMING.match(line):
            now = _seconds(line.split("-->")[0].strip())
            continue
        if m := _ONLY_TIME.match(line):
            now = _seconds(m[1])
            in_attendees = False
            continue
        if m := _SPEAKER_THEN_TIME.match(line):
            pending_speaker, now = m[1], _seconds(m[2])
            continue
        if m := _VOICE.match(line):
            out.append(Utterance(m[1].strip(), clean(m[2]), now))
            pending_speaker = None
            continue
        body, at = line, now
        if (m := _TIME_THEN_SPEAKER.match(line)) and _SPEAKER.match(m[2]):
            body, at = m[2], _seconds(m[1])
            now = at
        if (m := _SPEAKER.match(body)) and not in_attendees:
            if _is_speaker(m[1]):
                out.append(Utterance(m[1].strip(), m[2].strip(), at))
            else:
                # "Decision: …", "Action items: …" are the meeting's own notes, not anyone's speech.
                out.append(Utterance(NOTES_SPEAKER, f"{m[1].strip()}: {m[2].strip()}", at))
            pending_speaker = None
            continue
        if pending_speaker:
            out.append(Utterance(pending_speaker, line, now))
            pending_speaker = None
            continue
        if out and not in_attendees:
            out[-1].text += " " + line  # a wrapped line of the same remark
        else:
            header.append(line)

    # VTT/SRT repeat the speaker on every cue; merge consecutive lines by the same person.
    merged: list[Utterance] = []
    for u in out:
        prev = merged[-1] if merged else None
        close = prev is not None and (u.at is None or prev.until is None or u.at - prev.until <= MERGE_GAP_SECONDS)
        if prev and prev.speaker == u.speaker and close and len(prev.text) < SEGMENT_CHARS // 2:
            # A person's lines read as one remark; separate notes stay on their own lines.
            prev.text += ("\n" if u.speaker == NOTES_SPEAKER else " ") + u.text
            prev.until = u.at if u.at is not None else prev.until
        else:
            merged.append(u)
    return [u for u in merged if u.text.strip()], header


def _segments(utterances: list[Utterance]) -> Iterator[list[Utterance]]:
    seg: list[Utterance] = []
    size = 0
    for u in utterances:
        starts_late = (
            seg and u.at is not None and seg[0].at is not None and u.at - seg[0].at >= SEGMENT_SECONDS
        )
        if seg and (size + len(u.text) > SEGMENT_CHARS or starts_late):
            yield seg
            seg, size = [], 0
        seg.append(u)
        size += len(u.text)
    if seg:
        yield seg


def _text_of(filename: str, data: bytes) -> str:
    if filename.lower().endswith(".docx"):
        from docx import Document

        try:
            doc = Document(io.BytesIO(data))
        except Exception as e:
            raise ConnectorError(f"Couldn't open {filename} as a Word document.") from e
        return "\n".join(p.text for p in doc.paragraphs)
    return data.decode("utf-8-sig", errors="replace")


def parse_meeting(filename: str, data: bytes, default_date: date | None = None) -> Iterator[RawItem]:
    text = _text_of(filename, data)
    utterances, header = parse_utterances(text)
    if not utterances:
        raise ConnectorError(
            f"{filename}: no speakers found. Upload a Zoom/Teams .vtt, a Google Meet transcript, "
            "or notes written as “Name: what they said”."
        )
    stem = filename.rsplit(".", 1)[0]
    first = next((h for h in header if not h.lower().startswith(("attendees", "participants"))), "")
    title = re.sub(r"\s*[-–]\s*Transcript\s*$", "", first, flags=re.I).strip() or stem
    title = re.sub(r"\s*\(\d{4}[-/]\d{1,2}[-/]\d{1,2}[^)]*\)", "", title).strip() or stem
    head_text = "\n".join([filename, *header[:10]])
    when = find_date(filename) or find_date("\n".join(header[:10])) or default_date
    clock = time(0, 0)
    if (m := _START.search(head_text)) and when and date(int(m[1]), int(m[2]), int(m[3])) == when:
        clock = time(int(m[4]), int(m[5]))  # Google Meet: "(2026-10-14 18:00 GMT+05:30)"
    start = datetime.combine(when, clock, IST).astimezone(UTC) if when else None
    speakers_all = sorted({u.speaker for u in utterances})

    for n, seg in enumerate(_segments(utterances)):
        starts = [u.at for u in seg if u.at is not None]
        ends = [u.until for u in seg if u.until is not None]
        a = starts[0] if starts else None
        b = ends[-1] if ends else None
        span = f"{hhmmss(a)}–{hhmmss(b)}" if a is not None and b is not None and b > a else (
            hhmmss(a) if a is not None else f"part {n + 1}")
        speakers = list(dict.fromkeys(u.speaker for u in seg))
        lines = [f"{u.speaker}: {u.text}" for u in seg]
        yield RawItem(
            external_id=f"meeting:{filename}:{n}",
            kind="meeting_segment",
            text="\n".join(lines),
            title=f"{title} — {span}",
            author=", ".join(speakers[:3]) + (" …" if len(speakers) > 3 else ""),
            occurred_at=(start + timedelta(seconds=a or 0)) if start else None,
            locator=f"{filename} · {span}",
            meta={"meeting": title, "file": filename, "segment": n, "start_sec": a, "end_sec": b,
                  "speakers": speakers, "attendees": speakers_all, "date": when.isoformat() if when else None},
        )

"""Uploaded documents: Markdown, plain text, PDF and Word.

Each document is split into sections small enough to cite ("lines 12–30",
"page 3") but large enough to keep a thought together.
"""

import hashlib
import io
import re
from collections.abc import Iterator

import yaml

from app.connectors.base import ConnectorError, RawItem, clean, parse_time

MAX_CHARS = 1500
_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")


def _front_matter(text: str) -> tuple[dict, str, int]:
    """Returns (front matter, body, number of lines the front matter used)."""
    if not text.startswith("---\n"):
        return {}, text, 0
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text, 0
    try:
        meta = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        return {}, text, 0
    rest = text[end + 4 :].lstrip("\n")
    used = text[: len(text) - len(rest)].count("\n")
    return (meta if isinstance(meta, dict) else {}), rest, used


def _split_long(lines: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    """Split a section on blank lines into chunks under MAX_CHARS."""
    chunks: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    size = 0
    for ln, line in lines:
        if size > MAX_CHARS and not line.strip():
            chunks.append(cur)
            cur, size = [], 0
            continue
        cur.append((ln, line))
        size += len(line) + 1
    if any(line.strip() for _, line in cur):
        chunks.append(cur)
    return chunks


def _markdown_sections(text: str, first_line: int) -> Iterator[tuple[str, int, int, str]]:
    """Yields (heading path, start line, end line, text)."""
    path: list[str] = []
    section: list[tuple[int, str]] = []
    heading_for_section = ""

    def emit() -> Iterator[tuple[str, int, int, str]]:
        for chunk in _split_long(section):
            body = "\n".join(line for _, line in chunk).strip()
            if body:
                yield heading_for_section, chunk[0][0], chunk[-1][0], body

    in_code = False
    for i, line in enumerate(text.split("\n")):
        ln = first_line + i
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else _HEADING.match(line)
        if m:
            yield from emit()
            level = len(m.group(1))
            path = path[: level - 1] + [m.group(2).strip()]
            heading_for_section = " › ".join(path)
            section = [(ln, line)]
        else:
            section.append((ln, line))
    yield from emit()


def _doc_id(filename: str) -> str:
    return hashlib.sha256(filename.encode()).hexdigest()[:10]


def parse_markdown(filename: str, data: bytes) -> Iterator[RawItem]:
    raw = clean(data.decode("utf-8-sig", errors="replace"))
    meta, body, used = _front_matter(raw + "\n")
    title = str(meta.get("title") or filename.rsplit(".", 1)[0])
    when = parse_time(str(meta["date"])) if meta.get("date") else None
    author = str(meta.get("author", ""))
    hint = str(meta["sensitivity"]).lower() if meta.get("sensitivity") else None
    for n, (heading, start, end, text) in enumerate(_markdown_sections(body, used + 1)):
        # The top heading usually repeats the document title; don't say it twice.
        shown = heading.removeprefix(title).removeprefix(" › ") if heading.startswith(title) else heading
        yield RawItem(
            external_id=f"doc:{_doc_id(filename)}:{n}",
            kind="doc_section",
            text=text,
            title=f"{title} — {shown}" if shown else title,
            author=author,
            occurred_at=when,
            locator=f"{filename} · lines {start}–{end}",
            meta={"file": filename, "heading": heading, "line_start": start, "line_end": end, **(
                {"attendees": meta["attendees"]} if meta.get("attendees") else {}
            )},
            sensitivity_hint=hint,
        )


def parse_pdf(filename: str, data: bytes) -> Iterator[RawItem]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as e:  # pypdf raises many types for broken files
        raise ConnectorError(f"Couldn't open {filename} as a PDF.") from e
    info = reader.metadata or {}
    title = str(info.get("/Title") or filename.rsplit(".", 1)[0])
    author = str(info.get("/Author") or "")
    found = False
    for page_no, page in enumerate(reader.pages, start=1):
        text = clean(page.extract_text() or "")
        if not text:
            continue
        found = True
        lines = list(enumerate(text.split("\n"), start=1))
        for part, chunk in enumerate(_split_long(lines)):
            yield RawItem(
                external_id=f"doc:{_doc_id(filename)}:p{page_no}:{part}",
                kind="doc_section",
                text="\n".join(line for _, line in chunk).strip(),
                title=f"{title} — page {page_no}",
                author=author,
                locator=f"{filename} · page {page_no}",
                meta={"file": filename, "page": page_no},
            )
    if not found:
        raise ConnectorError(f"{filename} has no readable text (it may be a scanned image).")


def parse_docx(filename: str, data: bytes) -> Iterator[RawItem]:
    from docx import Document

    try:
        doc = Document(io.BytesIO(data))
    except Exception as e:
        raise ConnectorError(f"Couldn't open {filename} as a Word document.") from e
    # Rebuild as Markdown so headings split it the same way.
    md: list[str] = []
    for p in doc.paragraphs:
        style = (p.style.name if p.style is not None else "").lower()
        if style.startswith("heading"):
            level = int(re.sub(r"\D", "", style) or 1)
            md.append("#" * min(level, 4) + " " + p.text)
        elif style == "title":
            md.append("# " + p.text)
        else:
            md.append(p.text)
    for table in doc.tables:
        for row in table.rows:
            md.append(" | ".join(c.text.strip() for c in row.cells))
    props = doc.core_properties
    front = f"---\ntitle: {props.title or filename.rsplit('.', 1)[0]!r}\n"
    if props.author:
        front += f"author: {props.author!r}\n"
    if props.created:
        front += f"date: {props.created.isoformat()}\n"
    front += "---\n"
    for item in parse_markdown(filename, (front + "\n".join(md)).encode()):
        item.locator = item.locator.replace("lines", "paragraphs")
        yield item


def parse_document(filename: str, data: bytes) -> Iterator[RawItem]:
    lower = filename.lower()
    if lower.endswith((".md", ".markdown", ".txt")):
        return parse_markdown(filename, data)
    if lower.endswith(".pdf"):
        return parse_pdf(filename, data)
    if lower.endswith(".docx"):
        return parse_docx(filename, data)
    raise ConnectorError(f"Can't read {filename}: upload Markdown, text, PDF or DOCX.")

"""Sentinel: masks secrets and personal data before anything is stored or sent
to a model, and labels how sensitive each piece of text is.

This module is deterministic. The Sentinel agent (app.agents.sentinel) adds an
optional model pass for labelling only, after this has already redacted.
"""

import hashlib
from dataclasses import dataclass, field

from app.db.models import Sensitivity
from app.sentinel.rules import (
    ALL_RULES,
    CONFIDENTIAL_PATTERNS,
    RESTRICTED_PATTERNS,
    Rule,
)

_ORDER = {Sensitivity.team: 0, Sensitivity.restricted: 1, Sensitivity.confidential: 2}


def strictest(*labels: Sensitivity) -> Sensitivity:
    return max(labels, key=_ORDER.__getitem__, default=Sensitivity.team)


@dataclass
class Finding:
    rule_id: str
    category: str
    label: str
    start: int  # offsets in the *original* text
    end: int


@dataclass
class ScanResult:
    text: str
    findings: list[Finding] = field(default_factory=list)
    # Offsets of each placeholder in the *redacted* text, for the redactions table.
    placeholders: list[tuple[Finding, int, int]] = field(default_factory=list)
    sensitivity: Sensitivity = Sensitivity.team
    sensitivity_reasons: list[str] = field(default_factory=list)

    @property
    def secret_count(self) -> int:
        return sum(1 for f in self.findings if f.category == "secret")


def _find(text: str, rules: list[Rule]) -> list[Finding]:
    found: list[Finding] = []
    for rule in rules:
        for m in rule.pattern.finditer(text):
            start, end = m.span(rule.group)
            if start < 0 or end <= start:
                continue
            if rule.validate and not rule.validate(m.group(rule.group)):
                continue
            found.append(Finding(rule.id, rule.category, rule.label, start, end))
    # Overlapping matches are merged into one span so nothing leaks between them;
    # the earlier rule in the list (secrets before PII) names the merged span.
    priority = {r.id: i for i, r in enumerate(rules)}
    found.sort(key=lambda f: (f.start, priority[f.rule_id]))
    kept: list[Finding] = []
    for f in found:
        if kept and f.start < kept[-1].end:
            prev = kept[-1]
            winner = f if priority[f.rule_id] < priority[prev.rule_id] else prev
            kept[-1] = Finding(
                winner.rule_id, winner.category, winner.label, prev.start, max(prev.end, f.end)
            )
            continue
        kept.append(f)
    return kept


def label_sensitivity(text: str) -> tuple[Sensitivity, list[str]]:
    reasons = [p.pattern for p in CONFIDENTIAL_PATTERNS if p.search(text)]
    if reasons:
        return Sensitivity.confidential, reasons
    reasons = [p.pattern for p in RESTRICTED_PATTERNS if p.search(text)]
    if reasons:
        return Sensitivity.restricted, reasons
    return Sensitivity.team, []


def scan(text: str, floor: Sensitivity = Sensitivity.team) -> ScanResult:
    """Redact `text` and label it. `floor` is the source's default label."""
    findings = _find(text, ALL_RULES)
    out: list[str] = []
    placeholders: list[tuple[Finding, int, int]] = []
    cursor = 0
    length = 0
    for f in findings:
        out.append(text[cursor : f.start])
        length += f.start - cursor
        token = f"[REDACTED:{f.label}]"
        placeholders.append((f, length, length + len(token)))
        out.append(token)
        length += len(token)
        cursor = f.end
    out.append(text[cursor:])
    redacted = "".join(out)

    # Label from the original text: "salary" next to a masked number still counts.
    label, reasons = label_sensitivity(text)
    return ScanResult(
        text=redacted,
        findings=findings,
        placeholders=placeholders,
        sensitivity=strictest(label, floor),
        sensitivity_reasons=reasons,
    )


def content_hash(text: str) -> str:
    """Hash of whitespace-normalised text, used to detect "source changed"."""
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()

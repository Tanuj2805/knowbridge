"""Detection rules for Sentinel.

Secret rules are adapted from the gitleaks default rule set (MIT). PII rules are
written for Indian teams: +91 mobiles, Aadhaar, PAN, UPI handles, IFSC.

A rule may name a capture group; then only that group is masked, so
"DB_PASSWORD=hunter22" keeps "DB_PASSWORD=" and loses the value.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    category: str  # "secret" | "pii"
    label: str  # shown in the placeholder, e.g. [REDACTED:github-token]
    pattern: re.Pattern[str]
    group: int = 0
    validate: Callable[[str], bool] | None = None


def _luhn_ok(value: str) -> bool:
    digits = [int(c) for c in value if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_CODE_EXPR = re.compile(r"[(){}\[\]<>]|^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")


def _looks_like_secret_value(value: str) -> bool:
    """Filters out prose ("token: pending") and code that only *refers* to a secret:
    calls and lookups (`auth.dumps(...)`, `os.environ["KEY"]`) and dotted names
    (`settings.SECRET_KEY`). Real secrets don't contain brackets."""
    if len(value) < 6 or _CODE_EXPR.search(value):
        return False
    has_digit = any(c.isdigit() for c in value)
    has_symbol = any(not c.isalnum() for c in value)
    has_upper_and_lower = any(c.isupper() for c in value) and any(c.islower() for c in value)
    return has_digit or has_symbol or (has_upper_and_lower and len(value) >= 10)


# \b fails next to "_" and "-", so word-ish boundaries are spelled out.
_B = r"(?<![A-Za-z0-9_])"
_E = r"(?![A-Za-z0-9_])"

SECRET_RULES: list[Rule] = [
    Rule(
        "private-key",
        "secret",
        "private-key",
        re.compile(
            r"-----BEGIN[A-Z ]{0,30}PRIVATE KEY-----[\s\S]*?-----END[A-Z ]{0,30}PRIVATE KEY-----"
        ),
    ),
    Rule("aws-access-key", "secret", "aws-key", re.compile(_B + r"(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}" + _E)),
    Rule("github-pat-fine", "secret", "github-token", re.compile(r"github_pat_[A-Za-z0-9_]{60,100}")),
    Rule("github-token", "secret", "github-token", re.compile(_B + r"gh[pousr]_[A-Za-z0-9]{36,255}" + _E)),
    Rule("gcp-api-key", "secret", "google-api-key", re.compile(_B + r"AIza[0-9A-Za-z\-_]{35}" + _E)),
    Rule("slack-token", "secret", "slack-token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,72}")),
    Rule("slack-webhook", "secret", "slack-webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{20,}")),
    Rule("discord-webhook", "secret", "discord-webhook", re.compile(r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]{30,}")),
    Rule("stripe-key", "secret", "stripe-key", re.compile(_B + r"(?:sk|rk)_(?:test|live|prod)_[0-9a-zA-Z]{10,99}" + _E)),
    Rule("razorpay-key", "secret", "razorpay-key", re.compile(_B + r"rzp_(?:live|test)_[A-Za-z0-9]{14,}" + _E)),
    Rule("anthropic-key", "secret", "anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    Rule("openai-key", "secret", "openai-key", re.compile(_B + r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}" + _E)),
    Rule("firebase-key", "secret", "firebase-key", re.compile(_B + r"AAAA[A-Za-z0-9_-]{7}:[A-Za-z0-9_-]{140}" + _E)),
    Rule("jwt", "secret", "jwt", re.compile(_B + r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}" + _E)),
    Rule(
        "url-credentials",
        "secret",
        "password",
        re.compile(r"[a-z][a-z0-9+.-]{1,20}://[^\s:/@]{1,100}:([^\s@/]{3,200})@"),
        group=1,
    ),
    Rule(
        "assigned-secret",
        "secret",
        "secret",
        re.compile(
            r"(?i)(?:password|passwd|pwd|passcode|secret|api[_-]?key|apikey|access[_-]?key|"
            r"auth[_-]?token|client[_-]?secret|private[_-]?key|token)"
            r"[A-Za-z0-9_]{0,20}\s*(?:=|:|=>)\s*[\"'`]?([^\s\"'`,;]{6,200})"
        ),
        group=1,
        validate=_looks_like_secret_value,
    ),
    # Chat style, including Hinglish: "wifi password hai Nimbus@2026", "pass is abc123!"
    Rule(
        "spoken-password",
        "secret",
        "password",
        re.compile(
            r"(?i)\b(?:password|passwd|pass|pwd|otp|pin)\b\s*(?:is|hai|h|tha|was|=|:|-)\s*"
            r"[\"'`]?([^\s\"'`,;]{4,100})"
        ),
        group=1,
        validate=lambda v: not _CODE_EXPR.search(v)
        and (any(c.isdigit() for c in v) or any(not c.isalnum() for c in v)),
    ),
]

PII_RULES: list[Rule] = [
    Rule("email", "pii", "email", re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+")),
    Rule(
        "upi-id",
        "pii",
        "upi-id",
        re.compile(
            r"[A-Za-z0-9.\-_]{2,64}@(?:ok(?:axis|hdfcbank|icici|sbi)|ybl|ibl|axl|paytm|upi|apl|"
            r"yapl|icici|sbi|hdfcbank|axisbank|kotak|yesbank|pt(?:yes|sbi|hdfc|axis)|freecharge|jio)"
            + _E
        ),
    ),
    Rule("card-number", "pii", "card-number", re.compile(_B + r"(?:\d[ -]?){12,18}\d" + _E), validate=_luhn_ok),
    Rule("aadhaar", "pii", "aadhaar", re.compile(_B + r"[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}" + _E)),
    Rule("in-phone", "pii", "phone", re.compile(r"(?<![\w+])(?:\+91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}" + _E)),
    Rule("intl-phone", "pii", "phone", re.compile(r"(?<![\w])\+(?:[1-9]\d{0,2})[ -]?\(?\d{2,4}\)?(?:[ -]?\d{2,4}){2,3}" + _E)),
    Rule("pan", "pii", "pan", re.compile(_B + r"[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]" + _E)),
    Rule("ifsc", "pii", "ifsc", re.compile(_B + r"[A-Z]{4}0[A-Z0-9]{6}" + _E)),
    Rule(
        "bank-account",
        "pii",
        "bank-account",
        re.compile(r"(?i)\b(?:a/c|acct|account)(?:\s*(?:no\.?|number|#))?\s*[:#.\-]?\s*(\d{9,18})" + _E),
        group=1,
    ),
]

ALL_RULES = SECRET_RULES + PII_RULES


# --- sensitivity labelling ---------------------------------------------

# Labels need context, not bare keywords: "confidential document storage" in a
# README, `pip install`, "loop termination" or "passport-jwt" must stay Team.
# A text is confidential when it *marks itself* so, or talks about HR, pay,
# health or identity documents.
_MARK = r"(?m)^[\s#>*_\-]*(?:strictly\s+|highly\s+)?{word}\b"

CONFIDENTIAL_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        _MARK.format(word="confidential"),  # "Confidential. Only the club lead…", "## CONFIDENTIAL"
        r"\b(?:strictly|highly)\s+confidential\b",
        r"[\[(#]confidential\b",  # [confidential], (confidential), #confidential
        r"\b(?:this|the|these|it)\s+(?:\w+\s+){0,2}(?:is|are)\s+(?:strictly\s+)?confidential\b",
        r"\b(?:keep|kept|mark|marked|treat|treated)\s+(?:\w+\s+){0,2}(?:as\s+)?confidential\b",
        # Pay needs a person or a pay event: "Rahul's salary", "salary credited", not
        # "employees with a salary greater than 70000" in a SQL exercise.
        r"\b(?:my|his|her|their|your|our|[A-Z][a-z]+'s)\s+(?:salary|ctc|stipend|pay|payslip)\b",
        r"\b(?:salary|ctc|stipend)\s+(?:is|was|of|for|will|revision|hike|increment|details|structure|breakup|"
        r"slip|credited|delayed|pending|amount)\b",
        r"\b(?:stipends|payslips?|payroll (?:sheet|details|data|for))\b",
        r"\b(?:salary|annual|pay)\s+(?:increment|hike|revision)\b",
        r"\bcompensation\s+(?:package|details|revision|structure)\b",
        r"\b(?:appraisals?|performance reviews?|disciplinary|warning letter|termination letter)\b",
        r"\bperformance improvement plan\b",
        r"(?-i:\bPIP\b)",  # only the capitalised acronym, never `pip install`
        r"\b(?:medical (?:leave|condition|report|history|issue)|health issues?|sick leave|diagnosed with)\b",
        r"\b(?:aadhaar|pan card|passport (?:number|no\.?|copy|details))\b",
        _MARK.format(word="hr[- ]only"),  # "HR only: …" as a label, not 'comment says "HR only"'
        r"[\[(]hr[- ]only[\])]",
        r"\bfor hr(?:'s)? eyes only\b",
    ]
]

RESTRICTED_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        _MARK.format(word="restricted"),
        r"\b(?:internal only|internal use only|not for distribution|do not (?:share|forward|circulate))\b",
        r"\bsponsor(?:ship)? (?:contract|agreement|amount|deal)s?\b",
        r"\b(?:quotation|reimburse\w*|bank balance|bank account|treasury)\b",
        r"\b(?:budget (?:sheet|plan|approval|report)|(?:our|the|fest|club|event|total|tech) budget)\b",
        r"\bnda\b",
    ]
]

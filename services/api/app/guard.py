"""Guardrails for what a model reads and writes: prompt injection, leaks, made-up facts.

The project chat reads text anyone on the team could have written (a Slack message, an issue,
a doc), so that text may try to steer the model: "ignore your rules", fake system messages,
fake citation ids, invisible characters, links that smuggle data out. No single defence stops
all of that, so there are several, each cheap and each visible in the audit log:

  1. clean     Unicode is normalised; invisible, direction-changing and "tag" characters
               (used to hide instructions from people) are removed.
  2. fence     source text can't close or fake our tags, boundaries or citation ids.
  3. screen    sentences in sources that talk to an AI ("ignore previous instructions…")
               are cut out before the model sees them; a question that tries to change the
               rules is refused before any model call.
  4. sign      the chat history comes back from the browser, so the assistant's past turns
               carry an HMAC; a forged "assistant said…" turn is dropped.
  5. check     the answer: links and images only to URLs in the sources, no secrets, no
               system prompt (a canary marker gives a leak away), figures must appear in the
               sources, and an answer with no real source is marked as such.
  6. limit     how often one person may ask (in app/routers/rag.py).

The patterns look for text addressed to an AI, not for ordinary team talk: "ignore flaky
tests" or "act as the release owner" pass; "ignore all previous instructions" doesn't.
"""

import base64
import binascii
import codecs
import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass, field

from app import sentinel
from app.config import get_settings

# --- 1. clean --------------------------------------------------------------------------------------

# Invisible or direction-changing characters, and the Unicode "tag" block (U+E0000..E007F), which
# can spell out whole instructions a person never sees.
_INVISIBLE = re.compile(
    r"[­͏؜ᅟᅠ឴឵᠋-᠏​-‏‪-‮"
    r"⁠-⁤⁦-⁩⁪-⁯ㅤ︀-️﻿ﾠ\U000e0000-\U000e007f]"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_TAG_CHARS = re.compile(r"[\U000e0020-\U000e007e]{3,}")


def clean(text: str) -> str:
    """Normalised text with nothing hidden in it."""
    text = unicodedata.normalize("NFKC", text or "")
    text = _CONTROL.sub("", _INVISIBLE.sub("", text))
    return re.sub(r"\n{3,}", "\n\n", text)


def hidden_text(text: str) -> str:
    """What invisible Unicode tag characters in a text spell out (clean() removes them)."""
    return " ".join("".join(chr(ord(c) - 0xE0000) for c in m.group(0)) for m in _TAG_CHARS.finditer(text or ""))


# --- 2. fence --------------------------------------------------------------------------------------

_TAG = re.compile(r"<\s*(/?)\s*(evidence|conversation|system|instructions?)\b([^<>]{0,200})>", re.I)
_CHAT_TOKENS = re.compile(r"<\|[^|<>]{0,30}\|>|\[/?INST\]|<</?SYS>>", re.I)
_REF_LIKE = re.compile(r"\[\s*([CE]\s?\d{1,3})\s*\]")


def fence(text: str) -> str:
    """Source text that can't pass for our own markup: our tags become ‹look-alikes›, chat-template
    tokens are defused, and [C1]-style ids become (C1), so a source can't pose as a citation."""
    text = _TAG.sub(lambda m: f"‹{m.group(1)}{m.group(2)}{m.group(3)}›", text)
    text = _CHAT_TOKENS.sub(lambda m: m.group(0).replace("<", "‹").replace(">", "›").replace("[", "(")
                            .replace("]", ")"), text)
    return _REF_LIKE.sub(lambda m: f"({m.group(1).replace(' ', '')})", text)


# --- 3. screen ---------------------------------------------------------------------------------------

# "bot" is left out on purpose: teams talk to their own bots ("hey bot, deploy staging").
_AI = r"(?:ai|a\.i\.|assistant|model|llm|chatbot|gpt|chatgpt|claude|gemini|qwen|llama|copilot|knowbridge)"
_RULES = r"(?:instructions?|rules|prompts?|guidelines|directions|directives|constraints|guardrails|policies)"
_VERBS_SHOW = r"(?:reveal|print|show|repeat|output|leak|display|dump|share|recite|disclose|tell\s+me|give\s+me)\w*"


def _p(pattern: str, weight: int, kind: str) -> tuple[re.Pattern, int, str]:
    return re.compile(pattern, re.I), weight, kind


# (pattern, weight, kind). A sentence scoring 3 or more is cut; weaker signals only count together.
# Each was checked against ordinary team talk ("ignore the eslint rules", "you are now the owner of
# payments", "from now on, run the tests before merging", "new rules: no deploys on Friday"); the
# red-team suite (redteam/cases.py, tests/test_redteam.py) keeps both sides honest.
PATTERNS: list[tuple[re.Pattern, int, str]] = [
    _p(rf"\b(?:ignore|disregard|forget|override|bypass)\w*\b[^.\n]{{0,30}}\b(?:previous|prior|above|earlier|"
       rf"preceding|your|system|original|initial)\b[^.\n]{{0,25}}\b{_RULES}", 3, "override"),
    _p(rf"\b(?:above|previous|prior|earlier)\s+{_RULES}\s+(?:were|are|was|is)\s+(?:just\s+)?(?:a\s+)?"
       rf"(?:test|fake|wrong|outdated|cancel\w*|void|obsolete)", 3, "override"),
    _p(rf"\b(?:new|updated|revised)\s+system\s+(?:prompt|message|{_RULES})\b", 2, "new-rules"),
    _p(rf"\byour\s+(?:new|real|actual|true|updated|hidden|secret|only)\s+(?:{_RULES}|task|goal|objective|purpose)\b",
       2, "new-rules"),
    _p(rf"\byou\s+are\s+(?:no\s+longer\s+(?:an?\s+)?(?:{_AI}|bound|restricted|limited)|now\s+(?:an?\s+)?"
       rf"(?:unrestricted|unfiltered|uncensored|evil|different|new|free)\b|now\s+in\s+\w+\s+mode|free\s+"
       rf"(?:from|of)\s+(?:your|all|any)|not\s+bound\s+by|now\s+dan\b)", 3, "persona"),
    _p(r"\byou\s+are\s+(?:now\s+)?(?:an?\s+)?(?:unfiltered|uncensored|unrestricted|jailbroken|rogue|evil)\b", 3,
       "persona"),
    _p(rf"\bfrom\s+now\s+on,?\s+(?:you\s+(?:are|will\s+(?:act|behave|pretend|ignore|only|answer))|the\s+{_AI}\b)",
       3, "persona"),
    _p(rf"\b(?:{_VERBS_SHOW}|what\s+(?:is|are)|what'?s)\b[^.\n]{{0,30}}\b(?:system|initial|hidden|original|"
       rf"developer|secret)\s+(?:prompt|{_RULES}|message)", 3, "prompt-leak"),
    _p(r"\b(?:developer|god|dan|jailbreak|unrestricted|unfiltered|sudo)\s+mode\b|\bjailbr(?:eak|oken)\b", 3,
       "jailbreak"),
    _p(r"(?:^|\n|[.!?]\s)[\s#>*]*(?:system|assistant|developer)\s*(?:message|prompt)?\s*:", 2, "role-spoof"),
    _p(r"‹/?(?:evidence|system|conversation|instructions?)\b|‹\|im_|\(/?INST\)", 3, "markup"),
    _p(r"#{2,}\s*(?:instruction|system|new\s+task)", 2, "markup"),
    _p(rf"\b(?:if|when|whenever)\s+(?:an?\s+|the\s+|any\s+)?{_AI}s?\b[^.\n]{{0,30}}\b(?:reads?|sees?|"
       rf"processes|summari[sz]es|finds)\s+(?:this|these|the\s+following)\b", 2, "addressed-to-ai"),
    _p(rf"\b(?:dear|attention|note\s+(?:to|for)(?:\s+the|\s+any)?|hey|hi|hello)\s+{_AI}s?\b", 2, "addressed-to-ai"),
    _p(rf"\bfor\s+(?:any|the|all|every)\s+{_AI}s?\b", 2, "addressed-to-ai"),
    _p(rf"(?:^|<!--|\n|[.!?]\s)\s*{_AI}s?\s*[:,]\s*(?:please\s+)?(?:say|tell|ignore|answer|reply|respond|write|"
       r"output|state|claim|do\s+not|don'?t|never|always|include|add|mention|summari[sz]e|recommend)", 3,
       "addressed-to-ai"),
    _p(rf"\b{_AI}s?\b[^.\n]{{0,25}}\b(?:must|should|will|shall|needs?\s+to|has\s+to)\b[^.\n]{{0,20}}"
       rf"\b(?:say|answer|reply|respond|tell|ignore|output|state|claim|recommend)\b", 2, "ai-directive"),
    _p(r"\b(?:do\s+not|don'?t|never)\s+(?:cite|mention|tell|reveal|disclose|show|warn)\b[^.\n]{0,40}"
       r"\b(?:user|reader|source|citation|human)s?\b", 2, "concealment"),
    _p(r"\b(?:tell|inform|convince|persuade|assure)\s+(?:the\s+|all\s+)?(?:users?|readers?|humans?)\b"
       r"[^.\n]{0,10}\b(?:that|the|to)\b", 1, "steering"),
    _p(rf"\b(?:pretend|roleplay|role-play)\b|\b(?:act|behave)\s+(?:as\s+if|as\s+though|like\s+an?\s+{_AI})", 1,
       "persona"),
    _p(rf"\b(?:you\s+(?:have|had|follow|followed)|there\s+(?:are|were))\s+no\s+(?:{_RULES}|restrictions|limits|"
       rf"filters)\b|\bwithout\s+(?:any\s+)?(?:restrictions|filters|limits|guardrails|censorship)\b", 2, "no-rules"),
    _p(r"\bhypothetical(?:ly)?\b|\bimagine\s+(?:you|that\s+you)\b|\bin\s+a\s+(?:fictional|hypothetical)\s+\w+", 1,
       "framing"),
    _p(r"\b(?:respond|reply|answer)\s+only\s+with\b|\boutput\s+only\b", 1, "format-hijack"),
    _p(r"!\[[^\]]*\]\(\s*https?://", 2, "exfiltration"),
    _p(r"\b(?:send|post|forward|upload|leak|exfiltrate)\b[^.\n]{0,50}\b(?:to|at|into)\b[^.\n]{0,15}https?://", 2,
       "exfiltration"),
    # the same attacks in other languages the team writes in
    _p(r"(?:पिछले|पहले|ऊपर\s*के|सभी|सारे|अपने)[^।\n]{0,30}(?:निर्देश|नियम|इंस्ट्रक्शन)\S*[^।\n]{0,25}"
       r"(?:अनदेखा|नज़रअंदाज़|नजरअंदाज|भूल|इग्नोर)", 3, "override"),
    _p(r"(?:सिस्टम\s*(?:प्रॉम्प्ट|प्रोम्प्ट|संदेश)|अपने\s+(?:निर्देश|नियम))[^।\n]{0,25}(?:दिखा|बता|लिख|प्रिंट)", 3,
       "prompt-leak"),
    _p(r"\b(?:pichle|pichhle|pehle|pahle|upar\s+ke|saare|sare|sabhi|apne|purane)\b[^.\n]{0,25}\b(?:instructions?|"
       r"rules|niyam|nirdesh)\b[^.\n]{0,20}\b(?:ignore|bhool|bhul|nazarandaz|mat\s+maano|mat\s+mano)", 3, "override"),
    _p(r"\b(?:ignore|bhool|bhul)\w*\s+(?:karo|kar\s+do|jao)\b[^.\n]{0,25}\b(?:instructions?|rules|niyam)", 3,
       "override"),
    _p(r"\b(?:system\s+prompt|apne\s+(?:instructions|rules|niyam))\b[^.\n]{0,25}\b(?:dikhao|dikha\s+do|batao|"
       r"bata\s+do|likho|print\s+karo|bolo)", 3, "prompt-leak"),
    _p(r"\b(?:ignora|ignore|olvida|olvide|omite|descarta)\w*\s+(?:todas?\s+)?(?:las|tus|sus)\s+(?:\w+\s+)?"
       r"(?:instrucciones|reglas|indicaciones|órdenes)", 3, "override"),
    _p(r"\b(?:ignore[rz]?|oublie[rz]?)\s+(?:toutes\s+)?(?:les|tes|vos)\s+(?:\w+\s+)?(?:instructions|règles|consignes)",
       3, "override"),
    _p(r"\b(?:ignorier\w*|vergiss\w*|missacht\w*)\b[^.\n]{0,30}\b(?:anweisungen|regeln|vorgaben|befehle|"
       r"instruktionen)\b", 3, "override"),
    _p(r"\b(?:ignore|ignora|esque[cç]a)\s+(?:todas\s+)?(?:as\s+)?(?:suas\s+)?(?:\w+\s+)?(?:instru[cç][oõ]es|regras)",
       3, "override"),
    _p(r"\b(?:prompt|instrucciones|mensaje)\s+del\s+sistema\b|\b(?:prompt|message|instructions)\s+(?:du\s+)?"
       r"syst[eè]me\b|\bsystem-?(?:prompt|anweisung\w*|nachricht)\b", 2, "prompt-leak"),
]

# Only in a question: asking about the assistant itself (its prompt, rules, marker) or claiming
# authority over it. In a source these phrases are ordinary ("follow your instructions in the README").
QUESTION_PATTERNS: list[tuple[re.Pattern, int, str]] = [
    _p(r"\b(?:your|ur|the\s+(?:assistant|ai|bot|model)'?s?)\s+(?:own\s+|real\s+|exact\s+|full\s+|initial\s+|"
       r"original\s+|hidden\s+|secret\s+|internal\s+)?(?:system\s+)?(?:prompt|instructions|rules|guidelines|"
       r"configuration|config|guardrails|constraints|directives|programming|marker|canary)\b", 3,
       "about-the-assistant"),
    _p(r"\bsystem[\s_-]*(?:prompt|message|instructions?)\b", 2, "prompt-leak"),
    _p(r"\bwhat\s+(?:were|have)\s+you\s+(?:been\s+)?(?:told|given|instructed|programmed)\b", 3, "prompt-leak"),
    _p(r"\b(?:repeat|print|output|recite|copy|echo|dump|show|write)\w*\b[^.\n]{0,40}\b(?:words|text|everything|"
       r"anything|content|lines?)\b[^.\n]{0,25}\b(?:above|before|preceding|prior|earlier|so\s+far|between)\b", 3,
       "prompt-leak"),
    _p(r"\bhere\s+(?:is|are)\s+(?:my|the|your)\s+(?:system\s+)?(?:prompt|instructions|rules)\b", 3, "prompt-leak"),
    _p(r"<\s*/?\s*evidence\b", 3, "markup"),
    _p(r"\b(?:i\s*(?:'m|am)|this\s+is)\s+(?:the|an?|your)\s+(?:admin|administrator|developer|owner|creator|ceo|"
       r"security\s+(?:team|auditor)|auditor|boss)\b", 1, "authority"),
    _p(r"\b(?:i\s+)?(?:authori[sz]e|permit|allow|grant)\w*\s+you\s+to\b", 2, "authority"),
    _p(r"\b(?:show|give|reveal|list|tell)\w*\b[^.\n]{0,30}\b(?:confidential|restricted|classified|private)\b", 1,
       "authority"),
]
THRESHOLD = 3
REMOVED = "[text addressed to an AI removed]"
_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=\S)|\n+")
_SPLIT = re.compile(r"((?<=[.!?])\s+(?=\S)|\n+)")

# Ways an attack hides from a reader but not from a model.
_LOOKALIKES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ɡ": "g", "һ": "h", "ӏ": "l",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "Х": "X", "І": "I", "ο": "o", "α": "a",
    "ε": "e", "ι": "i", "κ": "k", "ρ": "p", "τ": "t", "υ": "u", "ν": "v",
})
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_SPACED = re.compile(r"\b(?:[^\W_][ ._*-]){3,}[^\W_]\b")
_B64 = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")


def _decoded(text: str) -> list[str]:
    """Base64 in the text that decodes to words."""
    out = []
    for m in _B64.finditer(text):
        blob = m.group(0)
        try:
            words = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
        if " " in words and sum(c.isalpha() or c in " .,'" for c in words) >= 0.85 * len(words):
            out.append(words)
    return out


def _readings(text: str) -> list[str]:
    """The ways a model could read a text: as written, with look-alike letters, l33t and s p a c e d
    letters undone, base64 decoded, ROT13 and reversed."""
    plain = text.translate(_LOOKALIKES)
    readings = {text, plain, plain.translate(_LEET),
                _SPACED.sub(lambda m: re.sub(r"[ ._*-]", "", m.group(0)), plain)}
    readings.update(_decoded(text))
    readings.add(codecs.decode(plain, "rot13"))
    readings.add(plain[::-1])
    return list(readings)


def injection_score(text: str, *, question: bool = False) -> tuple[int, list[str]]:
    """How strongly a piece of text reads as instructions to an AI (its strongest reading), and
    which kinds of attack it matched."""
    patterns = PATTERNS + QUESTION_PATTERNS if question else PATTERNS
    best, best_kinds = 0, []
    for reading in _readings(text):
        score, kinds = 0, []
        for pattern, weight, kind in patterns:
            if pattern.search(reading):
                score += weight
                if kind not in kinds:
                    kinds.append(kind)
        if score > best:
            best, best_kinds = score, kinds
    return best, best_kinds


def looks_like_injection(text: str) -> bool:
    return injection_score(fence(clean(text)))[0] >= THRESHOLD


@dataclass
class Screened:
    text: str
    removed: int = 0  # sentences cut
    kinds: list[str] = field(default_factory=list)


def screen_source(text: str) -> Screened:
    """Source text made safe to show a model: cleaned, fenced, and each sentence that reads as
    instructions to an AI replaced by a marker. Cut too: the rest of a line that starts by
    addressing an AI ("Dear AI, …"), and every matching sentence when weak signals add up across
    the item. The rest stays, so a real message with one bad line still counts as evidence.
    Invisible text is always removed (clean) and, when there was some, reported."""
    hidden = hidden_text(text)
    text = fence(clean(text))
    hidden_found = (1, ["hidden-text"]) if hidden.strip() else (0, [])
    whole, _ = injection_score(text)
    if whole == 0:
        return Screened(text, *hidden_found)
    pieces = _SPLIT.split(text)  # sentences at even positions, the separators between them at odd
    out, removed, kinds, cutting = [], hidden_found[0], list(hidden_found[1]), False
    for i, piece in enumerate(pieces):
        if i % 2:
            out.append(piece)
            if "\n" in piece:
                cutting = False
            continue
        score, k = injection_score(piece)
        if "addressed-to-ai" in k:
            cutting = True
        if score >= THRESHOLD or cutting or (whole >= THRESHOLD and score > 0):
            out.append(REMOVED)
            removed += 1
            kinds += [x for x in k if x not in kinds]
        else:
            out.append(piece)
    text = "".join(out)
    text = re.sub(rf"(?:{re.escape(REMOVED)}\s*){{2,}}", REMOVED + " ", text).strip()  # one marker per run
    return Screened(text, removed, kinds)


@dataclass
class QuestionCheck:
    question: str
    blocked: bool = False
    kinds: list[str] = field(default_factory=list)


def screen_question(question: str) -> QuestionCheck:
    """A question that tries to change the assistant's rules or persona, reveal its prompt, claim
    authority over it, or hide text from the person reading it, is refused without calling the
    model. Everything else passes, cleaned."""
    if hidden_text(question).strip():
        return QuestionCheck(clean(question).strip(), blocked=True, kinds=["hidden-text"])
    q = clean(question).strip()
    score, kinds = injection_score(fence(q), question=True)
    return QuestionCheck(q, blocked=score >= THRESHOLD, kinds=kinds)


# --- 4. sign -----------------------------------------------------------------------------------------


def _key(purpose: str) -> bytes:
    return hmac.new(get_settings().api_jwt_secret.encode(), purpose.encode(), hashlib.sha256).digest()


def sign_turn(user_id: object, project_id: object, content: str) -> str:
    """A tag proving this server wrote this answer, for this person, in this project."""
    digest = hashlib.sha256(content.encode()).hexdigest()
    return hmac.new(_key("chat-turn"), f"{user_id}|{project_id}|{digest}".encode(), hashlib.sha256).hexdigest()[:32]


def turn_is_ours(user_id: object, project_id: object, content: str, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(sign_turn(user_id, project_id, content), token or "")


def canary() -> str:
    """A marker only the system prompt contains: seeing it in an answer means the prompt leaked."""
    return "kb-" + hmac.new(_key("canary"), b"marker", hashlib.sha256).hexdigest()[:12]


def boundary(context: str) -> str:
    """An id for the record's start and end tags that a source can't guess (it depends on a
    server secret) but stays the same for the same record, so cached answers still work."""
    return hmac.new(_key("boundary"), context.encode(), hashlib.sha256).hexdigest()[:10]


# --- 5. check ----------------------------------------------------------------------------------------

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]{1,200})\]\(\s*(https?://[^)\s]+)\s*\)")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>()\[\]\"']+", re.I)
_HTML = re.compile(r"<\s*(?:img|script|iframe|a|link|style|object|embed|svg|form|input)\b[^>]*>", re.I)
_FIGURE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")
_CITE = re.compile(r"\[[CE]\d{1,3}\]")


@dataclass
class OutputCheck:
    text: str
    blocked: str = ""  # why the whole answer was withheld
    removed_links: int = 0
    redacted: int = 0
    unsupported_figures: list[str] = field(default_factory=list)
    uncited_sentences: int = 0

    def notes(self) -> dict:
        return {"removed_links": self.removed_links, "redacted": self.redacted,
                "unsupported_figures": self.unsupported_figures, "uncited_sentences": self.uncited_sentences}


def _norm_number(s: str) -> str:
    return s.replace(",", "").rstrip(".")


def check_output(answer: str, context: str, system_prompt: str) -> OutputCheck:
    """The model's answer, made safe to show and to copy: see the module docstring, step 5."""
    text = clean(answer)
    # the system prompt must never come back (the canary, or a long verbatim piece of it)
    if canary().lower() in text.lower() or _shares_long_run(text, system_prompt):
        return OutputCheck("", blocked="prompt-leak")

    allowed = {u.rstrip(".,;:") for u in _URL.findall(context)}
    removed = 0

    def link(m: re.Match) -> str:
        nonlocal removed
        if m.group(2).rstrip(".,;:") in allowed:
            return f"{m.group(1)} ({m.group(2)})"
        removed += 1
        return m.group(1)

    def bare(m: re.Match) -> str:
        nonlocal removed
        url = m.group(0).rstrip(".,;:")
        if url in allowed:
            return m.group(0)
        removed += 1
        return "[link removed]"

    before = len(_IMAGE.findall(text)) + len(_HTML.findall(text))
    text = _HTML.sub("", _IMAGE.sub("", text))
    removed += before
    text = _MD_LINK.sub(link, text)
    text = _URL.sub(bare, text)

    scan = sentinel.scan(text)  # secrets and personal data, the same rules as at ingest
    text = scan.text

    # every figure must be somewhere in the sources (dates and counts are where models slip)
    context_numbers = {_norm_number(n) for n in _FIGURE.findall(context)}
    unsupported = []
    for n in _FIGURE.findall(_CITE.sub("", text)):
        v = _norm_number(n)
        if len(v) >= 2 and v not in context_numbers and v not in unsupported:
            unsupported.append(v)

    sentences = [s for s in _SENTENCES.split(text) if len(s.split()) >= 6]
    uncited = sum(1 for s in sentences if not _CITE.search(s))
    return OutputCheck(re.sub(r"[ \t]{2,}", " ", text).strip(), removed_links=removed, redacted=len(scan.findings),
                       unsupported_figures=unsupported[:6], uncited_sentences=uncited)


def _shares_long_run(text: str, system_prompt: str, size: int = 60) -> bool:
    """True when the answer repeats any 60-character stretch of the system prompt."""
    a = re.sub(r"\s+", " ", text.lower())
    b = re.sub(r"\s+", " ", system_prompt.lower())
    return any(b[i: i + size] in a for i in range(0, max(0, len(b) - size), 20))

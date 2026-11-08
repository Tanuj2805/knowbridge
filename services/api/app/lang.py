"""Tags text as English, Hinglish (romanised Hindi mixed with English) or
Devanagari Hindi. Cheap and deterministic: it only drives a metric and a
hint to the agents, never a decision."""

import re

# Common romanised Hindi function words and fillers. Short English words that
# collide (to, me, the) are left out on purpose.
_HINGLISH = {
    "hai", "hain", "tha", "thi", "ho", "hoga", "hogi", "kya", "kyu", "kyun", "kyunki", "nahi", "nahin",
    "nai", "haan", "han", "acha", "accha", "achha", "theek", "thik", "bhai", "yaar", "kar", "karo", "karna",
    "karenge", "kiya", "kiye", "raha", "rahi", "rahe", "wala", "wali", "wale", "abhi", "kal", "aaj", "phir",
    "fir", "matlab", "bas", "sab", "sabko", "mujhe", "tujhe", "humko", "hum", "tum", "aap", "apna", "apni",
    "uska", "uski", "iska", "iski", "mein", "pe", "par", "se", "ko", "ka", "ki", "ke", "aur", "ya", "lekin",
    "toh", "jaldi", "zaroor", "chalo", "dekho", "dekh", "bata", "batao", "bol", "bolo", "pata", "samjha",
    "chahiye", "sakta", "sakti", "sakte", "gaya", "gayi", "diya", "liya", "wapas", "kaam", "baad", "pehle",
    "jab", "tab", "kaise", "kahan", "kaun", "kitna", "kitne", "bilkul", "arre", "arey", "na", "hona",
}
_WORD = re.compile(r"[A-Za-z]+")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def detect(text: str) -> str:
    if len(_DEVANAGARI.findall(text)) > 5:
        return "hi"
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < 3:
        return "en"
    hits = sum(1 for w in words if w in _HINGLISH)
    return "hi-en" if hits >= 2 and hits / len(words) >= 0.12 else "en"

"""Text clean-up for the fix stage: normalisation, dehyphenation, OCR heading artifacts, language."""

import re
import unicodedata
from dataclasses import replace

from eco.book import Block

_LIGATURES = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"})
_SPACE_RUN = re.compile(" {2,}")
_HYPHEN_BREAK = re.compile(r"(\w+)[-–]\s+(\w+)")
_SENTENCE_END = (".", "!", "?", ":", ";", '"', "”", ")")

_SHORT_WORDS = {
    "id": {"di", "ke"},
    "en": {
        "a",
        "an",
        "as",
        "at",
        "be",
        "by",
        "do",
        "go",
        "he",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "no",
        "of",
        "on",
        "or",
        "so",
        "to",
        "up",
        "us",
        "we",
    },
}

_STOPWORDS = {
    "id": {"yang", "dan", "di", "ini", "itu", "dengan", "untuk", "tidak", "dari", "dalam"},
    "en": {"the", "and", "of", "to", "is", "in", "that", "for", "with", "it"},
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_LIGATURES)
    return _SPACE_RUN.sub(" ", text)


def dehyphenate(blocks: list[Block]) -> tuple[list[Block], int]:
    """Join words split at a line end. Returns the new blocks and the number of joins."""
    vocabulary = {
        w.lower() for b in blocks if b.kind == "paragraph" for w in re.findall(r"\w+", b.text)
    }
    joins = 0

    def fix(match: re.Match) -> str:
        nonlocal joins
        first, second = match.groups()
        if not second[0].islower():
            return match.group(0)
        # ponytail: the brief's "or neither part is" cannot happen, both parts are always in the
        # vocabulary (fragments count), so only the joined word decides.
        if (first + second).lower() in vocabulary:
            joins += 1
            return first + second
        return f"{first}-{second}"

    out = [
        replace(b, text=_HYPHEN_BREAK.sub(fix, b.text)) if b.kind == "paragraph" else b
        for b in blocks
    ]
    return out, joins


def _letters(token: str) -> str:
    return "".join(c for c in token if c.isalpha()).lower()


def clean_heading_artifacts(text: str, lang: str | None = None) -> str:
    """Drop OCR artifacts from a heading: stray 1-2 letter tokens and a glued first letter.

    `lang` protects the real short words of that language from the stray-token rule.
    """
    protected = _SHORT_WORDS.get(lang or "", set())
    tokens = text.split()
    kept = []
    for i, token in enumerate(tokens):
        prev = _letters(tokens[i - 1]) if i else ""
        nxt = _letters(tokens[i + 1]) if i + 1 < len(tokens) else ""
        # ponytail: also turns a real "iPhone" after a word ending in "i" into "Phone".
        if token[:1].islower() and token[1:2].isupper() and prev.endswith(token[0]):
            kept.append(token[1:])
            continue
        letters = token.lower()
        stray = token.isalpha() and len(token) <= 2 and letters not in protected
        if stray and ((prev and prev.endswith(letters)) or (nxt and nxt.startswith(letters))):
            continue
        kept.append(token)
    return " ".join(kept)


def join_split_paragraphs(blocks: list[Block]) -> list[Block]:
    """Merge a paragraph into the previous one when the previous has no sentence end."""
    out: list[Block] = []
    for block in blocks:
        prev = out[-1] if out else None
        if (
            prev
            and prev.kind == block.kind == "paragraph"
            and prev.text
            and not prev.text.rstrip().endswith(_SENTENCE_END)
            and block.text[:1].islower()
        ):
            out[-1] = replace(prev, text=prev.text + " " + block.text)
        else:
            out.append(block)
    return out


def detect_language(text: str) -> str:
    words = re.findall(r"\w+", text.lower())
    counts = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS.items()}
    return "id" if counts["id"] > counts["en"] else "en"

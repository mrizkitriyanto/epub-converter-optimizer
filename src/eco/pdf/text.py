"""Text clean-up for the fix stage: normalisation, dehyphenation, OCR heading artifacts, language."""

import re
import unicodedata
from collections import Counter
from dataclasses import replace

from eco.book import Block

_LIGATURES = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"})
_SPACE_RUN = re.compile(" {2,}")
# A hyphen, en dash or em dash after a word (OCR reads a hyphen as either dash), then a line
# break, then a word: the word before it whole, as its start, the fragment, the dash and the
# fragment after. In a table cell, a hyphen or en dash and a space instead of the line break,
# between letters or digits; in text "-rw-rw-rw- 1" and "first- and" inside a line stay as they
# are, since there they cannot be told apart from a split.
_BREAK = re.compile(r"(?<!\S)(\S*?)(\w+)([-–—])\n[ \t]*(\w+)")
_CELL_BREAK = re.compile(r"(?<!\S)(\S*?)([^\W_]+)([-–]) +([^\W_]+)")
_BREAK_FRAGMENT = re.compile(r"\w+(?=[-–—]\n)|(?<=[-–—]\n)[ \t]*\w+")
_CELL_FRAGMENT = re.compile(r"[^\W_]+(?=[-–] +[^\W_])|(?<=[^\W_][-–] )[^\W_]+")
_TAG = re.compile(r"(<[^>]*>)")
_NOT_PROSE = {"formula", "image", "picture"}  # their text is a formula, code or an alt text
_SENTENCE_END = (".", "!", "?", ":", ";", '"', "”", ")")

_SHORT_WORDS = {
    "id": {"di", "ia", "ke", "si", "ya"},
    "en": {
        "a",
        "am",
        "an",
        "as",
        "at",
        "be",
        "by",
        "do",
        "go",
        "he",
        "if",
        "i",
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


def _vocabulary(blocks: list[Block]) -> Counter[str]:
    """The words of the whole book, lowercase, except the fragments at its line-end breaks."""
    words: Counter[str] = Counter()
    for b in blocks:
        cells = _TAG.split(b.html)[::2]  # the text between the tags of a table
        texts = [_BREAK_FRAGMENT.sub(" ", t) for t in (b.text, b.caption)]
        texts += [_CELL_FRAGMENT.sub(" ", t) for t in cells]
        words.update(w.lower() for t in texts for w in re.findall(r"\w+", t))
    return words


def dehyphenate(blocks: list[Block]) -> tuple[list[Block], int]:
    """Decide every hyphen that ended a line (spec section 8.4.6). Returns the new blocks and the
    number of words joined.

    The adapter keeps such a hyphen with its line break (`seper-\\ntinya`); a table cell has a
    space instead, as Docling's table model joins the words of a cell with spaces. The split joins
    when the joined word appears elsewhere in the book, or when a fragment appears nowhere else as
    a word of its own; otherwise the hyphen stays, with no space. A digit on either side, or a word
    that holds "/" or ".", always keeps its hyphen. With a capital after the break, or with an em
    dash (a real one is common), only the joined word decides. A word that already holds a hyphen
    is decided on its last part. A hyphen inside a line is left alone, and so is the text of code,
    a formula or an image, which is no prose; a caption is.
    """
    vocabulary = _vocabulary(blocks)
    joins = 0

    def fix(match: re.Match) -> str:
        nonlocal joins
        prefix, first, dash, second = match.groups()
        kept, joined = prefix + first + dash + second, prefix + first + second
        if first[-1].isdigit() or second[0].isdigit() or "/" in prefix or "." in prefix:
            return kept
        if not vocabulary[(first + second).lower()] and (
            second[0].isupper()
            or dash == "—"
            or (vocabulary[first.lower()] and vocabulary[second.lower()])
        ):
            return kept
        joins += 1
        return joined

    def text(value: str) -> str:
        while (fixed := _BREAK.sub(fix, value)) != value:  # again for a word over three lines
            value = fixed
        return value

    def html(value: str) -> str:
        parts = _TAG.split(value)
        return "".join(p if i % 2 else _CELL_BREAK.sub(fix, p) for i, p in enumerate(parts))

    out = [
        b
        if b.kind == "code"
        else replace(
            b,
            text=b.text if b.kind in _NOT_PROSE else text(b.text),
            caption=text(b.caption),
            html=html(b.html),
        )
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
            # a hyphen at the page end keeps its line break, the form dehyphenate decides
            gap = "\n" if re.search(r"\w[-–—]$", prev.text) else " "
            out[-1] = replace(prev, text=prev.text + gap + block.text)
        else:
            out.append(block)
    return out


def detect_language(text: str) -> str:
    words = re.findall(r"\w+", text.lower())
    counts = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS.items()}
    return "id" if counts["id"] > counts["en"] else "en"

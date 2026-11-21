import re
from collections import Counter
from collections.abc import Callable

# an unclosed comment runs to the end of the text, as in CSS, so a scan for "*/" is never repeated
_COMMENT = re.compile(r"/\*.*?(?:\*/|\Z)", re.DOTALL)
_FONT_FACE = re.compile(r"@font-face\s*\{[^}]*\}", re.IGNORECASE)
# A declaration, name: value, up to ";", "}" or the end, with a "*" before the name (an old IE
# hack) kept with it. It starts only at the start of the text or after "{", ";" or a nested
# block's "}", where `lead` takes the white space and comments before it: tried at every
# position, a run like "a:a:a:...{" took quadratic time. Strings and (...) groups, like
# url(data:...;base64,...), are atomic. Outside a declaration `skip` steps over a string, group
# or comment whole, to the end of the text if it is not closed, so one that never closes is
# scanned once.
_DECLARATION = re.compile(
    r"""(?P<lead>(?:\A|(?<=[{;}]))(?:\s|/\*.*?\*/)*)"""
    r"""(?P<head>\*?(?P<name>[-\w]+)\s*:\s*)(?P<value>(?:[^;{}()"']|"[^"]*"|'[^']*'|\([^)]*\))*)"""
    r"(?P<end>;|(?=\})|$)"
    r"""|(?P<skip>"[^"\n]*"?|'[^'\n]*'?|\([^)]*\)?|/\*.*?(?:\*/|\Z))""",
    re.DOTALL,
)
_URL = re.compile(r"""url\(\s*(["']?)(.*?)\1\s*\)""", re.IGNORECASE)
_LAYOUT = re.compile(r"(?:-\w+-)?(?:float|position|columns|column-count)", re.IGNORECASE)
_FLEX_OR_GRID = re.compile(r"(?:-\w+-)?(?:inline-)?(?:flex|grid)", re.IGNORECASE)

# On Xteink the reader's own text size, spacing and margins rule: absolute sizes become relative
# to 16 px, colors go (text black on white), and the page box of html and body loses its margins.
# one way to read each number, so a long run of digits is scanned once
_ABSOLUTE = re.compile(
    r"(?<![\w.-])(-?(?:\d+(?:\.\d*)?|\.\d+))(px|pt|pc|in|cm|mm)\b", re.IGNORECASE
)
_PX = {"px": 1, "pt": 4 / 3, "pc": 16, "in": 96, "cm": 96 / 2.54, "mm": 96 / 25.4}
_KEYWORD_EM = {
    "xx-small": 0.6,
    "x-small": 0.75,
    "small": 0.89,
    "medium": 1,
    "large": 1.2,
    "x-large": 1.5,
    "xx-large": 2,
    "xxx-large": 3,
}
_COLORS = {"color", "background", "background-color", "background-image"}
_SPACING = re.compile(r"(?:margin|padding)(?:-(?:top|right|bottom|left))?", re.IGNORECASE)
_IMPORTANT = re.compile(r"!\s*important\s*$", re.IGNORECASE)  # no leading \s*: linear
# starts only at the start or after "{", "}" or ";", so a run without them is scanned once
_BLOCK = re.compile(r"(?:\A|(?<=[{};]))(?P<sel>[^{};]*)\{(?P<body>[^{}]*)\}")
# starts only at the start of a rule body or after ";", like _DECLARATION, so a run of white
# space is scanned once and a longer name (-webkit-padding-start) is never matched inside
_BOX_DECLARATION = re.compile(
    r"(?:\A|(?<=;))(?P<lead>\s*)(?P<name>(?:margin|padding)(?:-[a-z]+)?)\s*:\s*(?P<value>[^;]*)(?:;|$)",
    re.IGNORECASE,
)
_MAX_SPACING_PX = 32  # 2em
# the size, and an optional line height after "/", of a font shorthand: the first one, whole
# tokens only, so small-caps is no size and a run of digits is scanned once
_FONT_SIZE = re.compile(
    r"(?<![\w./-])(?:(?P<abs>-?(?:\d+(?:\.\d*)?|\.\d+)(?:px|pt|pc|in|cm|mm))"
    r"|(?P<rel>-?(?:\d+(?:\.\d*)?|\.\d+)(?:%|r?em|ex|ch))"
    r"|(?P<kw>xx-small|x-small|small|medium|large|x-large|xx-large|xxx-large))(?![\w.%-])"
    r"(?:\s*/\s*(?P<lh>-?(?:\d+(?:\.\d*)?|\.\d+)(?:px|pt|pc|in|cm|mm))(?![\w.-]))?",
    re.IGNORECASE,
)
_BODY_SELECTOR = re.compile(r"body(?:[.#][\w-]+)+")
_PAGE_SELECTOR = re.compile(r"@page(?:\s*:[\w-]+)?")
_CLASS_SELECTOR = re.compile(r"\.([\w-]+)")


def _number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


def _px(m: re.Match) -> float:
    return float(m[1]) * _PX[m[2].lower()]


def _relative(name: str, value: str) -> str | None:
    """The value of a size declaration made relative, or None when it stays as written."""
    important = _IMPORTANT.search(value)
    core = value[: important.start()] if important else value
    text = core.strip()
    lowered = name.lower()
    new = None
    if lowered == "font-size":
        absolute = _ABSOLUTE.fullmatch(text)
        if text.lower() in _KEYWORD_EM:
            new = f"{_number(_KEYWORD_EM[text.lower()])}em"
        elif absolute:
            new = f"{_number(_px(absolute) / 16)}em"
    elif lowered == "font":
        found = _FONT_SIZE.search(text)
        if found:
            if found["rel"]:  # a relative size stays; the size comes before the family, so the
                size = found["rel"]  # search stops here and a family name is never read
            elif found["kw"]:
                size = f"{_number(_KEYWORD_EM[found['kw'].lower()])}em"
            else:
                size = f"{_number(_px(_ABSOLUTE.fullmatch(found['abs'])) / 16)}em"
            if found["lh"]:
                size += "/" + _number(max(1.2, _px(_ABSOLUTE.fullmatch(found["lh"])) / 16))
            new = text[: found.start()] + size + text[found.end() :]
    elif lowered == "line-height":
        absolute = _ABSOLUTE.fullmatch(text)
        if absolute:
            new = _number(max(1.2, _px(absolute) / 16))
    elif _SPACING.fullmatch(lowered):
        new = _ABSOLUTE.sub(lambda m: "2em" if _px(m) > _MAX_SPACING_PX else m[0], text)
    if new is None or new == text:
        return None
    trailing = core[len(core.rstrip()) :]
    return (
        core[: len(core) - len(core.lstrip())]
        + new
        + trailing
        + (important[0] if important else "")
    )


def _is_page_box(selector: str, page_classes: frozenset[str]) -> bool:
    """html, body, body with classes or an id, @page, or a class the book puts on its <body>."""
    if selector in ("html", "body") or _BODY_SELECTOR.fullmatch(selector):
        return True
    if _PAGE_SELECTOR.fullmatch(selector):
        return True
    found = _CLASS_SELECTOR.fullmatch(selector)
    return bool(found) and found[1] in page_classes


def _drop_box(declarations: str, counts: Counter | None) -> str:
    """A declaration list without its absolute margins and paddings."""

    def drop(d: re.Match) -> str:
        if not _ABSOLUTE.search(d["value"]):
            return d[0]
        if counts is not None:
            counts["sizes"] += 1
        return ""

    return _BOX_DECLARATION.sub(drop, declarations)


def _page_box(m: re.Match, counts: Counter | None, page_classes: frozenset[str]) -> str:
    """A rule for the page box loses its absolute margins and paddings."""
    selectors = [s.strip().lower() for s in m["sel"].split(",")]
    if not all(_is_page_box(s, page_classes) for s in selectors):
        return m[0]
    return m["sel"] + "{" + _drop_box(m["body"], counts) + "}"


def rewrite_css(
    text: str,
    retarget: Callable[[str], str | None],
    xteink: bool = False,
    counts: Counter | None = None,
    page_classes: frozenset[str] = frozenset(),
    page_box: bool = False,
) -> str:
    """Rewrite the url() of every declaration in a stylesheet, a <style> or a style attribute.

    `retarget` maps a url to its new value, or to None when its file is gone: the declaration
    goes with it. With `xteink`, comments, @font-face blocks and the declarations an e-ink
    reader cannot lay out (float, position, columns, flex and grid) go too; absolute sizes become
    relative, colors go, and html and body lose their absolute margins. `counts` adds up the
    sizes changed ("sizes") and the colors removed ("colors"). `page_classes` are the classes of
    the book's <body> elements, whose rules count as the page box too; `page_box` says that
    `text` is the style attribute of <body>.
    """
    if xteink:
        text = _FONT_FACE.sub("", _COMMENT.sub("", text))
        if page_box:
            text = _drop_box(text, counts)
        text = _BLOCK.sub(lambda m: _page_box(m, counts, page_classes), text)
    return _DECLARATION.sub(lambda m: _declaration(m, retarget, xteink, counts), text)


def _declaration(
    m: re.Match,
    retarget: Callable[[str], str | None],
    xteink: bool,
    counts: Counter | None = None,
) -> str:
    if m["skip"] is not None:
        return m[0]
    lead, name, value = m["lead"], m["name"], m["value"]
    if xteink and (
        _LAYOUT.fullmatch(name)
        or name.lower() == "display"
        and _FLEX_OR_GRID.fullmatch(value.split("!")[0].strip())
    ):
        return lead
    if xteink and name.lower() in _COLORS:
        if counts is not None:
            counts["colors"] += 1
        return lead
    if xteink and (relative := _relative(name, value)) is not None:
        if counts is not None:
            counts["sizes"] += 1
        value = relative
    gone = False

    def swap(url: re.Match) -> str:
        nonlocal gone
        new = retarget(url[2])
        if new is None:
            gone = True
        return url[0] if new is None or new == url[2] else f"url({url[1]}{new}{url[1]})"

    value = _URL.sub(swap, value)
    return lead if gone else lead + m["head"] + value + m["end"]

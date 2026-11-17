import re
from collections.abc import Callable

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_FONT_FACE = re.compile(r"@font-face\s*\{[^}]*\}", re.IGNORECASE)
# name: value, up to ";", "}" or the end; strings and (...) groups, like url(data:...;base64,...),
# are atomic
_DECLARATION = re.compile(
    r"""(?P<head>(?P<name>[-\w]+)\s*:\s*)(?P<value>(?:[^;{}()"']|"[^"]*"|'[^']*'|\([^)]*\))*)"""
    r"(?P<end>;|(?=\})|$)"
)
_URL = re.compile(r"""url\(\s*(["']?)(.*?)\1\s*\)""", re.IGNORECASE)
_LAYOUT = re.compile(r"(?:-\w+-)?(?:float|position|columns|column-count)", re.IGNORECASE)
_FLEX_OR_GRID = re.compile(r"(?:-\w+-)?(?:inline-)?(?:flex|grid)", re.IGNORECASE)


def rewrite_css(text: str, retarget: Callable[[str], str | None], xteink: bool = False) -> str:
    """Rewrite the url() of every declaration in a stylesheet, a <style> or a style attribute.

    `retarget` maps a url to its new value, or to None when its file is gone: the declaration
    goes with it. With `xteink`, comments, @font-face blocks and the declarations an e-ink
    reader cannot lay out (float, position, columns, flex and grid) go too.
    """
    if xteink:
        text = _FONT_FACE.sub("", _COMMENT.sub("", text))
    return _DECLARATION.sub(lambda m: _declaration(m, retarget, xteink), text)


def _declaration(m: re.Match, retarget: Callable[[str], str | None], xteink: bool) -> str:
    name, value = m["name"], m["value"]
    if xteink and (
        _LAYOUT.fullmatch(name)
        or name.lower() == "display"
        and _FLEX_OR_GRID.fullmatch(value.split("!")[0].strip())
    ):
        return ""
    gone = False

    def swap(url: re.Match) -> str:
        nonlocal gone
        new = retarget(url[2])
        if new is None:
            gone = True
        return url[0] if new is None or new == url[2] else f"url({url[1]}{new}{url[1]})"

    value = _URL.sub(swap, value)
    return "" if gone else m["head"] + value + m["end"]

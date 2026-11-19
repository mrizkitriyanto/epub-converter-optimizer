"""Named page styles and the default style in one data directory."""

import json
import re
from pathlib import Path

from eco.events import Finding
from eco.style import PageStyle

_NAME = re.compile(r"[A-Za-z0-9 _-]{1,40}")


def _path(data_dir: Path, name: str) -> Path:
    if not _NAME.fullmatch(name) or name != name.strip():
        raise ValueError("Style name must be 1-40 letters, digits, spaces, - or _")
    folder = data_dir / "styles"
    for path in folder.glob("*.json"):
        if path.stem.casefold() == name.casefold():
            return path
    return folder / f"{name}.json"


def list_styles(data_dir: Path) -> list[dict]:
    folder = data_dir / "styles"
    default = get_default(data_dir)
    result = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stem.casefold()):
        item = {"name": path.stem, "default": path.stem.casefold() == (default or "").casefold()}
        try:
            load_style(data_dir, path.stem)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            item["error"] = str(error)
        result.append(item)
    return result


def load_style(data_dir: Path, name: str, *, findings: list[Finding] | None = None) -> PageStyle:
    path = _path(data_dir, name)
    if not path.is_file():
        raise ValueError(f"Style not found: {name}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    library = data_dir / "fonts"
    return PageStyle.from_json(
        raw, (library,) if library.is_dir() else (), lenient=True, findings=findings
    )


def save_style(data_dir: Path, name: str, raw: dict, *, overwrite: bool = False) -> PageStyle:
    path = _path(data_dir, name)
    if path.exists() and not overwrite:
        raise ValueError(f"Style already exists: {path.stem}")
    library = data_dir / "fonts"
    style = PageStyle.from_json(raw, (library,) if library.is_dir() else ())
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(style.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return style


def delete_style(data_dir: Path, name: str) -> None:
    path = _path(data_dir, name)
    if not path.is_file():
        raise ValueError(f"Style not found: {name}")
    path.unlink()
    if (get_default(data_dir) or "").casefold() == name.casefold():
        set_default(data_dir, None)


def get_default(data_dir: Path) -> str | None:
    path = data_dir / "settings.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("default_style")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def set_default(data_dir: Path, name: str | None) -> None:
    if name is not None:
        load_style(data_dir, name)
    path = data_dir / "settings.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"default_style": name}), encoding="utf-8")
    temp.replace(path)

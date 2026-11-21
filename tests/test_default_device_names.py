"""The smoke checks and the docs name outputs after the default device, the X4 Pro."""

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_smoke_checks_and_docs_expect_the_x4_pro_name():
    for name in ("scripts/smoke_native.py", "scripts/docker-smoke.sh", "README.md", "README.id.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert ".x4.epub" not in text, name

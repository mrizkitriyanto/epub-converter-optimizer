import json

import typst

from eco.epub.focus import focus_letters
from eco.render.md2typst import FOCUS_COUNT_TYPST, focus_target_weight

# letters in a word -> letters in bold, the same in the EPUB and the XTC
TABLE = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 4, 10: 4, 12: 5, 20: 8}


def test_python_rule_follows_the_table():
    assert {n: focus_letters(n) for n in TABLE} == TABLE


def test_typst_rule_follows_the_same_table(tmp_path):
    main = tmp_path / "rule.typ"
    numbers = ", ".join(map(str, TABLE))
    main.write_text(
        FOCUS_COUNT_TYPST + f"#metadata(({numbers},).map(focus-count)) <c>\n", encoding="utf-8"
    )
    found = json.loads(typst.query(str(main), "<c>", field="value", one=True))
    assert found == list(TABLE.values())


def test_xtc_focus_uses_the_nearest_heavier_weight_the_font_has():
    assert focus_target_weight([400, 500, 600, 700], 400, 600) == 600
    assert focus_target_weight([400, 700, 900], 400, 600) == 700
    assert focus_target_weight([400, 500], 400, 700) == 500
    assert focus_target_weight([400], 400, 700) is None

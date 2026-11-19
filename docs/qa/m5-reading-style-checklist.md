# M5 reading style manual checks

Use a temporary `--data` folder and a short Markdown book for these checks. Keep the owner's normal model and job folders untouched.

| Check | Expected | Status |
|---|---|---|
| Upload a regular and bold `.ttf`/`.otf` for one family in Settings > Fonts | Family and weights appear; Focus Mode availability is shown | Browser check pending |
| Save a style in Review, make it default, and start another job | The new job uses the style, including its font and size | Browser check pending |
| Use `eco styles list` and `eco convert --style NAME` | Named and default styles are visible and selected correctly | Automated tests |
| Delete the shared font, then render an older job or style | Literata is used and `font_missing` names the removed family | Automated tests; browser check pending |
| Render body text with a character missing from the selected font | `font_fallback` gives a count and sample; live preview shows the chapter warning | Automated tests; browser check pending |
| Toggle Focus Mode strengths on an XTC chapter | Prefix weights change, text remains the same, and EPUB preview stays unchanged | Automated tests; X4 check pending |
| Compare XTC live preview to the downloaded file on Xteink X4 | Pages match after quantization | X4 hardware pending |
| Measure a 30-page chapter on an M3 Mac | Warm Focus Mode preview at most 1.5x baseline; absolute target at most 1 second | Windows laptop: 29 pages, median of 5 alternating runs: 1.309 s plain, 1.327 s Focus Mode, 1.014x. M3 Mac pending |

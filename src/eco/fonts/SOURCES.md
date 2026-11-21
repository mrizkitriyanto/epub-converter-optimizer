# Bundled fonts

Static TrueType files under the SIL Open Font License 1.1. Each family folder holds the `OFL.txt`
of its project. The files are used as they were published, except Bitter (see below). Fetched on
2026-11-18. `eco.style.BUNDLED_FONTS` lists the upright files; Literata's italic is picked up from
its folder.

## Literata

- Weights 400, 500, 600, 700, 800 and 400 italic (`Literata-Regular`, `-Medium`, `-SemiBold`,
  `-Bold`, `-ExtraBold`, `-Italic`). The 800 file was fetched on 2026-11-22 from the same commit.
- Source: https://github.com/googlefonts/literata, folder `fonts/ttf`, commit
  `0c2761b727a1b3a7cffd313c37f0f5163dfc7a63` (2023-05-19). Licence: `OFL.txt` of the same commit.

## Bitter

- Weights 400, 500, 600, 700, 800 (`Bitter-Regular`, `-Medium`, `-SemiBold`, `-Bold`, `-ExtraBold`).
  The 800 instance was made on 2026-11-22 from the same variable font.
- The project ships only a variable font. Source: https://github.com/google/fonts, file
  `ofl/bitter/Bitter[wght].ttf`, commit `b6380fac8e94cdc92aa045cf44d80a7743dde8d6` (2026-05-27).
  Licence: `ofl/bitter/OFL.txt` of the same commit.
- Instanced with fonttools (not a project dependency), one run per weight, `wght` the only axis:

  ```
  uv run --with fonttools fonttools varLib.instancer "Bitter[wght].ttf" wght=<400|500|600|700|800> --update-name-table -o Bitter-<Name>.ttf
  ```

  The instances keep the family name `Bitter`. The reserved font name of the licence is `Bitter Pro`.

## Lexend Deca

- Weights 400, 500, 600, 700, 800 (`LexendDeca-Regular`, `-Medium`, `-SemiBold`, `-Bold`,
  `-ExtraBold`). The 800 file was fetched on 2026-11-22 from the same commit.
- Source: https://github.com/googlefonts/lexend, folder `fonts/deca/ttf`, commit
  `7894f02b2e7eabc48595f1d4eff3b17b48c6e651` (2023-03-02). Licence: `OFL.txt` of the same commit.

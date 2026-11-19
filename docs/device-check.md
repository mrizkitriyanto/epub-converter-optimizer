# Device check

Generate the files in a new folder:

```console
python -m eco.xtc.devcheck device-check
```

Copy `gray-ramp.xtch`, `chapters.xtc`, and `css-check.epub` from that folder to the SD card. Test each firmware eco supports and record the result in `docs/decisions.md`.

## What to check

1. Open `gray-ramp.xtch`. Its first page must show, from left to right, white, light gray, dark gray, and black. Open pages 2 and 3 too.
2. Open the chapter menu. `One`, `Two`, and `Three` must jump to pages 1, 2, and 3 respectively.
3. Open `chapters.xtc`. Check all three pages and repeat the chapter-menu jumps.
4. Open `css-check.epub`. The 160-character code line must wrap instead of running off-screen, and the four-column table must remain readable.
5. Confirm that both sample images appear. Move through the large chapter, record whether it loads, and record its load time.

If the light and dark gray bars are swapped, exchange the 85 and 170 entries in `XTH_VALUES` in `src/eco/xtc/codec.py`, regenerate the kit, and run the tests before checking the device again.

The generated files are disposable test artifacts. Do not commit them.

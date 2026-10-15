# mbaacc-action-gifs

> Export every *Melty Blood Actress Again Current Code* character action as an animated GIF — frame data decoded straight from `0002.p`, with all VFX composited.

<p align="center">
  <img src="docs/preview.webp" alt="C-Akiha Circuit Spark — exported from MBAACC with VFX compositing">
</p>
<p align="center"><sub>C-Akiha <code>サーキットスパーク</code> — one exported action, VFX included (lossless WebP: 256 alpha levels)</sub></p>

A headless, offline renderer for MBAACC's animation data. No emulator, no screenshots: it reads
the game archive, decodes the frame/判定 data, and re-composites each action exactly as the
engine would — including the hit-effects, additive glow, scaling and rotation that the
existing community tool **FrameDisplay does not render at all**.

## What it does

- Decodes `0002.p` (custom container + 4096-byte XOR obfuscation per file)
- Parses `<CHAR>.HA6` frame data: `AFGP` sprite, `AFOF` offset, `AFD` duration, `AFAL` blend,
  `AFRG` colour, `AFZM` zoom, plus the `EF*` effect commands
- Decodes `<CHAR>.CG` atlases, including the 16x16 tile compression and the
  `type_id=2/3/4` pixel formats (8bpp palette, index-as-alpha, embedded RGB tables)
- Decodes palettes (`<CHAR>.pal`) and the move list (`<CHAR>_<moon>_C.TXT`), so every exported
  file is named with its input notation (`236A`, `j.0202C`, `63214B`, ...)
- Renders on a 60fps sub-frame timeline with:
  - character-internal effects (`EFTP=1`) and shared EFFECT sequences (`EFTP=8`)
  - recursive sub-effects, EF slot *replacement* semantics, additive blending
  - `AFZM` zoom / `AFAZ` rotation about the character origin
- Exports transparent-background GIF (or lossless animated WebP / APNG for full alpha),
  auto-cropped to each action's bounding box
- ~30k actions across all 97 character/moon forms in ~1 hour on 10 cores

## Install

```bash
pip install numpy pillow
```

Python 3.8+.

## Usage

```bash
python mbaa_gif.py --list                                    # list all character forms
python mbaa_gif.py -c C-AKIHA --effects -o out/gifs          # one form, every action
python mbaa_gif.py -c all --effects --format gif \
       --alpha-cutoff 128 -j 10 --no-sheet -o out/gifs       # full run (~60-70 min)
python mbaa_gif.py --effect-catalog                          # render all 163 EFFECT sequences
```

### Locating the game data

`0002.p` is found automatically (first hit wins):

1. `MBAACC_PACK` environment variable
2. `C:\Program Files\MBAACC\MBAACC\0002.p` (or the x86 variant)
3. next to the script / a few levels above it
4. `./0002.p`

…or pass `--pack /path/to/0002.p` explicitly.

### Useful options

| flag | meaning |
|---|---|
| `--effects` | also render shared `EFFECT` sequences (character-internal VFX are always rendered) |
| `--format gif\|webp\|apng` | output format; GIF is 1-bit transparent, webp/apng keep the full alpha gradient |
| `--alpha-cutoff 128` | GIF transparency threshold (higher = cleaner edges, softer glow gets clipped) |
| `--opaque` | dark opaque background instead of transparency |
| `--canvas 512x768` | fixed canvas so all actions align for comparison |
| `--sequences 114,180` | export only these sequence ids |
| `-j 10` / `--serial` | worker processes / single process |
| `--no-sheet` | skip the `_sheet.png` preview contact sheet |

## Output

```
out/gifs/<FORM>/<FORM>_<seq>_<input>_<action name>.gif
out/gifs/manifest.csv          # every exported action + metadata
out/effect_catalog/            # rendered catalogue of all EFFECT sequences
```

## Project layout

| file | role |
|---|---|
| `mbaa_core.py` | archive, HA6/EF parsing, CG atlas + palettes + move list |
| `mbaa_render.py` | timeline, effect compositing, blending, transforms, encoders |
| `mbaa_gif.py` | CLI / batch driver |
| `run_full.ps1` | full-run launcher with a visible progress window |
| `DISASM_NOTES.md` | reverse-engineering notes on `MBAA.exe` (draw function, matrix building, EF struct layout) |

## Known limitations

- Effects that the engine spawns *conditionally* (e.g. hit sparks on contact) cannot be
  distinguished from unconditional ones in the animation data, so they render as written
- `EFTP=8 param=26` (`バッシュ`) is skipped by default: the data attaches it to 5B/214A but the
  game shows no such VFX there — likely condition-triggered. Adjust `FX_SKIP_PARAMS` in
  `mbaa_render.py`
- `blend_mode 3` (reverse-subtract) and X/Y-axis 3D rotation are not implemented
- GIF frame timing is quantised to 10ms; use `--format webp` for exact timing

## Credits

The file formats were reverse-engineered from **FrameDisplay** by jmgao
(<https://github.com/jmgao/framedisplay>) — its source is the Rosetta stone for the HA6/CG
formulas, and is referenced throughout `DISASM_NOTES.md`. Transform semantics were
additionally verified against `MBAA.exe` via disassembly. This project is an independent
clean-room Python implementation with no FrameDisplay code included.

## License

MIT — see [LICENSE](LICENSE).

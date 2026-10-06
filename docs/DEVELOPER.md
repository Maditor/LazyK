# LazyK — Developer notes

⚡💬 *Read comics in any language, the lazy way.*

The logo follows Windows: a light bubble on the dark theme (and on the dark toolbar), a graphite bubble on the light theme. The .exe file icon uses the graphite version, which reads on both.

Translate comic pages on screen. LazyK captures the page, reads the bubbles with a vision model
(Google Gemini or Gemma 4 on Cloudflare Workers AI), translates the whole page in one call, and paints the
translation over the original text in a click-through overlay.

**This version:** Auto mode (default) + Hotkey mode, floating toolbar with font picker,
bread-shaped text layout, in-memory cache.
Coming next: Settings window, tray icon, fixed region, disk cache.

## Setup (Windows 11, Python 3.11)

1. Double-click `setup.bat` (creates `.venv`, installs packages).
2. Double-click `run.bat`. On first run the **API & Models** window opens: add a **Gemini API key**
   (free at aistudio.google.com) and/or a **Cloudflare account ID + token** (Workers AI permission).
   *Test connection* checks the key and model. Keys are saved in `settings.json` next to the app.

## Servers and models

The toolbar chip `Gemini · 3.5 Flash Lite ▾` opens a menu: pick the server, pick the model, toggle
auto-switching, or open **API keys & models…** (also the ⚙ button). Each server keeps its own key(s),
model and model list (editable, one per line).

* **Auto-switch model** (on): a busy model (503) gets one quick retry, then the next model of the list is
  used; a model out of quota (429) or not available (404) is skipped at once. The new model is remembered.
* **Auto-switch server** (on): when a server is out of quota or its key is rejected (e.g. Cloudflare's
  daily free neurons are used up), the other server is used if it has a key.

## Use

| Key | Action |
|---|---|
| `Alt+Shift+A` | Switch **Auto** ↔ **Hotkey** mode (saved) |
| `Alt+T` | Translate the active window now (works in both modes) |
| `Esc` | Hide the overlay |
| `Alt+Shift+T` | Pause / resume the tool |
| `Ctrl+Alt+Q` | Quit (until the tray icon exists) |

**Auto mode (default):** just read. When you scroll a browser (wheel, PageUp/PageDown, Space, arrows)
the overlay hides at once; ~700 ms after you stop, the page is captured and translated. Only the apps in
`auto_apps` react, so scrolling elsewhere does nothing. Scrolling again cancels the running job.
Pages already translated come back instantly (image-hash cache, no API call).

**Hotkey mode:** nothing happens until `Alt+T`; scrolling only hides the overlay.

## Toolbar

A small dark bar stays on top of every window (top-centre the first time; drag it by the `⋮⋮` grip or
the logo, the position is remembered). It never takes keyboard focus from the browser and never shows
up in screenshots, so it is never translated. Menus open upwards when the bar sits at the bottom.

```
⋮⋮ ● On · Auto | Gemini · 3.5 Flash Lite ▾ | ↻  ❚❚  👁  ⛶ | ⚙  ‹  ✕
```

| Part | What it does |
|---|---|
| ● + text | Running. Green = on, blue = scanning, purple = translating, grey = paused, red = error |
| Server chip | Pick server and model, auto-switch toggles, API keys |
| ↻ ❚❚ 👁 | Translate now · pause/resume · show/hide overlay |
| ⛶ | Draw a frame around the comic page (amber when your frame is used) |
| ⚙ | Settings: Mode ›, Reading order ›, Source language ›, Capture ›, Text › (font, minimum size field, show in screenshots), API keys. The menu stays open while you change things; ⚙ again, Esc or a click outside closes it |
| `‹` / `✕` | Collapse (keeps ● and ↻ ❚❚ 👁 ⛶) / quit |

## Capture frame (Region)

Click ⛶ (or `Alt+Shift+R`), the screen dims, drag a frame tightly around the comic page. The frame is
saved and used for every capture (also after restart) until you choose ⚙ → Capture → Browser page.
In Auto mode only wheel scrolling inside the frame triggers a scan. Use it when the reader shows
menus, comments or a busy background next to the page: only the page is sent, at full resolution.

## Text layout

* **Bubble cleaning:** when a bubble's outline is found, its inside is painted clean following the real
  outline (like a scanlation), in the bubble's own tone: white bubbles use your colours, grey bubbles stay
  grey, black bubbles stay black with white text.
* **Text follows the bubble:** every line is as wide as the bubble is at that height, so an oval bubble
  gets short top/bottom lines and a wide middle (bread shape) and almost all of its room is used.
* **Tight line spacing** (1.16 × font size) so more lines fit.
* **Length budget:** the translator is told roughly how many characters each bubble can hold, so
  Vietnamese (often 2–3× longer than Korean/Japanese) comes back concise.
* **No orphans:** with 4+ words no line holds a single word; 3 words become at most 2 lines (2 + 1).
* **Safe fallback:** open bubbles that leak into the panel background, captions and text on the art get
  a rounded box that covers the original text and never grows over a neighbour or the drawing.

## Test the coordinates first (125–150% scaling)

```
run.bat --demo
```
Click the browser, press `Alt+T`. Five white boxes appear about 20 px inside the four corners and the
centre of the **page area** (below the address bar). If they sit exactly there on every monitor and
scaling, the capture area and DPI mapping are correct. No API calls are made.

Offline check of the model's boxes, without the overlay:
```
run.bat --image page.png
```
prints every bubble (box, source, translation) and saves `page_translated.png`.

Set `"debug_save": true` in `settings.json` to keep every capture, a box image (orange = model box,
red = snapped text, blue = bubble) and the raw model output in `logs\debug\`.

## Settings (`settings.json`, edit while the app is closed)

| Key | Default | Notes |
|---|---|---|
| `mode` | `auto` | `auto` or `hotkey` (or press `Alt+Shift+A`) |
| `scroll_delay_ms` | `700` | Quiet time after the last scroll before capturing |
| `auto_apps` | browsers | Process names that trigger Auto; `[]` = any app |
| `server` | `gemini` | `gemini` or `cloudflare` |
| `gemini_models`, `cloudflare_models` | see file | Model lists, in auto-switch order |
| `auto_switch_model`, `auto_switch_server` | `true` | See *Servers and models* |
| `source_lang` | `auto` | `auto`, `ja`, `ko`, `zh`, `en` |
| `target_lang` | `Vietnamese` | |
| `layout` | `manga` | `manga` = right→left, `webtoon` = left→right |
| `skip_sfx` | `true` | Drop sound-effect lettering |
| `hotkey_*` | see above | e.g. `ctrl+shift+y`, `f8`, `alt+\``. `hotkey_translate` may also be `mouse3` / `mouse4` / `mouse5` (wheel click / side buttons, optionally with modifiers); set it from ⚙ → Translate key… |
| `layout` = `vn` | | Visual novel mode: `app/vn.py` (one small read + one translation per line, no tiles / bubbles) |
| `vn_region` | `null` | Text box frame (physical px), separate from `region` |
| `vn_auto` | `false` | Auto-scan when the text box changes (`hotkey_vn_auto`, `Alt+Shift+V`) |
| `vn_poll_ms`, `vn_stable_ms`, `vn_change_pct` | `200`, `350`, `0.3` | Watcher: look interval, quiet time before a scan, % of the box that must change |
| `vn_max_width`, `vn_game_colors` | `1000`, `true` | Image width sent to the AI; use the text box's own colour for the overlay |
| `hover_hide` | `true` | Mouse over a translated box hides that box until the mouse leaves |
| `hide_on_scroll` | `true` | |
| `show_status_pill` | `false` | Extra status pill near the page (errors always show) |
| `capture_mode`, `region` | `window`, `null` | Set by the ⛶ button |
| `browser_top_crop` | `0` | Logical px cut from the top, only used when the browser page area can't be detected (Firefox). ~85 for Firefox. |
| `box_format` | `auto` | Box axis order: detected from the pixels. Force `yxyx` or `xyxy` only if needed |
| `overlay_bg` / `overlay_fg` | `#ffffff` / `#111111` | |
| `overlay_outline` | `""` | e.g. `#cccccc` for a thin border |
| `overlay_shadow` | `false` | |
| `overlay_in_screenshots` | `true` | Print Screen / Snipping Tool capture the translated page (⚙ → Show in screenshots) |
| `font_family`, `font_bold` | `Segoe UI`, `true` | |
| `font_min` | `14` | Reading size (⚙ → Text): overlay text never gets smaller, only up to 1.6× bigger in roomy bubbles |
| `corner_radius`, `box_padding` | `10`, `6` | Logical px |
| `max_slice_width` | `1200` | Image width sent to the model |
| `ocr_concurrency` | `3` | Pieces sent in parallel |
| `manga_tiles` | `true` | Manga: send overlapping upscaled tiles |

## How it works

- **Capture area:** Chromium browsers (Chrome, Edge, Cốc Cốc, Brave, Opera) expose the page as a child
  window, so tabs and the address bar are excluded exactly. Other apps use the client area.
  The process is per-monitor DPI aware, so capture, OCR boxes and overlay all use physical pixels.
- **Page trim:** the empty browser background around a manga page is cut off first, so the page is
  sent at full resolution (small text reads better, boxes are more precise).
- **Pixel-accurate boxes:** the model's boxes are only rough. Each one is snapped with OpenCV to the real
  text strokes, and the enclosing speech bubble is found (white area with a closed outline). The overlay
  covers exactly the original text and uses the free room inside the bubble for the Vietnamese text.
  Whether the model answered `[y,x,y,x]` or `[x,y,x,y]` is decided by which reading snaps onto lettering.
- **Manga tiles:** in Manga layout the page is sent as 2 overlapping tiles (4 for a double-page spread),
  each upscaled up to 2x, so small Japanese lettering is readable. Half-bubbles at a tile seam are dropped
  when the neighbouring tile holds the whole bubble. Turn off with `"manga_tiles": false` (fewer API calls).
- **One bubble = one item:** models often return each vertical text column separately; fragments that
  snap to the same bubble are joined (columns right→left) before translating.
- **No overlapping boxes:** each box must cover its original text; it may grow into its bubble's free room,
  but is trimmed away from every other box. Crowded bubbles use a slightly smaller font (down to 75% of
  `font_min`) instead of covering a neighbour.
- **OCR:** image downscaled to 1200 px wide; tall webtoon captures are cut at blank gaps between panels.
  Gemma returns JSON boxes normalised to 0–1000; the parser tolerates fences, `<think>` blocks,
  missing commas and truncated output, and retries once.
- **Translation:** one text-only call per page, numbered lines in/out, with the previous page's lines as
  context for consistent pronouns. Missing lines are retried once.
- **Overlay:** borderless topmost Tk window with a colour key, plus `WS_EX_LAYERED | WS_EX_TRANSPARENT`
  (clicks and wheel go to the browser), `WS_EX_NOACTIVATE` (never steals focus) and
  `WDA_EXCLUDEFROMCAPTURE` (never appears in its own screenshots). Text is fitted by trying font sizes
  from max to min with word wrap; narrow vertical-Japanese boxes are widened.
- **429 / 503:** waits 4, 8, 15, 25, 40 s with a status message, then gives up.

## Build an exe

`build_exe.bat` → `dist\LazyK\LazyK.exe` (no console; log in `logs\lazyk.log`).
Copy the whole `dist\LazyK` folder.

## Files

```
main.py              entry point, logging, --demo / --image
app/config.py        settings.json
app/winapi.py        DPI awareness, window rects, click-through styles
app/api.py           Gemini + Cloudflare clients, model/server auto-switch, connection test
app/api_dialog.py    API & Models window
app/popup.py         dark dropdown menu
app/theme.py         shared colours, fonts, flat buttons, switches
app/ocr.py           slicing, OCR prompt, JSON parsing, reading order, dedupe
app/refine.py        page trim, box order detection, snap boxes to text / bubbles (OpenCV)
app/translate.py     page translation prompt + numbered-line parsing
app/textfit.py       bread-shaped line breaking, orphan rules, box layout (pure)
app/pipeline.py      capture, hash cache, OCR → translate, debug dump
app/overlay.py       overlay + status pill
app/hotkeys.py       global hotkeys, mouse buttons and scroll watching
app/vn.py            visual novel mode: one-line read + translate, text-box change watcher
app/controller.py    Tk loop, jobs on worker threads, cancellation
app/toolbar.py       floating toolbar, tooltips, font picker
app/preview.py       PIL rendering for --image
```

## Local OCR (`app/local_ocr.py`)

`settings.ocr_engine = "local"` replaces the vision-AI scan with on-device OCR; the AI only translates.

* Detector: RapidOCR PP-OCRv6 det small (bundled in the `rapidocr` wheel, pinned to 3.9.2).
* Recognizers: PP-OCRv6 rec small (bundled; ja / zh / en, vertical text OK), PP-OCRv5 Korean
  (downloaded, 13 MB), optional manga-ocr ONNX (mayocream/manga-ocr-onnx, 460 MB) that re-reads
  each Japanese block.
* `source_lang = auto`: the recognizer that won on the previous page runs first; when its mean score
  is below 0.85 the other one runs too and the higher total score wins.
* Lines are grouped into blocks (`_group_lines`) unless a drawn outline runs between them
  (`_divided`); blocks then go through the same `_finish` as the AI path (bubble snapping,
  fragment merge, reading order).
* Downloads live in `%LOCALAPPDATA%\LazyK\models`. onnxruntime-directml gives GPU on any DX12 card.
* `rapidocr` is installed with `--no-deps` (it requires opencv-python, which clashes with
  opencv-python-headless); its real dependencies are listed in requirements.txt.

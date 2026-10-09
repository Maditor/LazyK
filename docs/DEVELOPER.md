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
| `Alt+Shift+H` | Hide / show the toolbar (one shared key; also in the tray menu) |
| `Ctrl+Alt+Q` | Quit (also: tray icon → Quit LazyK) |

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
| ⚙ | Settings (short top level, submenus for the rest): Mode ›, Reading order ›, Source language ›, Capture ›, Text › (font, minimum size, colours, Box & overlay ›), OCR device ›, Read aloud ›, Hotkeys ›, More › (translation record, taskbar, developer mode), API keys. The menu stays open while you change things; ⚙ again, Esc or a click outside closes it |
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
| `hotkey_*` | see above | e.g. `ctrl+shift+y`, `f8`, `alt+\``. `hotkey_translate` may also be `mouse3` / `mouse4` / `mouse5` (wheel click / side buttons, optionally with modifiers); set it from ⚙ → Hotkeys → Translate key… |
| `layout` = `vn` | | Visual novel mode: `app/vn.py` (one small read + one translation per line, no tiles / bubbles) |
| `vn_region` | `null` | Text box frame (physical px), separate from `region` |
| `vn_auto` | `false` | Auto-scan when the text box changes (`hotkey_vn_auto`, `Alt+Shift+V`) |
| `hotkey_toolbar` | `alt+shift+h` | Hide / show the toolbar; every function keeps working. One key for both; set it from ⚙ → **Hotkeys → Show / hide toolbar key…** |
| `taskbar_icon` | `true` | Taskbar button (right-click → Close window quits; a click shows the toolbar). Hidden together with the toolbar |
| `vn_poll_ms`, `vn_stable_ms`, `vn_change_pct` | `200`, `350`, `0.3` | Watcher: look interval, quiet time before a scan, % of the box that must change |
| `vn_max_width`, `vn_game_colors` | `1000`, `true` | Image width sent to the AI; auto-detect the background colour for the overlay in every layout (VN: `vn.frame_colors`; manga / webtoon: `refine.attach_colors`, a ring around each text box) |
| `hover_hide` | `true` | Mouse over a translated box hides that box until the mouse leaves |
| `hide_on_scroll` | `true` | |
| `local_gpu`, `local_gpu_id` | `false`, `0` | Local OCR on a graphics card (DirectML) or the CPU, and which card (DirectML device number = DXGI adapter order). Set from ⚙ → OCR device, which lists the cards found by `app/gpus.py` |
| `tts_enabled` | `false` | Read the translation aloud after each fresh translation (⚙ → Read aloud). Not read again for cached pages |
| `tts_voice` | `auto` | `auto` = by `target_lang` (Vietnamese → `vi-VN-HoaiMyNeural`), or any Edge voice name, e.g. `vi-VN-NamMinhNeural` |
| `tts_speed`, `tts_volume` | `100`, `100` | Speed 50–200 % (sent to the service as `rate`), volume 0–100 % (MCI `setaudio`, so never above the system volume) |
| `record_enabled` | `true` | Append every fresh translation to `record-lazyk.txt` next to `settings.json`; the file is deleted when LazyK quits and emptied at start |
| `show_status_pill` | `false` | Extra status pill near the page (errors always show) |
| `capture_mode`, `region` | `window`, `null` | Set by the ⛶ button |
| `browser_top_crop` | `0` | Logical px cut from the top, only used when the browser page area can't be detected (Firefox). ~85 for Firefox. |
| `box_format` | `auto` | Box axis order: detected from the pixels. Force `yxyx` or `xyxy` only if needed |
| `overlay_bg` / `overlay_fg` | `#ffffff` / `#111111` | |
| `overlay_outline` | `""` | e.g. `#cccccc` for a thin border |
| `overlay_shadow` | `false` | |
| `overlay_in_screenshots` | `true` | Print Screen / Snipping Tool capture the translated page (⚙ → Text → Box & overlay) |
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
app/tts.py           read aloud: edge-tts voices, chunked + parallel synthesis, MCI playback, retries
app/record.py        session record of the translations (record-lazyk.txt)
app/gpus.py          lists the graphics cards (DXGI) in a child process: `main.py --list-gpus FILE`
app/controller.py    Tk loop, jobs on worker threads, cancellation
app/toolbar.py       floating toolbar, tooltips, font picker
app/tray.py          system tray icon (pystray): show / hide toolbar, quit
app/taskbar.py       taskbar button (hidden while the toolbar is hidden)
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

## VN mode: local OCR reader (`local_ocr.LocalOcr.read_vn`)

The comic-page reader (detect -> group -> join) misread dialogue boxes, so VN mode has its own:

1. Border in the box colour around the frame (text touching the edge is otherwise not detected); text under
   22 px is enlarged first.
2. Detected pieces that share a vertical band are one row. A row made of several pieces is read again as a
   whole line by a separate rec-only RapidOCR instance (`_rapid(kind, use_gpu, rec_only=True)`; never call a
   normal engine with `use_det=False`, it corrupts its later calls). This removes scrambled / duplicated /
   clipped words.
3. First row = speaker name only if it is short, has no sentence end, and is set apart (gap / size / indent /
   brackets / own colour). `read_vn` returns `{name, text, trace}`; the trace is logged ("VN OCR ...").
4. A manual (hotkey) re-scan in VN mode skips the image cache; cache key bumped to `v6`.

## Overlay look: background opacity / blur

`overlay_opacity` (0-100 %, 100 = solid, the old look) and `overlay_blur` (px). Tk canvases have no alpha or
blur, so a see-through box is a picture (`overlay.glass_image`): a screenshot of the screen under the overlay,
blurred, tinted with the box colour, rounded corners painted in KEY_COLOR. The screenshot is taken while the
overlay is hidden and reused on re-render. Speech-bubble polygons (manga) stay solid.
In visual novel mode the status pill is never shown (it sat at the frame's top-right corner, in the middle of
the game); the toolbar shows all states and errors.

Status callbacks: `LocalOcr` reports "Loading local OCR…" with ONE argument (`on_status(msg)`), while the
pipeline's own `on_status` takes `(state, msg)`. Always wrap it (`lambda m: on_status("scanning", m)`) when
calling `read` / `read_vn`.

VN auto-scan: a passing change in the box (the game's mouse-over effect, a blinking arrow) hides the visible
translation (`vn_hide`). When the box settles on the SAME text again the watcher sends `vn_restore`, which shows
`App.last` again: no scan, no API call. (Before, nothing came back until the hide/show key was pressed.)
`Overlay.show_items` applies hover-hide right after `show()`, so a box under the mouse never flashes.

## Developer mode (Settings → Developer mode)

`developer_mode` makes every tool window visible to screen recorders (OBS, Game Bar, Snipping Tool): toolbar,
status pill, tooltips and the translation overlay. Normally they use `WDA_EXCLUDEFROMCAPTURE` so the OCR and
the VN watcher never read the tool's own pixels. Implementation: `overlay.DEV["on"]` is read by the
`exclude_from_capture` property of every `_ClickThroughWindow`; `winapi.set_capture_excluded` re-applies it live.
Side effect handled: with the translation visible to the capture, the VN auto-scan watcher would see its own
box appear as "text changed" and loop (hide / scan / hide ...). While the overlay is painted into the capture,
`VNWatcher` ignores the pixels under the overlay boxes (`_overlay_mask`). Limit: text changes hidden under a box
that covers the whole frame are not seen then; use the scan key, or turn developer mode off.
A toolbar or pill placed over the captured page / VN frame can be read by the OCR in this mode.

## Taskbar button and hidden toolbar

`taskbar.TaskbarButton` is a minimised Toplevel whose only job is the taskbar button (all other windows are
tool windows / overlays without one). Windows restores it on a click: `<Map>` re-minimises it and calls
`App._taskbar_click` (shows or raises the toolbar). Its WM_DELETE_WINDOW (right-click → Close window) calls
`App.quit`. Its title carries the last error, so an error is readable while the toolbar is hidden.
`Toolbar.set_hidden` hides the window with ShowWindow(SW_HIDE) (like the overlay: no focus change); `raise_`
and `_keep_on_top` do nothing while hidden. The hidden state is not saved, a restart always shows the toolbar.

## Tray icon

`tray.TrayIcon` (pystray, own thread) lives as long as the app: right-click → **Show / Hide toolbar** (shows the
shared key) and **Quit LazyK**; a left click toggles the toolbar. Its callbacks only put `("tray", "toggle" | "quit")`
in `App.q`, so Tk is only touched from the main thread. `Toolbar.set_hidden` calls `App.on_toolbar_visibility`,
which hides / restores the taskbar button (`TaskbarButton.set_visible`, a withdrawn window has no button) and
rebuilds the tray menu text. If the tray cannot start (pystray not installed: run `setup.bat` again),
`App.tray_ok` is False and the taskbar button stays visible, so a hidden toolbar can always be brought back.
While the toolbar is hidden an error shows in the status pill and in the tray icon's hover text.
`App.quit` must call `TrayIcon.stop()`: pystray's thread is not a daemon.
On Windows 11 new tray icons start in the overflow (^) area: drag the LazyK icon out to keep it visible.
Settings has no hide button: ⚙ → **Hotkeys → Show / hide toolbar key…** only changes the shared key.

## Visual novel speed (v29)

- The VN text-box detector is its own RapidOCR instance (`_rapid(..., vn=True)`, cache key `<kind>_vn`) with `Det.limit_type = max`: the box is detected at its real size instead of being enlarged to 736 px on the short side (about 8x faster). Manga / webtoon keep the default engine.
- manga-ocr re-reads only rows whose RapidOCR score is below `VN_MOCR_BELOW` (0.90).
- `gtranslate` keeps a 500-line cache and skips the thread pool for a single line.
- The log shows `VN OCR timing: detect / rows / total` for every scan.
- `local_gpu` now defaults to the CPU; `settings.json` is switched once (`_gpu_cpu_default`).

## Blur (v30)

- `overlay_blur` is the screen seen through a box (`overlay.glass_image`), so it only shows when `overlay_opacity < 100`; at 100 the box is solid and blur had no effect. Typing a blur above 0 now sets the opacity to 75% if it was 100.
- A Gaussian blur keeps the average colour, so the auto-picked box colour (`vn_game_colors`, `bubble_colors`) and text colour are the same at any blur radius; they are chosen from the unblurred capture and blur only changes what shows through.
- Cleaned manga bubbles (`poly`) stay solid paper on purpose.
- Opacity and blur are visual novel only: the two menu entries show only when `layout == "vn"`, and `overlay.show_items` paints solid boxes in every other layout.
- The Read & translate menu (`Toolbar.open_server_menu`) is persistent like Settings: it is a builder that is re-run after every pick, stays open until Esc, its button or a click outside, and only the items that open a dialog (`Local OCR models…`, `API keys & models…`, a server without a key) use mode `"close"`.

## Speaker name detection (v31)

- `_split_name`: the bracket cue needs a balanced pair (`【Yuki】`, `(Yuki)`, `「Yuki」`) or a trailing colon (`_name_bracketed`). A first row with only an opening bracket, such as `(My life, everything,`, is the start of a thought, not a name. A row ending in a comma is never a name.



## Scroll detection (`app/scrollwatch.py`)

Auto mode used to rely only on the pynput low-level mouse hook (`WM_MOUSEWHEEL`). That misses
precision-touchpad scrolling in Chromium (DirectManipulation sends no wheel messages), scrollbar drags,
and a hook that Windows silently removes after a slow callback. `PageWatcher` grabs the watched page
(120 px wide grey copy) every 120 ms and reports `("pagemove", hwnd)` when the content shifted
vertically across most of the width (row profiles in 4 bands, best shift vs. no shift). Overlay
boxes are masked, and two looks are only compared when `overlay.version` and `busy` are unchanged, so
the translation appearing / hover-hide never count as a scroll. Animations (ads, video) change pixels
but do not shift, so they never trigger. `settings.scroll_watch = false` turns it off.

`App._poll` can no longer die on an exception (it always reschedules), and `InputWatcher.ensure_alive()`
restarts a pynput listener whose thread ended.


## Read aloud (`app/tts.py`, `app/piper_tts.py`)

`settings.tts_engine` picks the voice:

- `local`: Piper (`piper-tts`, installed by setup.bat with `--no-deps` so it does not add a second
  onnxruntime next to onnxruntime-directml). Voice models (`piper_<lang>.onnx` + `.onnx.json`, from
  rhasspy/piper-voices, table `_VOICES` in piper_tts.py; espeak-phonemized languages only) are packs of
  `local_ocr` (`PACKS["piper_<lang>"]`) and downloads into the same
  models folder. `piper_tts.ENGINE.sentences()` yields one sentence at a time (espeak-ng and the model
  behind one lock); each is resampled to 24 kHz and queued in `PcmPlayer` while the next is made.
- `online`: plain edge-tts, one request per translation (`group_text` joins whole sentences up to 400
  characters). The free service answers in ~2–3 s and drops reused / pre-opened websockets (an earlier
  `edge_fast` experiment with kept-open connections was removed), so each piece is downloaded completely,
  decoded with miniaudio and queued: later start, no stutter. Pieces are fetched WINDOW ahead.

`PcmPlayer` (miniaudio) plays queued int16 blocks back to back; the device stays open (silence) for
5 minutes. `speak()`/`stop()` clear the queue; a stopped reading cannot queue more (push checks `stop`).
Without miniaudio, mp3 / wav files are played through MCI. A missing local voice falls back to online and `Speaker.on_need_local` (= `App.setup_local_voice`)
starts pip-installing Piper (source runs only) and downloading the voice in the background; the same
happens when Text to speech is switched on, the target language changes, or at start-up.

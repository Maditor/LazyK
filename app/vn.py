"""Visual-novel mode: the dialogue box is a fixed frame, so skip everything manga needs
(tiles, bubble detection, reading order) and do one small read + one translation per line.

* run_vn()    capture of the text box -> one item that covers the whole frame
* VNWatcher   background thread: sees the text box change, waits until the text has finished
              appearing (typewriter effect), then asks the app for one scan
"""
import logging
import re
import threading
import time

import numpy as np
from PIL import Image

from . import winapi

log = logging.getLogger(__name__)

VN_MAX_TOKENS = 700
# Change detection: the frame is shrunk to 256 px wide; a pixel counts as changed above DIFF_LEVEL, and
# the text box counts as changed when more than vn_change_pct % of its pixels changed. Measured on
# 28 px text: one different word ~0.5 %, a small blinking "click to continue" arrow ~0.1 %.
DIFF_WIDTH, DIFF_LEVEL = 256, 25


# ------------------------------------------------------------------ one scan
def build_vn_prompt(source_lang, target, context_lines):
    from .translate import LANG_NAMES
    S = LANG_NAMES.get(source_lang, source_lang)
    ctx = ""
    if context_lines:
        ctx = ("\nPrevious lines of this scene, for context only (do NOT translate them):\n"
               + "\n".join(f"- {l}" for l in context_lines) + "\n")
    vi = ""
    if str(target).lower().startswith("viet"):
        vi = ("\n- Vietnamese pronouns: pick tôi/tao/tớ/mình/anh/em/cậu/mày/ông/bà/ngài... from the speakers' "
              "age, relationship and mood, and keep them consistent with the previous lines.")
    return f"""You translate visual novel / game dialogue. The image is the game's text box (it may include a speaker name label). The text is {S}.
{ctx}
Read all text in the image and translate the dialogue into natural {target}. Output exactly these three lines and nothing else:
NAME: <speaker name exactly as written, or empty>
SRC: <the dialogue exactly as written, on one line>
TR: <the {target} translation of the dialogue>

Rules:
- Natural spoken {target}, keep the tone, emotion and punctuation style (…, ?!).
- Keep it short enough to read at a glance.
- Do not translate or change the speaker name.
- If the image holds no readable dialogue, leave SRC and TR empty.{vi}"""


def parse_vn(raw: str):
    """-> (name, source, translation); tolerant of missing labels."""
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw or "", flags=re.I)
    raw = re.sub(r"```[a-z]*", "", raw).strip()
    name = re.search(r"^\s*NAME:[ \t]*(.*)$", raw, re.M | re.I)
    src = re.search(r"^\s*SRC:[ \t]*(.*?)\s*^\s*TR:", raw, re.S | re.M | re.I)
    tr = re.search(r"^\s*TR:[ \t]*(.*)$", raw, re.S | re.M | re.I)
    if not tr:
        # the model ignored the format: treat everything as the translation
        return "", "", ("" if re.search(r"^\s*SRC:\s*$", raw, re.M | re.I) else raw)
    return (name.group(1).strip() if name else ""), (src.group(1).strip() if src else ""), tr.group(1).strip()


def frame_colors(img: Image.Image):
    """Box colour of the game's text box (median pixel) and a readable text colour on it."""
    w, h = img.size
    small = np.asarray(img.convert("RGB").resize((64, max(1, round(64 * h / max(1, w)))), Image.BILINEAR))
    r, g, b = (int(v) for v in np.median(small.reshape(-1, 3), axis=0))
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return "#{:02x}{:02x}{:02x}".format(r, g, b), ("#ffffff" if lum < 140 else "#111111")


def _scaled_for_ai(img: Image.Image, max_w: int) -> Image.Image:
    w, h = img.size
    if w > max_w:
        return img.resize((max_w, max(1, round(h * max_w / w))), Image.LANCZOS)
    if w < 600:  # a small frame: enlarge so small text is still readable for the model
        f = 600 / w
        return img.resize((600, max(1, round(h * f))), Image.LANCZOS)
    return img


def run_vn(pipeline, client, img: Image.Image, cancel, on_status):
    """Read + translate the text box. Returns [] (nothing to show) or one item covering the frame."""
    from . import gtranslate, local_ocr
    from .api import Cancelled
    from .ocr import _encode
    s = pipeline.settings
    img = img.convert("RGB")
    mode = s.read_mode()
    prev = pipeline.prev_lines[-6:]
    name = ""
    if mode == "ai":
        part = _scaled_for_ai(img, int(s["vn_max_width"]))
        prompt = build_vn_prompt(s["source_lang"], s["target_lang"], prev)
        content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": _encode(part)}}]
        raw = client.chat(content, temperature=0.2, max_tokens=VN_MAX_TOKENS, cancel=cancel)
        name, src, tr = parse_vn(raw)
        src = src or tr  # context line for the next scan
    else:
        # the engine reports model loading with ONE argument (like the manga path in pipeline.py)
        r = local_ocr.ENGINE.read_vn(img, s, cancel, lambda m: on_status("scanning", m))
        if cancel.is_set():
            raise Cancelled()
        name, src = r["name"], r["text"].strip()
        if not src:
            log.info("VN OCR: nothing read (%s)", r["trace"])
            return []
        # what was read goes to the status line, so a wrong read is visible at once
        on_status("translating", f"Translating… “{src[:48]}{'…' if len(src) > 48 else ''}”")
        if mode == "local_google":
            try:
                tr = gtranslate.translate([src], s["source_lang"], s["target_lang"], cancel)[0]
            except gtranslate.TranslateError as e:
                if client is None:
                    raise
                log.warning("%s -> translating with the AI", e)
                tr = _ai_text(client, src, s, cancel, prev, name)
        else:
            tr = _ai_text(client, src, s, cancel, prev, name)
    if not src.strip() or not tr.strip():
        return []
    if not pipeline.prev_lines or pipeline.prev_lines[-1] != src:
        pipeline.prev_lines = (pipeline.prev_lines + [src])[-12:]
    w, h = img.size
    item = {"text": src, "type": "speech", "box": [0, 0, w, h], "bubble": None,
            "translation": f"{name}: {tr}" if name else tr, "colors": frame_colors(img)}
    return [item]


def _ai_text(client, text, s, cancel, context, speaker=""):
    """Text-only translation of one dialogue line (local OCR + AI)."""
    from .translate import LANG_NAMES
    S, T = LANG_NAMES.get(s["source_lang"], s["source_lang"]), s["target_lang"]
    ctx = ("Previous lines (context only):\n" + "\n".join(f"- {l}" for l in context) + "\n\n") if context else ""
    vi = (" Vietnamese pronouns: choose tôi/tao/tớ/mình/anh/em/cậu... from the speakers' relationship and keep them "
          "consistent.") if str(T).lower().startswith("viet") else ""
    who = f"Speaker: {speaker} (do not translate or output the name).\n" if speaker else ""
    prompt = (f"{ctx}{who}Translate this visual novel dialogue ({S}) into natural spoken {T}. Keep the tone and "
              f"punctuation style, keep it short.{vi} Output ONLY the translation.\n\n{text}")
    raw = client.chat(prompt, temperature=0.3, max_tokens=500, cancel=cancel)
    return re.sub(r"<think>[\s\S]*?</think>", "", raw or "", flags=re.I).strip()


# ------------------------------------------------------------------ change watcher
def _small(shot_img: Image.Image) -> np.ndarray:
    w, h = shot_img.size
    g = shot_img.convert("L").resize((DIFF_WIDTH, max(4, round(DIFF_WIDTH * h / max(1, w)))), Image.BILINEAR)
    return np.asarray(g, dtype=np.int16)


def differs(a, b, pct=0.3, ignore=None) -> bool:
    """ignore: boolean mask of pixels that do not count (the translation painted over the frame)."""
    if a is None or b is None or a.shape != b.shape:
        return True
    changed = np.abs(a - b) > DIFF_LEVEL
    if ignore is not None and ignore.shape == changed.shape:
        changed = changed[~ignore]
        if changed.size == 0:
            return False
    return float(changed.mean()) * 100 > pct


class VNWatcher(threading.Thread):
    """Costs almost nothing while off. On: one small screen grab every vn_poll_ms, and only while the
    game window is the one in front (alt-tabbed away = no scanning)."""

    def __init__(self, app):
        super().__init__(daemon=True, name="vn-watch")
        self.app = app
        self._stop_ev = threading.Event()

    def stop(self):
        self._stop_ev.set()

    def _active(self):
        a, s = self.app, self.app.s
        return s["layout"] == "vn" and bool(s["vn_auto"]) and not a.paused and not a.selecting

    def _overlay_mask(self, reg, shape):
        """Developer mode: the translation is visible to the screen capture, so the watcher would see it as
        'text changed'. Returns the mask of the pixels it covers (None while it is not visible, or when
        the capture cannot see it)."""
        ov = self.app.overlay
        if not (ov.visible and ov.rect and not ov.exclude_from_capture):
            return None
        m = np.zeros(shape, dtype=bool)
        sx, sy = shape[1] / max(1, reg[2]), shape[0] / max(1, reg[3])
        for _tag, (x1, y1, x2, y2), _poly in list(ov._hit):
            ax, ay = ov.rect[0] - reg[0], ov.rect[1] - reg[1]
            m[max(0, int(sy * (ay + y1))):max(0, int(sy * (ay + y2)) + 1),
              max(0, int(sx * (ax + x1))):max(0, int(sx * (ax + x2)) + 1)] = True
        return m

    @staticmethod
    def _game_in_front(reg):
        if not winapi.IS_WIN:
            return True
        fg = winapi.root_window(winapi.foreground_window())
        under = winapi.window_from_point(reg[0] + reg[2] / 2, reg[1] + reg[3] / 2)
        return bool(fg) and fg == under

    def run(self):
        try:
            import mss
            sct = mss.mss()
        except Exception:
            log.exception("VN watcher could not start")
            return
        prev = stable_ref = None
        changing, t_change = False, 0.0
        dropped = False  # a visible translation was removed because the box changed: it must come back
        painted, ref_painted, ign = False, False, None  # translation visible to the capture (developer mode)
        while True:
            s = self.app.s
            if self._stop_ev.wait(max(0.08, int(s["vn_poll_ms"]) / 1000)):
                break
            try:
                if not self._active():
                    prev = stable_ref = None
                    changing = dropped = painted = ref_painted = False
                    ign = None
                    continue
                reg = self.app._region()
                if not reg or not self._game_in_front(reg):
                    continue
                x, y, w, h = reg
                pct = float(s["vn_change_pct"])
                shot = sct.grab({"left": int(x), "top": int(y), "width": int(w), "height": int(h)})
                cur = _small(Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX"))
                now = time.time()
                mk = self._overlay_mask(reg, cur.shape)
                if mk is not None:
                    ign = mk
                elif not (painted or ref_painted):
                    ign = None
                shown = mk is not None
                if prev is None:            # just switched on: translate what is on screen now
                    changing, t_change = True, now
                elif differs(cur, prev, pct, ign if (shown or painted) else None):  # text is changing: drop the old translation right away
                    if not changing:
                        dropped = dropped or bool(self.app.overlay.visible or self.app.busy)
                        self.app.q.put(("vn_hide",))
                    changing, t_change = True, now
                prev, painted = cur, shown
                if changing and now - t_change >= int(s["vn_stable_ms"]) / 1000:
                    changing = False
                    if stable_ref is None or differs(cur, stable_ref, pct, ign if (shown or ref_painted) else None):
                        stable_ref, dropped, ref_painted = cur, False, shown
                        self.app.q.put(("vn_scan",))
                    elif dropped:
                        # Same text as before: the translation was only hidden by a passing change (the
                        # game's mouse-over effect, a blinking arrow). Show the same translation again,
                        # no new scan and no API call.
                        dropped = False
                        self.app.q.put(("vn_restore",))
            except Exception:
                log.exception("VN watcher tick failed")
                self._stop_ev.wait(1.0)

"""Capture -> OCR -> translate, with image-hash cache. Runs on a worker thread."""
import hashlib
import json
import logging
import os
import time
from collections import OrderedDict

from PIL import Image, ImageDraw

from . import gtranslate, refine
from .api import make_client
from .config import app_dir
from .ocr import run_local_ocr, run_ocr
from .translate import translate_lines

log = logging.getLogger(__name__)
CACHE_SIZE = 60


def grab(rect) -> Image.Image:
    import mss  # imported lazily: each thread needs its own mss instance
    x, y, w, h = rect
    with mss.mss() as sct:
        shot = sct.grab({"left": int(x), "top": int(y), "width": int(w), "height": int(h)})
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def image_key(img: Image.Image) -> str:
    """Hash that ignores tiny noise: 160px wide grayscale, 32 levels."""
    w, h = img.size
    small = img.convert("L").resize((160, max(1, round(160 * h / w))), Image.BILINEAR)
    data = bytes(v >> 3 for v in small.tobytes())
    return hashlib.md5(data + f"{w}x{h}".encode()).hexdigest()


def char_budget(item, settings, scale):
    """About how many characters fit in this bubble at a comfortable size (a hint for the translator)."""
    from .textfit import LINE_H
    size = max(8.0, settings["font_min"] * scale)
    shape = item.get("shape")
    if shape:
        area = sum(max(0, r - l) for l, r in shape["rows"]) * 0.72  # lines never fill the curved edges
    else:
        x1, y1, x2, y2 = item["box"]
        area = (x2 - x1 + 8 * scale) * (y2 - y1 + 8 * scale) * 1.4  # a rect may grow a little
    chars = area / (0.56 * size * size * LINE_H)
    return int(max(6, min(400, chars)))


class Pipeline:
    def __init__(self, settings):
        self.settings = settings
        self.cache = OrderedDict()
        self.prev_lines = []  # source lines of the last page, used as translation context
        self.last_engine = "ai"

    def clear_cache(self):
        self.cache.clear()

    def _cache_key(self, img_key):
        s = self.settings
        return f"{img_key}|{s['source_lang']}|{s['target_lang']}|{s['layout']}|{int(s['skip_sfx'])}|{s['box_format']}|v6|{int(s['manga_tiles'])}|{s['ocr_engine']}|{s['translator'] if s['ocr_engine'] == 'local' else 'ai'}"

    def process(self, img, cancel, on_status, scale=1.0, use_cache=True):
        """Return list of items {text, type, box, translation}. Raises Cancelled / errors.
        use_cache=False: a manual re-scan must really read again (the cached text may be the misread)."""
        s = self.settings
        key = self._cache_key(image_key(img))
        if use_cache and key in self.cache:
            self.cache.move_to_end(key)
            log.info("Cache hit")
            return self.cache[key], True

        mode = s.read_mode()
        client = make_client(s, on_status=lambda m: on_status("info", m)) if s.needs_ai() or s.has_credentials() else None
        if s["layout"] == "vn":
            from . import vn
            t0 = time.time()
            on_status("scanning", "Scanning…")
            items = vn.run_vn(self, client, img, cancel, on_status)
            log.info("VN: %d item(s) in %.1fs", len(items), time.time() - t0)
            if items:  # an empty box is not cached: the same pixels may hold text next time
                self.cache[key] = items
                while len(self.cache) > CACHE_SIZE:
                    self.cache.popitem(last=False)
            return items, False
        if mode == "local_google":
            gtranslate.prewarm()  # reopen the connection to Google while the page is being read
        debug = [] if s["debug_save"] else None
        t0 = time.time()
        on_status("scanning", "Scanning…")
        if s["ocr_engine"] == "local":
            items = run_local_ocr(img, s, cancel, on_status=lambda m: on_status("scanning", m))
        else:
            items = run_ocr(client, img, s, cancel, debug, on_status=lambda m: on_status("scanning", m))
        t1 = time.time()
        log.info("OCR: %d items in %.1fs", len(items), t1 - t0)
        if items:
            refine.attach_colors(img, items)  # background colour of every bubble / box (auto colour option)
            on_status("translating", "Translating…")
            src = [it["text"] for it in items]
            budgets = [char_budget(it, s, scale) for it in items]
            if mode == "local_google":
                try:
                    out = gtranslate.translate(src, s["source_lang"], s["target_lang"], cancel)
                    self.last_engine = "google"
                except gtranslate.TranslateError as e:
                    if client is None:
                        raise
                    # Google blocked for a moment: the AI translates this page if a key is set
                    log.warning("%s -> translating with the AI", e)
                    on_status("translating", "Google busy · AI translating…")
                    out = translate_lines(client, src, s, cancel, self.prev_lines[-12:], budgets)
                    self.last_engine = "ai"
            else:
                out = translate_lines(client, src, s, cancel, self.prev_lines[-12:], budgets)
                self.last_engine = "ai"
            for it, tr in zip(items, out):
                it["translation"] = tr
            self.prev_lines = src
        log.info("Translate: %.1fs", time.time() - t1)

        self.cache[key] = items
        while len(self.cache) > CACHE_SIZE:
            self.cache.popitem(last=False)
        if debug is not None:
            self._save_debug(img, items, debug)
        return items, False

    def _save_debug(self, img, items, raws):
        try:
            d = os.path.join(app_dir(), "logs", "debug")
            os.makedirs(d, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            img.save(os.path.join(d, f"{stamp}_capture.png"))
            vis = img.copy()
            dr = ImageDraw.Draw(vis)
            for i, it in enumerate(items):
                if it.get("model_box"):
                    dr.rectangle(it["model_box"], outline=(255, 170, 0), width=2)
                if it.get("bubble"):
                    dr.rectangle(it["bubble"], outline=(0, 120, 255), width=2)
                dr.rectangle(it["box"], outline=(255, 0, 0), width=3)
                dr.text((it["box"][0] + 3, it["box"][1] + 3), str(i + 1), fill=(255, 0, 0))
            vis.save(os.path.join(d, f"{stamp}_boxes.png"))
            with open(os.path.join(d, f"{stamp}_result.json"), "w", encoding="utf-8") as f:
                json.dump({"items": items, "raw": raws}, f, ensure_ascii=False, indent=2)
        except Exception:
            log.exception("Could not save debug files")

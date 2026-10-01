"""OCR with a vision model: slicing, JSON prompt, tolerant parsing, reading order.

All boxes returned by run_ocr() are in pixels of the ORIGINAL captured image.
"""
import base64
import io
import json
import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from .api import Cancelled

log = logging.getLogger(__name__)

OCR_MAX_TOKENS = 8192

LANG_DESC = {
    "ko": "Korean comic (manhwa/webtoon). Extract the original Korean text exactly.",
    "zh": "Chinese comic (manhua). Extract the original Chinese text exactly; do not convert "
          "between Simplified and Traditional.",
    "en": "English-language comic. Extract the original English text exactly.",
    "ja": "Japanese manga. Extract the original Japanese text exactly. Text is often written "
          "VERTICALLY (top-to-bottom, columns from right to left) - read each column top to bottom, "
          "starting from the rightmost column. If kanji has small furigana beside it, output only "
          "the main text and ignore the furigana.",
    "auto": "comic (manga, manhwa, manhua or English comic). The text may be Japanese, Korean, "
            "Chinese or English: extract it exactly in its original language. Japanese text is often "
            "written VERTICALLY (columns from right to left, each column top to bottom); ignore small "
            "furigana beside kanji.",
}

CJK_RE = re.compile(r"[ᄀ-ᇿ぀-ヿ㄰-㆏㐀-䶿一-鿿"
                    r"가-힯ｦ-ﾟ]")


# ---------------------------------------------------------------- slicing
def find_cuts(gray: np.ndarray, chunk_ratio: float = 1.6):
    """Split a tall image at quiet (blank) rows. Returns [(y0, y1, overlap_top), ...]."""
    H, W = gray.shape
    busy = np.abs(np.diff(gray.astype(np.int16), axis=1)).mean(axis=1) if W > 1 else np.zeros(H)
    QUIET = 2.5
    min_band = max(20, round(W * 0.035))
    target = round(W * chunk_ratio)
    overlap = max(150, round(W * 0.35))
    min_last = round(target * 0.5)
    cuts, y0, overlap_top = [], 0, 0
    while H - y0 > target * 1.4:
        lo = y0 + round(target * 0.5)
        hi = min(H - min_last, y0 + round(target * 2.0))
        if hi <= lo:
            break
        best = None
        y = lo
        while y <= hi:
            if busy[y] >= QUIET:
                y += 1
                continue
            e = y
            while e + 1 <= hi and busy[e + 1] < QUIET:
                e += 1
            length = e - y + 1
            if length >= min_band:
                mid = (y + e) // 2
                score = min(length, 3 * min_band) - abs(mid - (y0 + target)) * 0.08
                if best is None or score > best[1]:
                    best = (mid, score)
            y = e + 1
        if best:
            cut = best[0]
        else:
            # No blank gap: cut at the least busy row, slices overlap
            window = np.convolve(busy, np.ones(24), mode="same")
            a, b = lo + 12, hi - 12
            cut = int(a + np.argmin(window[a:b + 1])) if b > a else y0 + target
        cuts.append((y0, cut, overlap_top))
        if best:
            y0, overlap_top = cut, 0
        else:
            y0 = max(y0 + 1, cut - overlap)
            overlap_top = cut - y0
    cuts.append((y0, H, overlap_top))
    return cuts


def _encode(part: Image.Image) -> str:
    buf = io.BytesIO()
    part.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _make_slice(img, x0, y0, x1, y1, s, inner):
    part = img.crop((x0, y0, x1, y1))
    if abs(s - 1.0) > 0.01:
        part = part.resize((max(1, round((x1 - x0) * s)), max(1, round((y1 - y0) * s))), Image.LANCZOS)
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "s": s, "url": _encode(part),
            "size": part.size, "inner": inner}


def _span_cuts(length, n, overlap):
    """Split [0, length) into n overlapping ranges."""
    if n <= 1:
        return [(0, length)]
    step = (length - overlap) / n
    return [(round(i * step), round(i * step + step + overlap)) if i < n - 1 else (round(i * step), length)
            for i in range(n)]


def prepare_slices(img: Image.Image, max_width: int = 1200, tile: bool = False):
    """Cut the page into pieces the vision model reads well.

    * tall pages (webtoon): split at blank gaps between panels
    * tile=True (manga): overlapping 2 rows (x 2 columns for a double-page spread), each tile
      upscaled so small lettering stays readable
    Each slice: {x0,y0,x1,y1 (region in img px), s (slice px per img px), url, size, inner}
    where inner lists the edges that are internal cuts with an overlapping neighbour.
    """
    img = img.convert("RGB")
    W, H = img.size
    if H / W > 2.0:
        scale = min(1.0, max_width / W)
        small = img if scale >= 1.0 else img.resize((max(1, round(W * scale)), max(1, round(H * scale))), Image.LANCZOS)
        cuts = find_cuts(np.asarray(small.convert("L")))
        out = []
        for i, (y0, y1, ov) in enumerate(cuts):
            Y0, Y1 = round(y0 / scale), min(H, round(y1 / scale))
            inner = set()
            if ov:
                inner.add("top")
            if i + 1 < len(cuts) and cuts[i + 1][2]:
                inner.add("bottom")
            out.append(_make_slice(img, 0, Y0, W, Y1, scale, inner))
        return out
    if not tile or H < 360:
        s = min(1.0, max_width / W)
        return [_make_slice(img, 0, 0, W, H, s, set())]
    cols = 2 if W / H > 1.25 else 1
    tile_w = W / cols
    rows = 2 if H / tile_w > 0.9 else 1
    xs = _span_cuts(W, cols, round(W * 0.08))
    ys = _span_cuts(H, rows, round(H * 0.22))
    out = []
    for r, (y0, y1) in enumerate(ys):
        for c, (x0, x1) in enumerate(xs):
            inner = set()
            if r > 0:
                inner.add("top")
            if r < rows - 1:
                inner.add("bottom")
            if c > 0:
                inner.add("left")
            if c < cols - 1:
                inner.add("right")
            # Upscale small tiles (up to 2x) so the long side is about max_width
            s = max(0.5, min(2.0, max_width / max(x1 - x0, y1 - y0)))
            out.append(_make_slice(img, x0, y0, x1, y1, s, inner))
    return out


# ---------------------------------------------------------------- prompt
def build_ocr_prompt(source_lang: str, skip_sfx: bool) -> str:
    desc = LANG_DESC.get(source_lang, LANG_DESC["auto"])
    extra = ""
    if source_lang == "en":
        extra += ("\n7. Extract ONLY English text. Ignore any text written in Korean, Japanese or "
                  "Chinese characters (untranslated sound effects, signs, watermarks).")
    if skip_sfx:
        extra += '\n8. You may omit "sfx" elements entirely.'
    return f"""You are an OCR engine for comics. This image is a page (or part of a page) from a {desc}

Find EVERY text element on the image and return it as JSON. Do NOT translate.

Rules:
1. One element = one speech bubble, one caption/narration box, one piece of free-floating handwritten text, or one sound effect. Text that wraps onto several lines inside the SAME bubble is ONE element: join the wrapped fragments into a single string (Korean/English: join with a space; Japanese/Chinese: join with no space).
2. Two different bubbles are two different elements, even if they touch or are joined like a double bubble.
3. "type" must be one of: "bubble" (speech/thought bubble), "caption" (rectangular narration box or on-screen window/label), "aside" (small handwritten text drawn on the art with no outline), "sfx" (stylized sound-effect lettering drawn on the art).
4. "box_2d" is the bounding box of the TEXT of the element as [ymin, xmin, ymax, xmax], normalized to 0-1000 (0 = top/left edge of the image, 1000 = bottom/right edge). The box must tightly cover all the characters of that element.
5. Preserve punctuation (…, ?!, 「」, —). Skip elements that have no legible text; never write placeholders like "(blank)".
6. The order of elements in the array does not matter. If the image has no text at all, return {{"items":[]}}.{extra}

Return ONLY this JSON, with no markdown fence and no explanation:
{{"items":[{{"text":"...","type":"bubble","box_2d":[ymin,xmin,ymax,xmax]}}]}}"""


# ---------------------------------------------------------------- parsing
def _escape_newlines_in_strings(s: str) -> str:
    out, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            if esc:
                esc = False
                out.append(ch)
            elif ch == "\\":
                esc = True
                out.append(ch)
            elif ch == '"':
                in_str = False
                out.append(ch)
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                continue
            elif ch == "\t":
                out.append(" ")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    return "".join(out)


def _try(s):
    try:
        return json.loads(s)
    except Exception:
        return None


def parse_items(raw: str):
    """Tolerant JSON parse. Returns list of {text, type, box} or None if nothing parsable."""
    s = re.sub(r"<think>[\s\S]*?</think>", "", str(raw or ""), flags=re.I)
    s = re.sub(r"```(?:json)?", "", s, flags=re.I).strip()
    s = re.sub(r'([{,]\s*)"?(text|type|box_2d|box)"?\s*:(?=\s*["\[])', r'\1"\2":', s)
    s = _escape_newlines_in_strings(s)
    s = re.sub(r'"\s*\n?\s*"(text|type|box_2d|box)"\s*:', r'", "\1":', s)
    s = re.sub(r'\]\s*\n?\s*"(text|type|box_2d|box)"\s*:', r'], "\1":', s)
    s = re.sub(r"\}\s*\n?\s*\{", "}, {", s)
    s = re.sub(r",\s*([}\]])", r"\1", s)
    data = _try(s)
    if data is None:
        o1, o2 = s.find("{"), s.rfind("}")
        a1, a2 = s.find("["), s.rfind("]")
        obj = lambda: _try(s[o1:o2 + 1]) if o1 != -1 and o2 > o1 else None  # noqa: E731
        arr = lambda: _try(s[a1:a2 + 1]) if a1 != -1 and a2 > a1 else None  # noqa: E731
        if a1 != -1 and (o1 == -1 or a1 < o1):
            data = arr() or obj()
        else:
            data = obj() or arr()
    if data is None:
        # Truncated JSON: salvage complete items
        found = []
        for m in re.finditer(r'\{[^{}]*?"text"\s*:\s*"(?:[^"\\]|\\.)*"[^{}]*?\}', s):
            it = _try(m.group(0))
            if it:
                found.append(it)
        if not found:
            return None
        data = found
    if isinstance(data, dict):
        arr = next((data[k] for k in ("items", "elements", "bubbles", "texts") if isinstance(data.get(k), list)), [])
    elif isinstance(data, list):
        arr = data
    else:
        arr = []
    out = []
    for it in arr:
        if not isinstance(it, dict) or not isinstance(it.get("text"), str) or not it["text"].strip():
            continue
        out.append({
            "text": re.sub(r"\s*\n\s*", " ", it["text"]).strip(),
            "type": str(it.get("type") or "bubble").lower(),
            "box": next((it[k] for k in ("box_2d", "box", "bbox", "bbox_2d") if it.get(k) is not None), None),
        })
    return out


def normalize_box(box, order: str = "xyxy"):
    if box is None:
        return None
    try:
        if isinstance(box, dict):
            b = [float(box[k]) for k in ("x1", "y1", "x2", "y2")]
        elif isinstance(box, (list, tuple)) and len(box) == 4:
            b = [float(v) for v in box]
        else:
            return None
    except (TypeError, ValueError, KeyError):
        return None
    if order == "yxyx":
        b = [b[1], b[0], b[3], b[2]]
    return [min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3])]


# ---------------------------------------------------------------- ordering / dedupe
def sort_reading_order(items, layout: str):
    """Group boxes into rows (vertical overlap), rows top->bottom, inside a row RTL for manga."""
    with_box = [it for it in items if it.get("box")]
    no_box = [it for it in items if not it.get("box")]
    parent = list(range(len(with_box)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in range(len(with_box)):
        for b in range(a + 1, len(with_box)):
            A, B = with_box[a]["box"], with_box[b]["box"]
            ov = min(A[3], B[3]) - max(A[1], B[1])
            min_h = max(1, min(A[3] - A[1], B[3] - B[1]))
            if ov / min_h >= 0.1:
                parent[find(a)] = find(b)
    rows = {}
    for i, it in enumerate(with_box):
        rows.setdefault(find(i), []).append(it)
    rtl = layout == "manga"
    cx = lambda b: (b[0] + b[2]) / 2  # noqa: E731
    out = []
    for row in sorted(rows.values(), key=lambda r: min(it["box"][1] for it in r)):
        row.sort(key=lambda it: ((-cx(it["box"]) if rtl else cx(it["box"])), it["box"][1]))
        out.extend(row)
    return out + no_box


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    return "".join(ch for ch in s if not (ch.isspace() or unicodedata.category(ch)[0] in "PS"))


def similarity(a: str, b: str) -> float:
    A, B = norm_text(a), norm_text(b)
    L = max(len(A), len(B))
    if not L:
        return 1.0
    prev = list(range(len(B) + 1))
    for i in range(1, len(A) + 1):
        cur = [i] + [0] * len(B)
        for j in range(1, len(B) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (A[i - 1] != B[j - 1]))
        prev = cur
    return 1 - prev[len(B)] / L


def _overlap_ratio(A, B) -> float:
    ix = max(0, min(A[2], B[2]) - max(A[0], B[0]))
    iy = max(0, min(A[3], B[3]) - max(A[1], B[1]))
    inter = ix * iy
    small = min((A[2] - A[0]) * (A[3] - A[1]), (B[2] - B[0]) * (B[3] - B[1]))
    return inter / small if small > 0 else 0.0


def dedupe(items):
    """Drop repeats: same text twice, or near-same text on overlapping boxes (slice overlap)."""
    kept = []
    for it in items:
        dup = False
        for k in kept:
            same_box = it["box"] and k["box"] and _overlap_ratio(it["box"], k["box"]) > 0.3
            if same_box and similarity(it["text"], k["text"]) >= 0.8:
                dup = True
                if (it["box"][2] - it["box"][0]) * (it["box"][3] - it["box"][1]) > \
                        (k["box"][2] - k["box"][0]) * (k["box"][3] - k["box"][1]):
                    k.update(it)  # keep the bigger (less cut-off) one
                break
        if not dup:
            kept.append(it)
    return kept


# ---------------------------------------------------------------- main entry
def _to_pixels(b, order, sl, ox, oy, W, H):
    """Raw model box (0-1000 or slice px) -> capture pixels."""
    b = normalize_box(b, order)
    if not b:
        return None, False
    sw, sh = sl["size"]
    if max(b) <= 1000.5:  # normalized 0-1000 -> slice pixels
        b = [b[0] * sw / 1000, b[1] * sh / 1000, b[2] * sw / 1000, b[3] * sh / 1000]
    # Touching an internal cut edge: the bubble is probably cut in half in this tile
    m = 0.015
    cut = (("top" in sl["inner"] and b[1] < sh * m) or ("bottom" in sl["inner"] and b[3] > sh * (1 - m))
           or ("left" in sl["inner"] and b[0] < sw * m) or ("right" in sl["inner"] and b[2] > sw * (1 - m)))
    s = sl["s"]
    b = [b[0] / s + sl["x0"] + ox, b[1] / s + sl["y0"] + oy, b[2] / s + sl["x0"] + ox, b[3] / s + sl["y0"] + oy]
    b = [max(0, min(W, b[0])), max(0, min(H, b[1])), max(0, min(W, b[2])), max(0, min(H, b[3]))]
    if b[2] - b[0] < 2 or b[3] - b[1] < 2:
        return None, False
    return b, cut


def _inside_other_tile(box, sl, slices, ox, oy):
    """Is the box fully visible (with margin) in another tile? Then that tile has the whole bubble."""
    for o in slices:
        if o is sl:
            continue
        mx, my = 0.02 * (o["x1"] - o["x0"]), 0.02 * (o["y1"] - o["y0"])
        if (box[0] >= o["x0"] + ox + mx and box[2] <= o["x1"] + ox - mx and
                box[1] >= o["y0"] + oy + my and box[3] <= o["y1"] + oy - my):
            return True
    return False


def _is_cjk(text):
    letters = [ch for ch in text if not ch.isspace()]
    return bool(letters) and len(CJK_RE.findall(text)) / len(letters) > 0.5


def merge_fragments(items, layout):
    """Join items that belong to the same bubble (models often return one item per text column)."""
    from .refine import _iou
    n = len(items)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in range(n):
        for b in range(a + 1, n):
            A, B = items[a], items[b]
            same_bubble = A.get("bubble") and B.get("bubble") and _iou(A["bubble"], B["bubble"]) > 0.6
            if same_bubble or _overlap_ratio(A["box"], B["box"]) > 0.5:
                parent[find(a)] = find(b)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(items[i])
    out = []
    for g in groups.values():
        if len(g) == 1:
            out.append(g[0])
            continue
        mb = [it.get("model_box") or it["box"] for it in g]
        vertical = sum(b[3] - b[1] for b in mb) > 1.2 * sum(b[2] - b[0] for b in mb)
        order = sorted(range(len(g)), key=lambda i: (-(mb[i][0] + mb[i][2]) if vertical else mb[i][1], mb[i][0]))
        texts = []
        for i in order:
            t = g[i]["text"]
            if not any(similarity(t, u) >= 0.8 for u in texts):
                texts.append(t)
        joiner = "" if all(_is_cjk(t) for t in texts) else " "
        bubbles = [it["bubble"] for it in g if it.get("bubble")]
        merged = dict(g[order[0]])
        merged["text"] = joiner.join(texts)
        merged["box"] = [min(it["box"][0] for it in g), min(it["box"][1] for it in g),
                         max(it["box"][2] for it in g), max(it["box"][3] for it in g)]
        merged["bubble"] = max(bubbles, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if bubbles else None
        shapes = [it for it in g if it.get("shape") and it.get("bubble") == merged["bubble"]]
        merged["shape"] = shapes[0]["shape"] if shapes else None
        log.info("Merged %d fragments into one bubble: %s", len(g), merged["text"][:40])
        out.append(merged)
    return out


def run_ocr(client, img: Image.Image, settings, cancel, debug=None, on_status=None):
    """Return list of {text, type, box, bubble} in capture pixels, in reading order."""
    from . import refine

    img = img.convert("RGB")
    gray = np.asarray(img.convert("L"))
    inv = 255 - gray
    # 1. Cut the empty browser background so the page is sent at full resolution
    crop = refine.trim_borders(gray)
    ox, oy = (crop[0], crop[1]) if crop else (0, 0)
    work = img.crop(crop) if crop else img
    if crop:
        log.info("Trimmed capture %sx%s -> page %s", img.width, img.height, crop)
    tile = settings["layout"] == "manga" and bool(settings["manga_tiles"])
    slices = prepare_slices(work, int(settings["max_slice_width"]), tile=tile)
    log.info("Sending %d piece(s): %s", len(slices),
             [(sl["x0"], sl["y0"], sl["x1"], sl["y1"], round(sl["s"], 2)) for sl in slices])
    prompt = build_ocr_prompt(settings["source_lang"], settings["skip_sfx"])

    def call(sl):
        content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": sl["url"]}}]
        raw = ""
        for attempt in range(2):
            raw = client.chat(content, temperature=0.1, max_tokens=OCR_MAX_TOKENS, cancel=cancel)
            items = parse_items(raw)
            if items is not None:
                return raw, items
            log.warning("OCR piece returned no JSON (attempt %d): %.300s", attempt + 1, raw)
        return raw, None

    workers = max(1, min(int(settings["ocr_concurrency"]), len(slices)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(call, slices))
    if cancel.is_set():
        raise Cancelled()

    raw_items, ok = [], 0
    for sl, (raw, items) in zip(slices, results):
        if debug is not None:
            debug.append({"piece": [sl["x0"], sl["y0"], sl["x1"], sl["y1"]], "scale": sl["s"],
                          "offset": [ox, oy], "raw": raw})
        if items is None:
            continue
        ok += 1
        if not items:
            log.info("Piece %s: model found no text. Raw: %.200s", (sl["x0"], sl["y0"]), raw)
        for it in items:
            it["_raw"], it["_sl"] = it.pop("box"), sl
            raw_items.append(it)
    if not ok:
        raise RuntimeError("OCR returned no usable JSON")
    no_box = sum(1 for it in raw_items if it["_raw"] is None)
    if no_box:
        log.warning("%d items came without a box and are skipped", no_box)

    # 2. Which axis order did the model really use? Test both on the pixels.
    fmt = settings["box_format"]
    W, H = img.width, img.height
    if fmt in ("xyxy", "yxyx"):
        order = fmt
    else:
        cands = {o: [_to_pixels(it["_raw"], o, it["_sl"], ox, oy, W, H)[0] for it in raw_items]
                 for o in ("yxyx", "xyxy")}
        order = refine.choose_order(gray, cands)
    all_items, dropped = [], 0
    for it in raw_items:
        sl = it.pop("_sl")
        box, cut = _to_pixels(it.pop("_raw"), order, sl, ox, oy, W, H)
        if box and cut and _inside_other_tile(box, sl, slices, ox, oy):
            dropped += 1  # half a bubble at a tile seam; the neighbouring tile has all of it
            continue
        it["box"] = box
        all_items.append(it)
    if dropped:
        log.info("Dropped %d half-bubbles at tile seams", dropped)
    return _finish(all_items, gray, inv, settings)


def _finish(all_items, gray, inv, settings):
    """Snap boxes to bubbles, filter, join fragments, reading order (shared by AI and local OCR)."""
    from . import refine
    for it in all_items:
        box = it["box"]
        it["bubble"] = None
        # 3. Snap to the real text strokes / bubble outline
        if box:
            snapped = refine.refine_any(gray, inv, box)
            if snapped:
                it["model_box"] = box
                it["box"], it["bubble"] = list(snapped[0]), (list(snapped[1]) if snapped[1] else None)
                it["shape"] = snapped[2]

    if settings["skip_sfx"]:
        all_items = [it for it in all_items if it["type"] != "sfx"]
    if settings["source_lang"] == "en":
        all_items = [it for it in all_items
                     if len(CJK_RE.findall(it["text"])) <= 0.3 * max(1, len(norm_text(it["text"])))]
    # Overlay needs a position: items without a box cannot be drawn
    all_items = [it for it in all_items if it["box"]]
    all_items = dedupe(all_items)
    # 4. One bubble = one item (join column fragments), then reading order
    all_items = merge_fragments(all_items, settings["layout"])
    return sort_reading_order(all_items, settings["layout"])


def run_local_ocr(img: Image.Image, settings, cancel, on_status=None):
    """Same output as run_ocr, read on this PC (local_ocr) instead of by the AI."""
    from . import local_ocr, refine
    img = img.convert("RGB")
    gray = np.asarray(img.convert("L"))
    inv = 255 - gray
    crop = refine.trim_borders(gray)
    ox, oy = (crop[0], crop[1]) if crop else (0, 0)
    work = img.crop(crop) if crop else img
    items = local_ocr.ENGINE.read(work, settings, cancel, on_status)
    if cancel.is_set():
        raise Cancelled()
    for it in items:
        x1, y1, x2, y2 = it["box"]
        it["box"] = [x1 + ox, y1 + oy, x2 + ox, y2 + oy]
    log.info("Local OCR: %d blocks", len(items))
    return _finish(items, gray, inv, settings)

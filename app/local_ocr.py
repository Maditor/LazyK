"""Local OCR: reads the page on this PC, no API quota (the AI then only translates the text).

  Built in     RapidOCR with PaddleOCR PP-OCRv6 (detector + multilingual recognizer):
               Japanese (also vertical), Chinese, English. Nothing to download.
  Korean       PP-OCRv5 Korean recognizer, 13 MB download.
  manga-ocr    optional, 460 MB: reads Japanese manga lettering (hand drawn, stylised) better.
               PP-OCRv6 still finds the text; manga-ocr reads each block.

Models are ONNX, run with onnxruntime (DirectML = any Windows GPU, else CPU), and downloads are kept in
%LOCALAPPDATA%\\LazyK\\models so rebuilding or reinstalling the app keeps them.
"""
import hashlib
import logging
import os
import re
import threading
import time

import numpy as np
import requests
from PIL import Image

from .api import Cancelled

log = logging.getLogger(__name__)

GPU_ID = 0  # DirectML device used when the graphics card is on (set from settings.local_gpu_id)
# Visual novel: manga-ocr (slow, no KV cache) only re-reads rows RapidOCR is NOT sure about
VN_MOCR_BELOW = 0.90

# ---------------------------------------------------------------- model files
# name -> list of (url, sha256 or None); the first URL that works wins
FILES = {
    "mocr_encoder.onnx": [
        ("https://huggingface.co/mayocream/manga-ocr-onnx/resolve/main/encoder_model.onnx", None),
        ("https://huggingface.co/HighLiuk/japanese-onnx-models/resolve/main/ocr_encoder.onnx", None)],
    "mocr_decoder.onnx": [
        ("https://huggingface.co/mayocream/manga-ocr-onnx/resolve/main/decoder_model.onnx", None),
        ("https://huggingface.co/HighLiuk/japanese-onnx-models/resolve/main/ocr_decoder.onnx", None)],
    "mocr_vocab.txt": [
        ("https://huggingface.co/mayocream/manga-ocr-onnx/resolve/main/vocab.txt", None),
        ("https://huggingface.co/HighLiuk/japanese-onnx-models/resolve/main/ocr.txt", None)],
    "korean_rec.onnx": [
        ("https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/"
         "korean_PP-OCRv5_rec_mobile.onnx", "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b")],
}
# The manga-ocr files of both sources must not be mixed (vocab and decoder belong together)
MOCR_SET = ("mocr_encoder.onnx", "mocr_decoder.onnx", "mocr_vocab.txt")

PACKS = {
    "builtin": {"name": "Japanese · Chinese · English", "files": [], "size": "built in"},
    "ko": {"name": "Korean", "files": ["korean_rec.onnx"], "size": "13 MB"},
    "mocr": {"name": "manga-ocr (Japanese manga lettering)", "files": list(MOCR_SET), "size": "460 MB"},
}


def models_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    d = os.path.join(base, "LazyK", "models")
    os.makedirs(d, exist_ok=True)
    return d


def path(name):
    return os.path.join(models_dir(), name)


def pack_ready(pack):
    return all(os.path.isfile(path(f)) for f in PACKS[pack]["files"])


def download_pack(pack, on_progress=None, cancel=None):
    """Download the missing files of a pack. on_progress(fraction 0..1, text)."""
    need = [f for f in PACKS[pack]["files"] if not os.path.isfile(path(f))]
    if not need:
        return
    plain = [f for f in need if f not in MOCR_SET]
    mocr = [f for f in MOCR_SET if f in PACKS[pack]["files"]] if any(f in MOCR_SET for f in need) else []
    count = len(plain) + len(mocr)
    step = [0]

    def get(name, url, sha):
        def prog(got, total):
            if on_progress:
                frac = (step[0] + (got / total if total else 0)) / count
                size = f"{got / 1e6:.0f}/{total / 1e6:.0f} MB" if total else f"{got / 1e6:.0f} MB"
                on_progress(frac, f"{name} · {size}")
        _download(url, path(name), sha, cancel, prog)
        step[0] += 1

    for name in plain:
        last = None
        for url, sha in FILES[name]:
            try:
                get(name, url, sha)
                last = None
                break
            except Cancelled:
                raise
            except Exception as e:
                last = e
                log.warning("Download %s from %s failed: %s", name, url, e)
        if last:
            raise RuntimeError(f"Could not download {name}: {last}")

    if mocr:
        # the three manga-ocr files must come from the same source (vocab and decoder belong together)
        last = None
        for k in range(len(FILES[MOCR_SET[0]])):
            try:
                for name in mocr:
                    if not os.path.isfile(path(name)):
                        get(name, *FILES[name][k])
                last = None
                break
            except Cancelled:
                raise
            except Exception as e:
                last = e
                log.warning("manga-ocr source %d failed: %s", k + 1, e)
                for name in mocr:
                    if os.path.isfile(path(name)):
                        os.remove(path(name))
                step[0] = len(plain)
        if last:
            raise RuntimeError(f"Could not download manga-ocr: {last}")
    if on_progress:
        on_progress(1.0, "Done")


def _download(url, dest, sha, cancel, progress):
    tmp = dest + ".part"
    h = hashlib.sha256()
    with requests.get(url, stream=True, timeout=(15, 60), headers={"User-Agent": "LazyK"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        got, last = 0, 0.0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                if cancel is not None and cancel.is_set():
                    f.close()
                    os.remove(tmp)
                    raise Cancelled()
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if time.time() - last > 0.2:
                    progress(got, total)
                    last = time.time()
        progress(got, total)
    if total and got < total:
        os.remove(tmp)
        raise RuntimeError("download incomplete")
    if sha and h.hexdigest() != sha:
        os.remove(tmp)
        raise RuntimeError("checksum mismatch")
    os.replace(tmp, dest)


# ---------------------------------------------------------------- onnxruntime
def gpu_name():
    """'DirectML' / 'CUDA' when a GPU provider is installed, else ''."""
    try:
        import onnxruntime as ort
        av = ort.get_available_providers()
    except Exception:
        return ""
    if "CUDAExecutionProvider" in av:
        return "CUDA"
    if "DmlExecutionProvider" in av:
        return "DirectML"
    return ""


def _session(model, use_gpu):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.log_severity_level = 3
    providers = ["CPUExecutionProvider"]
    gpu = gpu_name() if use_gpu else ""
    if gpu == "DirectML":
        so.enable_mem_pattern = False  # required by DirectML
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        providers = [("DmlExecutionProvider", {"device_id": str(GPU_ID)}), "CPUExecutionProvider"]
    elif gpu == "CUDA":
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    try:
        return ort.InferenceSession(model, so, providers=providers)
    except Exception as e:
        if len(providers) == 1:
            raise
        log.warning("GPU session failed (%s), using CPU for %s", e, os.path.basename(model))
        return ort.InferenceSession(model, ort.SessionOptions(), providers=["CPUExecutionProvider"])


# ---------------------------------------------------------------- manga-ocr
class MangaOcr:
    """manga-ocr (ViT encoder + BERT decoder), ONNX export, greedy decoding."""

    def __init__(self, use_gpu):
        self.enc = _session(path("mocr_encoder.onnx"), use_gpu)
        self.dec = _session(path("mocr_decoder.onnx"), use_gpu)
        with open(path("mocr_vocab.txt"), encoding="utf-8") as f:
            self.vocab = f.read().splitlines()
        self.enc_in = self.enc.get_inputs()[0].name
        self.dec_names = [i.name for i in self.dec.get_inputs()]

    def __call__(self, crop: Image.Image, max_len=150):
        im = crop.convert("L").convert("RGB").resize((224, 224), Image.BILINEAR)
        x = (np.asarray(im, np.float32) / 255.0 - 0.5) / 0.5
        hidden = self.enc.run(None, {self.enc_in: x.transpose(2, 0, 1)[None]})[0]
        ids = [2]  # [CLS] starts, [SEP] (3) ends
        for _ in range(max_len):
            feed = {}
            for n in self.dec_names:
                if "hidden" in n:
                    feed[n] = hidden
                elif "mask" in n:
                    feed[n] = np.ones((1, len(ids)), np.int64)
                else:
                    feed[n] = np.array([ids], np.int64)
            logits = self.dec.run(None, feed)[0]
            nxt = int(logits[0, -1].argmax())
            ids.append(nxt)
            if nxt == 3:
                break
        text = "".join(self.vocab[i] for i in ids if i >= 5 and i < len(self.vocab))
        return _mocr_post(text)


def _mocr_post(text):
    text = "".join(text.split()).replace("…", "...")
    text = re.sub("[・.]{2,}", lambda m: (m.end() - m.start()) * ".", text)
    try:
        import jaconv
        text = jaconv.h2z(text, ascii=True, digit=True)
    except ImportError:
        pass
    return text


# ---------------------------------------------------------------- RapidOCR (PaddleOCR models)
def _patch_dml_device():
    """RapidOCR passes no device number to DirectML (it always takes card 0). Let it use GPU_ID instead.
    Card 0 keeps RapidOCR's own behaviour. Written against the pinned rapidocr 3.9.2; if the module is not
    as expected nothing changes (the default card is used)."""
    try:
        from rapidocr.inference_engine.onnxruntime import provider_config as pc
        if getattr(pc.ProviderConfig, "_lazyk_dml", False):
            return
        orig = pc.ProviderConfig.dml_ep_cfg

        def dml_ep_cfg(self):
            return {"device_id": str(GPU_ID)} if GPU_ID else orig(self)
        pc.ProviderConfig.dml_ep_cfg = dml_ep_cfg
        pc.ProviderConfig._lazyk_dml = True
    except Exception as e:  # noqa: BLE001
        log.info("Could not set the DirectML device (using the default card): %s", e)


def _rapid(kind, use_gpu, rec_only=False, vn=False):
    """kind: 'multi' (built-in PP-OCRv6: ja / zh / en) | 'ko' (PP-OCRv5 Korean) | 'det' (detector only).
    rec_only: no detector; the image given is already one line of text (visual novel row re-read).
    It must be its own instance: calling a normal engine with use_det=False corrupts its later calls.
    vn: detector for a visual novel text box. RapidOCR's default (limit_type 'min', 736) ENLARGES every image
    until its short side is 736 px, so a 1000x220 dialogue box is detected at ~3300x736: about 8x slower
    (measured 4.0 s -> 0.5 s, same lines read). limit_type 'max' keeps the original size (what Luna does);
    manga pages are big already and keep the default."""
    from rapidocr import RapidOCR
    import rapidocr
    builtin = os.path.join(os.path.dirname(rapidocr.__file__), "models")
    gpu = gpu_name() if use_gpu else ""
    params = {
        "Global.log_level": "error",
        "Global.use_cls": False,  # comic text is upright
        "Global.text_score": 0.0,  # keep every line: LazyK filters and scores them itself
        "Global.model_root_dir": models_dir(),
        "Det.model_path": os.path.join(builtin, "PP-OCRv6_det_small.onnx"),
        "Cls.model_path": os.path.join(builtin, "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
        "Rec.model_path": os.path.join(builtin, "PP-OCRv6_rec_small.onnx"),
        "Det.box_thresh": 0.45,
        "EngineConfig.onnxruntime.use_dml": gpu == "DirectML",
        "EngineConfig.onnxruntime.use_cuda": gpu == "CUDA",
    }
    if kind == "det":
        params["Global.use_rec"] = False
    if vn:
        params["Det.limit_type"] = "max"
    if rec_only:
        params["Global.use_det"] = False
    if kind == "ko":
        from rapidocr import LangRec, ModelType, OCRVersion
        params.update({"Rec.model_path": path("korean_rec.onnx"), "Rec.lang_type": LangRec.KOREAN,
                       "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE})
    if gpu == "DirectML":
        _patch_dml_device()
    try:
        return RapidOCR(params=params)
    except Exception as e:  # noqa: BLE001
        if gpu != "DirectML":
            raise
        log.warning("OCR on graphics card %s failed (%s): using the CPU", GPU_ID, e)
        params["EngineConfig.onnxruntime.use_dml"] = False
        return RapidOCR(params=params)


def _lines(res, min_score=0.5):
    """RapidOCR result -> [{text, box, score}] (boxes as x1 y1 x2 y2)."""
    out = []
    boxes = res.boxes if getattr(res, "boxes", None) is not None else []
    txts = getattr(res, "txts", None) or [""] * len(boxes)
    scores = getattr(res, "scores", None) or [1.0] * len(boxes)
    for box, txt, sc in zip(boxes, txts, scores):
        pts = np.asarray(box)
        b = [int(pts[:, 0].min()), int(pts[:, 1].min()), int(pts[:, 0].max()), int(pts[:, 1].max())]
        if sc >= min_score:
            out.append({"text": (txt or "").strip(), "box": b, "score": float(sc)})
    return out


def _divided(gray, A, B, vertical):
    """True when a drawn line (a bubble outline) runs between two text lines: they are in different bubbles."""
    if gray is None:
        return False
    if vertical:  # columns side by side: look at the strip between them
        if max(A[0], B[0]) - min(A[2], B[2]) < 3:
            return False  # touching / overlapping columns: nothing can be drawn between them
        x1, x2 = sorted((min(A[2], B[2]), max(A[0], B[0])))
        y1, y2 = max(A[1], B[1]), min(A[3], B[3])
        if y2 - y1 < 4:
            y1, y2 = min(A[1], B[1]), max(A[3], B[3])
        band = gray[y1:y2, x1:x2].T  # rows of the band run along the gap
    else:  # lines stacked: look at the strip between them
        if max(A[1], B[1]) - min(A[3], B[3]) < 3:
            return False
        y1, y2 = sorted((min(A[3], B[3]), max(A[1], B[1])))
        x1, x2 = max(A[0], B[0]), min(A[2], B[2])
        if x2 - x1 < 4:  # barely overlapping: use the span between their centres
            x1, x2 = sorted((int((A[0] + A[2]) / 2), int((B[0] + B[2]) / 2)))
            x1, x2 = x1 - 4, x2 + 4
        band = gray[y1:y2, max(0, x1):x2]
    if band.size == 0 or band.shape[0] == 0 or band.shape[1] < 3:
        return False
    dark = (band < 110).mean(axis=1)
    return bool((dark > 0.3).any())


def _group_lines(lines, cjk_join, gray=None):
    """Text lines -> blocks: lines stacked close together (or side-by-side columns) are one block,
    unless a bubble outline runs between them."""
    n = len(lines)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in range(n):
        A = lines[a]["box"]
        for b in range(a + 1, n):
            B = lines[b]["box"]
            vert_a, vert_b = (A[3] - A[1]) > 1.5 * (A[2] - A[0]), (B[3] - B[1]) > 1.5 * (B[2] - B[0])
            if vert_a and vert_b:  # vertical columns side by side
                t = min(A[2] - A[0], B[2] - B[0])
                gap = max(A[0], B[0]) - min(A[2], B[2])
                ov = min(A[3], B[3]) - max(A[1], B[1])
                ok = gap < 0.9 * t and ov > 0.3 * min(A[3] - A[1], B[3] - B[1])
            elif not vert_a and not vert_b:  # horizontal lines stacked
                t = min(A[3] - A[1], B[3] - B[1])
                gap = max(A[1], B[1]) - min(A[3], B[3])
                ov = min(A[2], B[2]) - max(A[0], B[0])
                ca, cb = (A[0] + A[2]) / 2, (B[0] + B[2]) / 2
                ok = gap < 0.8 * t and (ov > 0 or abs(ca - cb) < 0.5 * max(A[2] - A[0], B[2] - B[0])) \
                    and max(A[3] - A[1], B[3] - B[1]) < 1.8 * t
            else:
                ok = False
            if ok and _divided(gray, A, B, vert_a):
                ok = False
            if ok:
                parent[find(a)] = find(b)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(lines[i])
    blocks = []
    for g in groups.values():
        vertical = all((l["box"][3] - l["box"][1]) > 1.5 * (l["box"][2] - l["box"][0]) for l in g)
        g.sort(key=(lambda l: -l["box"][2]) if vertical else (lambda l: (l["box"][1], l["box"][0])))
        joiner = "" if cjk_join else " "
        blocks.append({"text": joiner.join(l["text"] for l in g),
                       "box": [min(l["box"][0] for l in g), min(l["box"][1] for l in g),
                               max(l["box"][2] for l in g), max(l["box"][3] for l in g)]})
    return blocks


# ---------------------------------------------------------------- visual novel text box
# The generic page reader (detect -> group -> join) is built for comic pages. On a dialogue box it
# fails in four ways: the speaker name is glued to the dialogue ("Yuki I never ..."), one text line
# is detected as two overlapping pieces (scrambled / duplicated / clipped words), text touching the
# frame edge is not detected at all, and small text is missed. The VN reader below fixes each.
_VN_END = re.compile(r"[.!?…。！？\"”」』)）]$")
_VN_BRACKETS = "【】[]「」『』()（）<>《》:："
_VN_OPEN, _VN_CLOSE = "([（「『【《<", ")]）」』】》>"


def _name_bracketed(t):
    """【Yuki】 (Yuki) 「Yuki」 or "Yuki:" look like a speaker label. A lone opening bracket does not:
    "(My life, everything," is the first line of a thought that closes on the next line."""
    t = t.strip()
    if not t:
        return False
    if t[-1] in ":：":
        return True
    return t[0] in _VN_OPEN and t[-1] in _VN_CLOSE and _VN_OPEN.index(t[0]) == _VN_CLOSE.index(t[-1])


def _pad_bgr(bgr, pad):
    """Border in the box's own colour: detectors miss text that touches the edge of the frame."""
    import cv2
    ring = np.concatenate([bgr[0], bgr[-1], bgr[:, 0], bgr[:, -1]])
    col = [int(v) for v in np.median(ring, axis=0)]
    return cv2.copyMakeBorder(bgr, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=col)


def _vn_keep(lines):
    """Gentle filter for a dialogue box: unlike _clean it keeps unsure lines (they get re-read)."""
    out = [l for l in lines if _TEXTY.search(l["text"]) and l["score"] >= 0.3]
    if not out:
        return []
    hs = sorted(l["box"][3] - l["box"][1] for l in out)
    med = hs[len(hs) // 2]
    keep = []
    for l in out:
        t = l["text"].replace(" ", "")
        if len(t) == 1 and l["score"] < 0.9:
            continue  # a lone, unsure character: a misread mark
        if (l["box"][3] - l["box"][1]) < 0.4 * med:
            continue  # tiny: furigana, a blinking arrow
        keep.append(l)
    return keep


def _vn_rows(lines):
    """Detected pieces -> text rows. Pieces that share a vertical band are the SAME row, however they
    were cut (this is what fixes the scrambled / duplicated words)."""
    rows = []
    for l in sorted(lines, key=lambda l: l["box"][1] + l["box"][3]):
        b = l["box"]
        for r in rows:
            ov = min(b[3], r["y2"]) - max(b[1], r["y1"])
            if ov > 0.5 * min(b[3] - b[1], r["y2"] - r["y1"]):
                r["segs"].append(l)
                r["x1"], r["y1"] = min(r["x1"], b[0]), min(r["y1"], b[1])
                r["x2"], r["y2"] = max(r["x2"], b[2]), max(r["y2"], b[3])
                break
        else:
            rows.append({"segs": [l], "x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3]})
    rows.sort(key=lambda r: r["y1"])
    for r in rows:
        r["segs"].sort(key=lambda l: l["box"][0])
    return rows


def _row_ink(bgr, row):
    """Colour of a row's letters: mean of the pixels that differ most from the row's background."""
    crop = bgr[max(0, row["y1"]):row["y2"], max(0, row["x1"]):row["x2"]].reshape(-1, 3).astype(np.float32)
    if len(crop) < 20:
        return None
    d = np.linalg.norm(crop - np.median(crop, axis=0), axis=1)
    k = max(20, int(0.08 * len(crop)))
    return crop[np.argsort(d)[-k:]].mean(axis=0)


def _split_name(rows):
    """First row = speaker name? It must look like one (short, no sentence end, narrower than the
    dialogue) AND be set apart (gap, size, indent, brackets or its own colour). -> (name, body rows)"""
    if len(rows) < 2:
        return "", rows
    r0, rest = rows[0], rows[1:]
    t = r0["text"].strip()
    core = t.strip(_VN_BRACKETS + " ")
    if not core or len(core) > 24 or len(core.split()) > 4 or _VN_END.search(core) or core[-1] in ",、，;；":
        return "", rows  # a name does not end like a sentence, nor with a comma (the sentence goes on below)
    h0, h1 = r0["y2"] - r0["y1"], rest[0]["y2"] - rest[0]["y1"]
    w0, wb = r0["x2"] - r0["x1"], max(r["x2"] - r["x1"] for r in rest)
    bracket_cue = _name_bracketed(t)
    if w0 > 0.6 * wb and not bracket_cue:
        return "", rows
    gap = rest[0]["y1"] - r0["y2"]
    if len(rest) >= 2:   # compare with the normal line spacing of the dialogue itself
        pitch = max(0, rest[1]["y1"] - rest[0]["y2"])
        gap_cue = gap > 1.6 * pitch + 0.25 * h1
    else:
        gap_cue = gap > 0.8 * h1
    size_cue = abs(h0 - h1) > 0.35 * max(h0, h1)
    indent_cue = abs(r0["x1"] - rest[0]["x1"]) > 0.5 * h1
    i0, i1 = r0.get("ink"), rest[0].get("ink")
    colour_cue = i0 is not None and i1 is not None and float(np.linalg.norm(i0 - i1)) > 70
    r0["cues"] = [n for n, v in (("gap", gap_cue), ("size", size_cue), ("indent", indent_cue),
                                 ("bracket", bracket_cue), ("colour", colour_cue)) if v]
    return (core, rest) if r0["cues"] else ("", rows)



_TEXTY = re.compile(r"[\w぀-ヿ㐀-鿿가-힯]")


# ---------------------------------------------------------------- engine
class LocalOcr:
    """Loads models lazily and keeps them in memory (the first page is slower)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._models = {}
        self._gpu = None
        self._last_lang = "multi"  # which recognizer won on the previous page
        self.hint = ""  # advice for the user after a page (shown in the toolbar)

    def reset(self):
        """Forget loaded models (after removing files)."""
        with self._lock:
            self._models.clear()

    def warm(self, settings):
        """Load the usual models in the background so the first page is not slow."""
        def run():
            from . import winapi
            winapi.lower_this_thread()
            try:
                with self._lock:
                    use_gpu = bool(settings["local_gpu"])
                    kind = "ko" if settings["source_lang"] == "ko" and pack_ready("ko") else "multi"
                    self._get(kind, lambda: _rapid(kind, use_gpu), use_gpu)
                    self._get(kind + "_vn", lambda: _rapid(kind, use_gpu, vn=True), use_gpu)
                    # visual novel rows are re-read by their own recognizer: load it now too, or the
                    # first dialogue box that needs it waits for the model to load
                    self._get(kind + "_rec", lambda: _rapid(kind, use_gpu, rec_only=True), use_gpu)
            except Exception:
                log.exception("Local OCR warm-up failed")
        threading.Thread(target=run, daemon=True).start()

    def _get(self, key, factory, use_gpu, on_status=None):
        sig = (bool(use_gpu), GPU_ID if use_gpu else 0)
        if self._gpu != sig:  # CPU / graphics card setting or which card changed: reload everything
            self._models.clear()
            self._gpu = sig
        if key not in self._models:
            if on_status:
                on_status("Loading local OCR…")
            t = time.time()
            self._models[key] = factory()
            log.info("Loaded %s in %.1fs", key, time.time() - t)
        return self._models[key]

    def _recognize(self, kind, bgr, use_gpu, on_status):
        """All detected lines with this recognizer, and how well it read them (0..1)."""
        eng = self._get(kind, lambda: _rapid(kind, use_gpu), use_gpu, on_status)
        t = time.time()
        lines = _lines(eng(bgr), min_score=0.0)
        good = _clean(lines)
        # coverage: share of the detected text the recognizer read confidently. A wrong language
        # (Korean read by the Japanese/Chinese model) leaves most lines low-score or junk.
        weight = sum(_area(l) for l in lines) or 1
        cover = sum(_area(l) * l["score"] for l in good) / weight
        log.info("RapidOCR %s: %d of %d lines, coverage %.2f, %.2fs", kind, len(good), len(lines),
                 cover, time.time() - t)
        return good, cover

    def read(self, img: Image.Image, settings, cancel, on_status=None):
        """Return [{text, type, box}] in img pixels (not yet snapped to bubbles / ordered)."""
        src = settings["source_lang"]
        use_gpu = bool(settings["local_gpu"])
        if src == "ko" and not pack_ready("ko"):
            raise RuntimeError("Local OCR: download the Korean model first (server menu → Local OCR models…)")
        bgr = np.ascontiguousarray(np.asarray(img.convert("RGB"))[:, :, ::-1])
        use_mocr = src in ("ja", "auto") and settings["local_manga_ocr"] and pack_ready("mocr")
        with self._lock:
            # 1. Recognizer: the chosen language first ('auto': the one that won last time). If it reads
            #    the page badly, the other one gets a try: a Korean page with 'Japanese' selected still works.
            first = "ko" if src == "ko" else ("multi" if src in ("ja", "zh", "en") else self._last_lang)
            kinds = [first]
            if pack_ready("ko"):
                kinds.append("multi" if first == "ko" else "ko")
            best = None
            for kind in kinds:
                if cancel.is_set():
                    raise Cancelled()
                lines, cover = self._recognize(kind, bgr, use_gpu, on_status)
                if best is None or cover > best[1] + 0.05:
                    best = (kind, cover, lines)
                if cover >= 0.7:
                    break  # read well: no need to try the other language
            kind, cover, lines = best
            self._last_lang = kind
            self.hint = ""
            if cover < 0.5 and not pack_ready("ko"):
                self.hint = "Korean page? Download the Korean model"
                log.warning("Local OCR read this page poorly (coverage %.2f). Korean page? "
                            "Download the Korean model in Local OCR models.", cover)
            cjk = kind == "multi" and src != "en"
            gray = np.asarray(img.convert("L"))
            blocks = _group_lines(lines, cjk_join=cjk and not _latin_page(lines), gray=gray)

            # 2. Japanese with manga-ocr: re-read every block with it
            if use_mocr and kind == "multi" and blocks and _japanese_page(lines):
                ocr = self._get("mocr", lambda: MangaOcr(use_gpu), use_gpu, on_status)
                t = time.time()
                for i, b in enumerate(blocks):
                    if cancel.is_set():
                        raise Cancelled()
                    if on_status and len(blocks) > 4:
                        on_status(f"Reading {i + 1}/{len(blocks)}…")
                    x1, y1, x2, y2 = b["box"]
                    pad = max(3, int(0.08 * min(x2 - x1, y2 - y1)))
                    crop = img.crop((max(0, x1 - pad), max(0, y1 - pad),
                                     min(img.width, x2 + pad), min(img.height, y2 + pad)))
                    text = ocr(crop)
                    if _TEXTY.search(text):
                        b["text"] = text
                log.info("manga-ocr: %d blocks in %.2fs", len(blocks), time.time() - t)
            return [dict(b, type="speech") for b in blocks]

    # -------------------------------------------------- visual novel text box
    def _vn_detect(self, kind, bgr, use_gpu, on_status):
        eng = self._get(kind + "_vn", lambda: _rapid(kind, use_gpu, vn=True), use_gpu, on_status)
        raw = _lines(eng(bgr), min_score=0.0)
        good = _vn_keep(raw)
        weight = sum(_area(l) for l in raw) or 1
        return raw, good, sum(_area(l) * l["score"] for l in good) / weight

    def _vn_reread(self, kind, bgr, row, use_gpu, on_status):
        """Read one row again as a whole line (no detector involved): (text, score) or ("", 0)."""
        eng = self._get(kind + "_rec", lambda: _rapid(kind, use_gpu, rec_only=True), use_gpu, on_status)
        H, W = bgr.shape[:2]
        m = max(4, int(0.15 * (row["y2"] - row["y1"])))
        crop = np.ascontiguousarray(bgr[max(0, row["y1"] - m):min(H, row["y2"] + m),
                                        max(0, row["x1"] - m):min(W, row["x2"] + m)])
        if crop.size == 0:
            return "", 0.0
        res = eng(crop, use_det=False, use_cls=False, use_rec=True)
        txts, scs = getattr(res, "txts", None) or (), getattr(res, "scores", None) or ()
        if not txts:
            return "", 0.0
        return (txts[0] or "").strip(), float(scs[0]) if scs else 0.0

    def read_vn(self, img: Image.Image, settings, cancel, on_status=None):
        """Read a visual novel dialogue box -> {"name", "text", "trace"}. One frame in, one string out."""
        src = settings["source_lang"]
        use_gpu = bool(settings["local_gpu"])
        if src == "ko" and not pack_ready("ko"):
            raise RuntimeError("Local OCR: download the Korean model first (server menu → Local OCR models…)")
        img = img.convert("RGB")
        bgr0 = np.ascontiguousarray(np.asarray(img)[:, :, ::-1])
        use_mocr = src in ("ja", "auto") and settings["local_manga_ocr"] and pack_ready("mocr")
        trace = {"scale": 1.0, "kind": "", "cover": 0.0, "rows": [], "name_cues": []}
        t_start = time.time()
        with self._lock:
            import cv2
            first = "ko" if src == "ko" else ("multi" if src in ("ja", "zh", "en") else self._last_lang)
            kinds = [first] + ([("multi" if first == "ko" else "ko")] if pack_ready("ko") else [])

            def detect_all(bgr):
                best = None
                for kind in kinds:
                    if cancel.is_set():
                        raise Cancelled()
                    raw, good, cover = self._vn_detect(kind, bgr, use_gpu, on_status)
                    if best is None or cover > best[1] + 0.05:
                        best = (kind, cover, good)
                    if cover >= 0.7:
                        break
                return best

            # 1. detect on a copy with a border (text touching the frame edge is otherwise missed)
            pad = max(16, int(0.06 * min(bgr0.shape[:2])))
            work = _pad_bgr(bgr0, pad)
            kind, cover, lines = detect_all(work)
            # 2. small text: enlarge so the detector and the recognizer see about 32 px letters
            hs = sorted(l["box"][3] - l["box"][1] for l in lines if l["score"] >= 0.5)
            if (not hs) or hs[len(hs) // 2] < 22:  # nothing found at 1:1 is retried once enlarged
                f = 2.0 if not hs else min(2.5, 32.0 / hs[len(hs) // 2])
                big = cv2.resize(bgr0, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
                work2 = _pad_bgr(big, int(pad * f))
                kind2, cover2, lines2 = detect_all(work2)
                if cover2 >= cover - 0.02 and len(lines2) >= len(lines):
                    work, kind, cover, lines, trace["scale"] = work2, kind2, cover2, lines2, round(f, 2)
            trace["kind"], trace["cover"] = kind, round(cover, 2)
            t_detect = time.time() - t_start
            self._last_lang = kind
            self.hint = "" if (cover >= 0.5 or pack_ready("ko")) else "Korean page? Download the Korean model"
            if not lines:
                return {"name": "", "text": "", "trace": trace}

            # 3. pieces -> rows; a row cut in several pieces is read again as one line
            rows = _vn_rows(lines)
            latin = _latin_page(lines)
            mocr = None
            if use_mocr and kind == "multi" and _japanese_page(lines):
                mocr = self._get("mocr", lambda: MangaOcr(use_gpu), use_gpu, on_status)
            for r in rows:
                if cancel.is_set():
                    raise Cancelled()
                segs = r["segs"]
                joined = ("" if (kind == "multi" and src != "en" and not latin) else " ").join(l["text"] for l in segs)
                r["text"], r["score"], r["reread"] = joined, min(l["score"] for l in segs), False
                if len(segs) > 1:
                    txt, sc = self._vn_reread(kind, work, r, use_gpu, on_status)
                    if txt and _TEXTY.search(txt) and sc >= 0.5:
                        r["text"], r["score"], r["reread"] = txt, sc, True
                if mocr is not None and r["score"] < VN_MOCR_BELOW:
                    H, W = work.shape[:2]
                    crop = Image.fromarray(np.ascontiguousarray(
                        work[max(0, r["y1"] - 4):min(H, r["y2"] + 4), max(0, r["x1"] - 4):min(W, r["x2"] + 4)][:, :, ::-1]))
                    t = mocr(crop)
                    if _TEXTY.search(t):
                        r["text"] = t
                r["ink"] = _row_ink(work, r)

            # 4. speaker name vs dialogue
            name, body = _split_name(rows)
            trace["name_cues"] = rows[0].get("cues", []) if name else []
            cjk_join = kind == "multi" and src != "en" and not latin
            text = ("" if cjk_join else " ").join(r["text"].strip() for r in body if r["text"].strip())
            trace["rows"] = [{"text": r["text"], "score": round(r["score"], 2), "reread": r["reread"],
                              "box": [r["x1"], r["y1"], r["x2"], r["y2"]]} for r in rows]
            log.info("VN OCR %s x%.1f cover %.2f: name=%r text=%r rows=%s", kind, trace["scale"], cover, name, text,
                     [(r["text"], round(r["score"], 2), "re" if r["reread"] else "") for r in rows])
            log.info("VN OCR timing: detect %.2fs, rows %.2fs, total %.2fs", t_detect,
                     time.time() - t_start - t_detect, time.time() - t_start)
            return {"name": name, "text": text, "trace": trace}


_KANA = re.compile(r"[\u3040-\u30ff]")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def _area(line):
    b = line["box"]
    return max(1, b[2] - b[0]) * max(1, b[3] - b[1])


def _clean(lines, min_score=0.6):
    """Drop what is not dialogue: low confidence, digit / symbol junk, tiny text (furigana, labels)
    and stray Latin letters on a CJK page (usually a misread)."""
    lines = [l for l in lines if l["score"] >= min_score and _TEXTY.search(l["text"])]
    if not lines:
        return []
    thick = sorted(min(l["box"][2] - l["box"][0], l["box"][3] - l["box"][1]) for l in lines)
    median = thick[len(thick) // 2]
    cjk_page = sum(len(_CJK.findall(l["text"])) for l in lines) > 0.5 * sum(len(l["text"]) for l in lines)
    out = []
    for l in lines:
        t = l["text"].replace(" ", "")
        letters = [c for c in t if c.isalpha()]
        if len(letters) < 0.5 * len(t):
            continue  # mostly digits / symbols: page numbers, junk
        if len(t) == 1 and l["score"] < 0.9:
            continue  # a lone, unsure character is usually a misread mark
        if min(l["box"][2] - l["box"][0], l["box"][3] - l["box"][1]) < 0.5 * median:
            continue  # much smaller than the dialogue: furigana, credits, scribbles
        if cjk_page and not _CJK.search(t) and l["score"] < 0.95:
            continue  # Latin junk on a Japanese / Korean / Chinese page
        out.append(l)
    return out


def _japanese_page(lines):
    text = "".join(l["text"] for l in lines)
    return len(_KANA.findall(text)) >= max(2, 0.1 * len(text))


def _latin_page(lines):
    text = "".join(l["text"] for l in lines if not l["text"].isspace())
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isascii() for c in letters) > 0.7 * len(letters)


ENGINE = LocalOcr()

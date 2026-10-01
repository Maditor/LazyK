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
        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
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
def _rapid(kind, use_gpu):
    """kind: 'multi' (built-in PP-OCRv6: ja / zh / en) | 'ko' (PP-OCRv5 Korean) | 'det' (detector only)."""
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
    if kind == "ko":
        from rapidocr import LangRec, ModelType, OCRVersion
        params.update({"Rec.model_path": path("korean_rec.onnx"), "Rec.lang_type": LangRec.KOREAN,
                       "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE})
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
            try:
                with self._lock:
                    use_gpu = bool(settings["local_gpu"])
                    kind = "ko" if settings["source_lang"] == "ko" and pack_ready("ko") else "multi"
                    self._get(kind, lambda: _rapid(kind, use_gpu), use_gpu)
            except Exception:
                log.exception("Local OCR warm-up failed")
        threading.Thread(target=run, daemon=True).start()

    def _get(self, key, factory, use_gpu, on_status=None):
        if self._gpu != use_gpu:  # GPU setting changed: reload everything
            self._models.clear()
            self._gpu = use_gpu
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

"""Optional speech-bubble model (RT-DETR comic text & bubble detector, run with onnxruntime).

It finds three things on a manga / webtoon page:
  bubble       - a speech bubble (its box), joined bubbles come out as separate boxes
  text_bubble  - the lettering inside a bubble
  text_free    - lettering outside any bubble (narration, signs, side remarks)

The model (comic_bubbles.onnx + comic_bubbles.json, the HuggingFace model exported to ONNX) ships in
models/ next to LazyK.exe / main.py, or sits in the user's models folder. Without it, LazyK uses its own
image-based bubble finder (bubbles.py).
"""
import json
import logging
import os
import threading
import time

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

NAME = "comic_bubbles"
_lock = threading.Lock()
_cache = {}


def files():
    """The model shipped with LazyK (models/ next to LazyK.exe / main.py), else the one in the user's
    models folder."""
    from . import config, local_ocr
    shipped = os.path.join(config.app_dir(), "models")
    if os.path.isfile(os.path.join(shipped, NAME + ".onnx")) and os.path.isfile(os.path.join(shipped, NAME + ".json")):
        return os.path.join(shipped, NAME + ".onnx"), os.path.join(shipped, NAME + ".json")
    return local_ocr.path(NAME + ".onnx"), local_ocr.path(NAME + ".json")


def installed() -> bool:
    onnx, meta = files()
    return os.path.isfile(onnx) and os.path.isfile(meta)


class Detector:
    def __init__(self, onnx_path, meta, use_gpu=False):
        from . import local_ocr
        self.meta = meta
        self.sess = local_ocr._session(onnx_path, use_gpu)
        self.input = self.sess.get_inputs()[0].name
        self.labels = {int(k): v for k, v in meta["labels"].items()}

    def _prep(self, img: Image.Image):
        h, w = self.meta["input"]
        a = np.asarray(img.convert("RGB").resize((w, h), Image.BILINEAR), dtype=np.float32)
        a = a * float(self.meta.get("rescale", 1 / 255))
        if self.meta.get("normalize"):
            a = (a - np.asarray(self.meta["mean"], np.float32)) / np.asarray(self.meta["std"], np.float32)
        return np.ascontiguousarray(a.transpose(2, 0, 1)[None])

    def __call__(self, img: Image.Image, conf=0.3):
        """-> [{"label", "box": (x1, y1, x2, y2) in img pixels, "score"}], best first.
        A long page (webtoon strip, wide spread) is read in overlapping square-ish tiles: squeezed into
        the model's square input whole, its bubbles would be distorted and boxed loosely."""
        W, H = img.size
        long_, short = max(W, H), min(W, H)
        if long_ <= 1.45 * short:
            return self._run(img, conf)
        tile = int(1.2 * short)
        step = int(tile * 0.7)
        starts = list(range(0, long_ - tile, step)) + [long_ - tile]
        dets = []
        for t0 in starts:
            box = (0, t0, W, t0 + tile) if H > W else (t0, 0, t0 + tile, H)
            for d in self._run(img.crop(box), conf):
                x1, y1, x2, y2 = d["box"]
                x1, x2, y1, y2 = x1 + box[0], x2 + box[0], y1 + box[1], y2 + box[1]
                lo, hi = (y1, y2) if H > W else (x1, x2)
                # cut by an inner tile edge: the neighbouring tile has it whole
                d["cut"] = (lo <= t0 + 3 and t0 > 0) or (hi >= t0 + tile - 3 and t0 + tile < long_)
                d["box"] = (x1, y1, x2, y2)
                dets.append(d)
        dets.sort(key=lambda d: (d["cut"], -d["score"]))
        keep = []
        for d in dets:
            b = d["box"]
            area = max(1.0, (b[2] - b[0]) * (b[3] - b[1]))
            dup = False
            for k in keep:
                if k["label"] != d["label"]:
                    continue
                kb = k["box"]
                inter = max(0.0, min(b[2], kb[2]) - max(b[0], kb[0])) * max(0.0, min(b[3], kb[3]) - max(b[1], kb[1]))
                karea = max(1.0, (kb[2] - kb[0]) * (kb[3] - kb[1]))
                if inter / (area + karea - inter) > 0.45 or inter / min(area, karea) > 0.75:
                    dup = True
                    break
            if not dup:
                keep.append(d)
        for d in keep:
            d.pop("cut", None)
        keep.sort(key=lambda d: -d["score"])
        return keep

    def _run(self, img: Image.Image, conf):
        W, H = img.size
        logits, boxes = self.sess.run(None, {self.input: self._prep(img)})
        logits, boxes = logits[0].astype(np.float32), boxes[0].astype(np.float32)
        Q, C = logits.shape
        if self.meta.get("focal", True):
            prob = 1 / (1 + np.exp(-logits))
            flat = prob.ravel()
            top = np.argsort(-flat)[:Q]
            scores, labels, queries = flat[top], top % C, top // C
        else:  # softmax with a final "no object" class
            e = np.exp(logits - logits.max(axis=1, keepdims=True))
            p = (e / e.sum(axis=1, keepdims=True))[:, :-1]
            labels, scores, queries = p.argmax(axis=1), p.max(axis=1), np.arange(Q)
        out = []
        for s, lab, q in zip(scores, labels, queries):
            if s <= conf:
                continue
            cx, cy, bw, bh = boxes[q]
            x1, y1 = (cx - bw / 2) * W, (cy - bh / 2) * H
            x2, y2 = (cx + bw / 2) * W, (cy + bh / 2) * H
            out.append({"label": self.labels.get(int(lab), str(int(lab))), "score": float(s),
                        "box": (max(0.0, float(x1)), max(0.0, float(y1)), min(float(W), float(x2)),
                                min(float(H), float(y2)))})
        out.sort(key=lambda d: -d["score"])
        return out


def get(use_gpu=False):
    """The loaded detector, or None when the model is not installed (or cannot load)."""
    if not installed():
        return None
    onnx, meta_path = files()
    from . import local_ocr
    key = (onnx, os.path.getmtime(onnx), bool(use_gpu), local_ocr.GPU_ID if use_gpu else 0)
    with _lock:
        if key not in _cache:
            _cache.clear()
            try:
                t = time.time()
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                _cache[key] = Detector(onnx, meta, use_gpu)
                log.info("Bubble model loaded in %.1fs", time.time() - t)
            except Exception:
                log.exception("Bubble model could not be loaded: using the built-in bubble finder")
                _cache[key] = None
        return _cache[key]


def detect(img: Image.Image, use_gpu=False, conf=0.3):
    det = get(use_gpu)
    if det is None:
        return None
    t = time.time()
    crop = None
    try:  # empty screen margins around the page: cut off, so the page is not squeezed into the model's square
        from . import refine
        crop = refine.trim_borders(np.asarray(img.convert("L")))
    except Exception:
        log.exception("Border trim failed")
    with _lock:
        res = det(img.crop(crop) if crop else img, conf)
    if crop:
        ox, oy = crop[0], crop[1]
        for d in res:
            x1, y1, x2, y2 = d["box"]
            d["box"] = (x1 + ox, y1 + oy, x2 + ox, y2 + oy)
    log.info("Bubble model: %d bubble(s), %d text area(s) in %.2fs",
             sum(d["label"] == "bubble" for d in res), sum(d["label"] != "bubble" for d in res), time.time() - t)
    return res

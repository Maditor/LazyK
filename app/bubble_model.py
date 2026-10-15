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


REPO = "ogkalu/comic-text-and-bubble-detector"  # Apache-2.0
CONFIG = NAME + "_config.json"      # the model's config.json (labels) as downloaded
PREPROC = NAME + "_preproc.json"    # its preprocessor_config.json (input size, scaling)


def _dirs():
    from . import config, local_ocr
    return [os.path.join(config.app_dir(), "models"), local_ocr.models_dir()]


def _ready_in(d):
    if not os.path.isfile(os.path.join(d, NAME + ".onnx")):
        return False
    return os.path.isfile(os.path.join(d, NAME + ".json")) or (
        os.path.isfile(os.path.join(d, CONFIG)) and os.path.isfile(os.path.join(d, PREPROC)))


def folder():
    """Where the model is: shipped with LazyK (models/ next to LazyK.exe / main.py), else the user's
    models folder. None when it is in neither."""
    return next((d for d in _dirs() if _ready_in(d)), None)


def installed() -> bool:
    return folder() is not None


def load_meta(d):
    """Input size, scaling and labels: comic_bubbles.json (own export), else built from the model's
    own config.json + preprocessor_config.json (downloaded from HuggingFace)."""
    own = os.path.join(d, NAME + ".json")
    if os.path.isfile(own):
        with open(own, encoding="utf-8") as f:
            return json.load(f)
    with open(os.path.join(d, CONFIG), encoding="utf-8") as f:
        cfg = json.load(f)
    with open(os.path.join(d, PREPROC), encoding="utf-8") as f:
        pre = json.load(f)
    size = pre.get("size") or {}
    h = int(size.get("height") or size.get("shortest_edge") or 640)
    w = int(size.get("width") or size.get("shortest_edge") or 640)
    return {"repo": REPO, "input": [h, w],
            "rescale": float(pre.get("rescale_factor", 1 / 255)) if pre.get("do_rescale", True) else 1.0,
            "normalize": bool(pre.get("do_normalize", False)),
            "mean": [float(v) for v in (pre.get("image_mean") or [0, 0, 0])],
            "std": [float(v) for v in (pre.get("image_std") or [1, 1, 1])],
            "labels": {str(k): v for k, v in (cfg.get("id2label") or {}).items()},
            "focal": bool(cfg.get("use_focal_loss", True))}


class Detector:
    def __init__(self, onnx_path, meta, use_gpu=False):
        from . import local_ocr
        self.meta = meta
        self.sess = local_ocr._session(onnx_path, use_gpu)
        ins, outs = self.sess.get_inputs(), self.sess.get_outputs()
        self.input = next((i.name for i in ins if len(i.shape or []) == 4), ins[0].name)
        self.sizes_input = next((i.name for i in ins if i.name != self.input), None)  # RT-DETR style
        shp = next(i.shape for i in ins if i.name == self.input)
        if isinstance(shp[2], int) and isinstance(shp[3], int) and shp[2] > 0 and shp[3] > 0:
            meta = dict(meta, input=[shp[2], shp[3]])  # a fixed input size wins over the config
            self.meta = meta
        self.out_names = [o.name for o in outs]
        self.labels = {int(k): v for k, v in meta["labels"].items()}
        log.info("Bubble model I/O: in %s, out %s, input %s", [(i.name, i.shape) for i in ins],
                 [(o.name, o.shape) for o in outs], meta["input"])

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
        feed = {self.input: self._prep(img)}
        if self.sizes_input:  # the original RT-DETR export also takes the image size
            h, w = self.meta["input"]
            feed[self.sizes_input] = np.array([[w, h]], dtype=np.int64)
        res = dict(zip(self.out_names, self.sess.run(None, feed)))
        if "labels" in res and "scores" in res and "boxes" in res:  # already decoded: labels, xyxy, scores
            return self._decoded(res, W, H, conf)
        logits = res.get("logits")
        boxes = res.get("pred_boxes")
        if logits is None or boxes is None:  # unnamed: the one ending in 4 values is the boxes
            arrs = list(res.values())
            boxes = next(a for a in arrs if a.shape[-1] == 4)
            logits = next(a for a in arrs if a is not boxes)
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


def _decoded_impl(self, res, W, H, conf):
    labels, boxes, scores = res["labels"][0], res["boxes"][0].astype(np.float32), res["scores"][0]
    h, w = self.meta["input"]
    if boxes.size and boxes.max() <= 1.5:  # normalized
        sx, sy = W, H
    else:  # in model-input pixels
        sx, sy = W / float(w), H / float(h)
    out = []
    for lab, b, sc in zip(labels, boxes, scores):
        if sc <= conf:
            continue
        x1, y1, x2, y2 = b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy
        out.append({"label": self.labels.get(int(lab), str(int(lab))), "score": float(sc),
                    "box": (max(0.0, float(x1)), max(0.0, float(y1)), min(float(W), float(x2)), min(float(H), float(y2)))})
    out.sort(key=lambda d: -d["score"])
    return out


Detector._decoded = _decoded_impl


def get(use_gpu=False):
    """The loaded detector, or None when the model is not installed (or cannot load)."""
    if not installed():
        return None
    d = folder()
    onnx = os.path.join(d, NAME + ".onnx")
    from . import local_ocr
    key = (onnx, os.path.getmtime(onnx), bool(use_gpu), local_ocr.GPU_ID if use_gpu else 0)
    with _lock:
        if key not in _cache:
            _cache.clear()
            try:
                t = time.time()
                _cache[key] = Detector(onnx, load_meta(d), use_gpu)
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

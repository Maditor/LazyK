"""Make model boxes pixel-accurate using the image itself.

Vision models give rough boxes (often off by tens of pixels, sometimes with x/y swapped).
Here we:
  * trim_borders()  - cut the empty browser background around a manga page before OCR
  * choose_order()  - decide whether boxes are [x1,y1,x2,y2] or [y1,x1,y2,x2] by checking
                      which reading lands on text-like pixels
  * refine_box()    - snap a box to the real text strokes and find the enclosing bubble
"""
import logging

import numpy as np

log = logging.getLogger(__name__)

try:
    import cv2
except Exception:  # optional: without OpenCV we keep the model boxes
    cv2 = None


def trim_borders(gray: np.ndarray, tol: float = 4.0, margin: int = 6):
    """Bounding box (x1, y1, x2, y2) of the non-uniform content (the page), or None."""
    H, W = gray.shape
    g = gray.astype(np.int16)
    col_busy = np.abs(np.diff(g, axis=0)).mean(axis=0) > tol * 0.25
    row_busy = np.abs(np.diff(g, axis=1)).mean(axis=1) > tol * 0.25
    # Also treat columns whose color differs from the page edge color as content
    bg = np.median(np.concatenate([g[:, :3].ravel(), g[:, -3:].ravel()]))
    col_busy |= np.abs(g.mean(axis=0) - bg) > tol * 2
    xs = np.nonzero(col_busy)[0]
    ys = np.nonzero(row_busy)[0]
    if len(xs) < 20 or len(ys) < 20:
        return None
    x1, x2 = max(0, xs[0] - margin), min(W, xs[-1] + 1 + margin)
    y1, y2 = max(0, ys[0] - margin), min(H, ys[-1] + 1 + margin)
    if (x2 - x1) > 0.92 * W and (y2 - y1) > 0.92 * H:
        return None  # nothing worth trimming
    return int(x1), int(y1), int(x2), int(y2)


def text_score(gray: np.ndarray, box) -> float:
    """How much a box looks like lettering: mostly light paper with some dark strokes."""
    H, W = gray.shape
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(W, x2), min(H, y2)
    if x2 - x1 < 3 or y2 - y1 < 3:
        return 0.0
    reg = gray[y1:y2, x1:x2]
    bright = (reg > 190).mean()
    dark = (reg < 100).mean()
    if bright > 0.35 and 0.015 < dark < 0.5:
        return 1.0 + min(dark, 0.25)
    # Light text on dark captions
    if dark > 0.35 and 0.015 < bright < 0.5:
        return 0.8
    return 0.0


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def order_score(gray, boxes) -> float:
    """Sum over boxes of how well each one snaps onto real lettering."""
    total = 0.0
    for b in boxes:
        if not b:
            continue
        snapped = refine_box(gray, b)
        if snapped:
            # A box in the right order overlaps the lettering it snaps to
            total += _iou(b, snapped[0]) * (1.5 if snapped[1] else 1.0)
    return total


def choose_order(gray, candidates: dict) -> str:
    """candidates: {order: [box, ...]} -> the order whose boxes sit best on lettering."""
    scores = {o: order_score(gray, boxes) for o, boxes in candidates.items()}
    best = max(scores, key=scores.get)
    other = min(scores.values())
    if scores[best] < 0.3 or scores[best] < 1.5 * other:
        best = "yxyx"  # no clear evidence: trust the format the prompt asked for
    log.info("Box order scores %s -> %s", {k: round(v, 2) for k, v in scores.items()}, best)
    return best


def refine_box(gray: np.ndarray, box, _grow: float = 1.0):
    """Return (text_box, bubble_box_or_None, shape_or_None) in image pixels, or None to keep the model box.

    shape = {"poly": [x, y, ...] outline of the bubble's inside (slightly shrunk),
             "y0": first row, "rows": [[left, right] or [-1, -1] per row]} - used to clean the bubble
    and to fit the translation to the bubble's real width at every height.
    """
    if cv2 is None:
        return None
    H, W = gray.shape
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    bw, bh = max(1, x2 - x1), max(1, y2 - y1)
    # bubbles are often much bigger than their text (a short "?" in a big balloon)
    m = int(max(40 * _grow, _grow * max(bw, bh)))
    X1, Y1, X2, Y2 = max(0, x1 - m), max(0, y1 - m), min(W, x2 + m), min(H, y2 + m)
    reg = gray[Y1:Y2, X1:X2]
    rh, rw = reg.shape
    if rh < 8 or rw < 8:
        return None
    bx1, by1 = max(0, x1 - X1), max(0, y1 - Y1)
    bx2, by2 = min(rw, x2 - X1), min(rh, y2 - Y1)
    if bx2 - bx1 < 2 or by2 - by1 < 2:
        return None

    bright = (reg > 200).astype(np.uint8)
    # Thin (1 px, anti-aliased) bubble outlines on a small page leave tiny gaps where the inside
    # "leaks" into the background. Thickening the dark lines by 1 px seals them.
    bright = cv2.erode(bright, np.ones((3, 3), np.uint8), iterations=1)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(bright, connectivity=4)
    sub = labels[by1:by2, bx1:bx2]
    counts = np.bincount(sub.ravel(), minlength=n)
    counts[0] = 0  # label 0 = not bright
    lab = int(np.argmax(counts))
    if lab == 0 or counts[lab] < 0.15 * sub.size:
        log.debug("refine %s: no light paper under the box", box)
        return None  # not dark text on light paper (e.g. white-on-black caption)
    cx, cy, cw, ch, _area = stats[lab]
    touches = (cx == 0) + (cy == 0) + (cx + cw == rw) + (cy + ch == rh)
    comp = (labels == lab).astype(np.uint8)
    bubble = None
    interior = None
    log.debug("refine %s: paper component %s touches %d edge(s)", box, (cx, cy, cw, ch), touches)
    if touches >= 2:
        # Text on open page background: dark strokes near the model box only
        ex, ey = int(0.12 * bw) + 4, int(0.12 * bh) + 4
        area = np.zeros_like(comp)
        area[max(0, by1 - ey):by2 + ey, max(0, bx1 - ex):bx2 + ex] = 1
        text = (area == 1) & (reg < 120)
    else:
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        interior = np.zeros_like(comp)
        cv2.drawContours(interior, [max(contours, key=cv2.contourArea)], -1, 1, thickness=-1)
        text = (interior == 1) & (comp == 0) & (reg < 150)
        # Touching one edge of the search area: the bubble continues outside it -> look wider
        at_image_edge = (cx == 0 and X1 == 0) or (cy == 0 and Y1 == 0) or \
            (cx + cw == rw and X2 == W) or (cy + ch == rh and Y2 == H)
        if touches == 1 and not at_image_edge and _grow < 3.5:
            return refine_box(gray, box, _grow=2.2 if _grow < 2 else 4.0)
        bubble = (cx + X1, cy + Y1, cx + cw + X1, cy + ch + Y1) if touches == 0 else None

    # Drop specks: keep stroke components of a reasonable size
    t = text.astype(np.uint8)
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(t, connectivity=8)
    keep = np.zeros(n2, bool)
    keep[1:] = st2[1:, cv2.CC_STAT_AREA] >= 3
    ys, xs = np.nonzero(keep[lab2])
    if len(xs) < 15:
        return None
    tb = (int(xs.min()) + X1, int(ys.min()) + Y1, int(xs.max()) + 1 + X1, int(ys.max()) + 1 + Y1)
    tb_area = (tb[2] - tb[0]) * (tb[3] - tb[1])
    if bubble is not None:
        # The "bubble" must not pull in drawing: its dark pixels have to stay near the model's text box.
        # An open bubble that leaks into the panel background would otherwise swallow the art.
        mx = my = 0.5 * max(bw, bh) + 6  # columns of one bubble come as thin separate boxes
        near = (tb[0] >= x1 - mx and tb[1] >= y1 - my and tb[2] <= x2 + mx and tb[3] <= y2 + my)
        if not near or tb_area > 2.5 * max(bw, bh) ** 2:
            log.debug("refine %s: dark pixels %s spread too far from the box", box, tb)
            ex, ey = int(0.12 * bw) + 4, int(0.12 * bh) + 4
            area = np.zeros_like(comp)
            area[max(0, by1 - ey):by2 + ey, max(0, bx1 - ex):bx2 + ex] = 1
            t = ((area == 1) & (reg < 150)).astype(np.uint8)
            n2, lab2, st2, _ = cv2.connectedComponentsWithStats(t, connectivity=8)
            keep = np.zeros(n2, bool)
            keep[1:] = st2[1:, cv2.CC_STAT_AREA] >= 3
            ys, xs = np.nonzero(keep[lab2])
            if len(xs) < 15:
                return None
            tb = (int(xs.min()) + X1, int(ys.min()) + Y1, int(xs.max()) + 1 + X1, int(ys.max()) + 1 + Y1)
            tb_area = (tb[2] - tb[0]) * (tb[3] - tb[1])
            bubble = None
    if tb_area > 6 * bw * bh or tb_area < 0.05 * bw * bh:
        return None  # snapped to something unrelated
    shape = None
    if bubble:
        b_area = (bubble[2] - bubble[0]) * (bubble[3] - bubble[1])
        if b_area > 0.5 * W * H or b_area > 60 * tb_area:
            log.debug("refine %s: bubble %s far bigger than its text", box, bubble)
            bubble = None  # a panel / the page, not a bubble
        else:
            shape = _bubble_shape(interior, (cx, cy, cw, ch), (X1, Y1), tb, tb_area, int(comp.sum()),
                                  model_area=bw * bh)
            if shape is not None:
                shape["fill"] = int(np.median(reg[comp == 1]))  # paper tone of this bubble
            if shape is None:
                # White area leaks into the panel background (open outline): not a reliable bubble,
                # so never grow into it and never merge other text through it
                bubble = None
    return tb, bubble, shape


def _bubble_shape(interior, stats, offset, tb, tb_area, paper_px, model_area=None):
    """Outline + per-row free span of a bubble. None when it does not look like a speech bubble."""
    cx, cy, cw, ch = stats
    X1, Y1 = offset
    contours, _ = cv2.findContours(interior, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    cnt = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(cnt)
    hull = cv2.contourArea(cv2.convexHull(cnt))
    # Bubbles are compact and mostly convex, and their text fills a fair part of them.
    # A white panel background or a big white area of the drawing is not.
    if hull <= 0:
        return None
    solidity, fill, paper = area / hull, tb_area / max(1.0, area), paper_px / max(1.0, area)
    # A speech bubble is compact, mostly empty paper, and its text fills a fair part of it.
    # A very clean, round bubble may hold just a word or two ("!?", "頼む").
    clean = solidity > 0.9 and paper > 0.9 and fill >= 0.015
    if not clean and (solidity < 0.7 or fill < 0.06 or paper < 0.6):
        return None
    # Never mistake a panel's white background for a bubble: panels are big rectangles,
    # bubbles are rounded and not hugely bigger than the text the model saw.
    rectangular = area / max(1.0, cw * ch) > 0.93
    if model_area:
        ratio = (cw * ch) / max(1.0, model_area)
        if ratio > (6 if rectangular else 30):
            return None
    k = max(2, int(round(0.025 * min(cw, ch))))
    er = cv2.erode(interior, np.ones((3, 3), np.uint8), iterations=k)
    cs, _ = cv2.findContours(er, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c2 = max(cs, key=cv2.contourArea)
    c2 = cv2.approxPolyDP(c2, 1.2, True).reshape(-1, 2)
    poly = [int(v) for pt in c2 for v in (pt[0] + X1, pt[1] + Y1)]
    tcx = int((tb[0] + tb[2]) / 2) - X1
    rows = []
    for y in range(cy, cy + ch):
        row = er[y, :]
        xs = np.flatnonzero(row)
        if len(xs) == 0:
            rows.append([-1, -1])
            continue
        # split into runs, keep the run under the text center (or the widest one)
        breaks = np.flatnonzero(np.diff(xs) > 1)
        starts = np.concatenate(([xs[0]], xs[breaks + 1]))
        ends = np.concatenate((xs[breaks], [xs[-1]]))
        idx = next((i for i, (a, b) in enumerate(zip(starts, ends)) if a <= tcx <= b),
                   int(np.argmax(ends - starts)))
        rows.append([int(starts[idx]) + X1, int(ends[idx]) + 1 + X1])
    return {"poly": poly, "y0": int(cy + Y1), "rows": rows}


def refine_any(gray, inv, box):
    """refine_box for dark text on light paper, else for light text on a dark bubble."""
    r = refine_box(gray, box)
    if r is not None:
        return r
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    reg = gray[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
    if reg.size and (reg < 80).mean() > 0.45:  # mostly dark: try the negative image
        r = refine_box(inv, box)
        if r is not None and r[2] is not None:
            r[2]["invert"] = True
            r[2]["fill"] = 255 - r[2].get("fill", 255)
            return r
    return None


def item_colors(rgb: np.ndarray, box, min_ring: int = 3):
    """(background, ink) hex colors for the text at `box` (x1, y1, x2, y2) of an RGB image.

    The background is read from a ring just outside the tight text box - that is the bubble's paper, the
    caption box or the art behind free text, never the strokes themselves. Outliers (a bubble outline,
    a bit of art) are ignored: the median is refined with the pixels close to it. Ink is white on dark
    backgrounds and near-black on light ones. None when the box is unusable."""
    H, W = rgb.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(W, x2), min(H, y2)
    bw, bh = x2 - x1, y2 - y1
    if bw < 2 or bh < 2:
        return None
    gap = 1
    ring = max(min_ring, int(0.2 * min(bw, bh)))
    pad = gap + ring
    ox1, oy1, ox2, oy2 = max(0, x1 - pad), max(0, y1 - pad), min(W, x2 + pad), min(H, y2 + pad)
    outer = rgb[oy1:oy2, ox1:ox2]
    mask = np.ones(outer.shape[:2], bool)
    mask[max(0, y1 - gap - oy1):y2 + gap - oy1, max(0, x1 - gap - ox1):x2 + gap - ox1] = False
    px = outer[mask]
    if len(px) < 12:  # the box fills the image: fall back to the box itself
        px = rgb[y1:y2, x1:x2].reshape(-1, 3)
    px = px.astype(np.float32)
    med = np.median(px, axis=0)
    close = px[np.abs(px - med).sum(axis=1) <= 60]
    col = close.mean(axis=0) if len(close) >= 0.3 * len(px) else med
    r, g, b = (int(round(float(v))) for v in col)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return "#{:02x}{:02x}{:02x}".format(r, g, b), ("#ffffff" if lum < 140 else "#111111")


def attach_colors(img, items):
    """Give every item its own box colors (item["colors"]) so the overlay can match the page - manga,
    webtoon and visual novel alike. Items whose colors cannot be read keep none (user colors apply)."""
    rgb = np.asarray(img.convert("RGB"))
    for it in items:
        try:
            c = item_colors(rgb, it["box"]) if it.get("box") else None
        except Exception:
            log.exception("Could not read the background color")
            c = None
        if c:
            it["colors"] = c

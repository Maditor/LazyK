"""Find the speech bubbles of a comic page from the image itself, before the text is grouped.

Why: grouping text lines by distance alone joins the text of two neighbouring bubbles (or a bubble and
the free text next to it), and a bubble is only cleaned when the old one-box-at-a-time snap happened to
find a closed outline. Here every bubble on the page is found once, then:
  * text lines inside one bubble are always one item, lines in different bubbles never are;
  * each bubble's inside is known exactly, so the translation can follow its real shape.

What counts as a bubble: a light area enclosed by a line, holding text (OCR lines inside it), not much
bigger than its text, and with no drawing inside it apart from the text. Outlines that are not one
solid line - dashed bubbles, cloud-like thought bubbles, spiky "shout" bubbles - are closed first by
thickening the dark lines a little (a few sizes are tried, the smallest that closes the bubble wins).
"""
import logging

import numpy as np

log = logging.getLogger(__name__)

try:
    import cv2
except Exception:  # optional: without OpenCV there is no bubble detection (per-box refine still runs)
    cv2 = None

PAPER = 200          # light enough to be bubble paper
GRAY_PAPER = 160     # a light-gray (toned) bubble
SEALS = (1, 2, 3, 5)  # how much the dark lines are thickened to close an outline (px at the work scale)


def _lines_mask(shape, boxes, grow=0.25):
    m = np.zeros(shape, np.uint8)
    H, W = shape
    for x1, y1, x2, y2 in boxes:
        gx, gy = int((x2 - x1) * grow) + 2, int((y2 - y1) * grow) + 2
        m[max(0, y1 - gy):min(H, y2 + gy), max(0, x1 - gx):min(W, x2 + gx)] = 1
    return m


def _rows(er, X1, Y1, tcx):
    """Per-row free span (the run under the text center) of a filled bubble mask."""
    rows = []
    for y in range(er.shape[0]):
        xs = np.flatnonzero(er[y])
        if len(xs) == 0:
            rows.append([-1, -1])
            continue
        breaks = np.flatnonzero(np.diff(xs) > 1)
        starts = np.concatenate(([xs[0]], xs[breaks + 1]))
        ends = np.concatenate((xs[breaks], [xs[-1]]))
        idx = next((i for i, (a, b) in enumerate(zip(starts, ends)) if a <= tcx <= b),
                   int(np.argmax(ends - starts)))
        rows.append([int(starts[idx]) + X1, int(ends[idx]) + 1 + X1])
    return rows


def _straight_share(cnt, w, h):
    """Share of the outline made of long straight lines (panel borders, caption boxes)."""
    per = cv2.arcLength(cnt, True)
    if per <= 0:
        return 0.0
    ap = cv2.approxPolyDP(cnt, 1.5, True).reshape(-1, 2)
    long_len = 0.35 * max(w, h)
    total = 0.0
    for i in range(len(ap)):
        d = float(np.hypot(*(ap[i] - ap[i - 1])))
        if d >= long_len:
            total += d
    return total / per


def find(gray: np.ndarray, boxes, invert=False):
    """gray: page (H x W uint8). boxes: text lines [x1, y1, x2, y2] in page pixels.

    Returns (bubbles, owner): bubbles = [{"bbox", "poly", "y0", "rows", "fill", "seal", "lines": [i..]}],
    owner[i] = index of the bubble that holds line i, or -1. invert: look for dark bubbles (light text)."""
    owner = [-1] * len(boxes)
    if cv2 is None or not boxes:
        return [], owner
    g = 255 - gray if invert else gray
    H, W = g.shape
    boxes = [[int(round(v)) for v in b] for b in boxes]
    centers = [((b[0] + b[2]) // 2, (b[1] + b[3]) // 2) for b in boxes]
    near_text = _lines_mask(g.shape, boxes)
    min_area = max(400, int(0.0004 * H * W))
    bubbles = []
    taken = np.zeros(len(boxes), bool)
    # white bubbles first; then light-gray ones (screen-toned bubbles) for the lines still left
    passes = [(PAPER, s) for s in SEALS] + [(GRAY_PAPER, s) for s in SEALS[:3]]
    for paper_t, seal in passes:
        if taken.all():
            break
        paper = (g > paper_t).astype(np.uint8)
        sealed = cv2.erode(paper, np.ones((3, 3), np.uint8), iterations=seal)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(sealed, connectivity=4)
        # which component each (not yet placed) line sits on: its center, or most of its box
        cand = {}
        for i, (cx, cy) in enumerate(centers):
            if taken[i]:
                continue
            x1, y1, x2, y2 = boxes[i]
            sub = labels[max(0, y1):y2, max(0, x1):x2]
            # the text strokes break the paper: look at the paper pixels around the line
            ring = labels[max(0, y1 - 3):min(H, y2 + 3), max(0, x1 - 3):min(W, x2 + 3)]
            vals = np.concatenate([sub.ravel(), ring.ravel()])
            vals = vals[vals > 0]
            if len(vals) == 0:
                continue
            lab = int(np.bincount(vals).argmax())
            cand.setdefault(lab, []).append(i)
        for lab, idx in cand.items():
            x, y, w, h, area = stats[lab]
            if area < min_area or area > 0.3 * H * W:
                continue
            edges = (x == 0) + (y == 0) + (x + w >= W) + (y + h >= H)
            if edges >= 2:
                continue  # page / panel background
            comp = (labels[y:y + h, x:x + w] == lab).astype(np.uint8)
            cs, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cs:
                continue
            cnt = max(cs, key=cv2.contourArea)
            interior = np.zeros_like(comp)
            cv2.drawContours(interior, [cnt], -1, 1, thickness=-1)
            inside = interior.sum()
            hull = cv2.contourArea(cv2.convexHull(cnt))
            if inside < min_area or hull <= 0:
                continue
            solidity = float(cv2.contourArea(cnt)) / hull
            # lines whose centers are really inside this bubble
            mine = [i for i in idx if 0 <= centers[i][1] - y < h and 0 <= centers[i][0] - x < w
                    and interior[centers[i][1] - y, centers[i][0] - x]]
            if not mine:
                continue
            tb = [min(boxes[i][0] for i in mine), min(boxes[i][1] for i in mine),
                  max(boxes[i][2] for i in mine), max(boxes[i][3] for i in mine)]
            t_area = max(1, (tb[2] - tb[0]) * (tb[3] - tb[1]))
            tol = 0.04 * max(w, h) + 3
            if tb[0] < x - tol or tb[1] < y - tol or tb[2] > x + w + tol or tb[3] > y + h + tol:
                log.debug("bubble %s: its text runs out of it (an SFX over a panel)", (x, y, w, h))
                continue  # a bubble holds its text; lettering that crosses the area is drawn over the art
            rect_like = inside / max(1.0, w * h) > 0.93
            # bubbles are not hugely bigger than their text; a white panel background is
            if inside > (6 if rect_like else 30) * t_area or inside > 0.25 * H * W:
                log.debug("bubble %s: too big for its text", (x, y, w, h))
                continue
            if solidity < 0.75:
                log.debug("bubble %s seal %d: solidity %.2f", (x, y, w, h), seal, solidity)
                continue  # not a bubble shape (a leak into the drawing)
            fill_ratio = t_area / inside
            # (a ragged shape - cloud, spikes - must be well filled by its text: a face with one stray "line"
            # on it is a ragged light area too)
            if fill_ratio < (0.06 if solidity >= 0.85 else 0.1) and not (solidity > 0.9 and fill_ratio >= 0.015):
                log.debug("bubble %s: text fills only %.3f", (x, y, w, h), fill_ratio)
                continue  # a big light area with a speck of "text": a face, a sky, not a bubble
            # nothing drawn inside apart from the text: dark pixels away from the text lines are few
            dark = (interior == 1) & (comp == 0)
            stray = dark & (near_text[y:y + h, x:x + w] == 0)
            if stray.sum() > 0.02 * inside:
                log.debug("bubble %s seal %d: drawing inside (%.3f)", (x, y, w, h), seal, stray.sum() / inside)
                continue
            # paper must be most of it (thickened outline + text are the rest)
            # straight outline: a panel's background (or a caption box). Caption boxes are tight around
            # their text; a white panel area holding an SFX or a sign is not a bubble to wipe clean
            straight = _straight_share(cnt, w, h)
            # (a bubble cut by a panel border has one straight side, and is well filled by its text)
            if not (rect_like and fill_ratio >= 0.15) and (straight > 0.5 or (straight > 0.25 and fill_ratio < 0.4)):
                log.debug("bubble %s: straight-edged area (a panel), not a bubble (straight %.2f, fill %.2f)", (x, y, w, h), straight, fill_ratio)
                continue
            if comp.sum() < 0.5 * inside:
                log.debug("bubble %s: paper only %.2f", (x, y, w, h), comp.sum() / inside)
                continue
            # the shrunk inside (the thickening already moved it away from the outline by `seal` px)
            # painted area: the inside, one more pixel away from the outline (the thickening already keeps
            # `seal` px). Text touching the outline is still covered; the outline stays visible.
            er = cv2.erode(interior, np.ones((3, 3), np.uint8), iterations=1)
            ecs, _ = cv2.findContours(er, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not ecs:
                continue
            c2 = cv2.approxPolyDP(max(ecs, key=cv2.contourArea), 1.2, True).reshape(-1, 2)
            if len(c2) < 3:
                continue
            tcx = (tb[0] + tb[2]) // 2 - x
            fill = int(np.median(g[y:y + h, x:x + w][comp == 1]))
            if paper_t < PAPER and fill > PAPER + 15:
                continue  # found again in the gray pass: a white area, already judged above
            bubbles.append({
                "bbox": [int(x), int(y), int(x + w), int(y + h)],
                "poly": [int(v) for pt in c2 for v in (pt[0] + x, pt[1] + y)],
                "y0": int(y), "rows": _rows(er, x, y, tcx),
                "fill": (255 - fill) if invert else fill, "invert": invert,
                "seal": seal, "paper": paper_t, "straight": round(straight, 2), "solidity": round(solidity, 2), "lines": mine,
            })
            for i in mine:
                owner[i] = len(bubbles) - 1
                taken[i] = True
    log.info("Bubbles: %d found (%s)%s", len(bubbles),
             ", ".join(f"seal {b['seal']}" for b in bubbles), " [dark]" if invert else "")
    return bubbles, owner


def empty_bubbles(gray: np.ndarray, boxes, limit=8):
    """Bubbles that hold lettering but no detected text line (the detector missed the whole bubble).
    -> [[x1, y1, x2, y2], ...] regions to read again, closer up. Strict: clean, round, closed bubbles
    whose inside has several small dark marks (letters), never a panel or a face."""
    if cv2 is None:
        return []
    H, W = gray.shape
    centers = [((b[0] + b[2]) // 2, (b[1] + b[3]) // 2) for b in boxes]
    paper = (gray > PAPER).astype(np.uint8)
    sealed = cv2.erode(paper, np.ones((3, 3), np.uint8), iterations=1)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(sealed, connectivity=4)
    min_area = max(900, int(0.001 * H * W))
    used = {int(labels[cy, cx]) for cx, cy in centers if 0 <= cy < H and 0 <= cx < W}
    out = []
    for lab in range(1, n):
        x, y, w, h, area = stats[lab]
        if area < min_area or area > 0.06 * H * W or lab in used:
            continue
        if x == 0 or y == 0 or x + w >= W or y + h >= H:
            continue
        if w < 30 or h < 30 or max(w, h) > 6 * min(w, h):
            continue
        comp = (labels[y:y + h, x:x + w] == lab).astype(np.uint8)
        cs, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cs:
            continue
        cnt = max(cs, key=cv2.contourArea)
        hull = cv2.contourArea(cv2.convexHull(cnt))
        if hull <= 0 or cv2.contourArea(cnt) / hull < 0.9 or _straight_share(cnt, w, h) > 0.25:
            continue  # only clean, round bubbles: this guess must not grab a panel
        interior = np.zeros_like(comp)
        cv2.drawContours(interior, [cnt], -1, 1, thickness=-1)
        inside = int(interior.sum())
        if any(x <= cx < x + w and y <= cy < y + h and interior[cy - y, cx - x] for cx, cy in centers):
            continue  # has a line already
        marks = ((interior == 1) & (comp == 0)).astype(np.uint8)
        dark = int(marks.sum())
        if not 0.03 * inside <= dark <= 0.35 * inside:
            continue
        m, _l, st, _ = cv2.connectedComponentsWithStats(marks, connectivity=8)
        small = [s for s in st[1:] if s[cv2.CC_STAT_AREA] >= 4 and s[2] < 0.5 * w and s[3] < 0.5 * h]
        if len(small) < 3:
            continue  # letters are several separate small marks
        out.append([int(x), int(y), int(x + w), int(y + h)])
    out.sort(key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    return out[:limit]


# ---------------------------------------------------------------- with the bubble model (bubble_model.py)
def _ring_votes(labels, n, idx, boxes, x1, y1):
    votes = np.zeros(n, np.int64)
    for i in idx:
        bx1, by1, bx2, by2 = boxes[i]
        ring = labels[max(0, by1 - y1 - 3):max(0, by2 - y1 + 3), max(0, bx1 - x1 - 3):max(0, bx2 - x1 + 3)]
        if ring.size:
            votes += np.bincount(ring.ravel(), minlength=n)[:n]
    votes[0] = 0
    return votes


def _ellipse(w, h):
    m = np.zeros((h, w), np.uint8)
    cv2.ellipse(m, (w // 2, h // 2), (max(2, int(w * 0.46)), max(2, int(h * 0.46))), 0, 0, 360, 1, -1)
    return m


def _edge_interior(crop, lines_in, boxes, x1, y1, split=None):
    """The region enclosed by strong edges around the text (the bubble's outline), whatever its fill:
    gradients and soft tones have no strong edge inside. None when it is not a believable bubble."""
    h, w = crop.shape
    blur = cv2.GaussianBlur(crop, (3, 3), 0)
    edges = cv2.Canny(blur, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    free = (edges == 0).astype(np.uint8)
    for bx1, by1, bx2, by2 in [boxes[i] for i in lines_in]:  # the letters' own edges are not walls
        free[max(0, by1 - y1):max(0, by2 - y1), max(0, bx1 - x1):max(0, bx2 - x1)] = 1
    if split is not None:
        free &= split
    free[0, :] = free[-1, :] = 0
    free[:, 0] = free[:, -1] = 0
    n, labels, _stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)
    if n <= 1:
        return None
    votes = _ring_votes(labels, n, lines_in, boxes, x1, y1)
    if votes.max() <= 0:
        return None
    comp = (labels == int(votes.argmax())).astype(np.uint8)
    cs, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    out = np.zeros_like(comp)
    cv2.drawContours(out, [max(cs, key=cv2.contourArea)], -1, 1, thickness=-1)
    share = out.sum() / float(w * h)
    # a bubble touches its box only here and there; an area that runs along the box edge has leaked
    # out into the picture (a bubble without a closed outline)
    rim = np.concatenate([out[1, 1:-1], out[-2, 1:-1], out[1:-1, 1], out[1:-1, -2]])
    return out if 0.35 <= share <= 0.97 and rim.mean() < 0.35 else None


ELLIPSE_PAD = 0.05  # webtoon ellipse: this share of the box width / height left free on each side


def _shape_in_box(gray, box, lines_in, boxes, foreign=(), text_areas=(), rgb=None, ellipse=False):
    """Exact inside of the bubble the model boxed: the light (or, for a dark bubble, dark) area around its
    text, cut at the model's box (so an open outline or a joined neighbour cannot leak in).
    foreign: lines of OTHER bubbles reaching into this box - the area must not hold them (two joined
    bubbles are split at their narrow neck). When no clean area is found: an ellipse inside the box."""
    H, W = gray.shape
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(W, x2), min(H, y2)
    w, h = x2 - x1, y2 - y1
    if w < 8 or h < 8:
        return None
    crop = gray[y1:y2, x1:x2]
    invert = float(np.median(crop)) < 100  # a black bubble with white letters
    g = 255 - crop if invert else crop
    level = float(np.percentile(g, 75))
    paper_t = PAPER if level > 215 else max(120.0, level - 30)  # white, or a gray toned bubble
    paper = (g > paper_t).astype(np.uint8)
    paper[0, :] = paper[-1, :] = 0  # the box edge closes the bubble
    paper[:, 0] = paper[:, -1] = 0
    k3 = np.ones((3, 3), np.uint8)
    if foreign:  # a joined neighbour's text reaches in: split the paper half-way between the two texts
        mine_m = np.ones((h, w), np.uint8)
        other_m = np.ones((h, w), np.uint8)
        for idx, m in ((lines_in, mine_m), (foreign, other_m)):
            for i in idx:
                bx1, by1, bx2, by2 = boxes[i]
                m[max(0, by1 - y1):max(0, by2 - y1), max(0, bx1 - x1):max(0, bx2 - x1)] = 0
        d_mine = cv2.distanceTransform(mine_m, cv2.DIST_L2, 3)
        d_other = cv2.distanceTransform(other_m, cv2.DIST_L2, 3)
        split = (d_mine + 4 < d_other).astype(np.uint8)  # a small gap between the two halves
        paper &= split
    else:
        split = None
    if ellipse:
        # webtoon: bubbles are plain ovals - an ellipse a little inside the model's box is the cleanest
        # paint (no tracing, so gradients, soft tones and missing outlines do not matter)
        interior = np.zeros((h, w), np.uint8)
        px, py = max(3, int(w * ELLIPSE_PAD)), max(3, int(h * ELLIPSE_PAD))
        cv2.ellipse(interior, (w // 2, h // 2), (max(2, w // 2 - px), max(2, h // 2 - py)), 0, 0, 360, 1, -1)
        if split is not None:
            interior &= split
        fill = int(np.median(g[interior == 1])) if interior.any() else 255
    else:
        interior = None
        for seal in (1, 2, 4, 6):  # more erosion cuts the neck between joined bubbles
            sealed = cv2.erode(paper, k3, iterations=seal)
            n, labels, stats, _ = cv2.connectedComponentsWithStats(sealed, connectivity=4)
            if n <= 1:
                break
            votes = _ring_votes(labels, n, lines_in, boxes, x1, y1)
            if votes.max() <= 0:
                break
            lab = int(votes.argmax())
            if foreign and _ring_votes(labels, n, foreign, boxes, x1, y1)[lab] > 0:
                continue  # still joined to the neighbour: cut deeper
            comp = cv2.dilate((labels == lab).astype(np.uint8), k3, iterations=seal - 1) & paper if seal > 1 \
                else (labels == lab).astype(np.uint8)
            cs, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cs:
                break
            interior = np.zeros_like(comp)
            cv2.drawContours(interior, [max(cs, key=cv2.contourArea)], -1, 1, thickness=-1)
            if interior.sum() < 0.3 * w * h:
                interior = None  # screen-toned / textured bubble: no clean paper to follow
            else:
                fill = int(np.median(g[comp == 1]))
            break
        # Gradient / colored bubbles (webtoon): the paper is not one tone, so a brightness cut keeps only
        # part of the bubble. The outline is still a strong edge while a gradient is not: the area inside
        # the edges around the text is the bubble.
        if interior is None or interior.sum() < 0.6 * w * h:
            alt = _edge_interior(crop, lines_in, boxes, x1, y1, split)
            if alt is not None and (interior is None or alt.sum() > interior.sum()):
                interior = alt
                fill = int(np.median(g[cv2.erode(alt, k3, iterations=2) == 1])) if alt.sum() > 50 else 255
        if interior is None:  # an ellipse inside the model's box
            interior = _ellipse(w, h)
            fill = int(np.median(g[interior == 1]))
        # the lettering is always inside: where it touches the outline (or the paper around it is cut off)
        # the found area misses part of it, and the translation would dodge that part of the bubble. The
        # missing part is put back - but only as far as the bubble's own (convex) outline reaches, so
        # nothing is painted outside the bubble.
        cs, _ = cv2.findContours(interior, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cs:
            hull = np.zeros_like(interior)
            cv2.drawContours(hull, [cv2.convexHull(max(cs, key=cv2.contourArea))], -1, 1, thickness=-1)
            text = np.zeros_like(interior)
            for bx1, by1, bx2, by2 in [boxes[i] for i in lines_in] + [list(map(int, t)) for t in text_areas]:
                text[max(0, by1 - y1):max(0, by2 - y1), max(0, bx1 - x1):max(0, bx2 - x1)] = 1
            interior |= text & hull
            cs, _ = cv2.findContours(interior, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            interior = np.zeros_like(interior)
            cv2.drawContours(interior, [max(cs, key=cv2.contourArea)], -1, 1, thickness=-1)
    er = cv2.erode(interior, k3, iterations=1)
    ecs, _ = cv2.findContours(er, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not ecs:
        return None
    c2 = cv2.approxPolyDP(max(ecs, key=cv2.contourArea), 1.2, True).reshape(-1, 2)
    if len(c2) < 3:
        return None
    if lines_in:
        tcx = (min(boxes[i][0] for i in lines_in) + max(boxes[i][2] for i in lines_in)) // 2 - x1
    else:
        tcx = w // 2
    tcx = min(max(0, tcx), w - 1)
    color = None
    if rgb is not None:  # the bubble's own color (pink, cream, a gradient's middle), not just its gray
        inner = cv2.erode(interior, k3, iterations=2) == 1
        light = inner & ((g >= np.percentile(g[inner], 30)) if inner.any() else inner)  # leave the letters out
        if light.sum() > 30:
            c = np.median(rgb[y1:y2, x1:x2][light], axis=0)
            color = "#" + "".join(f"{int(v):02x}" for v in c)
    ys, xs = np.nonzero(er)
    return {"bbox": [x1 + int(xs.min()), y1 + int(ys.min()), x1 + int(xs.max()) + 1, y1 + int(ys.max()) + 1],
            "poly": [int(v) for pt in c2 for v in (pt[0] + x1, pt[1] + y1)],
            "y0": y1, "rows": _rows(er, x1, y1, tcx), "fill": (255 - fill) if invert else fill,
            "invert": invert, "seal": 0, "solidity": 1.0, "straight": 0.0, "paper": int(paper_t), "color": color}


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _hits(b, d, m=0):
    return b[0] < d[2] + m and b[2] > d[0] - m and b[1] < d[3] + m and b[3] > d[1] - m


def from_model(gray, boxes, dets, rgb=None, ellipse=False):
    """Like find(), with the bubble model's boxes instead of guessing from the image.
    Returns (groups, owner, empty): owner[i] = group of line i (-1: none); a group is a bubble (dict) or
    a free-text area ({"free": True, "bbox"}: lettering on the art, drawn without a bubble);
    empty = model bubbles holding no detected line (to read again, closer up)."""
    owner = [-1] * len(boxes)
    if cv2 is None:
        return [], owner, []
    boxes = [[int(round(v)) for v in b] for b in boxes]
    centers = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]
    found, empty = [], []

    def inside(c, b, m=0.0):
        return b[0] - m <= c[0] <= b[2] + m and b[1] - m <= c[1] <= b[3] + m

    bub = []  # the same bubble boxed twice (one box inside the other): keep the surer one
    for d in sorted((d for d in dets if d["label"] == "bubble"), key=lambda d: -d["score"]):
        b, a = d["box"], _area(d["box"])
        if not any(_inter(b, k["box"]) > 0.7 * min(a, _area(k["box"])) for k in bub):
            bub.append(d)
    bub.sort(key=lambda d: _area(d["box"]))
    # lettering the model calls free text (beside a bubble, even inside its box) does not go to the bubble,
    # unless the model also sees bubble text there
    tb = [d["box"] for d in dets if d["label"] == "text_bubble"]
    tf = [d["box"] for d in dets if d["label"] == "text_free"]
    reserved = {i for i, c in enumerate(centers)
                if any(inside(c, b) for b in tf) and not any(inside(c, b) for b in tb)}
    claim, taken = [], set(reserved)  # (bubble det, its lines); lines already in a bubble
    for d in bub:  # small bubbles first: a line belongs to the smallest bubble around it
        mine = [i for i, c in enumerate(centers) if i not in taken and inside(c, d["box"], 2)]
        if not mine:
            empty.append([int(round(v)) for v in d["box"]])
            continue
        taken.update(mine)
        claim.append((d, mine))
    for d, mine in claim:
        foreign = [i for i in taken if i not in mine and i not in reserved and _hits(boxes[i], d["box"])]
        db = d["box"]
        # the model's text areas inside this bubble: all of its lettering, also words the OCR missed
        cover = [[int(round(max(t[0], db[0]))), int(round(max(t[1], db[1]))),
                  int(round(min(t[2], db[2]))), int(round(min(t[3], db[3])))] for t in tb
                 if inside(((t[0] + t[2]) / 2, (t[1] + t[3]) / 2), db, 2)]
        shape = _shape_in_box(gray, d["box"], mine, boxes, foreign, cover, rgb, ellipse)
        if shape is None:  # tiny box: drawn as free text inside the bubble
            shape = {"free": True, "bbox": [int(round(v)) for v in d["box"]]}
        else:  # lines in the box but outside the bubble's outline (a remark beside it, a clock face...)
            poly = np.asarray(shape["poly"], np.int32).reshape(-1, 2)
            keep = []
            for i in mine:
                b = boxes[i]
                tol = 0.3 * min(b[2] - b[0], b[3] - b[1]) + 4
                if cv2.pointPolygonTest(poly, centers[i], True) >= -tol:
                    keep.append(i)
            if keep:
                taken.difference_update(set(mine) - set(keep))
                mine[:] = keep
        shape["cover"] = cover
        found.append(shape)
        for i in mine:
            owner[i] = len(found) - 1
    for d in dets:  # lettering outside bubbles: one group per free-text area
        if d["label"] != "text_free":
            continue
        mine = [i for i, c in enumerate(centers)
                if owner[i] < 0 and (i not in taken or i in reserved) and inside(c, d["box"], 2)]
        if mine:
            found.append({"free": True, "bbox": [int(round(v)) for v in d["box"]],
                          "cover": [[int(round(v)) for v in d["box"]]]})
            for i in mine:
                owner[i] = len(found) - 1
    log.info("Bubble model: %d bubble(s) with text, %d empty, %d free-text area(s)",
             sum(1 for f in found if not f.get("free")), len(empty), sum(1 for f in found if f.get("free")))
    return found, owner, empty

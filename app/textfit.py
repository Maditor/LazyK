"""Fit text into a bubble: bread-shaped lines (narrow top/bottom, wide middle), no orphans.

Rules for single-word lines ("orphans"), counting space-separated words:
  * 4+ words: no line may hold a single word (relaxed only if nothing else fits at the minimum size)
  * 3 words : at most 2 lines (2 + 1 is fine, 1 + 1 + 1 is not)
  * 1-2 words: anything goes
"""
import math

BREAD_K = 0.8          # 0 = rectangle; 0.8 makes 3-line blocks roughly 80% / 100% / 80% wide
LINE_H = 1.16          # line pitch as a multiple of the font size (tighter than the font default)
EXTRA_LINE_COST = 0.06  # how much an extra line must improve the shape to be chosen


def _split_long_words(words, width, measure):
    """A word wider than the box is broken by characters."""
    out = []
    for w in words:
        while measure(w) > width and len(w) > 1:
            cut = len(w) - 1
            while cut > 1 and measure(w[:cut]) > width:
                cut -= 1
            out.append(w[:cut])
            w = w[cut:]
        out.append(w)
    return out


def bread_profile(n: int):
    """Relative target width of each line: an ellipse-like curve, widest in the middle."""
    if n <= 2:
        return [1.0] * n
    ts = [((i + 0.5) / n) * 2 - 1 for i in range(n)]
    return [math.sqrt(1 - BREAD_K * t * t) for t in ts]


def _partition(words, ww, space, n, width, strict):
    """Split words into exactly n lines, closest to the bread profile. None if impossible.

    width: one number (same limit for every line) or a list of n per-line limits (a bubble's
    width at each line); with a list, lines are filled in proportion to their room.
    """
    limits = list(width) if isinstance(width, (list, tuple)) else [width] * n
    N = len(words)
    if n > N:
        return None
    if strict and N == 3 and n == 3:
        return None
    pre = [0.0]
    for w in ww:
        pre.append(pre[-1] + w)

    def line_w(i, j):
        return pre[j] - pre[i] + space * (j - i - 1)

    if isinstance(width, (list, tuple)):
        prof = limits
    else:
        prof = bread_profile(n)
    scale = line_w(0, N) / sum(prof)
    targets = [min(scale * p, lim) for p, lim in zip(prof, limits)]
    INF = float("inf")
    dp = [[INF] * (N + 1) for _ in range(n + 1)]
    back = [[-1] * (N + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for j in range(1, n + 1):
        remaining = n - j
        for i in range(j, N - remaining + 1):
            for k in range(i - 1, j - 2, -1):
                w = line_w(k, i)
                if w > limits[j - 1] + 0.5:
                    break  # adding more words only makes the line wider
                if dp[j - 1][k] == INF:
                    continue
                if strict and N >= 4 and i - k == 1:
                    continue
                c = dp[j - 1][k] + ((w - targets[j - 1]) / max(1.0, limits[j - 1])) ** 2
                if c < dp[j][i]:
                    dp[j][i], back[j][i] = c, k
    if dp[n][N] == INF:
        return None
    lines, i = [], N
    for j in range(n, 0, -1):
        k = back[j][i]
        lines.append(" ".join(words[k:i]))
        i = k
    return lines[::-1], dp[n][N]


def break_lines(words, width, measure, max_lines, strict=True):
    """Lines that fit the width, shaped like bread.

    Starts from the fewest possible lines, then also tries up to 2 extra lines (if the height
    allows) because one more line often gives a much rounder shape at the same font size.
    """
    if not words:
        return [""]
    ww = [measure(w) for w in words]
    space = measure(" ")
    total = sum(ww) + space * (len(words) - 1)
    lo = max(1, math.ceil(total / max(1.0, width)))
    best, best_cost, first = None, None, None
    for n in range(lo, min(max_lines, len(words)) + 1):
        res = _partition(words, ww, space, n, width, strict)
        if not res or not all(measure(l) <= width + 1 for l in res[0]):
            continue
        if first is None:
            first = n
        cost = res[1] + EXTRA_LINE_COST * (n - first)
        if best_cost is None or cost < best_cost:
            best, best_cost = res[0], cost
        if n >= first + 2:
            break
    return best


def fit(text: str, width: float, height: float, min_size: int, max_size: int, metrics):
    """metrics(size) -> (measure_fn, line_height). Returns (size, lines, block_height, fits)."""
    for size in range(max_size, min_size - 1, -1):
        measure, lh = metrics(size)
        max_lines = int(height // lh)
        if max_lines < 1:
            continue
        words = _split_long_words(text.split(), width, measure)
        lines = break_lines(words, width, measure, max_lines)
        if lines:
            return size, lines, lh * len(lines), True
    # Nothing fits the height: smallest size, as many lines as needed (caller grows the box)
    measure, lh = metrics(min_size)
    words = _split_long_words(text.split(), width, measure)
    lines = (break_lines(words, width, measure, len(words))
             or break_lines(words, width, measure, len(words), strict=False)
             or words or [""])
    return min_size, lines, lh * len(lines), False


def _intersects(a, b, gap=0.0):
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


def _shrink_away(r, obstacle, core, gap):
    """Cut rect r so it no longer touches obstacle, never cutting into core. None if impossible."""
    if not _intersects(r, obstacle, gap):
        return r
    options = []
    if obstacle[0] - gap >= core[2]:
        options.append((r[0], r[1], obstacle[0] - gap, r[3]))
    if obstacle[2] + gap <= core[0]:
        options.append((obstacle[2] + gap, r[1], r[2], r[3]))
    if obstacle[1] - gap >= core[3]:
        options.append((r[0], r[1], r[2], obstacle[1] - gap))
    if obstacle[3] + gap <= core[1]:
        options.append((r[0], obstacle[3] + gap, r[2], r[3]))
    if not options:
        return None
    return max(options, key=lambda q: (q[2] - q[0]) * (q[3] - q[1]))


def _clip(r, W, H):
    return (max(0, r[0]), max(0, r[1]), min(W, r[2]), min(H, r[3]))


def tight(metrics):
    """Wrap metrics(size) so lines use LINE_H spacing instead of the font's loose default."""
    return lambda size: (metrics(size)[0], max(1, round(size * LINE_H)))


def fit_shape(text, shape, fmin, fmax, pad, metrics, strict=True, tall=False):
    """Fit text inside a bubble outline, each line as wide as the bubble is at that height.

    Returns (size, [(line, cx, cy), ...]) or None.
    """
    rows, y0 = shape["rows"], shape["y0"]
    widths = [max(0, r - l) for l, r in rows]
    valid = [i for i, w in enumerate(widths) if w > 0]
    if not valid or not text.split():
        return None
    top, bot = valid[0], valid[-1] + 1
    shape_ratio = (bot - top) / max(1.0, float(max(widths)))
    tot = float(sum(widths))
    center = sum(i * w for i, w in enumerate(widths)) / tot  # width-weighted middle of the bubble
    for size in range(fmax, fmin - 1, -1):
        measure, lh = metrics(size)
        max_lines = int((bot - top - 2 * pad) // lh)
        if max_lines < 1:
            continue
        words = _split_long_words(text.split(), max(widths) - 2 * pad, measure)
        ww = [measure(w) for w in words]
        space = measure(" ")
        best, best_cost, first = None, None, None
        for n in range(1, min(max_lines, len(words)) + 1):
            btop = center - n * lh / 2
            btop = max(top + pad, min(btop, bot - pad - n * lh))
            limits, centers = [], []
            for k in range(n):
                a, b = int(btop + k * lh), int(btop + (k + 1) * lh)
                band = rows[max(0, a):min(len(rows), b)]
                if not band or any(r[1] <= r[0] for r in band):
                    break
                left = max(r[0] for r in band) + pad
                right = min(r[1] for r in band) - pad
                if right - left < 4:
                    break
                limits.append(right - left)
                centers.append(((left + right) / 2, y0 + btop + (k + 0.5) * lh))
            if len(limits) < n:
                continue
            res = _partition(words, ww, space, n, limits, strict)
            if not res or any(measure(l) > lim + 1 for l, lim in zip(res[0], limits)):
                continue
            if first is None:
                first = n
            if tall:
                # tall bubbles (manga, drawn for vertical Japanese): a block shaped like the bubble -
                # more, shorter lines filling it top to bottom
                bw = max(measure(l) for l in res[0]) or 1.0
                cost = 0.3 * res[1] + abs(math.log(max(1e-3, n * lh / bw) / max(1e-3, shape_ratio)))
            else:
                cost = res[1] + EXTRA_LINE_COST * (n - first)
            if best_cost is None or cost < best_cost:
                best, best_cost = [(l, cx, cy) for l, (cx, cy) in zip(res[0], centers)], cost
            if n >= first + (8 if tall else 2):
                break
        if best:
            return size, best
    return None


def bubble_colors(shape, settings):
    """White bubbles use the user's colors; a gray (toned) or black bubble keeps its tone, darkened as
    needed, with white text."""
    level = int(shape.get("fill", 255))
    if level >= 235 and not shape.get("invert"):
        return settings["overlay_bg"], settings["overlay_fg"]
    color = shape.get("color")
    if color and not shape.get("invert"):
        lum = _lum(color)
        if lum and max(lum[1]) - min(lum[1]) >= 0.12:  # a colored bubble (webtoon): keep its color
            return color, "#111111"
    fill = "#{0:02x}{0:02x}{0:02x}".format(max(0, min(255, level)))
    return fill, "#ffffff"


def _lum(color):
    try:
        c = color.lstrip("#")
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        rgb = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except Exception:
        return None
    lin = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2], rgb


READABLE = 7.5  # contrast ratio (WCAG) the translation keeps against its box
WHITE_PAPER = 0.75  # luminance from which a box counts as white paper (about #e1e1e1)


def readable(fill, ink):
    """Colors taken from the page: white paper gets dark text; a gray (or dark) box gets white text,
    the box darkened until the text stands out clearly; a colored box keeps its color, pushed lighter
    or darker for its text."""
    f, i = _lum(fill), _lum(ink)
    if f is None or i is None:
        return fill, ink
    (lf, rgb), (li, _) = f, i
    gray = max(rgb) - min(rgb) < 0.12
    if lf >= WHITE_PAPER:
        dark_ink = True
    elif gray:
        dark_ink = False
    else:
        if (max(lf, li) + 0.05) / (min(lf, li) + 0.05) >= READABLE:
            return fill, ink
        dark_ink = lf >= 0.2
    ink = "#111111" if dark_ink else "#ffffff"
    li = _lum(ink)[0]
    new = fill
    for k in range(0, 11):
        t = k / 10
        c = [v + (1 - v) * t for v in rgb] if dark_ink else [v * (1 - t) for v in rgb]
        new = "#" + "".join(f"{int(round(v * 255)):02x}" for v in c)
        lf = _lum(new)[0]
        if (max(lf, li) + 0.05) / (min(lf, li) + 0.05) >= READABLE:
            return new, ink
    return new, ink


def _place_lines(lines, rect, lh):
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    top = cy - lh * len(lines) / 2
    return [(l, cx, top + (k + 0.5) * lh) for k, l in enumerate(lines)]


def layout_items(items, region_w, region_h, settings, scale, metrics):
    """Decide how every translation is drawn, without covering neighbours.

    Bubbles with a detected outline: the inside of the bubble is painted clean ("poly") and the text
    follows the bubble's width line by line. Everything else: a rounded box ("rect") that covers the
    original text, may grow into free room, and is trimmed away from every other item.
    Returns list of {kind, poly|rect, size, lines:[(text, cx, cy)]}.
    """
    metrics = tight(metrics)
    pad = settings["box_padding"] * scale
    # font_min is the user's reading size: text never gets smaller than it, only bigger in roomy bubbles
    fmin = max(6, round(settings["font_min"] * scale))
    # roomy bubbles: up to 1.6x; "Auto text size" off = always the minimum size (steady, and faster to lay out)
    fmax = max(fmin, round(settings["font_min"] * 1.6 * scale)) if settings["auto_text_size"] else fmin
    floor = fmin
    inner = 3 * scale
    gap = 2 * scale
    W, H = region_w, region_h
    text_pad = max(2.0, 2 * scale)

    out = []
    blocked = []   # areas owned by cleaned bubbles
    rest = []
    for it in items:
        text = (it.get("translation") or "").strip()
        if not text or not it.get("box"):
            continue
        shape = it.get("shape")
        placed = None
        if shape and it.get("bubble"):
            bx = it["bubble"]
            tall = settings["layout"] == "manga" and (bx[3] - bx[1]) > 1.25 * (bx[2] - bx[0])
            placed = (fit_shape(text, shape, fmin, fmax, text_pad, metrics, tall=tall)
                      # tight: use the bubble right up to its outline before giving up on the shape
                      or fit_shape(text, shape, fmin, fmin, 0.5, metrics, strict=False))
        if placed:
            size, lines = placed
            if it.get("colors") and settings["vn_game_colors"]:  # auto color: the bubble's own paper
                fill, ink = it["colors"]
            else:
                fill, ink = bubble_colors(shape, settings)
            out.append({"kind": "poly", "poly": shape["poly"], "rect": tuple(it["bubble"]),
                        "size": size, "lines": lines, "fill": fill, "ink": ink})
            blocked.append(tuple(it["bubble"]))
        else:
            if it.get("colors") and settings["vn_game_colors"]:  # auto color: the box / bubble's own color (all layouts)
                colors = tuple(it["colors"])
            else:
                colors = bubble_colors(shape, settings) if shape else (settings["overlay_bg"], settings["overlay_fg"])
            rest.append((it, text, colors))

    # Manga / webtoon text that is NOT in a bubble (narration on the art, signs, side remarks): cover only
    # the original lettering and set the translation compactly around it with an outline, instead of a
    # big box over the drawing. (Visual novel keeps its boxes.)
    if settings["layout"] != "vn":
        free = [r for r in rest if not r[0].get("bubble")]
        rest = [r for r in rest if r[0].get("bubble")]
    else:
        free = []

    todo = []
    for it, text, colors in rest:
        x1, y1, x2, y2 = it["box"]
        core = _clip((x1 - pad, y1 - pad, x2 + pad, y2 + pad), W, H)
        pref = list(core)
        if it.get("bubble"):
            bx1, by1, bx2, by2 = it["bubble"]
            ix, iy = (bx2 - bx1) * 0.146, (by2 - by1) * 0.146
            pref = [min(pref[0], bx1 + ix), min(pref[1], by1 + iy), max(pref[2], bx2 - ix), max(pref[3], by2 - iy)]
        min_w = 5.5 * fmin + 2 * inner
        if pref[2] - pref[0] < min_w:
            cx = (pref[0] + pref[2]) / 2
            pref[0], pref[2] = cx - min_w / 2, cx + min_w / 2
        todo.append({"text": text, "core": core, "pref": _clip(tuple(pref), W, H), "colors": colors,
                     "covers": _covers(it, W, H)})

    # Trim each preferred rect away from every other item's core and from cleaned bubbles
    for i, a in enumerate(todo):
        r = a["pref"]
        for j, b in enumerate(todo):
            if i != j:
                r = _shrink_away(r, b["core"], a["core"], gap) or r
        for bb in blocked:
            r = _shrink_away(r, bb, a["core"], gap) or r
        a["pref"] = r

    placed_rects = list(blocked)
    for it, text, colors in free:
        b = _free_layout(it, text, colors, W, H, fmin, metrics, scale)
        if b:
            out.append(b)
    for a in todo:
        r = a["pref"]
        for p in placed_rects:
            r = _shrink_away(r, p, a["core"], gap) or r
        text = a["text"]
        size, lines, th, ok = fit(text, r[2] - r[0] - 2 * inner, r[3] - r[1] - 2 * inner, fmin, fmax, metrics)
        if not ok:
            size, lines, th, ok = fit(text, r[2] - r[0] - 2 * inner, r[3] - r[1] - 2 * inner, floor, fmin, metrics)
        if not ok:
            others = placed_rects + [b["core"] for b in todo if b is not a]
            cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
            w0, h0 = r[2] - r[0], r[3] - r[1]
            for gw, gh in ((1.2, 1.0), (1.0, 1.25), (1.3, 1.25), (1.5, 1.4), (1.7, 1.6)):
                cand = _clip((cx - w0 * gw / 2, cy - h0 * gh / 2, cx + w0 * gw / 2, cy + h0 * gh / 2), W, H)
                if any(_intersects(cand, o, gap) for o in others):
                    continue
                size, lines, th, ok = fit(text, cand[2] - cand[0] - 2 * inner, cand[3] - cand[1] - 2 * inner,
                                          floor, fmax, metrics)
                if ok:
                    r = cand
                    break
        if not ok:
            size, lines, th, _ = fit(text, r[2] - r[0] - 2 * inner, 1e9, floor, floor, metrics)
            need = th + 2 * inner
            cy = (r[1] + r[3]) / 2
            r = (r[0], max(0, cy - need / 2), r[2], min(H, cy + need / 2))
        measure, lh = metrics(size)
        tw = max(measure(l) for l in lines) + 2 * inner + 4 * scale
        thh = th + 2 * inner + 2 * scale
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        c = a["core"]
        rect = (max(r[0], min(c[0], cx - tw / 2)), max(r[1], min(c[1], cy - thh / 2)),
                min(r[2], max(c[2], cx + tw / 2)), min(r[3], max(c[3], cy + thh / 2)))
        placed_rects.append(rect)
        out.append({"kind": "rect", "rect": rect, "size": size, "lines": _place_lines(lines, rect, lh),
                    "fill": a["colors"][0], "ink": a["colors"][1], "covers": a["covers"]})
    user = (settings["overlay_bg"], settings["overlay_fg"])
    for b in out:  # the user's own colors stay as chosen; colors taken from the page are made readable
        if b.get("fill") and b.get("ink") and (b["fill"], b["ink"]) != user:
            b["fill"], b["ink"] = readable(b["fill"], b["ink"])
    return resolve_overlaps(out, W, H, gap)


def _free_layout(it, text, colors, W, H, fmin, metrics, scale):
    """Translation of free text: a small patch over the original lettering + the text around it, in the
    most compact block (least area outside the original text) at the reading size."""
    x1, y1, x2, y2 = it["box"]
    m = max(2.0, 2 * scale)
    patch = _clip((x1 - m, y1 - m, x2 + m, y2 + m), W, H)
    # huge lettering (a sound effect drawn across the panel): covering it would wipe the drawing, so the
    # translation is only written over it, with its outline
    chars = max(1, len("".join(str(it.get("text") or "").split())))
    letter = math.sqrt((x2 - x1) * (y2 - y1) / chars)  # about how big the original letters are
    huge = letter > 4.5 * fmin and min(x2 - x1, y2 - y1) > 6 * fmin and (x2 - x1) * (y2 - y1) > 0.02 * W * H
    pw = patch[2] - patch[0]
    cx, cy = (patch[0] + patch[2]) / 2, (patch[1] + patch[3]) / 2
    inner = 2 * scale
    measure, lh = metrics(fmin)
    longest = max((measure(w) for w in text.split()), default=0)
    widths = sorted({max(longest + 2 * inner, min(W, pw * f)) for f in (1, 1.25, 1.5, 2, 2.5, 3, 4, 6)}
                    | {max(longest + 2 * inner, min(W, 4.5 * fmin))})
    best = None
    for w in widths:
        size, lines, th, _ok = fit(text, w - 2 * inner, 1e9, fmin, fmin, metrics)
        tw = max(measure(l) for l in lines) + 2 * inner
        h = th + 2 * inner
        rx1 = min(max(0, cx - tw / 2), max(0, W - tw))
        ry1 = min(max(0, cy - h / 2), max(0, H - h))
        r = (rx1, ry1, rx1 + tw, ry1 + h)
        ix = max(0, min(r[2], patch[2]) - max(r[0], patch[0]))
        iy = max(0, min(r[3], patch[3]) - max(r[1], patch[1]))
        outside = tw * h - ix * iy
        cost = outside + 0.15 * abs(tw - h) * min(tw, h)  # least drawing covered, not a thin sliver
        if best is None or cost < best[0]:
            best = (cost, r, size, lines)
    _cost, r, size, lines = best
    _measure, lh = metrics(size)
    if huge:
        patch = None
    return {"kind": "free", "rect": r, "patch": patch, "size": size, "lines": _place_lines(lines, r, lh),
            "fill": colors[0], "ink": colors[1], "covers": _covers(it, W, H) if patch else []}


def _covers(it, W, H):
    """Areas of the original lettering to paint over (the bubble model's text areas + the read lines):
    words the OCR missed are hidden too, not left showing beside the translation."""
    m = 2
    return [_clip((c[0] - m, c[1] - m, c[2] + m, c[3] + m), W, H) for c in (it.get("cover") or [])]


def _poly_box(b):
    """Obstacle box of a cleaned bubble: its outline's bounding box, trimmed at the rounded corners."""
    xs, ys = b["poly"][0::2], b["poly"][1::2]
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    ix, iy = (x2 - x1) * 0.06, (y2 - y1) * 0.06
    return (x1 + ix, y1 + iy, x2 - ix, y2 - iy)


def _shift(b, dx, dy):
    x1, y1, x2, y2 = b["rect"]
    b["rect"] = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
    b["lines"] = [(t, cx + dx, cy + dy) for t, cx, cy in b["lines"]]


def resolve_overlaps(boxes, W, H, gap):
    """Last pass: white areas must never overlap.

    Cleaned bubbles (poly) stay where they are. Every rounded box is checked from top to bottom against
    everything already placed; if it overlaps, the lower one is moved down just below the other
    (or sideways when the two sit next to each other on the same line).
    """
    fixed = [_poly_box(b) for b in boxes if b["kind"] == "poly"]
    placed = list(fixed)
    for b in sorted((b for b in boxes if b["kind"] in ("rect", "free")), key=lambda b: (b["rect"][1], b["rect"][0])):
        for _ in range(12):  # a move can create a new overlap further down: repeat a few times
            r = b["rect"]
            hit = next((o for o in placed if _intersects(r, o, gap)), None)
            if hit is None:
                break
            h, w = r[3] - r[1], r[2] - r[0]
            v_overlap = min(r[3], hit[3]) - max(r[1], hit[1])
            side_by_side = v_overlap > 0.6 * min(h, hit[3] - hit[1])
            if side_by_side:
                right = hit[2] + gap - r[0]          # move right past it
                left = r[2] - (hit[0] - gap)         # or left past it
                if r[0] >= hit[0] and r[2] + right <= W:
                    _shift(b, right, 0)
                elif r[0] - left >= 0:
                    _shift(b, -left, 0)
                else:
                    _shift(b, 0, hit[3] + gap - r[1])
            else:
                if r[1] >= hit[1]:
                    dy = hit[3] + gap - r[1]         # the lower box goes below the upper one
                else:
                    dy = -(r[3] - (hit[1] - gap))    # this one is higher: move it up instead
                if r[3] + dy > H or r[1] + dy < 0:   # no room: try the other side of the obstacle
                    dy = hit[3] + gap - r[1] if dy < 0 else -(r[3] - (hit[1] - gap))
                    if r[3] + dy > H or r[1] + dy < 0:
                        break                        # nowhere to go: leave it
                _shift(b, 0, dy)
        placed.append(b["rect"])
    return boxes

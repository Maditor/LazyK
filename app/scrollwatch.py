"""Scroll detection by watching the page itself (manga / webtoon, Auto mode).

The mouse-wheel hook misses a lot: touchpad two-finger scrolling in Chrome / Edge (no wheel messages),
dragging the scrollbar, a reader that scrolls by itself, and a hook that Windows silently drops after
it was slow once. So a few times per second this thread grabs a small gray copy of the page area and
checks whether its content moved up or down. A move counts exactly like a wheel scroll: the overlay
hides and Auto translates again once the page stands still.

Only a real vertical shift of the whole width counts, not "something changed": an animated ad or a
video beside the comic never triggers a scan.
"""
import logging
import threading
import time

import numpy as np
from PIL import Image

from . import winapi

log = logging.getLogger(__name__)

SMALL_W = 120        # width of the gray copy (px)
TICK_S = 0.12        # how often the page is looked at
STILL = 1.5          # mean gray difference below this = nothing moved
KEEP_LOOKS = 6       # a slow scroll may take this many looks to show as a shift
BANDS = 4            # the width is cut in vertical bands; most of them must agree on the shift


def _small(img: Image.Image) -> np.ndarray:
    w, h = img.size
    sh = max(8, min(600, round(SMALL_W * h / max(1, w))))
    return np.asarray(img.convert("L").resize((SMALL_W, sh), Image.BILINEAR), dtype=np.float32)


def _profiles(a, keep):
    """Mean gray per row and band, ignoring masked pixels (the translation boxes). NaN = row fully masked."""
    h, w = a.shape
    out = np.full((h, BANDS), np.nan, dtype=np.float32)
    edges = np.linspace(0, w, BANDS + 1).astype(int)
    for b in range(BANDS):
        sl = slice(edges[b], edges[b + 1])
        k = keep[:, sl]
        n = k.sum(axis=1)
        s = (a[:, sl] * k).sum(axis=1)
        ok = n >= max(2, 0.3 * (edges[b + 1] - edges[b]))
        out[ok, b] = s[ok] / n[ok]
    return out


def _err(p, q, k):
    """Mean |difference| between profile q shifted by k rows and p, per band (NaN where nothing overlaps)."""
    h = p.shape[0]
    if k >= 0:
        d = np.abs(p[k:] - q[:h - k])
    else:
        d = np.abs(p[:h + k] - q[-k:])
    with np.errstate(all="ignore"):
        return np.nanmean(d, axis=0) if d.size else np.full(p.shape[1], np.nan)


def moved(prev, cur, keep):
    """True when cur shows prev's content shifted up or down (a scroll)."""
    if prev is None or cur is None or prev.shape != cur.shape:
        return False
    k_all = keep
    diff = np.abs(cur - prev)[k_all]
    if diff.size == 0 or float(diff.mean()) < STILL:
        return False
    p, q = _profiles(cur, keep), _profiles(prev, keep)
    h = p.shape[0]
    e0 = _err(p, q, 0)
    best = None
    lim = int(h * 0.75)
    for k in range(-lim, lim + 1):
        if k == 0:
            continue
        e = _err(p, q, k)
        score = np.nanmean(e)
        if np.isnan(score):
            continue
        if best is None or score < best[0]:
            best = (score, k, e)
    if best is None:
        return False
    _, k, e = best
    # bands where the shifted copy fits clearly better than "nothing moved"
    agree = np.sum((e < 0.5 * e0) & (e0 > STILL))
    valid = np.sum(~np.isnan(e0) & ~np.isnan(e))
    return valid > 0 and agree >= max(2, int(0.6 * valid + 0.5))


class PageWatcher(threading.Thread):
    """Puts ('pagemove', hwnd) in app.q while the watched page is being scrolled."""

    def __init__(self, app):
        super().__init__(daemon=True, name="page-watch")
        self.app = app
        self._stop_ev = threading.Event()
        self.last_move = 0.0

    def stop(self):
        self._stop_ev.set()

    def _watched(self):
        """(rect, hwnd) to watch, or None: the frame, else the browser page the user is reading."""
        a, s = self.app, self.app.s
        if a.paused or a.selecting or s["layout"] == "vn":
            return None
        if s["mode"] != "auto" and not (s["hide_on_scroll"] and (a.overlay.visible or a.busy)):
            return None
        hwnd = a._auto_hwnd or a.target_hwnd
        if not hwnd or winapi.is_own_window(hwnd) or not a._allowed_app(hwnd):
            return None
        if winapi.IS_WIN:
            # only while that window is the one being used: in front, or under the mouse
            fg = winapi.root_window(winapi.foreground_window())
            pos = winapi.cursor_pos()
            under = winapi.window_from_point(*pos) if pos else None
            if hwnd not in (fg, under):
                return None
        region = a._region()
        if region:
            return region, hwnd
        try:
            rect, _dpi = winapi.capture_rect_for_window(hwnd, int(s["browser_top_crop"]))
        except Exception:
            return None
        return rect, hwnd

    def _keep_mask(self, rect, shape):
        """False where the translation boxes are (when the screen capture can see them)."""
        ov = self.app.overlay
        keep = np.ones(shape, dtype=bool)
        if not (ov.visible and ov.rect and not ov.exclude_from_capture):
            return keep
        sx, sy = shape[1] / max(1, rect[2]), shape[0] / max(1, rect[3])
        ax, ay = ov.rect[0] - rect[0], ov.rect[1] - rect[1]
        for _tag, (x1, y1, x2, y2), _poly in list(ov._hit):
            keep[max(0, int(sy * (ay + y1)) - 1):max(0, int(sy * (ay + y2)) + 2),
                 max(0, int(sx * (ax + x1)) - 1):max(0, int(sx * (ax + x2)) + 2)] = False
        return keep

    def run(self):
        try:
            import mss
            sct = mss.mss()
        except Exception:
            log.exception("Page watcher could not start")
            return
        prev, prev_key, stale = None, None, 0
        log.info("Page watcher on (scrolls are also seen without the mouse wheel)")
        while not self._stop_ev.wait(TICK_S):
            try:
                tgt = self._watched()
                if tgt is None:
                    prev = None
                    continue
                rect, hwnd = tgt
                x, y, w, h = (int(v) for v in rect)
                if w < 50 or h < 50:
                    prev = None
                    continue
                ov = self.app.overlay
                # The translation appearing, disappearing or a box hidden under the mouse is not a scroll:
                # compare only two looks taken with the overlay in the same state, at the same place.
                key = (x, y, w, h, ov.version, self.app.busy)
                shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
                cur = _small(Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX"))
                if key != prev_key or prev is None or prev.shape != cur.shape:
                    prev, prev_key, stale = cur, key, 0
                    continue
                keep = self._keep_mask(rect, cur.shape)
                if moved(prev, cur, keep):
                    self.last_move = time.time()
                    self.app.q.put(("pagemove", hwnd))
                    prev = cur
                    stale = 0
                else:
                    # Not (yet) a visible shift. A slow scroll moves less than one small pixel per look:
                    # keep the old picture a few looks so the movement adds up; after that it is
                    # something else changing (an animation) and becomes the new reference.
                    stale += 1
                    if stale >= KEEP_LOOKS:
                        prev, stale = cur, 0
            except Exception:
                log.exception("Page watcher tick failed")
                prev = None
                self._stop_ev.wait(1.0)

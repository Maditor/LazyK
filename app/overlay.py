"""Transparent, click-through Tk overlay that paints translated bubbles, plus a status pill."""
import logging
import tkinter as tk
import tkinter.font as tkfont

from . import winapi
from .textfit import layout_items

log = logging.getLogger(__name__)

KEY_COLOR = "#ff00fe"  # painted = fully transparent (never used for boxes/text)


def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    if r < 1:
        return canvas.create_rectangle(x1, y1, x2, y2, **kw)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


class _ClickThroughWindow:
    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=KEY_COLOR)
        try:
            self.win.attributes("-transparentcolor", KEY_COLOR)
        except tk.TclError:
            pass  # non-Windows dev runs
        self.canvas = tk.Canvas(self.win, bg=KEY_COLOR, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.visible = False
        self.hwnd = None  # set after the first map (Windows)
        self.exclude_from_capture = True  # tooltips / status pill: never in any screenshot

    def place(self, x, y, w, h):
        self.win.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")

    def show(self):
        if not winapi.IS_WIN:
            self.win.deiconify()
            self.win.lift()
        elif self.hwnd is None:
            # First map goes through Tk; afterwards we show/hide with ShowWindow so the
            # overlay never steals keyboard focus from the browser.
            prev = winapi.foreground_window()
            self.win.deiconify()
            self.win.update_idletasks()
            self.hwnd = winapi.tk_toplevel_hwnd(self.win)
            winapi.make_overlay_window(self.hwnd, self.exclude_from_capture)
            winapi.show_no_activate(self.hwnd)
            if prev and winapi.foreground_window() != prev:
                winapi.set_foreground(prev)
        else:
            self.win.update_idletasks()  # apply pending geometry before showing
            winapi.make_overlay_window(self.hwnd, self.exclude_from_capture)
            winapi.show_no_activate(self.hwnd)
        self.visible = True

    def hide(self):
        if self.visible:
            if self.hwnd:
                winapi.hide_window(self.hwnd)
            else:
                self.win.withdraw()
        self.visible = False


class Overlay(_ClickThroughWindow):
    def __init__(self, root, settings):
        super().__init__(root)
        self.settings = settings
        self._fonts = {}
        self.rect = None

    def _font(self, size):
        key = (self.settings["font_family"], size, bool(self.settings["font_bold"]))
        f = self._fonts.get(key)
        if f is None:
            f = tkfont.Font(family=key[0], size=-size, weight="bold" if key[2] else "normal")
            self._fonts[key] = f
        return f

    def _metrics(self, size):
        f = self._font(size)
        return f.measure, f.metrics("linespace")

    def show_items(self, rect, items, dpi=96):
        s = self.settings
        # The tool always hides the overlay before its own capture, so it may appear in the user's
        # screenshots (Print Screen, Snipping Tool) without being read back by the OCR
        self.exclude_from_capture = not s["overlay_in_screenshots"]
        x, y, w, h = rect
        self.rect = rect
        scale = dpi / 96.0
        self.canvas.delete("all")
        self.place(x, y, w, h)
        boxes = layout_items(items, w, h, s, scale, self._metrics)
        radius = s["corner_radius"] * scale
        outline = s["overlay_outline"] or ""
        for b in boxes:
            if b["kind"] == "poly":
                # Clean the inside of the bubble, following its real outline
                self.canvas.create_polygon(b["poly"], fill=b["fill"], outline="")
            else:
                x1, y1, x2, y2 = b["rect"]
                if s["overlay_shadow"]:
                    off = max(1, round(2 * scale))
                    rounded_rect(self.canvas, x1 + off, y1 + off, x2 + off, y2 + off, radius,
                                 fill="#8a8a8a", outline="")
                rounded_rect(self.canvas, x1, y1, x2, y2, radius, fill=b.get("fill", s["overlay_bg"]),
                             outline=outline, width=1 if outline else 0)
            font = self._font(b["size"])
            for line, cx, cy in b["lines"]:
                self.canvas.create_text(cx, cy, text=line, font=font, fill=b.get("ink", s["overlay_fg"]),
                                        anchor="center")
        self.show()
        log.info("Overlay: %d boxes at %s (dpi %s)", len(boxes), rect, dpi)

    def clear(self):
        self.canvas.delete("all")
        self.hide()


class StatusPill(_ClickThroughWindow):
    COLORS = {"scanning": "#3b82f6", "translating": "#a855f7", "ready": "#22c55e",
              "error": "#ef4444", "paused": "#9ca3af", "info": "#f59e0b"}

    def __init__(self, root):
        super().__init__(root)
        self._hide_job = None
        self._font = tkfont.Font(family="Segoe UI", size=-13, weight="bold")

    def set(self, state, text, anchor_rect=None, dpi=96, auto_hide_ms=None):
        if self._hide_job:
            self.win.after_cancel(self._hide_job)
            self._hide_job = None
        scale = dpi / 96.0
        self._font.configure(size=-max(11, round(12 * scale)))
        text = text if len(text) <= 90 else text[:87] + "…"
        tw = self._font.measure(text)
        hgt = round(26 * scale)
        dot = round(8 * scale)
        padx = round(10 * scale)
        w = padx + dot + round(7 * scale) + tw + padx
        c = self.canvas
        c.delete("all")
        rounded_rect(c, 0, 0, w - 1, hgt - 1, hgt / 2, fill="#1f2430", outline="")
        cy = hgt / 2
        c.create_oval(padx, cy - dot / 2, padx + dot, cy + dot / 2,
                      fill=self.COLORS.get(state, "#9ca3af"), outline="")
        c.create_text(padx + dot + round(7 * scale), cy, text=text, anchor="w",
                      font=self._font, fill="#f3f4f6")
        if anchor_rect:
            ax, ay, aw, _ah = anchor_rect
        else:
            ax, ay, aw = 0, 0, self.win.winfo_screenwidth()
        margin = round(10 * scale)
        self.place(ax + aw - w - margin, ay + margin, w, hgt)
        self.show()
        if auto_hide_ms:
            self._hide_job = self.win.after(auto_hide_ms, self.hide)

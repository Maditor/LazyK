"""Transparent, click-through Tk overlay that paints translated bubbles, plus a status pill."""
import logging
import tkinter as tk
import tkinter.font as tkfont

from . import winapi
from .textfit import layout_items

log = logging.getLogger(__name__)

KEY_COLOR = "#ff00fe"  # painted = fully transparent (never used for boxes/text)


def glass_image(bg, size, offset, fill, opacity, blur, radius):
    """A see-through box with a frosted background, as a picture (Tk canvas has no alpha or blur).
    bg: screenshot of the area under the overlay, offset: (x, y) of the box in it, size: (w, h).
    opacity: % solid. Corners outside the rounded rectangle are KEY_COLOR, so they stay transparent."""
    from PIL import Image, ImageColor, ImageDraw, ImageFilter
    w, h = int(size[0]), int(size[1])
    x0, y0 = int(offset[0]), int(offset[1])
    m = int(3 * blur)  # blur with the pixels around the box too, or its edges go dark / flat
    left, top = max(0, x0 - m), max(0, y0 - m)
    crop = bg.crop((left, top, min(bg.width, x0 + w + m), min(bg.height, y0 + h + m))).convert("RGB")
    if blur > 0:
        crop = crop.filter(ImageFilter.GaussianBlur(blur))
    base = crop.crop((x0 - left, y0 - top, x0 - left + w, y0 - top + h))
    if base.size != (w, h):  # box partly outside the screenshot
        pad = Image.new("RGB", (w, h), ImageColor.getrgb(fill))
        pad.paste(base, (0, 0))
        base = pad
    base = Image.blend(base, Image.new("RGB", (w, h), ImageColor.getrgb(fill)), max(0, min(100, opacity)) / 100.0)
    ss = 4
    mask = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), radius=max(0, radius) * ss, fill=255)
    mask = mask.resize((w, h), Image.LANCZOS).point(lambda v: 255 if v >= 128 else 0)  # hard edge: no pink fringe
    out = Image.new("RGB", (w, h), ImageColor.getrgb(KEY_COLOR))
    out.paste(base, (0, 0), mask)
    return out


def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    if r < 1:
        return canvas.create_rectangle(x1, y1, x2, y2, **kw)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


# Developer mode (Settings): every tool window becomes visible to screen recorders such as OBS.
DEV = {"on": False}


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
        self._excl = True  # tooltips / status pill: never in any screenshot (unless developer mode)

    @property
    def exclude_from_capture(self):
        return self._excl and not DEV["on"]

    @exclude_from_capture.setter
    def exclude_from_capture(self, v):
        self._excl = bool(v)

    def apply_capture(self):
        """Re-apply the capture setting to an already mapped window (developer mode toggled)."""
        if self.hwnd:
            winapi.set_capture_excluded(self.hwnd, self.exclude_from_capture)

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
        self._hit = []        # (tag, screen bbox, polygon or None) per painted box, for hover-hide
        self._hover_tag = None
        self._pics = []       # PhotoImages of see-through boxes (Tk drops an image nobody references)
        self._bg = None       # (rect, screenshot of the screen under the overlay, taken while it was hidden)

    def _background(self, rect):
        """Screenshot of what is under the overlay. Never of the overlay itself: reuse the one taken
        while it was hidden (a re-render keeps it), or hide, grab, and show again."""
        if self._bg and self._bg[0] == tuple(rect):
            return self._bg[1]
        from .pipeline import grab
        was = self.visible
        if was:
            self.hide()
            self.win.update_idletasks()
        try:
            img = grab(rect)
        except Exception:
            log.exception("Overlay: could not read the screen under the overlay")
            img = None
        self._bg = (tuple(rect), img) if img is not None else None
        return img

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
        # Visual novel auto-scan watches the screen: our own translation must not look like new text
        self.exclude_from_capture = (not s["overlay_in_screenshots"]) or (s["layout"] == "vn" and bool(s["vn_auto"]))
        x, y, w, h = rect
        self.rect = rect
        scale = dpi / 96.0
        self.canvas.delete("all")
        self.place(x, y, w, h)
        boxes = layout_items(items, w, h, s, scale, self._metrics)
        self._hit, self._hover_tag, self._pics = [], None, []
        opacity, blur = int(s["overlay_opacity"]), int(s["overlay_blur"])
        see_through = opacity < 100 and any(b["kind"] != "poly" for b in boxes)
        bgshot = self._background(rect) if see_through else None
        if not see_through:
            self._bg = None
        radius = s["corner_radius"] * scale
        outline = s["overlay_outline"] or ""
        for i, b in enumerate(boxes):
            tag = f"box{i}"
            first = len(self.canvas.find_all())
            if b["kind"] == "poly":
                # Clean the inside of the bubble, following its real outline
                self.canvas.create_polygon(b["poly"], fill=b["fill"], outline="")
                pts = b["poly"]
                self._hit.append((tag, b["rect"], list(zip(pts[0::2], pts[1::2]))))
            else:
                x1, y1, x2, y2 = b["rect"]
                self._hit.append((tag, b["rect"], None))
                if s["overlay_shadow"]:
                    off = max(1, round(2 * scale))
                    rounded_rect(self.canvas, x1 + off, y1 + off, x2 + off, y2 + off, radius,
                                 fill="#8a8a8a", outline="")
                pic = None
                if bgshot is not None:
                    try:
                        from PIL import ImageTk
                        pic = ImageTk.PhotoImage(glass_image(
                            bgshot, (x2 - x1, y2 - y1), (x1, y1), b.get("fill", s["overlay_bg"]),
                            opacity, blur * scale, radius))
                    except Exception:
                        log.exception("Overlay: see-through box failed, painting it solid")
                if pic is not None:
                    self._pics.append(pic)
                    self.canvas.create_image(round(x1), round(y1), image=pic, anchor="nw")
                    if outline:
                        rounded_rect(self.canvas, x1, y1, x2, y2, radius, fill="", outline=outline, width=1)
                else:
                    rounded_rect(self.canvas, x1, y1, x2, y2, radius, fill=b.get("fill", s["overlay_bg"]),
                                 outline=outline, width=1 if outline else 0)
            font = self._font(b["size"])
            for line, cx, cy in b["lines"]:
                self.canvas.create_text(cx, cy, text=line, font=font, fill=b.get("ink", s["overlay_fg"]),
                                        anchor="center")
            for item in self.canvas.find_all()[first:]:
                self.canvas.addtag_withtag(tag, item)
        self.show()
        if s["hover_hide"]:
            # the mouse may already be over the new box: hide it before Tk paints, so it never flashes
            self.set_hover(winapi.cursor_pos())
        log.info("Overlay: %d boxes at %s (dpi %s)", len(boxes), rect, dpi)

    @staticmethod
    def _inside(pt, bbox, poly):
        x, y = pt
        x1, y1, x2, y2 = bbox
        if not (x1 <= x <= x2 and y1 <= y <= y2):
            return False
        if not poly:
            return True
        inside, j = False, len(poly) - 1  # ray casting for bubbles with a real outline
        for i in range(len(poly)):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
                inside = not inside
            j = i
        return inside

    def set_hover(self, screen_pt):
        """Hide the one box under the mouse (screen px); None shows everything again."""
        tag = None
        if screen_pt and self.visible and self.rect:
            ox, oy = self.rect[0], self.rect[1]
            pt = (screen_pt[0] - ox, screen_pt[1] - oy)
            for t, bbox, poly in reversed(self._hit):
                if self._inside(pt, bbox, poly):
                    tag = t
                    break
        if tag == self._hover_tag:
            return
        if self._hover_tag:
            self.canvas.itemconfigure(self._hover_tag, state="normal")
        if tag:
            self.canvas.itemconfigure(tag, state="hidden")
        self._hover_tag = tag

    def clear(self):
        self.canvas.delete("all")
        self._hit, self._hover_tag, self._pics, self._bg = [], None, [], None
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

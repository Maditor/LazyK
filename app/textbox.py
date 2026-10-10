"""'Text box' (Settings → Look): the translation in a separate window instead of over the page.

The box can be dragged anywhere and resized from its bottom-right corner; position and size are saved.
It never takes the keyboard from the game / browser (like the toolbar) and it is invisible to screen
captures (like the toolbar), so it is never read back by the OCR even when it sits over the scanned area.
"""
import logging
import tkinter as tk
import tkinter.font as tkfont

from . import winapi

log = logging.getLogger(__name__)

PAD = 14          # inner margin (px)
GRIP = 16         # size of the resize corner
MIN_W, MIN_H = 180, 60
MIN_FONT = 10
PLACEHOLDER = "Translations appear here · drag to move · corner to resize"


class TextBox:
    def __init__(self, root, settings):
        self.root, self.s = root, settings
        self.win = None
        self.canvas = None
        self.hwnd = None
        self.texts = []
        self._drag = None
        self._fonts = {}
        self._hover = False
        self._used = False  # placeholder only until the first translation (no flash between lines)
        self._bg = None     # (rect, screenshot of what is under the box) for the see-through look
        self._pic = None    # its PhotoImage (Tk drops an image nobody references)
        self._regrab = None

    # ------------------------------------------------------------ window
    def _geometry(self):
        r = self.s["text_box_rect"]
        if isinstance(r, (list, tuple)) and len(r) == 4 and winapi.point_on_screen(r[0] + 20, r[1] + 20):
            return [int(v) for v in r]
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(760, int(sw * 0.6)), 170
        return [(sw - w) // 2, int(sh * 0.72), w, h]

    def _build(self):
        w = self.win = tk.Toplevel(self.root)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        from .overlay import KEY_COLOR
        w.configure(bg=KEY_COLOR)
        try:
            w.attributes("-transparentcolor", KEY_COLOR)  # rounded corners: the screen shows through
        except tk.TclError:
            pass
        x, y, ww, hh = self._geometry()
        w.geometry(f"{ww}x{hh}+{x}+{y}")
        self.canvas = tk.Canvas(w, bg=KEY_COLOR, highlightthickness=0, bd=0, cursor="fleur")
        self.canvas.pack(fill="both", expand=True)
        c = self.canvas
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Motion>", self._cursor)
        c.bind("<Configure>", lambda e: self.render())
        c.bind("<Enter>", lambda e: self._set_hover(True))
        c.bind("<Leave>", lambda e: self._set_hover(False))

    def show(self):
        if self.win is None or not self.win.winfo_exists():
            self._build()
        prev = winapi.foreground_window()
        self.win.deiconify()
        self.win.update_idletasks()
        self.hwnd = winapi.tk_toplevel_hwnd(self.win)
        winapi.make_toolbar_window(self.hwnd, self._excluded())
        if prev and winapi.foreground_window() != prev:
            winapi.set_foreground(prev)
        self.render()
        self._keep_on_top()

    def destroy(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
        self.win = self.canvas = self.hwnd = None

    @property
    def shown(self):
        return self.win is not None and self.win.winfo_exists()

    def _excluded(self):
        from .overlay import DEV
        return not DEV["on"]  # never OCR'd, even over the scanned area (developer mode: visible)

    def apply_capture(self):
        if self.hwnd:
            winapi.set_capture_excluded(self.hwnd, self._excluded())

    def _keep_on_top(self):
        if not self.shown:
            return
        try:
            self.win.attributes("-topmost", True)
            if self.hwnd:
                winapi.show_no_activate(self.hwnd)
        except tk.TclError:
            return
        self.win.after(3000, self._keep_on_top)

    # ------------------------------------------------------------ content
    def set_texts(self, texts):
        self.texts = [t for t in (texts or []) if t and t.strip()]
        self._used = self._used or bool(self.texts)
        self._bg = None  # the game behind may have changed: look again
        if not self.shown:
            self.show()
        else:
            self.render()

    def _font(self, size):
        key = (self.s["font_family"], size, bool(self.s["font_bold"]))
        f = self._fonts.get(key)
        if f is None:
            f = tkfont.Font(family=key[0], size=-size, weight="bold" if key[2] else "normal")
            self._fonts[key] = f
        return f

    def render(self):
        if not self.shown:
            return
        c, s = self.canvas, self.s
        w, h = max(1, c.winfo_width()), max(1, c.winfo_height())
        bg, fg = s["overlay_bg"], s["overlay_fg"]
        c.delete("all")
        self._paint_box(w, h, bg)  # opacity / blur act on the box only: the text stays 100 %
        inner_w = max(40, w - 2 * PAD)
        if self.texts:
            text = "\n\n".join(self.texts) if len(self.texts) > 1 else self.texts[0]
            fmin = max(MIN_FONT, int(s["font_min"]))
            top = int(fmin * 1.6) if s["auto_text_size"] else fmin
            size = top
            while True:  # the biggest size up to `top` that fits; below the minimum only if it must
                item = c.create_text(PAD, PAD, text=text, font=self._font(size), fill=fg, anchor="nw",
                                     width=inner_w)
                x1, y1, x2, y2 = c.bbox(item)
                if y2 - y1 <= h - 2 * PAD or size <= MIN_FONT:
                    break
                c.delete(item)
                size -= 1 if size <= fmin else 2
            # center the block vertically when there is room
            dy = max(0, (h - 2 * PAD - (y2 - y1)) // 2)
            c.move(item, 0, dy)
        elif not self._used:
            c.create_text(w // 2, h // 2, text=PLACEHOLDER, font=self._font(max(MIN_FONT, 12)),
                          fill=_mix(bg, fg, 0.45), width=inner_w, justify="center")
        # resize corner: three short diagonal lines (only while the mouse is over the box, or empty)
        if self._hover or not self._used:
            ink = _mix(bg, fg, 0.5)
            for k in (4, 8, 12):
                c.create_line(w - 3, h - 3 - k, w - 3 - k, h - 3, fill=ink, width=1)

    def _screen_under(self, w, h):
        """Screenshot of the screen under the box. The box is hidden from captures, so it can be taken
        while the box is up; in developer mode (box visible to captures) it is hidden for a moment."""
        rect = (self.win.winfo_rootx(), self.win.winfo_rooty(), w, h)
        if self._bg and self._bg[0] == rect:
            return self._bg[1]
        from .pipeline import grab
        # Windows leaves a capture-excluded window out of screenshots: no need to hide it
        hide = not (winapi.IS_WIN and self._excluded())
        try:
            if hide:
                if self.hwnd:
                    winapi.hide_window(self.hwnd)
                else:
                    self.win.withdraw()
                self.win.update()
            img = grab(rect)
        except Exception:
            log.exception("Text box: could not read the screen under the box")
            img = None
        finally:
            if hide:
                if self.hwnd:
                    winapi.show_no_activate(self.hwnd)
                else:
                    self.win.deiconify()
        self._bg = (rect, img) if img is not None else None
        return img

    def _paint_box(self, w, h, fill):
        from .overlay import glass_image, rounded_rect
        s, c = self.s, self.canvas
        radius = int(s["corner_radius"])
        outline = s["overlay_outline"] or ""
        try:
            opacity, blur = int(s["overlay_opacity"]), int(s["overlay_blur"])
        except (TypeError, ValueError):
            opacity, blur = 100, 0
        self._pic = None
        if opacity < 100:
            shot = self._screen_under(w, h)
            if shot is not None:
                try:
                    from PIL import ImageTk
                    self._pic = ImageTk.PhotoImage(glass_image(shot, (w, h), (0, 0), fill, opacity, blur, radius))
                except Exception:
                    log.exception("Text box: see-through box failed, painting it solid")
        if self._pic is not None:
            c.create_image(0, 0, image=self._pic, anchor="nw")
            if outline:
                rounded_rect(c, 0, 0, w - 1, h - 1, radius, fill="", outline=outline, width=1)
        else:
            rounded_rect(c, 0, 0, w - 1, h - 1, radius, fill=fill, outline=outline, width=1 if outline else 0)

    def _set_hover(self, on):
        if self._hover != on:
            self._hover = on
            self.render()

    # ------------------------------------------------------------ move / resize
    def _in_grip(self, e):
        return e.x >= self.canvas.winfo_width() - GRIP and e.y >= self.canvas.winfo_height() - GRIP

    def _cursor(self, e):
        self.canvas.configure(cursor="size_nw_se" if self._in_grip(e) else "fleur")

    def _press(self, e):
        g = (self.win.winfo_x(), self.win.winfo_y(), self.win.winfo_width(), self.win.winfo_height())
        self._drag = ("size" if self._in_grip(e) else "move", e.x_root, e.y_root, g)

    def _motion(self, e):
        if not self._drag:
            return
        kind, x0, y0, (gx, gy, gw, gh) = self._drag
        dx, dy = e.x_root - x0, e.y_root - y0
        if kind == "move":
            self.win.geometry(f"+{gx + dx}+{gy + dy}")
        else:
            self.win.geometry(f"{max(MIN_W, gw + dx)}x{max(MIN_H, gh + dy)}")
        if self._regrab is None and int(self.s["overlay_opacity"]) < 100:
            self._regrab = self.win.after(60, self._after_move)  # see-through: what is behind changed

    def _after_move(self):
        self._regrab = None
        if self.shown:
            self.win.update_idletasks()
            self.render()

    def _release(self, _e):
        if self._drag:
            self.render()
            self._drag = None
            self.s.update(text_box_rect=[self.win.winfo_x(), self.win.winfo_y(),
                                         self.win.winfo_width(), self.win.winfo_height()])


def _mix(a, b, t):
    """Color between a and b (#rrggbb), t = 0..1."""
    try:
        pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
        pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb))
    except (ValueError, TypeError, IndexError):
        return "#808080"

"""Color picker for the text / box colors: color field, hue bar, hex, swatches and an eyedropper.

The Windows color dialog has no way to take a color from the screen, which is what you want when
matching a game's text box or a comic's paper. Changes are shown live on the translation; Cancel puts
the old color back.
"""
import colorsys
import logging
import tkinter as tk

from . import theme as T
from . import winapi

log = logging.getLogger(__name__)

SV_W, SV_H = 240, 150
HUE_H = 14
SWATCHES = ["#ffffff", "#f4f1ea", "#fff4c2", "#ffe0ec", "#dff1ff", "#c8c8c8",
            "#000000", "#1c1c1c", "#2b2f3a", "#3a2a1a", "#0f2a44", "#5b1a1a"]


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def _rgb(hexa):
    h = hexa.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _valid(hexa):
    try:
        _rgb(hexa)
        return len(hexa.lstrip("#")) in (3, 6)
    except (ValueError, TypeError):
        return False


class ColorDialog:
    """on_change(hex) while choosing (live preview); on_done(hex or None) once (None = canceled)."""

    def __init__(self, root, initial, title, on_change=None, on_done=None):
        self.root, self.on_change, self.on_done = root, on_change, on_done
        self.initial = initial if _valid(initial) else "#ffffff"
        r, g, b = (v / 255 for v in _rgb(self.initial))
        self.h, self.sv_s, self.v = colorsys.rgb_to_hsv(r, g, b)
        self.f = T.fonts(root)
        self._sv_img = self._hue_img = None
        self._done = False

        w = self.win = tk.Toplevel(root)
        w.title(f"LazyK · {title}")
        w.configure(bg=T.BG, padx=18, pady=16)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        f = self.f
        tk.Label(w, text=title, bg=T.BG, fg=T.FG, font=f["title"], anchor="w").pack(fill="x")

        self.sv = tk.Canvas(w, width=SV_W, height=SV_H, highlightthickness=0, bd=0, cursor="crosshair")
        self.sv.pack(pady=(10, 6))
        self.hue = tk.Canvas(w, width=SV_W, height=HUE_H, highlightthickness=0, bd=0, cursor="sb_h_double_arrow")
        self.hue.pack()
        for c, fn in ((self.sv, self._sv_at), (self.hue, self._hue_at)):
            c.bind("<ButtonPress-1>", fn)
            c.bind("<B1-Motion>", fn)

        row = tk.Frame(w, bg=T.BG)
        row.pack(fill="x", pady=(10, 4))
        self.swatch = tk.Canvas(row, width=56, height=30, highlightthickness=1, highlightbackground=T.BORDER, bd=0)
        self.swatch.pack(side="left")
        box = tk.Frame(row, bg=T.FIELD, highlightthickness=1, highlightbackground=T.BORDER, highlightcolor=T.ACCENT)
        box.pack(side="left", padx=8)
        self.hexvar = tk.StringVar()
        self.entry = tk.Entry(box, textvariable=self.hexvar, bg=T.FIELD, fg=T.FG, insertbackground=T.FG,
                              relief="flat", font=f["body"], width=9, highlightthickness=0, bd=0)
        self.entry.pack(ipady=5, padx=6)
        self.entry.bind("<Return>", lambda e: self._typed())
        self.entry.bind("<FocusOut>", lambda e: self._typed())
        T.FlatButton(row, "Pick from screen", self.eyedropper, font=f["bold"], padx=10, pady=5).pack(side="right")

        sw = tk.Frame(w, bg=T.BG)
        sw.pack(fill="x", pady=(6, 10))
        for i, col in enumerate(SWATCHES):
            c = tk.Canvas(sw, width=18, height=18, bg=col, highlightthickness=1, highlightbackground=T.BORDER,
                          bd=0, cursor="hand2")
            c.grid(row=0, column=i, padx=(0, 2))
            c.bind("<ButtonRelease-1>", lambda e, col=col: self.set_hex(col))

        btns = tk.Frame(w, bg=T.BG)
        btns.pack(fill="x")
        T.FlatButton(btns, "OK", self._ok, "primary", font=f["bold"]).pack(side="right")
        T.FlatButton(btns, "Cancel", self._cancel, font=f["bold"]).pack(side="right", padx=8)
        w.bind("<Escape>", lambda e: self._cancel())
        w.protocol("WM_DELETE_WINDOW", self._cancel)

        self._draw_hue()
        self._refresh(notify=False)
        w.update_idletasks()
        px, py = winapi.cursor_pos() or (w.winfo_screenwidth() // 2, w.winfo_screenheight() // 3)
        L, Tp, R, B = winapi.work_area(px, py)
        ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
        w.geometry(f"+{max(L, min(px - ww // 2, R - ww))}+{max(Tp, min(py - 40, B - wh))}")
        w.lift()
        w.focus_force()

    # ------------------------------------------------------------ drawing
    def _draw_hue(self):
        from PIL import Image, ImageTk
        img = Image.new("RGB", (SV_W, 1))
        px = img.load()
        for x in range(SV_W):
            px[x, 0] = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(x / (SV_W - 1), 1, 1))
        self._hue_img = ImageTk.PhotoImage(img.resize((SV_W, HUE_H)))
        self.hue.delete("all")
        self.hue.create_image(0, 0, image=self._hue_img, anchor="nw")
        self._hue_mark = self.hue.create_rectangle(0, 0, 0, 0, outline="#ffffff", width=2)

    def _draw_sv(self):
        import numpy as np
        from PIL import Image, ImageTk
        r, g, b = colorsys.hsv_to_rgb(self.h, 1, 1)
        s = np.linspace(0, 1, SV_W)[None, :, None]
        v = np.linspace(1, 0, SV_H)[:, None, None]
        hue = np.array([r, g, b])[None, None, :]
        arr = (v * (1 - s + s * hue) * 255).astype(np.uint8)
        self._sv_img = ImageTk.PhotoImage(Image.fromarray(arr, "RGB"))
        self.sv.delete("all")
        self.sv.create_image(0, 0, image=self._sv_img, anchor="nw")

    def _refresh(self, notify=True, redraw_sv=True):
        if redraw_sv:
            self._draw_sv()
        x, y = self.sv_s * (SV_W - 1), (1 - self.v) * (SV_H - 1)
        ring = "#000000" if self.v > 0.6 and self.sv_s < 0.5 else "#ffffff"
        self.sv.delete("mark")
        self.sv.create_oval(x - 6, y - 6, x + 6, y + 6, outline=ring, width=2, tags="mark")
        hx = self.h * (SV_W - 1)
        self.hue.coords(self._hue_mark, hx - 3, 1, hx + 3, HUE_H - 1)
        col = self.value()
        self.swatch.delete("all")
        self.swatch.create_rectangle(0, 0, 28, 32, fill=self.initial, width=0)  # before | now
        self.swatch.create_rectangle(28, 0, 60, 32, fill=col, width=0)
        if self.hexvar.get().lower() != col:
            self.hexvar.set(col)
        if notify and self.on_change:
            try:
                self.on_change(col)
            except Exception:  # noqa: BLE001
                log.exception("Color preview failed")

    # ------------------------------------------------------------ input
    def value(self):
        return _hex(c * 255 for c in colorsys.hsv_to_rgb(self.h, self.sv_s, self.v))

    def set_hex(self, hexa):
        if not _valid(hexa):
            return
        r, g, b = (v / 255 for v in _rgb(hexa))
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if s > 0.001 and v > 0.001:
            self.h = h  # gray keeps the hue the user was on
        self.sv_s, self.v = s, v
        self._refresh()

    def _sv_at(self, e):
        self.sv_s = min(1, max(0, e.x / (SV_W - 1)))
        self.v = 1 - min(1, max(0, e.y / (SV_H - 1)))
        self._refresh(redraw_sv=False)

    def _hue_at(self, e):
        self.h = min(1, max(0, e.x / (SV_W - 1)))
        self._refresh()

    def _typed(self):
        t = self.hexvar.get().strip()
        if not t.startswith("#"):
            t = "#" + t
        if _valid(t) and t.lower() != self.value():
            self.set_hex(t.lower())

    # ------------------------------------------------------------ eyedropper
    def eyedropper(self):
        self.win.withdraw()
        self.root.after(150, lambda: ScreenPicker(self.root, self._picked))

    def _picked(self, hexa):
        if self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            if hexa:
                self.set_hex(hexa)

    # ------------------------------------------------------------ close
    def _finish(self, value):
        if self._done:
            return
        self._done = True
        if self.win.winfo_exists():
            self.win.destroy()
        if self.on_done:
            self.on_done(value)

    def _ok(self):
        self._typed()
        self._finish(self.value())

    def _cancel(self):
        if self.on_change and self.value() != self.initial:
            self.on_change(self.initial)  # take the live preview back
        self._finish(None)


class ScreenPicker:
    """Full-screen still of all monitors with a magnifier: click a pixel to take its color.
    on_pick(hex), or on_pick(None) after Esc / right click."""
    ZOOM, CELLS = 11, 11   # magnifier: 11 x 11 pixels, each drawn 11 px wide

    def __init__(self, root, on_pick):
        self.root, self.on_pick = root, on_pick
        self._done = False
        try:
            import mss
            from PIL import Image, ImageTk
            with mss.mss() as sct:
                mon = sct.monitors[0]  # the whole virtual screen
                main = sct.monitors[1] if len(sct.monitors) > 1 else mon
                shot = sct.grab(mon)
            self.img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            self.ox, self.oy = mon["left"], mon["top"]
            hint_x = main["left"] - mon["left"] + main["width"] // 2
            hint_y = main["top"] - mon["top"] + 24
            self._photo = ImageTk.PhotoImage(self.img)
        except Exception:
            log.exception("Eyedropper: could not capture the screen")
            on_pick(None)
            return
        w = self.win = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.geometry(f"{self.img.width}x{self.img.height}+{self.ox}+{self.oy}")
        c = self.canvas = tk.Canvas(w, highlightthickness=0, bd=0, cursor="crosshair")
        c.pack(fill="both", expand=True)
        c.create_image(0, 0, image=self._photo, anchor="nw")
        size = self.ZOOM * self.CELLS
        self._lens = None
        self._lens_item = c.create_image(0, 0, anchor="nw")
        self._lens_box = c.create_rectangle(0, 0, size, size, outline="#ffffff", width=2)
        self._lens_mid = c.create_rectangle(0, 0, 0, 0, outline="#ff3b6b", width=2)
        self._label_bg = c.create_rectangle(0, 0, 0, 0, fill="#131418", outline="")
        self._label = c.create_text(0, 0, text="", fill="#e8e9ee", anchor="nw", font=("Segoe UI", 10, "bold"))
        hint = c.create_text(hint_x, hint_y, anchor="n", fill="#ffffff", font=("Segoe UI", 11, "bold"),
                             text="Click to take a color  ·  Esc to cancel")
        hb = c.bbox(hint)
        c.tag_lower(c.create_rectangle(hb[0] - 10, hb[1] - 6, hb[2] + 10, hb[3] + 6, fill="#131418", outline=""), hint)
        c.bind("<Motion>", self._move)
        c.bind("<ButtonRelease-1>", self._click)
        c.bind("<ButtonRelease-3>", lambda e: self._finish(None))
        w.bind("<Escape>", lambda e: self._finish(None))
        self._pending = None
        w.focus_force()
        w.grab_set()
        pos = winapi.cursor_pos()
        if pos:
            self._update(pos[0] - self.ox, pos[1] - self.oy)

    def _color_at(self, x, y):
        x = min(self.img.width - 1, max(0, int(x)))
        y = min(self.img.height - 1, max(0, int(y)))
        return _hex(self.img.getpixel((x, y)))

    def _move(self, e):
        self._pending = (e.x, e.y)
        if not getattr(self, "_queued", False):
            self._queued = True
            self.win.after(15, self._flush)

    def _flush(self):
        self._queued = False
        if self._pending and not self._done:
            self._update(*self._pending)

    def _update(self, x, y):
        from PIL import Image, ImageTk
        n, z = self.CELLS, self.ZOOM
        half = n // 2
        crop = self.img.crop((x - half, y - half, x + half + 1, y + half + 1)).resize((n * z, n * z), Image.NEAREST)
        self._lens = ImageTk.PhotoImage(crop)
        size = n * z
        lx = x + 24 if x + 24 + size < self.img.width else x - 24 - size
        ly = y + 24 if y + 24 + size + 24 < self.img.height else y - 24 - size - 24
        c = self.canvas
        c.itemconfigure(self._lens_item, image=self._lens)
        c.coords(self._lens_item, lx, ly)
        c.coords(self._lens_box, lx, ly, lx + size, ly + size)
        c.coords(self._lens_mid, lx + half * z, ly + half * z, lx + (half + 1) * z, ly + (half + 1) * z)
        col = self._color_at(x, y)
        c.itemconfigure(self._label, text=f"  {col}  ")
        c.coords(self._label, lx, ly + size + 4)
        bx = c.bbox(self._label)
        if bx:
            c.coords(self._label_bg, bx[0] - 2, bx[1] - 2, bx[2] + 2, bx[3] + 2)
            c.tag_raise(self._label)

    def _click(self, e):
        self._finish(self._color_at(e.x, e.y))

    def _finish(self, value):
        if self._done:
            return
        self._done = True
        try:
            self.win.grab_release()
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_pick(value)

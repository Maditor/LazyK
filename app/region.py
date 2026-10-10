"""Full-screen frame picker: drag a rectangle around the comic page (like a snipping tool)."""
import tkinter as tk
import tkinter.font as tkfont

from . import winapi

ACCENT = "#6d5dfc"
MIN_SIZE = 80


class RegionSelector:
    """Calls on_done((x, y, w, h)) in physical screen px, or on_done(None) when canceled."""

    def __init__(self, root, on_done, current=None):
        self.on_done = on_done
        self.start = None
        vs = winapi.virtual_screen()
        if vs:
            self.vx, self.vy, vw, vh = vs
        else:
            self.vx, self.vy, vw, vh = 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()
        w = self.win = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.35)
        w.configure(bg="black", cursor="crosshair")
        w.geometry(f"{vw}x{vh}+{self.vx}+{self.vy}")
        c = self.canvas = tk.Canvas(w, bg="black", highlightthickness=0, cursor="crosshair")
        c.pack(fill="both", expand=True)
        font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        # Hint on the monitor under the mouse
        px, py = root.winfo_pointerx() - self.vx, root.winfo_pointery() - self.vy
        c.create_text(px, py - 40, text="Drag a frame around the comic page  ·  Enter = keep old  ·  Esc = cancel",
                      fill="white", font=font)
        self.rect = None
        if current:
            x, y, cw, ch = current
            self.rect = c.create_rectangle(x - self.vx, y - self.vy, x - self.vx + cw, y - self.vy + ch,
                                           outline=ACCENT, width=3, dash=(6, 4))
        self.size_lbl = c.create_text(0, 0, text="", fill="white", font=font, anchor="nw")
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._move)
        c.bind("<ButtonRelease-1>", self._release)
        w.bind("<Escape>", lambda _e: self._finish(None))
        w.bind("<Button-3>", lambda _e: self._finish(None))
        w.bind("<Return>", lambda _e: self._finish(tuple(current) if current else None))
        w.after(50, lambda: (w.focus_force(), w.grab_set()))

    def _press(self, e):
        self.start = (e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline=ACCENT, width=3)

    def _move(self, e):
        if not self.start:
            return
        x0, y0 = self.start
        self.canvas.coords(self.rect, x0, y0, e.x, e.y)
        self.canvas.coords(self.size_lbl, min(x0, e.x), max(y0, e.y) + 6)
        self.canvas.itemconfigure(self.size_lbl, text=f"{abs(e.x - x0)} × {abs(e.y - y0)}")

    def _release(self, e):
        if not self.start:
            return
        x0, y0 = self.start
        x1, y1 = min(x0, e.x), min(y0, e.y)
        w, h = abs(e.x - x0), abs(e.y - y0)
        self.start = None
        if w < MIN_SIZE or h < MIN_SIZE:
            self.canvas.itemconfigure(self.size_lbl, text=f"Too small (min {MIN_SIZE} px), drag again")
            return
        self._finish((x1 + self.vx, y1 + self.vy, w, h))

    def _finish(self, rect):
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()
        self.on_done(rect)

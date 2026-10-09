"""Small themed dialogs for presets: type a name, or confirm a delete."""
import tkinter as tk

from . import theme as T
from . import winapi


class _Base:
    def __init__(self, root, title, anchor):
        self.root = root
        w = self.win = tk.Toplevel(root)
        w.title(f"LazyK · {title}")
        w.configure(bg=T.BG, padx=18, pady=16)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        self.f = T.fonts(root)
        tk.Label(w, text=title, bg=T.BG, fg=T.FG, font=self.f["title"], anchor="w").pack(fill="x")
        self.anchor = anchor

    def _place(self):
        w = self.win
        w.update_idletasks()
        if self.anchor:
            x, top, bottom = self.anchor
            L, Tp, R, B = winapi.work_area(x, top)
            ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
            y = bottom + 8 if bottom + 8 + wh <= B else max(Tp, top - 8 - wh - 40)
            w.geometry(f"+{max(L, min(x, R - ww))}+{y}")
        w.lift()
        w.focus_force()


class NameDialog(_Base):
    """on_ok(name) is called with a non-empty name that is not in `taken`."""

    def __init__(self, root, title, initial, taken, on_ok, anchor=None):
        super().__init__(root, title, anchor)
        self.on_ok, self.taken = on_ok, {t.lower() for t in taken}
        w, f = self.win, self.f
        tk.Label(w, text="Name", bg=T.BG, fg=T.MUTED, font=f["small"], anchor="w").pack(fill="x", pady=(8, 2))
        row = tk.Frame(w, bg=T.FIELD, highlightthickness=1, highlightbackground=T.BORDER, highlightcolor=T.ACCENT)
        row.pack(fill="x")
        self.var = tk.StringVar(value=initial)
        self.entry = tk.Entry(row, textvariable=self.var, bg=T.FIELD, fg=T.FG, insertbackground=T.FG, relief="flat",
                              font=f["body"], width=30, highlightthickness=0, bd=0)
        self.entry.pack(fill="x", ipady=6, padx=8)
        self.msg = tk.Label(w, text="For example: Manga JP, Webtoon KR, My VN game", bg=T.BG, fg=T.MUTED,
                            font=f["small"], anchor="w")
        self.msg.pack(fill="x", pady=(6, 10))
        btns = tk.Frame(w, bg=T.BG)
        btns.pack(fill="x")
        T.FlatButton(btns, "Save", self._ok, "primary", font=f["bold"]).pack(side="right")
        T.FlatButton(btns, "Cancel", w.destroy, font=f["bold"]).pack(side="right", padx=8)
        self.entry.bind("<Return>", lambda e: self._ok())
        w.bind("<Escape>", lambda e: w.destroy())
        self._place()
        self.entry.focus_set()
        self.entry.select_range(0, "end")

    def _ok(self):
        name = " ".join(self.var.get().split())
        if not name:
            self.msg.configure(text="Type a name first", fg=T.ERR)
            return
        if name.lower() in self.taken:
            self.msg.configure(text="A preset with this name already exists", fg=T.ERR)
            return
        self.win.destroy()
        self.on_ok(name)


class ConfirmDialog(_Base):
    def __init__(self, root, title, text, button, on_ok, anchor=None):
        super().__init__(root, title, anchor)
        w, f = self.win, self.f
        tk.Label(w, text=text, bg=T.BG, fg=T.MUTED, font=f["body"], anchor="w", justify="left",
                 wraplength=320).pack(fill="x", pady=(6, 12))
        btns = tk.Frame(w, bg=T.BG)
        btns.pack(fill="x")
        T.FlatButton(btns, button, lambda: (w.destroy(), on_ok()), "primary", font=f["bold"]).pack(side="right")
        T.FlatButton(btns, "Cancel", w.destroy, font=f["bold"]).pack(side="right", padx=8)
        w.bind("<Escape>", lambda e: w.destroy())
        w.bind("<Return>", lambda e: (w.destroy(), on_ok()))
        self._place()

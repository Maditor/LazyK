"""Small dialog: press a key or a mouse button to assign it to 'Translate now'."""
import tkinter as tk

from . import theme as T
from . import winapi
from .hotkeys import pretty


class KeyDialog:
    def __init__(self, root, watcher, current, default, on_pick, anchor=None, title="Translate key"):
        self.watcher, self.on_pick, self.default = watcher, on_pick, default
        self.root = root
        self.done = False
        w = self.win = tk.Toplevel(root)
        w.title(f"LazyK · {title}")
        w.configure(bg=T.BG, padx=18, pady=16)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        f = T.fonts(root)
        tk.Label(w, text=title, bg=T.BG, fg=T.FG, font=f["title"], anchor="w").pack(fill="x")
        tk.Label(w, text=f"Now: {pretty(current)}", bg=T.BG, fg=T.MUTED, font=f["small"],
                 anchor="w").pack(fill="x", pady=(0, 10))
        self.box = tk.Label(w, text="Press a key or a mouse button…", bg=T.FIELD, fg=T.FG, font=f["bold"],
                            width=34, pady=18, highlightthickness=1, highlightbackground=T.ACCENT)
        self.box.pack(fill="x")
        tk.Label(w, text="Keys such as ~ or F8, with Ctrl / Alt / Shift if you like.\n"
                         "Mouse: side buttons (4 / 5) or the wheel click. Esc cancels.\n"
                         "A mouse button you pick here no longer reaches the browser.",
                 bg=T.BG, fg=T.MUTED, font=f["small"], justify="left", anchor="w").pack(fill="x", pady=(8, 10))
        row = tk.Frame(w, bg=T.BG)
        row.pack(fill="x")
        T.FlatButton(row, "Cancel", self._cancel, font=f["bold"]).pack(side="right")
        T.FlatButton(row, f"Reset ({pretty(default)})", lambda: self._finish(default), kind="ghost",
                     font=f["body"]).pack(side="right", padx=6)
        w.protocol("WM_DELETE_WINDOW", self._cancel)
        w.update_idletasks()
        if anchor:
            x, top, bottom = anchor
            L, Tp, R, B = winapi.work_area(x, top)
            ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
            y = bottom + 8 if bottom + 8 + wh <= B else max(Tp, top - 8 - wh - 40)
            w.geometry(f"+{max(L, min(x, R - ww))}+{y}")
        w.lift()
        # the global listener hears the key; the callback runs on its thread, so hop to Tk
        watcher.capture_next(lambda spec: root.after(0, lambda: self._finish(spec)))

    def _finish(self, spec):
        if self.done:
            return
        self.done = True
        self.watcher.cancel_capture()
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if spec:
            self.on_pick(spec)

    def _cancel(self):
        self._finish(None)

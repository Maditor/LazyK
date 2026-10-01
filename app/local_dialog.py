"""'Local OCR' window: which models are on this PC, download / remove them, GPU and manga-ocr switches."""
import os
import threading
import tkinter as tk

from . import local_ocr as L
from . import theme as T

ROWS = [
    ("builtin", "Japanese · Chinese · English", "PaddleOCR PP-OCRv6. Reads vertical and horizontal text."),
    ("ko", "Korean", "PaddleOCR PP-OCRv5 Korean, for manhwa and webtoons."),
    ("mocr", "manga-ocr", "Optional. Reads hand-drawn Japanese manga lettering more accurately."),
]


class LocalDialog:
    def __init__(self, root, settings, on_changed=None):
        self.root, self.s, self.on_changed = root, settings, on_changed
        self.f = T.fonts(root)
        w = self.win = tk.Toplevel(root)
        w.title("LazyK · Local OCR")
        w.configure(bg=T.BG)
        w.resizable(False, False)
        w.attributes("-topmost", True)
        try:
            from .config import icon_path
            from . import winapi
            self._icon = tk.PhotoImage(file=icon_path(on_dark=not winapi.system_light_theme()))
            w.iconphoto(False, self._icon)
        except Exception:
            pass
        self.cancel = threading.Event()
        self.busy = None  # pack being downloaded
        self.rows = {}
        self.gpu = tk.BooleanVar(value=bool(settings["local_gpu"]))
        self.mocr = tk.BooleanVar(value=bool(settings["local_manga_ocr"]))
        self._build()
        self._refresh()
        w.update_idletasks()
        x = (w.winfo_screenwidth() - w.winfo_width()) // 2
        y = max(8, (w.winfo_screenheight() - w.winfo_height()) // 3)
        w.geometry(f"+{x}+{y}")
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Escape>", lambda e: self.close())
        w.focus_force()

    # ------------------------------------------------------------ layout
    def _build(self):
        w, f = self.win, self.f
        head = tk.Frame(w, bg=T.BG, padx=22, pady=14)
        head.pack(fill="x")
        tk.Label(head, text="Local OCR", bg=T.BG, fg=T.FG, font=f["title"]).pack(anchor="w")
        tk.Label(head, text="Read the page on this PC: no API quota for scanning. "
                            "The AI or Google Translate then translates the text (pick the mode in the server menu).",
                 bg=T.BG, fg=T.MUTED, font=f["small"], wraplength=440, justify="left").pack(anchor="w", pady=(2, 0))

        card = tk.Frame(w, bg=T.PANEL, padx=16, pady=6, highlightthickness=1, highlightbackground=T.BORDER)
        card.pack(fill="x", padx=22)
        for i, (pack, title, sub) in enumerate(ROWS):
            if i:
                tk.Frame(card, bg=T.BORDER, height=1).pack(fill="x")
            row = tk.Frame(card, bg=T.PANEL, pady=10)
            row.pack(fill="x")
            right = tk.Frame(row, bg=T.PANEL)
            right.pack(side="right", anchor="n")
            top = tk.Frame(row, bg=T.PANEL)
            top.pack(fill="x", anchor="w")
            tk.Label(top, text=title, bg=T.PANEL, fg=T.FG, font=f["bold"]).pack(side="left")
            tk.Label(top, text=L.PACKS[pack]["size"], bg=T.PANEL, fg=T.MUTED, font=f["small"]).pack(side="left", padx=6)
            tk.Label(row, text=sub, bg=T.PANEL, fg=T.MUTED, font=f["small"], wraplength=300,
                     justify="left").pack(anchor="w")
            bar = tk.Canvas(row, width=300, height=4, bg=T.FIELD, highlightthickness=0, bd=0)
            note = tk.Label(row, text="", bg=T.PANEL, fg=T.MUTED, font=f["small"], wraplength=300, justify="left")
            state = tk.Label(right, text="", bg=T.PANEL, font=f["small"])
            btn = T.FlatButton(right, "Download", lambda p=pack: self._download(p), "secondary",
                               font=f["bold"], padx=12, pady=4)
            link = tk.Label(right, text="Remove", bg=T.PANEL, fg=T.MUTED, font=f["small"], cursor="hand2")
            link.bind("<ButtonRelease-1>", lambda e, p=pack: self._remove(p))
            self.rows[pack] = {"state": state, "btn": btn, "link": link, "bar": bar, "note": note}

        opts = tk.Frame(w, bg=T.BG, padx=22, pady=8)
        opts.pack(fill="x")
        gpu = L.gpu_name()
        for var, title, sub, cmd in (
                (self.gpu, "Use the graphics card",
                 f"{gpu} found: much faster" if gpu else "No GPU runtime found: runs on the CPU",
                 lambda: self.s.update(local_gpu=bool(self.gpu.get()))),
                (self.mocr, "Read Japanese with manga-ocr", "When it is downloaded. Slower, more accurate.",
                 lambda: self.s.update(local_manga_ocr=bool(self.mocr.get())))):
            r = tk.Frame(opts, bg=T.BG, pady=3)
            r.pack(fill="x")
            T.Switch(r, var, command=cmd).pack(side="right")
            tk.Label(r, text=title, bg=T.BG, fg=T.FG, font=f["bold"]).pack(anchor="w")
            tk.Label(r, text=sub, bg=T.BG, fg=T.MUTED, font=f["small"]).pack(anchor="w")
        tk.Label(opts, text="Downloads are kept in " + L.models_dir(), bg=T.BG, fg=T.MUTED, font=f["small"],
                 wraplength=440, justify="left").pack(anchor="w", pady=(6, 0))

        foot = tk.Frame(w, bg=T.BG, padx=22, pady=12)
        foot.pack(fill="x")
        self.use_btn = T.FlatButton(foot, "", self._toggle_use, "primary", font=f["bold"])
        self.use_btn.pack(side="right")
        T.FlatButton(foot, "Close", self.close, "secondary", font=f["bold"]).pack(side="right", padx=8)

    def _refresh(self):
        for pack, r in self.rows.items():
            ready = L.pack_ready(pack)
            loading = self.busy == pack
            r["btn"].pack_forget()
            r["link"].pack_forget()
            r["state"].pack_forget()
            if loading:
                r["bar"].pack(anchor="w", pady=(6, 0))
                r["note"].pack(anchor="w")
                r["btn"].configure(text="Cancel")
                r["btn"].command = self.cancel.set
                r["btn"].pack()
            else:
                r["bar"].pack_forget()
                r["note"].pack_forget()
                if ready:
                    r["state"].configure(text="✓ Ready", fg=T.OK)
                    r["state"].pack(anchor="e")
                    if pack != "builtin":
                        r["link"].pack(anchor="e", pady=(2, 0))
                else:
                    r["btn"].configure(text="Download")
                    r["btn"].command = lambda p=pack: self._download(p)
                    r["btn"].set_enabled(self.busy is None)
                    r["btn"].pack()
        local = self.s["ocr_engine"] == "local"
        self.use_btn.configure(text="Use AI to read instead" if local else "Use local OCR")

    # ------------------------------------------------------------ actions
    def _progress(self, pack, frac, text):
        r = self.rows[pack]
        if not r["bar"].winfo_exists():
            return
        r["bar"].update_idletasks()
        wdt = max(1, r["bar"].winfo_width())
        r["bar"].delete("all")
        r["bar"].create_rectangle(0, 0, int(wdt * frac), 4, fill=T.ACCENT, width=0)
        r["note"].configure(text=f"{int(frac * 100)}% · {text}", fg=T.MUTED)

    def _download(self, pack):
        if self.busy:
            return
        self.busy = pack
        self.cancel.clear()
        self._refresh()

        def later(fn):
            try:
                self.win.after(0, fn)
            except (tk.TclError, RuntimeError):
                pass  # window closed meanwhile

        def run():
            err = None
            try:
                L.download_pack(pack, lambda fr, t: later(lambda: self._progress(pack, fr, t)), self.cancel)
            except Exception as e:
                err = "Cancelled" if self.cancel.is_set() else str(e)
            later(lambda: self._done(pack, err))
        threading.Thread(target=run, daemon=True).start()

    def _done(self, pack, err):
        if not self.win.winfo_exists():
            return
        self.busy = None
        self._refresh()
        if err:
            r = self.rows[pack]
            r["note"].configure(text=("✕ " + err)[:160], fg=T.ERR)
            r["note"].pack(anchor="w")
        elif self.on_changed:
            self.on_changed()

    def _remove(self, pack):
        for name in L.PACKS[pack]["files"]:
            try:
                os.remove(L.path(name))
            except OSError:
                pass
        L.ENGINE.reset()
        self._refresh()

    def _toggle_use(self):
        self.s.update(ocr_engine="ai" if self.s["ocr_engine"] == "local" else "local")
        self._refresh()
        if self.on_changed:
            self.on_changed()

    def close(self):
        self.cancel.set()
        self.win.destroy()

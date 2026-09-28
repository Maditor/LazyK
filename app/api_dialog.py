"""'API & Models' window: one tab per server with its own key(s), model list and a connection test."""
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

from . import theme as T
from .api import KEY_URLS, SERVER_NAMES, SERVERS, test_connection

FIELDS = {
    "gemini": [("gemini_api_key", "API key", True)],
    "cloudflare": [("cf_account_id", "Account ID", False), ("cf_api_token", "API token", True)],
}
HINTS = {
    "gemini": "Free key from Google AI Studio. Quotas are per model, so auto-switch keeps you going.",
    "cloudflare": "API token with the “Workers AI” permission, plus your account ID.",
}


def short_model(name: str) -> str:
    """'gemini-3.5-flash-lite' -> '3.5 Flash Lite', '@cf/google/gemma-4-26b-a4b-it' -> 'gemma-4-26b'."""
    n = str(name or "")
    if n.startswith("gemini-"):
        return " ".join(p.capitalize() if not p[0].isdigit() else p for p in n[7:].split("-"))
    n = n.rsplit("/", 1)[-1]
    return n.replace("-a4b-it", "").replace("-it", "")


class ApiDialog:
    def __init__(self, root, settings, on_saved=None, tab=None):
        self.root = root
        self.s = settings
        self.on_saved = on_saved
        T.setup_ttk(root)
        self.f = T.fonts(root)
        w = self.win = tk.Toplevel(root)
        w.title("LazyK · API & Models")
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

        self.vars = {k: tk.StringVar(value=str(settings[k] or "")) for srv in SERVERS for k, _, _ in FIELDS[srv]}
        self.model_vars = {srv: tk.StringVar(value=settings[f"{srv}_model"]) for srv in SERVERS}
        self.model_lists = {srv: list(settings[f"{srv}_models"] or []) for srv in SERVERS}
        self.active = tk.StringVar(value=settings["server"])
        self.auto_model = tk.BooleanVar(value=bool(settings["auto_switch_model"]))
        self.auto_server = tk.BooleanVar(value=bool(settings["auto_switch_server"]))
        self.tab = tab or settings["server"]

        self._build()
        self._show_tab(self.tab)
        w.update_idletasks()
        x = (w.winfo_screenwidth() - w.winfo_width()) // 2
        y = max(8, min((w.winfo_screenheight() - w.winfo_height()) // 3, w.winfo_screenheight() - w.winfo_height() - 48))
        w.geometry(f"+{x}+{y}")
        w.bind("<Escape>", lambda _e: self.win.destroy())
        w.focus_force()

    # ------------------------------------------------------------ layout
    def _build(self):
        w, f = self.win, self.f
        head = tk.Frame(w, bg=T.BG, padx=22, pady=14)
        head.pack(fill="x")
        tk.Label(head, text="API & Models", bg=T.BG, fg=T.FG, font=f["title"]).pack(anchor="w")
        tk.Label(head, text="Keys are stored only in settings.json next to the app.",
                 bg=T.BG, fg=T.MUTED, font=f["small"]).pack(anchor="w", pady=(2, 0))

        # Segmented tabs
        seg = tk.Frame(w, bg=T.FIELD, padx=3, pady=3)
        seg.pack(fill="x", padx=22)
        self.tab_btns = {}
        for srv in SERVERS:
            b = tk.Label(seg, text=SERVER_NAMES[srv], bg=T.FIELD, fg=T.MUTED, font=f["bold"],
                         pady=7, cursor="hand2")
            b.pack(side="left", fill="x", expand=True)
            b.bind("<ButtonRelease-1>", lambda e, s=srv: self._show_tab(s))
            self.tab_btns[srv] = b

        self.card = tk.Frame(w, bg=T.PANEL, padx=18, pady=12, highlightthickness=1,
                             highlightbackground=T.BORDER)
        self.card.pack(fill="x", padx=22, pady=(12, 0))

        # Behaviour
        beh = tk.Frame(w, bg=T.BG, padx=22, pady=8)
        beh.pack(fill="x")
        for var, title, sub in (
                (self.auto_model, "Switch model when busy", "503 / out of quota → next model in the list"),
                (self.auto_server, "Switch server when one runs out", "e.g. Cloudflare daily quota → Gemini")):
            row = tk.Frame(beh, bg=T.BG, pady=3)
            row.pack(fill="x")
            T.Switch(row, var).pack(side="right")
            tk.Label(row, text=title, bg=T.BG, fg=T.FG, font=f["bold"]).pack(anchor="w")
            tk.Label(row, text=sub, bg=T.BG, fg=T.MUTED, font=f["small"]).pack(anchor="w")

        foot = tk.Frame(w, bg=T.BG, padx=22, pady=12)
        foot.pack(fill="x")
        tk.Frame(w, bg=T.BORDER, height=1).place(in_=foot, relx=0, rely=0, relwidth=1)
        T.FlatButton(foot, "Save", self._save, "primary", font=f["bold"]).pack(side="right")
        T.FlatButton(foot, "Cancel", self.win.destroy, "secondary", font=f["bold"]).pack(side="right", padx=8)

    def _show_tab(self, srv):
        self.tab = srv
        for k, b in self.tab_btns.items():
            on = k == srv
            b.configure(bg=T.HOVER if on else T.FIELD, fg=T.FG if on else T.MUTED)
        for child in self.card.winfo_children():
            child.destroy()
        f, c = self.f, self.card

        top = tk.Frame(c, bg=T.PANEL)
        top.pack(fill="x")
        tk.Label(top, text=SERVER_NAMES[srv], bg=T.PANEL, fg=T.FG, font=f["h2"]).pack(side="left")
        self.badge = tk.Label(top, bg=T.PANEL, font=f["small"], padx=8, pady=1)
        self.badge.pack(side="left", padx=8)
        self.use_btn = T.FlatButton(top, "Use this server", lambda: self._set_active(srv), "secondary",
                                    font=f["small"], padx=10, pady=3)
        self.use_btn.pack(side="right")
        self._refresh_badge()
        tk.Label(c, text=HINTS[srv], bg=T.PANEL, fg=T.MUTED, font=f["small"], wraplength=420,
                 justify="left").pack(anchor="w", pady=(4, 10))

        for key, label, secret in FIELDS[srv]:
            tk.Label(c, text=label, bg=T.PANEL, fg=T.MUTED, font=f["small"]).pack(anchor="w")
            row = tk.Frame(c, bg=T.FIELD, highlightthickness=1, highlightbackground=T.BORDER,
                           highlightcolor=T.ACCENT)
            row.pack(fill="x", pady=(2, 10))
            e = tk.Entry(row, textvariable=self.vars[key], bg=T.FIELD, fg=T.FG, insertbackground=T.FG,
                         relief="flat", font=f["mono"], show="•" if secret else "", width=48,
                         highlightthickness=0, bd=0)
            e.pack(side="left", fill="x", expand=True, ipady=6, padx=(8, 0))
            if secret:
                eye = tk.Label(row, text="Show", bg=T.FIELD, fg=T.MUTED, font=f["small"], padx=8, cursor="hand2")
                eye.pack(side="right")
                eye.bind("<ButtonRelease-1>", lambda ev, en=e, lb=eye: (
                    en.configure(show="" if en.cget("show") else "•"),
                    lb.configure(text="Hide" if not en.cget("show") else "Show")))
        link = tk.Label(c, text="Get a key ↗", bg=T.PANEL, fg=T.ACCENT, font=f["small"], cursor="hand2")
        link.pack(anchor="w", pady=(0, 10))
        link.bind("<ButtonRelease-1>", lambda e: webbrowser.open(KEY_URLS[srv]))

        tk.Label(c, text="Model", bg=T.PANEL, fg=T.MUTED, font=f["small"]).pack(anchor="w")
        mrow = tk.Frame(c, bg=T.PANEL)
        mrow.pack(fill="x", pady=(2, 4))
        cb = ttk.Combobox(mrow, textvariable=self.model_vars[srv], values=self.model_lists[srv],
                          style="Dark.TCombobox", font=f["mono"])
        cb.pack(side="left", fill="x", expand=True)
        tk.Label(c, text="Pick from the list or type any model name. Auto-switch walks this list in order.",
                 bg=T.PANEL, fg=T.MUTED, font=f["small"]).pack(anchor="w")

        tk.Label(c, text="Model list (one per line)", bg=T.PANEL, fg=T.MUTED, font=f["small"]).pack(anchor="w", pady=(10, 0))
        self.list_text = tk.Text(c, height=2, bg=T.FIELD, fg=T.FG, insertbackground=T.FG, relief="flat",
                                 font=f["mono"], highlightthickness=1, highlightbackground=T.BORDER,
                                 highlightcolor=T.ACCENT, padx=8, pady=6)
        self.list_text.insert("1.0", "\n".join(self.model_lists[srv]))
        self.list_text.pack(fill="x", pady=(2, 10))
        self.list_text.bind("<FocusOut>", lambda e, s=srv, box=cb: self._read_list(s, box))

        test = tk.Frame(c, bg=T.PANEL)
        test.pack(fill="x")
        self.test_btn = T.FlatButton(test, "Test connection", lambda: self._test(srv), "secondary",
                                     font=f["bold"], padx=12, pady=5)
        self.test_btn.pack(side="left")
        self.test_lbl = tk.Label(test, text="", bg=T.PANEL, fg=T.MUTED, font=f["small"], wraplength=300,
                                 justify="left")
        self.test_lbl.pack(side="left", padx=10)

    def _tmp_settings(self):
        from .config import Settings
        tmp = Settings.__new__(Settings)  # in-memory copy, nothing saved
        tmp.data = dict(self.s.data)
        tmp.data.update(self._collect())
        tmp.save = lambda: None
        tmp.path = None
        tmp._lock = threading.Lock()
        return tmp

    def _read_list(self, srv, cb=None):
        lines = [l.strip() for l in self.list_text.get("1.0", "end").splitlines() if l.strip()]
        self.model_lists[srv] = lines
        if cb is not None:
            cb.configure(values=lines)

    def _refresh_badge(self):
        on = self.active.get() == self.tab
        self.badge.configure(text="● ACTIVE" if on else "not active", fg=T.OK if on else T.MUTED,
                             bg="#16301f" if on else T.FIELD)
        self.use_btn.set_enabled(not on)

    def _set_active(self, srv):
        self.active.set(srv)
        self._refresh_badge()

    # ------------------------------------------------------------ actions
    def _collect(self):
        if hasattr(self, "list_text") and self.list_text.winfo_exists():
            self._read_list(self.tab)
        data = {k: v.get().strip() for k, v in self.vars.items()}
        for srv in SERVERS:
            model = self.model_vars[srv].get().strip()
            lst = [m for m in self.model_lists[srv] if m]
            if model and model not in lst:
                lst.insert(0, model)
            data[f"{srv}_models"] = lst
            data[f"{srv}_model"] = model or (lst[0] if lst else "")
        data["server"] = self.active.get()
        data["auto_switch_model"] = bool(self.auto_model.get())
        data["auto_switch_server"] = bool(self.auto_server.get())
        return data

    def _test(self, srv):
        tmp = self._tmp_settings()
        self.test_btn.set_enabled(False)
        self.test_lbl.configure(text="Testing…", fg=T.MUTED)

        def run():
            ok, msg, secs = test_connection(tmp, srv)
            self.win.after(0, lambda: self._test_done(ok, msg, secs))
        threading.Thread(target=run, daemon=True).start()

    def _test_done(self, ok, msg, secs):
        if not self.win.winfo_exists():
            return
        self.test_btn.set_enabled(True)
        self.test_lbl.configure(text=(f"✓ {msg} · {secs:.1f}s" if ok else f"✕ {msg}"), fg=T.OK if ok else T.ERR)

    def _save(self):
        data = self._collect()
        self.s.update(**data)
        self.win.destroy()
        if self.on_saved:
            self.on_saved()

"""Shared dark theme (flat, Japo-style) for all LazyK windows."""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

BG = "#131418"        # window background
PANEL = "#1b1d23"     # cards / toolbar
FIELD = "#23262e"     # inputs, chips
HOVER = "#2d313b"
BORDER = "#2c2f38"
FG = "#e8e9ee"
MUTED = "#8b91a0"
ACCENT = "#7c6cff"
ACCENT_HOVER = "#8f81ff"
OK = "#22c55e"
WARN = "#f59e0b"
ERR = "#ef4444"

UI_FONT = "Segoe UI"


def fonts(root):
    fams = set(tkfont.families(root))
    fam = UI_FONT if UI_FONT in fams else ("Segoe UI Variable" if "Segoe UI Variable" in fams else "TkDefaultFont")
    return {
        "body": tkfont.Font(root, family=fam, size=9),
        "bold": tkfont.Font(root, family=fam, size=9, weight="bold"),
        "title": tkfont.Font(root, family=fam, size=13, weight="bold"),
        "h2": tkfont.Font(root, family=fam, size=10, weight="bold"),
        "small": tkfont.Font(root, family=fam, size=8),
        "mono": tkfont.Font(root, family="Consolas" if "Consolas" in fams else "TkFixedFont", size=9),
    }


def setup_ttk(root):
    """Dark style for ttk widgets (Combobox, Scrollbar)."""
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure("Dark.TCombobox", fieldbackground=FIELD, background=FIELD, foreground=FG,
                 arrowcolor=FG, bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD,
                 selectbackground=FIELD, selectforeground=FG, padding=5)
    st.map("Dark.TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
           background=[("active", HOVER)])
    st.configure("Dark.Vertical.TScrollbar", background=FIELD, troughcolor=PANEL, bordercolor=PANEL,
                 arrowcolor=MUTED, lightcolor=FIELD, darkcolor=FIELD)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "white")
    root.option_add("*TCombobox*Listbox.relief", "flat")


class FlatButton(tk.Label):
    """Flat button with hover; kind = primary | secondary | ghost."""

    def __init__(self, parent, text, command, kind="secondary", font=None, padx=14, pady=6, **kw):
        colors = {"primary": (ACCENT, ACCENT_HOVER, "white"),
                  "secondary": (FIELD, HOVER, FG),
                  "ghost": (parent["bg"], HOVER, MUTED)}[kind]
        self._bg, self._hover, fg = colors
        super().__init__(parent, text=text, bg=self._bg, fg=fg, font=font, padx=padx, pady=pady,
                         cursor="hand2", **kw)
        self.command = command
        self.enabled = True
        self.bind("<Enter>", lambda e: self.enabled and self.configure(bg=self._hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg))
        self.bind("<ButtonRelease-1>", lambda e: self.enabled and self.command and self.command())

    def set_enabled(self, on):
        self.enabled = on
        self.configure(fg=(FG if on else MUTED), cursor="hand2" if on else "arrow")


class Switch(tk.Canvas):
    """Small iOS-like toggle bound to a BooleanVar."""

    def __init__(self, parent, variable, command=None):
        super().__init__(parent, width=34, height=18, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self.var = variable
        self.command = command
        self.bind("<ButtonRelease-1>", self._toggle)
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _toggle(self, _e=None):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        col = ACCENT if on else "#3a3e49"
        self.create_oval(1, 1, 17, 17, fill=col, outline=col)
        self.create_oval(17, 1, 33, 17, fill=col, outline=col)
        self.create_rectangle(9, 1, 25, 17, fill=col, outline=col)
        x = 25 if on else 9
        self.create_oval(x - 6, 3, x + 6, 15, fill="white", outline="white")

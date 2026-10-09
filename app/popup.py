"""Dark dropdown menus for the toolbar, with cascading submenus.

* Opens below its button, or above it when the toolbar sits at the bottom of the screen.
* "sub" rows show a › arrow and open a child menu beside the row (right, or left when there is no room).
* A persistent menu (Settings) stays open while you change things: every pick updates the check marks
  and values in place. It closes on its button again, Esc, or a click outside.
"""
import tkinter as tk

from . import theme as T
from . import winapi


class PopupMenu:
    """builder() returns the rows:
        ("header", text) | ("sep",) | ("col",) new column
        ("item", text, checked, callback, sub_text[, mode])   mode: None | "keep" | "close"
        ("sub", text, value_text, child_builder)
        ("entry", label, value, on_submit(str), suffix)       small number field
    anchor: (x, top, bottom) of the button, or ("side", row_widget) for a child menu.
    """

    def __init__(self, root, builder, anchor, fonts, on_close=None, parent=None, persistent=False):
        self.root, self.fonts = root, fonts
        self.builder = builder if callable(builder) else (lambda items=builder: items)
        self.on_close, self.parent, self.persistent = on_close, parent, persistent
        self.child, self._open_row, self._open_name = None, None, None
        self.subs = {}
        self.closed = False
        w = self.win = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=T.BORDER)
        self._render()
        self._place(anchor)
        w.bind("<Escape>", lambda e: self._top().close())
        w.bind("<FocusOut>", lambda e: self.win.after(150, self._maybe_close))
        w.after(30, w.focus_force)

    # ------------------------------------------------------------ building
    def _render(self):
        for c in self.win.winfo_children():
            c.destroy()
        self.subs = {}
        f = self.fonts
        outer = tk.Frame(self.win, bg=T.PANEL, padx=4, pady=4)
        outer.pack(padx=1, pady=1)
        body = tk.Frame(outer, bg=T.PANEL)
        body.pack(side="left", anchor="n")
        for it in self.builder():
            kind = it[0]
            if kind == "col":
                tk.Frame(outer, bg=T.BORDER, width=1).pack(side="left", fill="y", padx=6, pady=4)
                body = tk.Frame(outer, bg=T.PANEL)
                body.pack(side="left", anchor="n")
            elif kind == "note":  # small muted line (credit / link); a click runs it[2] and closes
                _, text, cb = (list(it) + [None])[:3]
                lab = tk.Label(body, text=text, bg=T.PANEL, fg=T.MUTED, font=f["small"], anchor="w", padx=10, pady=3,
                               cursor="hand2" if cb else "")
                lab.pack(fill="x")
                if cb:
                    lab.bind("<Enter>", lambda e, w=lab: w.configure(fg=T.ACCENT))
                    lab.bind("<Leave>", lambda e, w=lab: w.configure(fg=T.MUTED))
                    lab.bind("<ButtonRelease-1>", lambda e, c=cb: (self._top().close(), c()))
            elif kind == "header":
                tk.Label(body, text=it[1].upper(), bg=T.PANEL, fg=T.MUTED, font=f["small"],
                         anchor="w", padx=10, pady=4).pack(fill="x")
            elif kind == "sep":
                tk.Frame(body, bg=T.BORDER, height=1).pack(fill="x", pady=4, padx=6)
            elif kind == "sub":
                _, text, value, child_builder = it
                row = self._row(body, text, False, value,
                                lambda r, n=text, b=child_builder: self._open_sub(r, n, b), arrow=True)
                self.subs[text] = (row, child_builder)
            elif kind == "entry":
                self._entry(body, *it[1:])
            else:
                _, text, checked, cb, sub, mode = (list(it) + [None, None])[:6]
                self._row(body, text, checked, sub, lambda r, c=cb, m=mode: self._pick(c, m))
        # keep the open submenu's row highlighted after a rebuild
        if self._open_name in self.subs and self.child is not None:
            self._open_row = self.subs[self._open_name][0]
            for x in self._open_row.widgets:
                x.configure(bg=T.HOVER)

    def _row(self, body, text, checked, sub, action, arrow=False):
        f = self.fonts
        row = tk.Frame(body, bg=T.PANEL, cursor="hand2")
        row.pack(fill="x")
        mark = tk.Label(row, text="✓" if checked else "", width=2, bg=T.PANEL, fg=T.ACCENT, font=f["bold"])
        mark.pack(side="left", padx=(6, 0))
        lbl = tk.Label(row, text=text, bg=T.PANEL, fg=T.FG, font=f["bold" if checked else "body"],
                       anchor="w", padx=4, pady=6)
        lbl.pack(side="left", fill="x", expand=True)
        widgets = [row, mark, lbl]
        if arrow:
            a = tk.Label(row, text="›", bg=T.PANEL, fg=T.MUTED, font=f["h2"], padx=10)
            a.pack(side="right")
            widgets.append(a)
        if sub:
            s = tk.Label(row, text=sub, bg=T.PANEL, fg=T.MUTED, font=f["small"], padx=6 if arrow else 10)
            s.pack(side="right")
            widgets.append(s)
        row.widgets = widgets
        for wd in widgets:
            wd.bind("<Enter>", lambda e, ws=widgets: [x.configure(bg=T.HOVER) for x in ws])
            wd.bind("<Leave>", lambda e, r=row: self._unhover(r))
            wd.bind("<ButtonRelease-1>", lambda e, r=row: action(r))
        return row

    def _entry(self, body, label, value, on_submit, suffix=""):
        f = self.fonts
        row = tk.Frame(body, bg=T.PANEL)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="", width=2, bg=T.PANEL).pack(side="left", padx=(6, 0))
        tk.Label(row, text=label, bg=T.PANEL, fg=T.FG, font=f["body"], anchor="w", padx=4).pack(side="left")
        if suffix:
            tk.Label(row, text=suffix, bg=T.PANEL, fg=T.MUTED, font=f["small"], padx=8).pack(side="right")
        var = tk.StringVar(value=str(value))
        box = tk.Frame(row, bg=T.FIELD, highlightthickness=1, highlightbackground=T.BORDER,
                       highlightcolor=T.ACCENT)
        box.pack(side="right")
        e = tk.Entry(box, textvariable=var, width=4, justify="center", bg=T.FIELD, fg=T.FG,
                     insertbackground=T.FG, relief="flat", bd=0, highlightthickness=0, font=f["bold"])
        e.pack(ipady=3, padx=4)

        def submit(_e=None):
            if var.get().strip() != str(value):
                on_submit(var.get().strip())
                # rebuild after this event finishes (the field itself is replaced)
                self.win.after(1, self._top().refresh)
        e.bind("<Return>", submit)
        e.bind("<KP_Enter>", submit)
        e.bind("<FocusOut>", submit)
        # scrolling the mouse wheel over the field nudges the value
        e.bind("<MouseWheel>", lambda ev: (var.set(str(_int(var.get(), value) + (1 if ev.delta > 0 else -1))),
                                           submit()))

    def _unhover(self, row):
        if self._open_row is row:
            return  # keep the row of the open submenu highlighted
        for x in row.widgets:
            x.configure(bg=T.PANEL)

    # ------------------------------------------------------------ placement
    def _place(self, anchor):
        w = self.win
        w.update_idletasks()
        mw, mh = w.winfo_reqwidth(), w.winfo_reqheight()
        if anchor[0] == "side":
            row = anchor[1]
            rx, ry = row.winfo_rootx(), row.winfo_rooty()
            pw = self.parent.win
            L, Tp, R, B = winapi.work_area(rx, ry)
            right = pw.winfo_rootx() + pw.winfo_width() + 2
            x = right if right + mw <= R else pw.winfo_rootx() - mw - 2   # flip to the left side
            # never lower than the parent menu (it may sit right above the toolbar) nor off screen
            limit = min(B, pw.winfo_rooty() + pw.winfo_height())
            y = max(Tp, min(ry - 5, limit - mh))
        else:
            x, top, bottom = anchor
            L, Tp, R, B = winapi.work_area(x, top)
            if bottom + 6 + mh <= B:
                y = bottom + 6                       # room below the toolbar
            elif top - 6 - mh >= Tp:
                y = top - 6 - mh                     # toolbar near the bottom: open upwards
            else:
                y = max(Tp, B - mh)
            x = max(L, min(x, R - mw))
        w.geometry(f"+{int(x)}+{int(y)}")

    def _keep_on_screen(self):
        """After a rebuild the size may change: nudge the window back inside the work area."""
        w = self.win
        w.update_idletasks()
        x, y, mw, mh = w.winfo_x(), w.winfo_y(), w.winfo_reqwidth(), w.winfo_reqheight()
        L, Tp, R, B = winapi.work_area(x, y)
        if self.parent is not None:
            pw = self.parent.win
            B = min(B, pw.winfo_rooty() + pw.winfo_height())
        nx, ny = max(L, min(x, R - mw)), max(Tp, min(y, B - mh))
        if (nx, ny) != (x, y):
            w.geometry(f"+{nx}+{ny}")

    # ------------------------------------------------------------ submenus
    def _open_sub(self, row, name, builder):
        if self.child and self._open_name == name:
            self.child.close(silent=True)    # second click on the same row closes it
            return
        if self.child:
            self.child.close(silent=True)
        old, self._open_row, self._open_name = self._open_row, row, name
        if old is not None and old is not row:
            self._unhover(old)
        for x in row.widgets:
            x.configure(bg=T.HOVER)
        self.child = PopupMenu(self.root, builder, ("side", row), self.fonts, parent=self,
                               persistent=self.persistent)

    def open_sub_by_name(self, name):
        if name in self.subs:
            row, builder = self.subs[name]
            self._open_sub(row, name, builder)

    def refresh(self):
        """Rebuild this menu and its open submenu in place (same position) after a change."""
        if self.closed:
            return
        try:
            had_focus = self._owns_focus(self.win.focus_get()) and self.child is None
        except (tk.TclError, KeyError):
            had_focus = False
        self._render()
        self._keep_on_screen()
        if had_focus:
            self.win.focus_force()  # keep focus in the menu so it does not close itself
        if self.child is not None:
            self.child.refresh()

    # ------------------------------------------------------------ closing
    def _top(self):
        m = self
        while m.parent is not None:
            m = m.parent
        return m

    def _owns_focus(self, widget):
        """Is keyboard focus inside this menu or one of its submenus?"""
        m = self
        while m is not None:
            try:
                if widget is not None and str(widget).startswith(str(m.win)):
                    return True
            except tk.TclError:
                pass
            m = m.child
        return False

    def _maybe_close(self):
        if self.closed:
            return
        try:
            focus = self.win.focus_get()
        except (tk.TclError, KeyError):
            focus = None
        top = self._top()
        if focus is None or not top._owns_focus(focus):
            top.close()              # clicked outside every menu level

    def _pick(self, cb, mode=None):
        top = self._top()
        stay = mode == "keep" or (top.persistent and mode != "close")
        if stay:
            if cb:
                cb()
            top.refresh()            # new check marks / values, same place
            return
        top.close()
        if cb:
            cb()

    def close(self, silent=False):
        if self.closed:
            return
        self.closed = True
        if self.child:
            self.child.close(silent=True)
            self.child = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self.parent is not None and self.parent.child is self:
            p = self.parent
            p.child = None
            row, p._open_row, p._open_name = p._open_row, None, None
            if row is not None:
                try:
                    p._unhover(row)
                except tk.TclError:
                    pass
        cb, self.on_close = self.on_close, None
        if cb and not silent:
            cb()


def _int(text, default):
    try:
        return int(float(str(text).strip()))
    except ValueError:
        return int(default)

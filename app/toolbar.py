"""Floating always-on-top toolbar: shows the tool is running, quick toggles, font picker."""
import logging
import tkinter as tk
import tkinter.font as tkfont

from . import theme, winapi
from .api import SERVER_NAMES, SERVER_SHORT
from .api_dialog import ApiDialog, short_model
from .hotkeys import pretty
from .overlay import _ClickThroughWindow, rounded_rect
from .popup import PopupMenu

log = logging.getLogger(__name__)

# Flat dark theme shared with the dialogs
BG = theme.PANEL
BORDER = theme.BORDER
CHIP = theme.FIELD
HOVER = theme.HOVER
FG = theme.FG
MUTED = theme.MUTED
ACCENT = theme.ACCENT
STATE_COLORS = {"idle": "#22c55e", "ready": "#22c55e", "scanning": "#3b82f6", "translating": "#a855f7",
                "error": "#ef4444", "paused": "#9ca3af", "info": "#f59e0b", "hotkey": "#38bdf8"}

ICON_FONT = "Segoe MDL2 Assets"  # ships with Windows 10/11
GLYPHS = {"translate": "", "pause": "", "play": "", "eye": "",
          "eye_off": "", "close": "", "left": "", "right": "", "font": "",
          "crop": "\uE7A8", "gear": "\uE713", "down": "\uE70D"}
FALLBACK = {"translate": "↻", "pause": "❚❚", "play": "▶", "eye": "◉", "eye_off": "○",
            "close": "✕", "left": "‹", "right": "›", "font": "Aa", "crop": "⛶", "gear": "⚙", "down": "▾"}

LANG_CYCLE = ["auto", "ja", "ko", "zh", "en"]
LANG_LABEL = {"auto": "Auto", "ja": "JA", "ko": "KO", "zh": "ZH", "en": "EN"}


class Tip(_ClickThroughWindow):
    """Tooltip that never steals focus."""

    def __init__(self, root):
        super().__init__(root)
        self.font = tkfont.Font(family="Segoe UI", size=9)

    def show_at(self, text, x, y):
        pad_x, pad_y = 8, 4
        w = self.font.measure(text) + 2 * pad_x
        h = self.font.metrics("linespace") + 2 * pad_y
        c = self.canvas
        c.delete("all")
        rounded_rect(c, 0, 0, w - 1, h - 1, 6, fill="#0d0e11", outline="")
        c.create_text(pad_x, h / 2, text=text, anchor="w", font=self.font, fill=FG)
        self.place(x, y, w, h)
        self.show()

    def show_near(self, text, anchor):
        """Below the widget, or above it when the toolbar sits at the bottom of the screen."""
        x, top, bottom = anchor
        h = self.font.metrics("linespace") + 8
        w = self.font.measure(text) + 16
        L, T, R, B = winapi.work_area(x, top)
        y = bottom + 6 if bottom + 6 + h <= B else top - 6 - h
        self.show_at(text, max(L, min(x, R - w)), y)


class Toolbar:
    def __init__(self, root, app):
        self.root = root
        self.app = app
        self.s = app.s
        self.hwnd = None
        self.icons = ICON_FONT in set(tkfont.families(root))
        self.f_ui = tkfont.Font(family="Segoe UI", size=9)
        self.f_ui_b = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.f_icon = tkfont.Font(family=ICON_FONT, size=10) if self.icons else self.f_ui_b
        self.tip = Tip(root)
        self._tip_job = None
        self._status_job = None
        self._drag = None
        self.picker = None
        self.menu = None
        self.fonts = theme.fonts(root)
        self.f_small = tkfont.Font(family="Segoe UI", size=8)

        self.hidden = False  # hidden with the toolbar key; never saved, so a restart always shows it
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BORDER)
        self.frame = tk.Frame(self.win, bg=BG, padx=6, pady=4)
        self.frame.pack(padx=1, pady=1)
        self._build()
        self.refresh()
        self.set_collapsed(bool(self.s["toolbar_collapsed"]), save=False)

    # ------------------------------------------------------------ widgets
    def _glyph(self, name):
        return GLYPHS[name] if self.icons else FALLBACK[name]

    def _button(self, parent, text, command, tip, icon=False, chip=False, width=None, keep_focus=False):
        lbl = tk.Label(parent, text=text, bg=CHIP if chip else BG, fg=FG, cursor="hand2",
                       font=self.f_icon if icon else self.f_ui_b, padx=7 if chip else 5, pady=2)
        if width:
            lbl.configure(width=width)
        base = CHIP if chip else BG
        lbl.bind("<Enter>", lambda e: (lbl.configure(bg=HOVER), self._tip_later(lbl, lbl.tip_text)))
        lbl.bind("<Leave>", lambda e: (lbl.configure(bg=base), self._tip_cancel()))
        def click(_e):
            self._tip_cancel()
            if not keep_focus:
                self.app.restore_focus()  # the browser keeps the keyboard (Space / PageDown)
            command()
        lbl.bind("<ButtonRelease-1>", click)
        lbl.tip_text = tip
        return lbl

    def _sep(self, parent):
        tk.Frame(parent, bg=BORDER, width=1, height=18).pack(side="left", padx=4)

    def _build(self):
        f = self.frame
        grip = tk.Label(f, text="⋮⋮", bg=BG, fg=MUTED, cursor="fleur", font=self.f_ui_b, padx=2)
        grip.pack(side="left")
        drag_widgets = [grip]
        try:
            from .config import icon_path
            self._logo = tk.PhotoImage(file=icon_path(on_dark=True)).subsample(26, 26)  # the bar is dark
            logo = tk.Label(f, image=self._logo, bg=BG, cursor="fleur")
            logo.pack(side="left", padx=(2, 0))
            drag_widgets.append(logo)
            from .config import APP_CREDIT
            logo.bind("<Enter>", lambda e: self._tip_later(logo, APP_CREDIT), add="+")
            logo.bind("<Leave>", lambda e: self._tip_cancel(), add="+")
        except Exception:
            pass
        for w in drag_widgets:
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

        self.dot = tk.Canvas(f, width=10, height=10, bg=BG, highlightthickness=0, bd=0)
        self.dot.pack(side="left", padx=(4, 4))
        self.dot_id = self.dot.create_oval(1, 1, 9, 9, fill=STATE_COLORS["idle"], outline="")
        self.dot.bind("<Enter>", lambda e: self._tip_later(self.dot, self.status_text))
        self.dot.bind("<Leave>", lambda e: self._tip_cancel())
        self.status_text = "On"

        self.body = tk.Frame(f, bg=BG)           # hidden when collapsed
        self.body.pack(side="left")
        b = self.body
        self.lbl_status = tk.Label(b, text="On", bg=BG, fg=FG, font=self.f_ui, width=13, anchor="w")
        self.lbl_status.pack(side="left")
        self._sep(b)
        self.btn_preset = self._button(b, "Default ▾", self.open_preset_menu,
                                       "Presets: saved setups (reading order, languages, engines, look). The one in use keeps your changes",
                                       chip=True, keep_focus=True)
        self.btn_preset.pack(side="left", padx=1)
        self.btn_server = self._button(b, "Gemini · 3.5 Flash Lite ▾", self.open_server_menu,
                                       "Mode (who reads and who translates), AI server and model", chip=True, keep_focus=True)
        self.btn_server.pack(side="left", padx=1)
        self._sep(b)

        self.actions = tk.Frame(f, bg=BG)        # always visible, also when collapsed
        self.actions.pack(side="left")
        a = self.actions
        self.btn_translate = self._button(a, self._glyph("translate"), self.app.translate, "Translate now (Alt+T)", icon=True)
        self.btn_translate.pack(side="left")
        self.btn_pause = self._button(a, self._glyph("pause"), self.app.toggle_pause, "Pause / resume (Alt+Shift+T)", icon=True)
        self.btn_pause.pack(side="left")
        self.btn_overlay = self._button(a, self._glyph("eye"), self.app.toggle_overlay, "Show / hide overlay (Esc hides)", icon=True)
        self.btn_overlay.pack(side="left")
        self.btn_region = self._button(a, self._glyph("crop"), self.app.select_region,
                                       "Draw a frame around the comic page (Alt+Shift+R)", icon=True, keep_focus=True)
        self.btn_region.pack(side="left")

        self.tail = tk.Frame(f, bg=BG)           # hidden when collapsed
        self.tail.pack(side="left")
        self._sep(self.tail)
        self.btn_settings = self._button(self.tail, self._glyph("gear"), self.open_settings_menu,
                                         "Settings", icon=True, keep_focus=True)
        self.btn_settings.pack(side="left")
        tk.Frame(f, bg=BG, width=4).pack(side="left")

        self.btn_collapse = self._button(f, self._glyph("left"), self.toggle_collapsed, "Collapse / expand", icon=True)
        self.btn_collapse.pack(side="left")
        self.btn_close = self._button(f, self._glyph("close"), self.app.quit, "Quit LazyK (Ctrl+Alt+Q)", icon=True)
        self.btn_close.pack(side="left")

    # ------------------------------------------------------------ state
    def refresh(self):
        s = self.s
        from . import presets
        act = presets.active(s)
        self.btn_preset.configure(text=(act if len(act) <= 14 else act[:13] + "…") + "  ▾")
        srv = s["server"]
        mode = s.read_mode()
        if mode == "local_google":  # this PC reads, Google translates: no AI at all
            self.btn_server.configure(text="Local + Google  ▾")
        elif mode == "local_ai":  # this PC reads, the AI only translates
            self.btn_server.configure(text=f"Local + {SERVER_SHORT.get(srv, srv)}  ▾")
        else:
            self.btn_server.configure(text=f"{SERVER_SHORT.get(srv, srv)} · {short_model(s[f'{srv}_model']) or '—'}  ▾")
        region = bool(self.app._region())
        self.btn_region.configure(fg="#f59e0b" if region else FG)  # amber = capturing your own frame
        self.btn_translate.tip_text = f"Translate now ({pretty(s['hotkey_translate'])})"
        self.btn_pause.configure(text=self._glyph("play" if self.app.paused else "pause"))
        self.btn_overlay.configure(text=self._glyph("eye" if self.app.overlay.visible else "eye_off"))
        if not self._status_job and not self.app.busy:
            self._set_idle()

    def _set_idle(self):
        if self.app.paused:
            self._show_state("paused", "Paused")
        elif self.s["layout"] == "vn":
            auto = bool(self.s["vn_auto"])
            self._show_state("idle" if auto else "hotkey", "VN · Auto" if auto else "VN · Hotkey")
        else:
            self._show_state("idle" if self.s["mode"] == "auto" else "hotkey",
                             "On · Auto" if self.s["mode"] == "auto" else "On · Hotkey")

    def _show_state(self, state, text):
        self.status_text = text
        self.dot.itemconfigure(self.dot_id, fill=STATE_COLORS.get(state, MUTED))
        short = text if len(text) <= 18 else text[:17] + "…"
        self.lbl_status.configure(text=short, fg=STATE_COLORS["error"] if state == "error" else FG)

    def set_status(self, state, text, hold_ms=None):
        """Show a job state; after hold_ms fall back to the idle 'On · Auto' label."""
        if self._status_job:
            self.win.after_cancel(self._status_job)
            self._status_job = None
        self._show_state(state, text)
        if hold_ms:
            self._status_job = self.win.after(hold_ms, self._status_done)
        self.btn_overlay.configure(text=self._glyph("eye" if self.app.overlay.visible else "eye_off"))

    def _status_done(self):
        self._status_job = None
        self._set_idle()

    def set_collapsed(self, collapsed, save=True):
        # Collapsed: status dot + translate / pause / show-hide / frame only
        if collapsed:
            self.body.pack_forget()
            self.tail.pack_forget()
            self.btn_collapse.configure(text=self._glyph("right"))
        else:
            self.body.pack(side="left", after=self.dot)
            self.tail.pack(side="left", after=self.actions)
            self.btn_collapse.configure(text=self._glyph("left"))
        self.collapsed = collapsed
        if save:
            self.s.update(toolbar_collapsed=collapsed)

    def toggle_collapsed(self):
        self.set_collapsed(not self.collapsed)

    # ------------------------------------------------------------ window
    def show(self):
        self.win.update_idletasks()
        pos = self.s["toolbar_pos"]
        if isinstance(pos, (list, tuple)) and len(pos) == 2 and winapi.point_on_screen(pos[0] + 10, pos[1] + 10):
            x, y = int(pos[0]), int(pos[1])
        else:
            x = (self.win.winfo_screenwidth() - self.win.winfo_reqwidth()) // 2
            y = 6
        self.win.geometry(f"+{x}+{y}")
        prev = winapi.foreground_window()
        self.win.deiconify()
        self.win.update_idletasks()
        self.hwnd = winapi.tk_toplevel_hwnd(self.win)
        winapi.make_toolbar_window(self.hwnd, not self.s["developer_mode"])
        if prev and winapi.foreground_window() != prev:
            winapi.set_foreground(prev)
        self._keep_on_top()

    def set_hidden(self, hidden):
        """Hide / show the whole toolbar. Hotkeys, auto-scan and translation keep working: only the window goes."""
        self.hidden = bool(hidden)
        if self.hidden:
            if self.menu:
                self.menu.close()
            self._tip_cancel()
            self.tip.hide()
            if self.picker and self.picker.win.winfo_exists():
                self.picker.win.destroy()
            if self.hwnd:
                winapi.hide_window(self.hwnd)
            else:
                self.win.withdraw()
        else:
            if self.hwnd:
                winapi.show_no_activate(self.hwnd)
            else:
                self.win.deiconify()
            self.raise_()
        self.app.on_toolbar_visibility(self.hidden)  # taskbar button / tray menu follow
        self.app.restore_focus()

    def raise_(self):
        """Stay above the overlay (both are topmost; the newest one wins)."""
        if self.hidden:
            return
        if self.hwnd:
            winapi.show_no_activate(self.hwnd)
        else:
            self.win.lift()
        if self.picker and self.picker.win.winfo_exists():
            self.picker.win.lift()

    def _keep_on_top(self):
        # Other topmost windows (video players, games) can cover us; re-assert every few seconds
        try:
            if not self.hidden:
                self.win.attributes("-topmost", True)
                if self.hwnd:
                    winapi.show_no_activate(self.hwnd)
        except tk.TclError:
            return
        self.win.after(3000, self._keep_on_top)

    def _drag_start(self, e):
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _drag_move(self, e):
        if self._drag:
            self.win.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _drag_end(self, _e):
        self._drag = None
        self.app.restore_focus()
        self.s.update(toolbar_pos=[self.win.winfo_x(), self.win.winfo_y()])

    # ------------------------------------------------------------ tooltips
    def _tip_later(self, widget, text):
        self._tip_cancel()
        self._tip_job = self.win.after(450, lambda: self._tip_show(widget, text))

    def _tip_show(self, widget, text):
        self._tip_job = None
        self.tip.show_near(text, self._anchor(widget))

    def _tip_cancel(self):
        if self._tip_job:
            self.win.after_cancel(self._tip_job)
            self._tip_job = None
        self.tip.hide()

    # ------------------------------------------------------------ server / model
    def _anchor(self, widget):
        return (widget.winfo_rootx(), widget.winfo_rooty(), widget.winfo_rooty() + widget.winfo_height())

    def _popup(self, builder, widget, persistent=False):
        self.menu = PopupMenu(self.root, builder, self._anchor(widget), self.fonts,
                              on_close=self._menu_closed, persistent=persistent)

    # ------------------------------------------------------------ OCR device (CPU / graphics card)
    def _device_label(self):
        from . import gpus, local_ocr
        s = self.s
        if not s["local_gpu"] or not local_ocr.gpu_name():
            return "CPU"
        card = next((g for g in gpus.cached() or [] if g["id"] == int(s["local_gpu_id"])), None)
        return gpus.short_name(card["name"], 18) if card else "GPU"

    def _device_rows(self):
        """CPU + every graphics card found. Shared by the toolbar menu and ⚙."""
        from . import gpus, local_ocr
        s, a = self.s, self.app
        has_dml = bool(local_ocr.gpu_name())
        on_gpu = bool(s["local_gpu"]) and has_dml
        cur = int(s["local_gpu_id"] or 0)
        rows = [("item", "CPU", not on_gpu, lambda: a.set_ocr_device(None), None)]
        if not has_dml:
            rows.append(("header", "No GPU support installed"))
            return rows
        cards = gpus.cached()
        if cards is None:  # not read yet (it is done late at start): read it now that the menu needs it
            gpus.load(on_done=lambda: self.app.q.put(("gpus",)))
        if cards is None:
            rows.append(("header", "Looking for graphics cards…"))
        elif not cards:  # the list could not be read: the Windows default card still works
            rows.append(("item", "Default graphics card", on_gpu and cur == 0, lambda: a.set_ocr_device(0), None))
        else:
            for g in cards:
                kind = "dedicated" if g["mb"] >= 1024 else "integrated"
                rows.append(("item", gpus.short_name(g["name"], 30), on_gpu and cur == g["id"],
                             lambda i=g["id"]: a.set_ocr_device(i), kind))
        return rows

    def refresh_menu(self):
        """Rebuild the open menu (something it shows has just changed, e.g. the list of graphics cards)."""
        try:
            if self.menu and not self.menu.closed:
                self.menu.refresh()
        except Exception:
            log.exception("Could not refresh the menu")

    def open_preset_menu(self):
        """Pick a preset (the one in use keeps every change by itself), create one, rename / delete it."""
        if self.menu:
            self.menu.close()
            return
        from . import presets
        s, a = self.s, self.app
        anchor = self._anchor(self.btn_preset)
        act = presets.active(s)
        rows = [("item", p["name"], p["name"] == act, lambda n=p["name"]: a.apply_preset(n), None, "close")
                for p in presets.all_(s)]
        rows += [("sep",), ("item", "Create new preset", False, lambda: a.create_preset(anchor), None, "close")]
        if act != presets.DEFAULT:
            rows += [("item", f"Rename “{act}”", False, lambda: a.rename_preset(act, anchor), None, "close"),
                     ("item", f"Delete “{act}”", False, lambda: a.delete_preset(act, anchor), None, "close")]
        self._popup(rows, self.btn_preset)

    def open_server_menu(self):
        """Who reads and who translates. Short: the AI's server / model / auto-switch share one submenu.
        Stays open while you pick (like Settings); a click outside, Esc or the button again closes."""
        if self.menu:
            self.menu.close()
            return
        s, a = self.s, self.app

        def ai():
            srv = s["server"]
            rows = [("header", "Server")]
            for k in ("gemini", "cloudflare"):
                has_key = {"gemini": bool(str(s["gemini_api_key"]).strip()),
                           "cloudflare": bool(str(s["cf_api_token"]).strip() and str(s["cf_account_id"]).strip())}[k]
                rows.append(("item", SERVER_NAMES[k], srv == k,
                             (lambda v=k: a.set_server(v)) if has_key else (lambda v=k: self.open_api_dialog(v)),
                             "" if has_key else "no key", None if has_key else "close"))
            rows += [("sep",), ("header", "Model")]
            cur = s[f"{srv}_model"]
            rows += [("item", m, m == cur, lambda v=m: a.set_model(v), None) for m in s[f"{srv}_models"] or []]
            rows += [("sep",),
                     ("item", "Switch model when busy", bool(s["auto_switch_model"]),
                      lambda: a.toggle_setting("auto_switch_model"), None),
                     ("item", "Switch server when out of quota", bool(s["auto_switch_server"]),
                      lambda: a.toggle_setting("auto_switch_server"), None),
                     ("sep",),
                     ("item", "API keys", False, self.open_api_dialog, None, "close")]
            return rows

        def top():
            mode, srv = s.read_mode(), s["server"]
            label = f"{SERVER_SHORT.get(srv, srv)} · {short_model(s[f'{srv}_model']) or '—'}"
            rows = [("item", "AI reads and translates", mode == "ai", lambda: a.set_read_mode("ai"), None),
                    ("item", "Local OCR + AI translation", mode == "local_ai", lambda: a.set_read_mode("local_ai"), None),
                    ("item", "Local OCR + Google Translate", mode == "local_google",
                     lambda: a.set_read_mode("local_google"), "no key"),
                    ("sep",),
                    ("sub", "AI (backup)" if mode == "local_google" else "AI", label, ai)]
            if mode != "ai":
                rows += [("sub", "OCR device", self._device_label(), self._device_rows),
                         ("item", "OCR models", False, self.open_local_dialog, None, "close")]
            return rows
        self._popup(top, self.btn_server, persistent=True)

    def open_settings_menu(self):
        """Settings stay open while you change them; ⚙ again, Esc or a click outside closes.
        Six short rows; everything else is one level down."""
        if self.menu:
            self.menu.close()
            return
        from . import langs
        from .config import APP_CREDIT
        s, a = self.s, self.app

        def region():
            return s["capture_mode"] == "region" and s["region"]

        def order():
            return [("item", "Manga · right → left", s["layout"] == "manga", lambda: a.set_layout("manga"), None),
                    ("item", "Webtoon · left → right", s["layout"] == "webtoon", lambda: a.set_layout("webtoon"), None),
                    ("item", "Visual novel · text box", s["layout"] == "vn", lambda: a.set_layout("vn"), None)]

        def scanning():
            if s["layout"] == "vn":
                r = s["vn_region"]
                return [("item", "Auto-scan when text changes", bool(s["vn_auto"]), a.toggle_vn_auto,
                         pretty(s["hotkey_vn_auto"])),
                        ("sep",),
                        ("item", "Text box frame", False, a.select_region,
                         f"{r[2]}×{r[3]}" if r else "not drawn", "close")]
            return [("item", "Auto · after scrolling stops", s["mode"] == "auto", lambda: a.set_mode("auto"), None),
                    ("item", "Hotkey only", s["mode"] == "hotkey", lambda: a.set_mode("hotkey"),
                     pretty(s["hotkey_translate"])),
                    ("sep",),
                    ("item", "Capture the browser page", not region(), lambda: a.set_capture("window"), None),
                    ("item", "Capture my frame", bool(region()), lambda: a.set_capture("region"),
                     f"{s['region'][2]}×{s['region'][3]}" if s["region"] else "not drawn",
                     None if s["region"] else "close"),
                    ("item", "Draw a new frame", False, a.select_region, pretty(s["hotkey_region"]), "close")]

        def language():
            rows = [("header", "From")]
            rows += [("item", lab, s["source_lang"] == code, lambda c=code: a.set_source_lang(c), None)
                     for code, lab, _ in langs.SOURCES]
            rows += [("col",), ("header", "To")]
            cur = langs.target(s["target_lang"])[0]
            rows += [("item", lab, cur == name, lambda n=name: a.set_target_lang(n), None)
                     for name, lab, *_ in langs.TARGETS]
            return rows

        def look():
            fam = s["font_family"]
            vn = s["layout"] == "vn"
            rows = [("header", "Text"),
                    ("item", "Font", False, self.open_font_picker, fam if len(fam) <= 16 else fam[:15] + "…", "close"),
                    ("entry", "Minimum size", s["font_min"], a.set_font_size, "px"),
                    ("item", "Auto text size", bool(s["auto_text_size"]), a.toggle_auto_text_size, "up to 1.6×"),
                    ("item", "Text color", False,
                     lambda: a.pick_overlay_color("overlay_fg", "Translated text color"), s["overlay_fg"], "close"),
                    ("sep",),
                    ("header", "Box"),
                    ("item", "Box color", False,
                     lambda: a.pick_overlay_color("overlay_bg", "Translated box background"), s["overlay_bg"], "close"),
                    ("item", "Box color from the page", bool(s["vn_game_colors"]), a.toggle_vn_colors, None)]
            if vn:  # see-through boxes are for visual novels only
                rows += [("entry", "Box opacity", s["overlay_opacity"], a.set_overlay_opacity, "%"),
                         ("entry", "Box blur", s["overlay_blur"], a.set_overlay_blur, "px")]
            rows += [("sep",),
                     ("header", "Display"),
                     ("item", "Text box", bool(s["text_box"]) and vn, a.toggle_text_box,
                      "separate, movable" if vn else "🔒 Visual novel only"),
                     ("item", "Hide the box under the mouse", bool(s["hover_hide"]), a.toggle_hover_hide, None),
                     ("item", "Show in screenshots", bool(s["overlay_in_screenshots"]), a.toggle_overlay_capture, None),
                     ("sep",),
                     ("item", "Reset look", False, a.reset_overlay_colors, None)]
            return rows

        def speech():
            from . import piper_tts, tts
            local = str(s["tts_engine"]).lower() == "local"
            lang = tts.pick_voice(s)[:2].lower()
            pv = piper_tts.voice_for(lang)
            if not pv:
                note = "online for this language"
            elif piper_tts.ready(lang):
                note = "fast · offline"
            else:
                note = f"download {pv[2]}"
            return [("item", "Read the translation aloud", bool(s["tts_enabled"]), a.toggle_tts, None),
                    ("sep",),
                    ("item", "Local voice", local, lambda: a.set_tts_engine("local"), note),
                    ("item", "Online voice", not local, lambda: a.set_tts_engine("online"), "nicer · slower"),
                    ("sep",),
                    ("entry", "Speed", s["tts_speed"], a.set_tts_speed, "%"),
                    ("entry", "Volume", s["tts_volume"], a.set_tts_volume, "%"),
                    ("item", "Test voice", False, a.test_tts, None)]

        def more():
            def key(label, name):
                return ("item", label, False,
                        lambda: a.open_key_dialog(name, label.rstrip("…"), self._anchor(self.btn_settings)),
                        pretty(s[name]), "close")
            rows = [("header", "Keys"), key("Translate key", "hotkey_translate")]
            if s["layout"] == "vn":
                rows.append(key("Auto-scan key", "hotkey_vn_auto"))
            rows += [key("Show / hide toolbar key", "hotkey_toolbar"),
                     ("sep",),
                     ("item", "Keep translation record", bool(s["record_enabled"]), a.toggle_record, None),
                     ("item", "Open translation record", False, a.open_record, None, "close"),
                     ("item", "Show in taskbar", bool(s["taskbar_icon"]), a.toggle_taskbar_icon, None),
                     ("item", "Developer mode", bool(s["developer_mode"]), a.toggle_developer_mode, "visible to OBS"),
                     ("sep",),
                     ("item", "API keys & models", False, self.open_api_dialog, None, "close")]
            return rows

        def top():
            layout = {"manga": "Manga", "webtoon": "Webtoon", "vn": "Visual novel"}.get(s["layout"], "Manga")
            if s["layout"] == "vn":
                scan = "Auto" if s["vn_auto"] else "Manual"
            else:
                scan = ("Auto" if s["mode"] == "auto" else "Hotkey") + (" · frame" if region() else "")
            return [("sub", "Reading order", layout, order),
                    ("sub", "Scanning", scan, scanning),
                    ("sub", "Language", f"{langs.source_short(s['source_lang'])} → {langs.short(s['target_lang'])}",
                     language),
                    ("sub", "Look", f"{s['font_min']} px", look),
                    ("sub", "Text to speech", "On" if s["tts_enabled"] else "Off", speech),
                    ("sep",),
                    ("sub", "More", "", more),
                    ("sep",),
                    ("note", APP_CREDIT)]  # just the credit: nothing to click by mistake
        self._popup(top, self.btn_settings, persistent=True)

    def _menu_closed(self):
        self.menu = None
        self.app.restore_focus()

    def open_local_dialog(self):
        from .local_dialog import LocalDialog
        LocalDialog(self.root, self.s, on_changed=self.app.on_local_changed)

    def open_api_dialog(self, tab=None):
        ApiDialog(self.root, self.s, on_saved=self.app.on_api_saved, tab=tab)

    # ------------------------------------------------------------ font picker
    def open_font_picker(self):
        if self.picker and self.picker.win.winfo_exists():
            self.picker.win.lift()
            return
        self.picker = FontPicker(self.root, self.s, self.app.apply_font, anchor=self._anchor(self.btn_settings))


class FontPicker:
    """Searchable list of installed Windows fonts with a live Vietnamese preview."""
    SAMPLE = "Xin chào! Chuyện gì vậy?\nĐừng có đùa tớ nữa mà…"

    def __init__(self, root, settings, on_apply, anchor=None):
        self.s = settings
        self.on_apply = on_apply
        self.original = (settings["font_family"], bool(settings["font_bold"]))
        fams = sorted({f for f in tkfont.families(root) if not f.startswith("@")}, key=str.lower)
        self.all = fams

        w = self.win = tk.Toplevel(root)
        w.title("LazyK · Overlay font")
        w.configure(bg=BG, padx=12, pady=12)
        w.attributes("-topmost", True)
        w.resizable(False, True)

        tk.Label(w, text="Overlay font", bg=BG, fg=FG, font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(w, text=f"{len(fams)} fonts installed", bg=BG, fg=MUTED, font=("Segoe UI", 8),
                 anchor="w").pack(fill="x", pady=(0, 6))
        self.q = tk.StringVar()
        e = tk.Entry(w, textvariable=self.q, bg=CHIP, fg=FG, insertbackground=FG, relief="flat",
                     font=("Segoe UI", 10))
        e.pack(fill="x", ipady=4)
        self.q.trace_add("write", lambda *_: self._filter())

        box = tk.Frame(w, bg=BG)
        box.pack(fill="both", expand=True, pady=6)
        self.lb = tk.Listbox(box, height=14, width=34, bg=CHIP, fg=FG, selectbackground=ACCENT,
                             selectforeground="white", relief="flat", highlightthickness=0,
                             activestyle="none", font=("Segoe UI", 10), exportselection=False)
        sb = tk.Scrollbar(box, command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.lb.bind("<<ListboxSelect>>", lambda _e: self._preview())
        self.lb.bind("<Double-Button-1>", lambda _e: self._apply(close=True))

        self.bold = tk.BooleanVar(value=bool(settings["font_bold"]))
        tk.Checkbutton(w, text="Bold", variable=self.bold, command=self._preview, bg=BG, fg=FG,
                       selectcolor=CHIP, activebackground=BG, activeforeground=FG,
                       font=("Segoe UI", 9)).pack(anchor="w")

        self.pv_font = tkfont.Font(family=settings["font_family"], size=14)
        self.pv = tk.Label(w, text=self.SAMPLE, bg=settings["overlay_bg"], fg=settings["overlay_fg"],
                           font=self.pv_font, height=3, justify="center")
        self.pv.pack(fill="x", pady=(6, 8))

        row = tk.Frame(w, bg=BG)
        row.pack(fill="x")
        for text, cmd, bg in (("Apply", lambda: self._apply(close=True), ACCENT),
                              ("Cancel", self._cancel, CHIP)):
            tk.Button(row, text=text, command=cmd, bg=bg, fg="white" if bg == ACCENT else FG,
                      activebackground=bg, activeforeground="white", relief="flat", bd=0,
                      padx=14, pady=4, font=("Segoe UI", 9, "bold"), cursor="hand2").pack(side="right", padx=(6, 0))

        w.bind("<Return>", lambda _e: self._apply(close=True))
        w.bind("<Escape>", lambda _e: self._cancel())
        w.protocol("WM_DELETE_WINDOW", self._cancel)
        self._filter(select=settings["font_family"])
        if anchor:
            w.update_idletasks()
            x, top, bottom = anchor
            L, T, R, B = winapi.work_area(x, top)
            ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
            y = bottom + 8 if bottom + 8 + wh <= B else max(T, top - 8 - wh - 40)  # 40 = title bar
            w.geometry(f"+{max(L, min(x, R - ww))}+{y}")
        w.lift()
        w.focus_force()
        e.focus_set()

    def _filter(self, select=None):
        q = self.q.get().strip().lower()
        self.items = [f for f in self.all if q in f.lower()] if q else list(self.all)
        self.lb.delete(0, "end")
        for f in self.items:
            self.lb.insert("end", f)
        target = select or (self.items[0] if q and self.items else None)
        if target in self.items:
            i = self.items.index(target)
            self.lb.selection_clear(0, "end")
            self.lb.selection_set(i)
            self.lb.see(i)
            self._preview()

    def _selected(self):
        sel = self.lb.curselection()
        return self.items[sel[0]] if sel else None

    def _preview(self):
        fam = self._selected() or self.s["font_family"]
        self.pv_font.configure(family=fam, weight="bold" if self.bold.get() else "normal")
        # Live preview on the real overlay too
        self.on_apply(fam, self.bold.get(), save=False)

    def _apply(self, close=False):
        fam = self._selected() or self.s["font_family"]
        self.on_apply(fam, self.bold.get(), save=True)
        if close:
            self.win.destroy()

    def _cancel(self):
        self.on_apply(*self.original, save=True)
        self.win.destroy()

"""Tk main loop: receives hotkeys / scroll events, runs jobs on worker threads, draws results."""
import logging
import queue
import threading
import tkinter as tk

from . import winapi
from .api import Cancelled
from .api import SERVER_NAMES
from .api_dialog import ApiDialog, short_model
from .hotkeys import InputWatcher, pretty
from . import overlay as overlay_mod
from .overlay import Overlay, StatusPill
from .pipeline import Pipeline, grab
from .record import Record
from .region import RegionSelector
from .toolbar import LANG_CYCLE, Toolbar
from .tts import Speaker
from .vn import VNWatcher

log = logging.getLogger(__name__)
CAPTURE_DELAY_MS = 120  # the overlay is hidden first so our own capture never reads it back


class App:
    def __init__(self, settings, demo=False):
        self.s = settings
        self.demo = demo
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("LazyK")
        try:
            from .config import icon_path
            # title bars / taskbar follow the Windows theme
            self._icon = tk.PhotoImage(file=icon_path(on_dark=not winapi.system_light_theme()))
            self.root.iconphoto(True, self._icon)  # default icon for every window of the app
        except Exception:
            pass
        overlay_mod.DEV["on"] = bool(settings["developer_mode"])
        self.overlay = Overlay(self.root, settings)
        self.status = StatusPill(self.root)
        self.pipeline = Pipeline(settings)
        self.q = queue.Queue()
        self.record = Record(settings)
        self.tts = Speaker(settings, on_error=lambda m: self.q.put(("toast", "error", m, 4000)))
        from . import local_ocr
        local_ocr.GPU_ID = max(0, int(settings["local_gpu_id"] or 0))
        # Warm-ups (OCR models, Google, voice, graphics card list) run one after another, at low
        # priority, once the toolbar is up: see _quiet_start. All at once at launch made the PC stutter.
        self.gen = 0            # job generation: results of older jobs are dropped
        self.cancel = None
        self.busy = False
        self.paused = False
        self.rect, self.dpi = None, 96
        self._cred_win = None
        self._auto_job = None   # pending "scrolling stopped" timer
        self._auto_hwnd = None  # window that was scrolled
        self.last = None        # (rect, items, dpi) of the last shown page, for re-render
        self._overlay_vis = False
        self.target_hwnd = None  # last non-LazyK window the user worked in (the browser)
        self._fg_tick = 0
        self.selecting = False   # region picker open
        self.toolbar = Toolbar(self.root, self)
        self.taskbar = None
        self.tray = None
        self.tray_ok = False     # False: no tray icon (pystray missing) -> the taskbar button stays as the way back
        if settings["taskbar_icon"]:
            self._make_taskbar()
        self.watcher = InputWatcher(
            {"translate": settings["hotkey_translate"], "hide": settings["hotkey_hide"],
             "pause": settings["hotkey_pause"], "quit": settings["hotkey_quit"],
             "mode": settings["hotkey_mode"], "region": settings["hotkey_region"],
             "vn_auto": settings["hotkey_vn_auto"], "toolbar": settings["hotkey_toolbar"]},
            on_hotkey=lambda name: self.q.put(("hotkey", name)),
            on_scroll=lambda x, y: self.q.put(("scroll", x, y)),
        )

    # ------------------------------------------------------------ lifecycle
    def run(self):
        self.watcher.start()
        self._make_tray()
        self.vn_watcher = VNWatcher(self)  # idle unless Reading order = Visual novel and auto-scan is on
        self.vn_watcher.start()
        from .scrollwatch import PageWatcher
        self.page_watcher = PageWatcher(self)  # sees scrolling the wheel hook misses (touchpad, scrollbar)
        if self.s["scroll_watch"]:
            self.root.after(2500, self.page_watcher.start)
        self.root.after(30, self._poll)
        self.toolbar.show()
        if not self.demo:
            self._quiet_start()
        if self.s.needs_ai() and not self.s.has_credentials() and not self.demo:
            self._ask_credentials()
        else:
            self._status("ready", "Ready", auto_hide=2000)
        self.root.mainloop()

    def _quiet_start(self):
        """Load what the first page will need, gently: one thing at a time, spaced out, lowest priority.
        Whatever the user does first (a scan) still loads what it needs on its own."""
        from . import gpus, gtranslate, local_ocr
        s = self.s
        steps = []
        if s["ocr_engine"] == "local":
            steps.append((1200, lambda: local_ocr.ENGINE.warm(s)))
        if s.read_mode() == "local_google":
            steps.append((3500, gtranslate.warm))
        if s["tts_enabled"]:
            steps.append((5000, self.tts.warm))
        # the graphics card list is only for the OCR device menu: read it late (or when that menu opens)
        steps.append((15000, lambda: gpus.load(on_done=lambda: self.q.put(("gpus",)))))
        for ms, fn in steps:
            self.root.after(ms, fn)

    def quit(self):
        self._cancel_job()
        self.record.clear()  # the record only lives as long as the session
        if self.tray:
            self.tray.stop()  # its thread would keep the process alive
            self.tray = None
        self.watcher.stop()
        if getattr(self, "vn_watcher", None):
            self.vn_watcher.stop()
        if getattr(self, "page_watcher", None):
            self.page_watcher.stop()
        self.root.quit()

    def _ask_credentials(self, then=None):
        if self._cred_win and self._cred_win.winfo_exists():
            self._cred_win.lift()
            return
        self._cred_win = ApiDialog(self.root, self.s, on_saved=lambda: (self.on_api_saved(), then and then())).win

    # ------------------------------------------------------------ event loop
    def _poll(self):
        try:
            self._poll_once()
        except Exception:
            log.exception("Main loop tick failed")  # never let one error stop the loop: it runs everything
        finally:
            self.root.after(30, self._poll)

    def _poll_once(self):
        try:
            while True:
                ev = self.q.get_nowait()
                try:
                    self._dispatch(ev)
                except Exception:
                    log.exception("Event %s failed", ev[0])
        except queue.Empty:
            pass
        self._hover_tick = getattr(self, "_hover_tick", 0) + 1
        if self._hover_tick % 2 == 0:  # ~60 ms
            self._update_hover()
        if self.overlay.visible != self._overlay_vis:
            self._overlay_vis = self.overlay.visible
            self.toolbar.refresh()
        self._fg_tick += 1
        if self._fg_tick % 5 == 0:  # ~150 ms: remember the window the user is reading in
            fg = winapi.foreground_window()
            if fg and not winapi.is_own_window(fg):
                self.target_hwnd = winapi.root_window(fg)
        if self._fg_tick % 100 == 0:  # ~3 s: the key / wheel listeners must still be running
            restarted = self.watcher.ensure_alive()
            if restarted:
                log.warning("Input listener stopped, restarted: %s", ", ".join(restarted))

    def _update_hover(self):
        """Hide the translated box under the mouse so the original art / text below can be checked."""
        if not (self.s["hover_hide"] and self.overlay.visible):
            self.overlay.set_hover(None)
            return
        pos = winapi.cursor_pos()
        self.overlay.set_hover(pos)

    def restore_focus(self):
        """After a toolbar click, give the keyboard back to the browser."""
        fg = winapi.foreground_window()
        if self.target_hwnd and (not fg or winapi.is_own_window(fg)):
            winapi.set_foreground(self.target_hwnd)

    def _dispatch(self, ev):
        kind = ev[0]
        if kind == "hotkey":
            name = ev[1]
            if name == "translate":
                self.translate()
            elif name == "hide":
                if self.overlay.visible or self.busy:
                    self._cancel_job()
                    self.overlay.clear()
                    self.status.hide()
            elif name == "pause":
                self.toggle_pause()
            elif name == "quit":
                self.quit()
            elif name == "mode":
                self.toggle_mode()
            elif name == "region":
                self.select_region()
            elif name == "vn_auto":
                self.toggle_vn_auto()
            elif name == "toolbar":
                self.toggle_toolbar()
        elif kind == "tray":  # from the tray icon's thread
            if ev[1] == "toggle":
                self.toggle_toolbar()
            elif ev[1] == "quit":
                self.quit()
        elif kind == "vn_hide":
            if self.s["layout"] == "vn" and (self.overlay.visible or self.busy):
                self._cancel_job()
                self.overlay.clear()
                self.status.hide()
        elif kind == "vn_restore":
            if (self.s["layout"] == "vn" and self.s["vn_auto"] and not self.paused and not self.busy
                    and not self.overlay.visible and self.last):
                self.overlay.show_items(*self.last)
                self.toolbar.raise_()
        elif kind == "vn_scan":
            if self.s["layout"] == "vn" and self.s["vn_auto"] and not self.paused:
                self._vn_t0 = ev[1] if len(ev) > 1 else None  # last time the text changed (for the log)
                self.translate(auto=True)
        elif kind == "scroll":
            self._on_scroll(ev[1], ev[2])
        elif kind == "pagemove":
            self._on_page_move(ev[1])
        elif kind == "status":
            _, gen, state, text = ev
            if gen == self.gen:
                self._status(state, text)
            self.toolbar.refresh()  # model / server may have been switched automatically
        elif kind == "gpus":
            self.toolbar.refresh_menu()  # the OCR device list just arrived
        elif kind == "toast":
            _, state, text, ms = ev
            if not self.busy:
                self._status(state, text, auto_hide=ms)
        elif kind == "done":
            _, gen, rect, dpi, items, cached = ev
            if gen != self.gen:
                log.info("Job %d finished but was superseded; result dropped", gen)
                if not self.busy:
                    self.status.hide()  # its "Translating…" must not stay on the page
                return
            log.info("Job %d done: %d items%s", gen, len(items), " (cached)" if cached else "")
            self.busy = False
            if not items:
                if self.s["layout"] == "vn" and self.s["vn_auto"]:
                    self.toolbar.refresh()  # an empty text box between lines is normal: no message
                    return
                from . import local_ocr
                hint = local_ocr.ENGINE.hint if self.s["ocr_engine"] == "local" else ""
                self._status("error" if hint else "info", hint or "No text found", auto_hide=6000 if hint else 2500)
                return
            self.overlay.show_items(rect, items, dpi)
            t0 = getattr(self, "_vn_t0", None)
            if self.s["layout"] == "vn" and t0:
                import time as _t
                log.info("VN: translation shown %.2fs after the text stopped changing", _t.time() - t0)
                self._vn_t0 = None
            self.toolbar.raise_()
            self.last = (rect, items, dpi)
            if not cached:
                self.record.add(items)
            if self.s["tts_enabled"] and not cached:  # a page coming back from the cache is not read again
                self.tts.speak(items)
            n = sum(1 for it in items if it.get("translation"))
            if self.s["ocr_engine"] == "local" and not cached:
                from . import local_ocr
                if local_ocr.ENGINE.hint:  # e.g. a Korean page without the Korean model
                    self._status("error", local_ocr.ENGINE.hint, auto_hide=6000)
                    return
            self._status("ready", f"Ready · {n} bubble" + ("s" if n != 1 else "") + (" (cached)" if cached else ""), auto_hide=2000)
        elif kind == "error":
            _, gen, msg = ev
            if gen == self.gen:
                self.busy = False
                self._status("error", f"Error: {msg}", auto_hide=8000)

    def _status(self, state, text, auto_hide=None):
        if auto_hide is None and state == "error":
            auto_hide = 8000  # an error must never stay up forever (the details are in the log)
        self.toolbar.set_status(state, text, auto_hide)
        if getattr(self, "taskbar", None):  # hover text of the taskbar button: an error stays readable with the toolbar hidden
            self.taskbar.set_title(text if state == "error" else "")
        if getattr(self, "tray", None):  # same for the tray icon (the taskbar button is hidden with the toolbar)
            self.tray.set_title(text if state == "error" else "")
        if self.s["layout"] == "vn":
            # Visual novel: the pill would sit at the top-right corner of the text box frame, which is
            # in the middle of the game screen. The toolbar shows every state and error instead.
            self.status.hide()
            return
        # The toolbar is the main indicator; the pill near the page is optional (always for errors)
        if self.s["show_status_pill"] or state == "error" or ((self.toolbar.collapsed or self.toolbar.hidden) and state != "info"):
            # "Scanning…" / "Translating…" are replaced by the next state; the long limit only matters
            # if a job is dropped without a final word, so a stale pill never sits on the page.
            self.status.set(state, text, self.rect, self.dpi, auto_hide or 120000)

    # ------------------------------------------------------------ actions
    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self._cancel_job()
            self.overlay.clear()
            self._status("paused", "Paused", auto_hide=1500)
        else:
            self._status("ready", "Resumed", auto_hide=1500)
        self.toolbar.refresh()

    def _cancel_job(self):
        self.tts.stop()
        self.gen += 1
        if self.cancel:
            self.cancel.set()
        self.cancel = None
        if self.busy:
            self.busy = False
            self.toolbar.set_status("idle", "", hold_ms=1)  # drop "Scanning…"

    # ------------------------------------------------------------ capture region
    def _region_key(self):
        return "vn_region" if self.s["layout"] == "vn" else "region"

    def _region(self):
        """The frame to capture, or None for 'the browser page'. Visual novel: always the text box frame."""
        if self.s["layout"] != "vn" and self.s["capture_mode"] != "region":
            return None
        r = self.s[self._region_key()]
        if isinstance(r, (list, tuple)) and len(r) == 4:
            return tuple(int(v) for v in r)
        return None

    def select_region(self):
        if self.selecting:
            return
        self.selecting = True
        self._cancel_job()
        self._cancel_auto_timer()
        self.overlay.clear()
        self.status.hide()
        RegionSelector(self.root, self._region_done, current=self.s[self._region_key()])

    def _region_done(self, rect):
        self.selecting = False
        if rect:
            if self._region_key() == "vn_region":
                self.s.update(vn_region=list(rect))
            else:
                self.s.update(region=list(rect), capture_mode="region")
            self.pipeline.prev_lines = []
            log.info("Capture region set to %s", rect)
            self.toolbar.refresh()
            self._status("info", f"Region {rect[2]}×{rect[3]}", auto_hide=1500)
            self.root.after(250, lambda: self.translate())
        self.restore_focus()

    def toggle_capture_mode(self):
        if self.s["capture_mode"] == "region":
            self.s.update(capture_mode="window")
        elif self.s["region"]:
            self.s.update(capture_mode="region")
        else:
            self.select_region()
            return
        self.toolbar.refresh()
        self._status("info", "Capture: " + ("your frame" if self._region() else "browser page"), auto_hide=1500)

    # ------------------------------------------------------------ server / model
    def set_server(self, srv):
        self.s.update(server=srv)
        self.toolbar.refresh()
        self._status("info", SERVER_NAMES[srv] + " · " + short_model(self.s[f"{srv}_model"]), auto_hide=1800)

    MODE_NAMES = {"ai": "AI reads & translates", "local_ai": "Local OCR + AI translation",
                  "local_google": "Local OCR + Google Translate"}

    def set_read_mode(self, mode):
        """ai | local_ai | local_google (see Settings.read_mode)."""
        if mode == "ai":
            self.s.update(ocr_engine="ai")
        else:
            self.s.update(ocr_engine="local", translator="google" if mode == "local_google" else "ai")
        self.toolbar.refresh()
        if mode != "ai":
            from . import local_ocr
            local_ocr.ENGINE.warm(self.s)
        self._status("info", self.MODE_NAMES[mode], auto_hide=1800)
        if self.s.needs_ai() and not self.s.has_credentials():
            self._ask_credentials()

    def set_ocr_device(self, gpu_id):
        """None = CPU, else the DirectML card number. Models reload on their next use."""
        from . import gpus, local_ocr
        if gpu_id is None:
            self.s.update(local_gpu=False)
            label = "CPU"
        else:
            self.s.update(local_gpu=True, local_gpu_id=int(gpu_id))
            local_ocr.GPU_ID = int(gpu_id)
            card = next((g for g in gpus.cached() or [] if g["id"] == int(gpu_id)), None)
            label = gpus.short_name(card["name"]) if card else f"graphics card {gpu_id}"
        if self.s["ocr_engine"] == "local":
            local_ocr.ENGINE.warm(self.s)  # load the models on the new device while the user keeps reading
        self.toolbar.refresh()
        self._status("info", "OCR on " + label, auto_hide=1800)

    def test_google(self):
        from . import gtranslate
        self._status("translating", "Testing Google…")

        def run():
            ok, msg, secs = gtranslate.test(self.s)
            self.q.put(("toast", "ready" if ok else "error",
                        f"Google OK · {secs:.1f}s" if ok else f"Google: {msg}", 3000 if ok else 8000))
        threading.Thread(target=run, daemon=True).start()

    def on_local_changed(self):
        self.pipeline.clear_cache()  # pages read before a model download may have been read badly
        self.toolbar.refresh()
        if self.s["ocr_engine"] == "local":
            from . import local_ocr
            local_ocr.ENGINE.reset()
            local_ocr.ENGINE.warm(self.s)

    def set_model(self, model):
        self.s.update(**{f"{self.s['server']}_model": model})
        self.toolbar.refresh()
        self._status("info", "Model: " + short_model(model), auto_hide=1800)

    def set_mode(self, mode):
        if self.s["mode"] != mode:
            self.toggle_mode()

    LAYOUT_NAMES = {"manga": "Manga (right→left)", "webtoon": "Webtoon (left→right)",
                    "vn": "Visual novel (text box)"}

    def set_layout(self, layout):
        if self.s["layout"] == layout:
            return
        self._cancel_job()
        self._cancel_auto_timer()
        self.overlay.clear()
        self.pipeline.prev_lines = []
        self.s.update(layout=layout)
        self.toolbar.refresh()
        self._status("info", "Reading order: " + self.LAYOUT_NAMES[layout], auto_hide=2000)
        if layout == "vn" and not self._region():
            self.root.after(300, self.select_region)  # first time: draw a frame around the text box

    def toggle_vn_auto(self):
        self.s.update(vn_auto=not self.s["vn_auto"])
        if self.s["layout"] != "vn":
            self.set_layout("vn")
        self.toolbar.refresh()
        on = self.s["vn_auto"]
        self._status("info", "VN auto-scan " + ("ON" if on else "OFF"), auto_hide=1500)
        self.rerender()  # the overlay is (not) excluded from screen captures while auto-scan is on

    # ------------------------------------------------------------ presets
    def apply_preset(self, name):
        """Switch everything a preset holds in one go, with the same side effects as changing each by hand."""
        from . import local_ocr, presets
        p = presets.get(self.s, name)
        if not p:
            return
        old = presets.snapshot_data(self.s.data)
        self._cancel_job()
        self._cancel_auto_timer()
        self.overlay.clear()
        vals = {k: v for k, v in (p.get("values") or {}).items() if k in presets.KEYS}
        self.s.update(**vals, preset_active=name)
        new = self.s
        if old["layout"] != new["layout"] or old["target_lang"] != new["target_lang"]:
            self.pipeline.prev_lines = []  # story context belongs to the other comic / language
        local_ocr.GPU_ID = max(0, int(new["local_gpu_id"] or 0))
        if new["ocr_engine"] == "local":
            local_ocr.ENGINE.warm(new)
        if new["tts_enabled"]:
            self.tts.warm()
        else:
            self.tts.stop()
        if new.read_mode() == "local_google":
            from . import gtranslate
            gtranslate.prewarm()
        self.toolbar.refresh()
        self._status("info", "Preset: " + name, auto_hide=1800)
        if new.needs_ai() and not new.has_credentials():
            self._ask_credentials()
        elif new["layout"] == "vn" and not self._region():
            self.root.after(300, self.select_region)

    def create_preset(self, anchor=None):
        """Name the current setup as a new preset; it becomes the one in use (Default stays as it was)."""
        from . import presets
        from .name_dialog import NameDialog
        taken = [p["name"] for p in presets.all_(self.s)]
        guess = {"manga": "Manga", "webtoon": "Webtoon", "vn": "Visual novel"}.get(self.s["layout"], "Preset")
        n, base = 2, guess
        while guess.lower() in {t.lower() for t in taken}:
            guess, n = f"{base} {n}", n + 1

        def ok(name):
            name = presets.create(self.s, name)
            self.toolbar.refresh()
            self._status("ready", "Created preset: " + name, auto_hide=1800)
        NameDialog(self.root, "Create new preset", guess, taken, ok, anchor=anchor)

    def rename_preset(self, name, anchor=None):
        from . import presets
        from .name_dialog import NameDialog
        if name == presets.DEFAULT:
            return
        taken = [p["name"] for p in presets.all_(self.s) if p["name"] != name]

        def ok(new):
            presets.rename(self.s, name, new)
            self.toolbar.refresh()
        NameDialog(self.root, "Rename preset", name, taken, ok, anchor=anchor)

    def delete_preset(self, name, anchor=None):
        from . import presets
        from .name_dialog import ConfirmDialog
        if name == presets.DEFAULT:
            return

        def ok():
            was_active = presets.active(self.s) == name
            presets.delete(self.s, name)
            if was_active:
                self.s.data["preset_active"] = presets.DEFAULT
                self.apply_preset(presets.DEFAULT)  # back to Default's own settings
            else:
                self.s.save()
                self.toolbar.refresh()
            self._status("info", "Deleted preset: " + name, auto_hide=1800)
        ConfirmDialog(self.root, "Delete preset", f"Delete “{name}”?", "Delete", ok, anchor=anchor)

    def set_target_lang(self, name):
        from . import langs
        if self.s["target_lang"] != name:
            self.s.update(target_lang=name)
            self.pipeline.prev_lines = []  # context lines were in the other language's story
        self.toolbar.refresh()
        self._status("info", "Translate to: " + langs.target(name)[1], auto_hide=1800)

    def set_source_lang(self, code):
        names = {"auto": "Auto detect", "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "en": "English"}
        self.s.update(source_lang=code)
        self.toolbar.refresh()
        self._status("info", "Source: " + names.get(code, code), auto_hide=1800)

    def set_capture(self, mode):
        if mode == "region" and not self.s["region"]:
            self.select_region()
            return
        self.s.update(capture_mode=mode)
        self.toolbar.refresh()
        self._status("info", "Capture: " + ("your frame" if mode == "region" else "browser page"), auto_hide=1500)

    def toggle_toolbar(self):
        """Hide / show the toolbar (hotkey, settings menu, or a click on the taskbar button)."""
        self.toolbar.set_hidden(not self.toolbar.hidden)

    def _make_taskbar(self):
        from .taskbar import TaskbarButton
        self.taskbar = TaskbarButton(self.root, on_click=self._taskbar_click, on_close=self.quit)

    def _make_tray(self):
        from .config import icon_path
        from .tray import TrayIcon
        self.tray = TrayIcon(
            icon_path(on_dark=not winapi.system_light_theme()),  # the tray follows the taskbar theme
            on_toggle=lambda: self.q.put(("tray", "toggle")),
            on_quit=lambda: self.q.put(("tray", "quit")),
            is_hidden=lambda: self.toolbar.hidden,
            key_text=lambda: pretty(self.s["hotkey_toolbar"]))
        self.tray_ok = self.tray.start()
        if not self.tray_ok:
            self.tray = None

    def on_toolbar_visibility(self, hidden):
        """Toolbar hidden -> the taskbar button goes too and only the tray icon stays. Without a tray the
        taskbar button stays, so there is always a way back."""
        if self.taskbar:
            self.taskbar.set_visible(not (hidden and self.tray_ok))
        if self.tray:
            self.tray.refresh()

    def _taskbar_click(self):
        if self.toolbar.hidden:
            self.toolbar.set_hidden(False)
        else:
            self.toolbar.raise_()
        self.restore_focus()

    def toggle_taskbar_icon(self):
        on = not self.s["taskbar_icon"]
        self.s.update(taskbar_icon=on)
        if on and not self.taskbar:
            self._make_taskbar()
            if self.toolbar.hidden:
                self.on_toolbar_visibility(True)
        elif not on and self.taskbar:
            self.taskbar.destroy()
            self.taskbar = None
        self.toolbar.refresh()

    def toggle_developer_mode(self):
        """Developer mode: OBS, Game Bar etc. can record the toolbar, menus, status pill and translation."""
        on = not self.s["developer_mode"]
        self.s.update(developer_mode=on)
        overlay_mod.DEV["on"] = on
        for w in (self.overlay, self.status, self.toolbar.tip):
            w.apply_capture()
        winapi.set_capture_excluded(self.toolbar.hwnd, not on)
        self.rerender()
        self.toolbar.refresh()
        self._status("info", "Developer mode " + ("ON: recorders can see the tool" if on else "off"), auto_hide=2500)

    def toggle_overlay_capture(self):
        self.s.update(overlay_in_screenshots=not self.s["overlay_in_screenshots"])
        self.rerender()  # re-applies the capture setting to the visible overlay

    def toggle_setting(self, key):
        self.s.update(**{key: not self.s[key]})
        self.toolbar.refresh()

    def on_api_saved(self):
        self.toolbar.refresh()
        srv = self.s["server"]
        self._status("ready", "Saved · " + SERVER_NAMES[srv], auto_hide=1800)

    # ------------------------------------------------------------ toolbar actions
    def toggle_layout(self):
        self.s.update(layout="webtoon" if self.s["layout"] == "manga" else "manga")
        self.toolbar.refresh()
        self._status("info", "Reading order: " + ("Manga (right→left)" if self.s["layout"] == "manga"
                                                  else "Webtoon (left→right)"), auto_hide=2000)

    def cycle_source_lang(self):
        cur = self.s["source_lang"]
        nxt = LANG_CYCLE[(LANG_CYCLE.index(cur) + 1) % len(LANG_CYCLE)] if cur in LANG_CYCLE else "auto"
        self.s.update(source_lang=nxt)
        self.toolbar.refresh()
        names = {"auto": "Auto detect", "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "en": "English"}
        self._status("info", "Source: " + names[nxt], auto_hide=2000)

    def toggle_overlay(self):
        if self.overlay.visible:
            self.tts.stop()
            self.overlay.clear()
        elif self.last and not self.busy:
            self.overlay.show_items(*self.last)
            self.toolbar.raise_()
        self.toolbar.refresh()

    def rerender(self):
        if self.overlay.visible and self.last:
            self.overlay.show_items(*self.last)
            self.toolbar.raise_()

    def apply_font(self, family, bold, save=True):
        self.s.data.update(font_family=family, font_bold=bool(bold))
        if save:
            self.s.save()
        self.rerender()
        self.toolbar.refresh()

    def set_font_size(self, text):
        """Typed in Settings → Text → Minimum size."""
        try:
            size = int(float(str(text).strip()))
        except ValueError:
            return
        self.change_font_size(size - int(self.s["font_min"]))

    def change_font_size(self, delta):
        """The size in Settings is the smallest the overlay text may get (it only grows in big bubbles)."""
        fmin = max(8, min(40, int(self.s["font_min"]) + delta))
        self.s.update(font_min=fmin, font_max=max(int(self.s["font_max"]), round(fmin * 1.6)))
        self.rerender()
        self.toolbar.refresh()

    def _mode_text(self):
        if self.s["mode"] == "auto":
            return "Auto: translates when you stop scrolling"
        return f"Hotkey: {pretty(self.s['hotkey_translate'])} to translate"

    # ------------------------------------------------------------ translate key
    HOTKEY_KEYS = ("hotkey_translate", "hotkey_hide", "hotkey_pause", "hotkey_quit", "hotkey_mode",
                   "hotkey_region", "hotkey_vn_auto", "hotkey_toolbar")

    def _bindings(self):
        return {"translate": self.s["hotkey_translate"], "hide": self.s["hotkey_hide"],
                "pause": self.s["hotkey_pause"], "quit": self.s["hotkey_quit"],
                "mode": self.s["hotkey_mode"], "region": self.s["hotkey_region"],
                "vn_auto": self.s["hotkey_vn_auto"], "toolbar": self.s["hotkey_toolbar"]}

    def open_key_dialog(self, setting="hotkey_translate", title="Translate key", anchor=None):
        from .config import DEFAULTS
        from .key_dialog import KeyDialog
        if getattr(self, "_key_win", None) and self._key_win.win.winfo_exists():
            self._key_win.win.lift()
            return
        self._key_win = KeyDialog(self.root, self.watcher, self.s[setting], DEFAULTS[setting],
                                  lambda spec: self.set_hotkey(setting, spec, title), anchor, title)

    def set_hotkey(self, setting, spec, title="Key"):
        spec = str(spec).lower()
        for k in self.HOTKEY_KEYS:
            if k != setting and str(self.s[k]).lower() == spec:
                self._status("error", f"{pretty(spec)} is already used by another action", auto_hide=4000)
                return
        self.s.update(**{setting: spec})
        self.watcher.set_bindings(self._bindings())
        self.toolbar.refresh()
        if self.tray:
            self.tray.refresh()  # the menu shows the toolbar key
        self._status("info", f"{title}: {pretty(spec)}", auto_hide=2500)
        self.restore_focus()

    def set_translate_key(self, spec):
        self.set_hotkey("hotkey_translate", spec, "Translate key")

    def toggle_vn_colors(self):
        self.s.update(vn_game_colors=not self.s["vn_game_colors"])
        self.rerender()
        self.toolbar.refresh()

    # ------------------------------------------------------------ overlay colours
    def pick_overlay_color(self, key, title):
        """key: overlay_bg | overlay_fg. Windows colour dialog; applied live on the visible overlay."""
        from tkinter import colorchooser
        _rgb, hexa = colorchooser.askcolor(color=self.s[key], title=title, parent=self.root)
        if hexa:
            self.s.update(**{key: hexa.lower()})
            self.rerender()
            self.toolbar.refresh()
        self.restore_focus()

    def set_overlay_opacity(self, text):
        """Typed in Settings → Text → Background opacity (0-100 %)."""
        try:
            v = int(float(str(text).strip().rstrip("%")))
        except ValueError:
            return
        self.s.update(overlay_opacity=max(0, min(100, v)))
        self.rerender()
        self.toolbar.refresh()

    def set_overlay_blur(self, text):
        """Typed in Settings → Text → Background blur (0-40 px)."""
        try:
            v = int(float(str(text).strip()))
        except ValueError:
            return
        v = max(0, min(40, v))
        upd = {"overlay_blur": v}
        if v > 0 and int(self.s["overlay_opacity"]) >= 100:
            # blur is the screen seen through the box: a fully solid box has nothing to blur, so the setting
            # used to do nothing. Make the box see-through (the colours stay the auto-picked ones).
            upd["overlay_opacity"] = 75
            self._status("info", "Blur shows through a see-through box: opacity set to 75%", auto_hide=4000)
        self.s.update(**upd)
        self.rerender()
        self.toolbar.refresh()

    def reset_overlay_colors(self):
        from .config import DEFAULTS
        self.s.update(overlay_bg=DEFAULTS["overlay_bg"], overlay_fg=DEFAULTS["overlay_fg"],
                      overlay_opacity=DEFAULTS["overlay_opacity"], overlay_blur=DEFAULTS["overlay_blur"])
        self.rerender()
        self.toolbar.refresh()

    def toggle_record(self):
        self.s.update(record_enabled=not self.s["record_enabled"])
        self.toolbar.refresh()

    def open_record(self):
        if not self.record.open():
            self._status("info", "Nothing recorded yet", auto_hide=2000)

    def toggle_tts(self):
        self.s.update(tts_enabled=not self.s["tts_enabled"])
        if self.s["tts_enabled"]:
            self.tts.warm()
        else:
            self.tts.stop()
        self.toolbar.refresh()

    def set_tts_speed(self, text):
        """Typed in Settings → Text to speech → Speed (50-200 %). Plays a short sample."""
        from . import tts
        try:
            v = int(float(str(text).strip().rstrip("%")))
        except ValueError:
            return
        self.s.update(tts_speed=max(50, min(200, v)))
        self.toolbar.refresh()
        self.tts.speak([tts.sample_text(self.s)])

    def set_tts_volume(self, text):
        """Typed in Settings → Text to speech → Volume (0-100 %). Plays a short sample."""
        from . import tts
        try:
            v = int(float(str(text).strip().rstrip("%")))
        except ValueError:
            return
        self.s.update(tts_volume=max(0, min(100, v)))
        self.toolbar.refresh()
        self.tts.speak([tts.sample_text(self.s)])

    def test_tts(self):
        from . import tts
        self.tts.speak([tts.sample_text(self.s)])

    def toggle_auto_text_size(self):
        self.s.update(auto_text_size=not self.s["auto_text_size"])
        self.rerender()  # the page on screen is laid out again with the new rule
        self._status("info", "Text size: " + ("grows in roomy boxes" if self.s["auto_text_size"] else
                                              f"always {self.s['font_min']} px"), auto_hide=1800)

    def toggle_hover_hide(self):
        self.s.update(hover_hide=not self.s["hover_hide"])
        if not self.s["hover_hide"]:
            self.overlay.set_hover(None)

    def toggle_mode(self):
        self.s.update(mode="hotkey" if self.s["mode"] == "auto" else "auto")
        self._cancel_auto_timer()
        self.toolbar.refresh()
        self._status("info", "Auto" if self.s["mode"] == "auto" else "Hotkey only", auto_hide=1500)

    def _cancel_auto_timer(self):
        if self._auto_job:
            self.root.after_cancel(self._auto_job)
            self._auto_job = None

    def _allowed_app(self, hwnd) -> bool:
        apps = [a.lower() for a in (self.s["auto_apps"] or [])]
        if not apps:
            return True  # empty list = any app
        return winapi.process_name(hwnd) in apps

    def _on_scroll(self, x, y):
        """Wheel (x, y = cursor) or navigation key (x, y = None)."""
        if x is not None and not getattr(self, "_wheel_seen", False):
            self._wheel_seen = True
            log.info("Mouse wheel events are arriving")  # for the log: the wheel hook works
        if self.paused or self.selecting or self.s["layout"] == "vn":
            return  # visual novels use the wheel / Space to advance: the scroll trigger is for manga
        if x is None and winapi.is_own_window(winapi.foreground_window()):
            return  # typing in the font picker / dialog
        region = self._region()
        if region and x is not None:
            rx, ry, rw, rh = region
            if not (rx <= x < rx + rw and ry <= y < ry + rh):
                return  # wheel outside the frame
        auto = self.s["mode"] == "auto"
        if not auto and not self.s["hide_on_scroll"]:
            return
        # Which window is being scrolled: under the cursor for the wheel, focused one for keys
        hwnd = winapi.window_from_point(x, y) if x is not None else winapi.root_window(winapi.foreground_window())
        if auto:
            if not hwnd or not self._allowed_app(hwnd):
                return  # scrolling some other app: ignore completely
        elif not (self.overlay.visible or self.busy):
            return
        elif x is not None and self.rect:
            rx, ry, rw, rh = self.rect
            if not (rx <= x < rx + rw and ry <= y < ry + rh):
                return
        # Page is moving: hide right away and drop any job in flight
        was_busy = self.busy
        if was_busy:
            log.info("Job %d cancelled by scrolling", self.gen)
        if self.overlay.visible or self.busy:
            self._cancel_job()
            self.overlay.clear()
            if was_busy:
                self.status.hide()
        if auto:
            self._auto_hwnd = hwnd
            self._cancel_auto_timer()
            delay = max(150, int(self.s["scroll_delay_ms"]))
            self._auto_job = self.root.after(delay, self._auto_fire)

    def _on_page_move(self, hwnd):
        """The page watcher saw the page scroll: same as a wheel scroll over it."""
        if self.paused or self.selecting or self.s["layout"] == "vn":
            return
        auto = self.s["mode"] == "auto"
        if not auto and not self.s["hide_on_scroll"]:
            return
        if self.overlay.visible or self.busy:
            if self.busy:
                log.info("Job %d cancelled: the page moved", self.gen)
            was_busy = self.busy
            self._cancel_job()
            self.overlay.clear()
            if was_busy:
                self.status.hide()
        if auto:
            self._auto_hwnd = hwnd
            self._cancel_auto_timer()
            delay = max(150, int(self.s["scroll_delay_ms"]))
            self._auto_job = self.root.after(delay, self._auto_fire)

    def _auto_fire(self):
        self._auto_job = None
        if self.paused or self.s["mode"] != "auto" or not self._auto_hwnd:
            return
        self.translate(hwnd=self._auto_hwnd, auto=True)

    def translate(self, hwnd=None, auto=False):
        self._cancel_auto_timer()
        if self.selecting:
            return
        if self.paused:
            if auto:
                return
            self._status("paused", "Paused · press " + pretty(self.s["hotkey_pause"]) + " to resume",
                         auto_hide=2500)
            return
        if self.s.needs_ai() and not self.s.has_credentials() and not self.demo:
            if not auto:
                self._ask_credentials(then=self.translate)
            return
        region = self._region()
        if self.s["layout"] == "vn" and not region:
            if not auto:
                self.select_region()  # draw the frame around the text box first
            return
        if region:
            rect = region
            dpi = winapi.dpi_for_point(rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
        else:
            if not hwnd:
                fg = winapi.foreground_window()
                # Toolbar / font picker / dialog focused: use the window the user was reading in
                hwnd = self.target_hwnd if (not fg or winapi.is_own_window(fg)) else winapi.root_window(fg)
            if not hwnd or winapi.is_own_window(hwnd):
                self._status("error", "Click the comic page first", auto_hide=4000)
                return
            try:
                rect, dpi = winapi.capture_rect_for_window(hwnd, int(self.s["browser_top_crop"]))
            except Exception as e:
                if not auto:
                    self._status("error", f"Error: {e}", auto_hide=5000)
                return
        if self.busy and rect == self.rect and not auto:
            # Same page already being processed: don't throw that work away
            self._status("scanning", "Still working…")
            log.info("Translate ignored: job %d still running on the same area", self.gen)
            return
        self._cancel_job()
        self.overlay.clear()
        self.rect, self.dpi = rect, dpi
        if self.s["tts_enabled"]:
            self.tts.prepare()  # open the voice connection while the page is being read
        gen, cancel = self.gen, threading.Event()
        self.cancel, self.busy = cancel, True
        log.info("Job %d start (%s): rect %s dpi %s", gen, "auto" if auto else "manual", rect, dpi)
        if self.demo:
            self.q.put(("done", gen, rect, dpi, demo_items(rect), False))
            return
        self._status("scanning", "Scanning…")
        delay = 15 if (self.s["layout"] == "vn" and self.s["vn_auto"]) else CAPTURE_DELAY_MS
        self.root.after(delay, lambda: threading.Thread(
            target=self._work, args=(gen, rect, dpi, cancel, auto), daemon=True).start())

    def _work(self, gen, rect, dpi, cancel, auto=True):
        try:
            if cancel.is_set():
                return
            img = grab(rect)
            fresh = (not auto) and self.s["layout"] == "vn"  # hotkey re-scan in VN mode: skip the cache
            items, cached = self.pipeline.process(
                img, cancel, lambda st, msg: self.q.put(("status", gen, st, msg)), scale=dpi / 96.0,
                use_cache=not fresh)
            self.q.put(("done", gen, rect, dpi, items, cached))
        except Cancelled:
            log.info("Job %d cancelled", gen)
        except Exception as e:
            log.exception("Job failed")
            self.q.put(("error", gen, str(e)[:160]))


def demo_items(rect):
    """Calibration boxes 20px inside each corner + centre: checks capture rect and DPI mapping."""
    _x, _y, w, h = rect
    bw, bh, m = 180, 60, 20
    spots = {
        "Top-left": (m, m), "Top-right": (w - m - bw, m), "Centre": ((w - bw) / 2, (h - bh) / 2),
        "Bottom-left": (m, h - m - bh), "Bottom-right": (w - m - bw, h - m - bh),
    }
    return [{"text": k, "type": "bubble", "box": [x, y, x + bw, y + bh],
             "translation": f"{k}: 20px from the edge"} for k, (x, y) in spots.items()]

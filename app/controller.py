"""Tk main loop: receives hotkeys / scroll events, runs jobs on worker threads, draws results."""
import logging
import queue
import threading
import tkinter as tk

from . import winapi
from .api import Cancelled
from .api import SERVER_NAMES
from .api_dialog import ApiDialog, short_model
from .hotkeys import InputWatcher
from .overlay import Overlay, StatusPill
from .pipeline import Pipeline, grab
from .region import RegionSelector
from .toolbar import LANG_CYCLE, Toolbar

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
        self.overlay = Overlay(self.root, settings)
        self.status = StatusPill(self.root)
        self.pipeline = Pipeline(settings)
        self.q = queue.Queue()
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
        self.watcher = InputWatcher(
            {"translate": settings["hotkey_translate"], "hide": settings["hotkey_hide"],
             "pause": settings["hotkey_pause"], "quit": settings["hotkey_quit"],
             "mode": settings["hotkey_mode"], "region": settings["hotkey_region"]},
            on_hotkey=lambda name: self.q.put(("hotkey", name)),
            on_scroll=lambda x, y: self.q.put(("scroll", x, y)),
        )

    # ------------------------------------------------------------ lifecycle
    def run(self):
        self.watcher.start()
        self.root.after(30, self._poll)
        self.toolbar.show()
        if not self.s.has_credentials() and not self.demo:
            self._ask_credentials()
        else:
            self._status("ready", "Ready", auto_hide=2000)
        self.root.mainloop()

    def quit(self):
        self._cancel_job()
        self.watcher.stop()
        self.root.quit()

    def _ask_credentials(self, then=None):
        if self._cred_win and self._cred_win.winfo_exists():
            self._cred_win.lift()
            return
        self._cred_win = ApiDialog(self.root, self.s, on_saved=lambda: (self.on_api_saved(), then and then())).win

    # ------------------------------------------------------------ event loop
    def _poll(self):
        try:
            while True:
                ev = self.q.get_nowait()
                try:
                    self._dispatch(ev)
                except Exception:
                    log.exception("Event %s failed", ev[0])
        except queue.Empty:
            pass
        if self.overlay.visible != self._overlay_vis:
            self._overlay_vis = self.overlay.visible
            self.toolbar.refresh()
        self._fg_tick += 1
        if self._fg_tick % 5 == 0:  # ~150 ms: remember the window the user is reading in
            fg = winapi.foreground_window()
            if fg and not winapi.is_own_window(fg):
                self.target_hwnd = winapi.root_window(fg)
        self.root.after(30, self._poll)

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
        elif kind == "scroll":
            self._on_scroll(ev[1], ev[2])
        elif kind == "status":
            _, gen, state, text = ev
            if gen == self.gen:
                self._status(state, text)
            self.toolbar.refresh()  # model / server may have been switched automatically
        elif kind == "done":
            _, gen, rect, dpi, items, cached = ev
            if gen != self.gen:
                log.info("Job %d finished but was superseded; result dropped", gen)
                return
            log.info("Job %d done: %d items%s", gen, len(items), " (cached)" if cached else "")
            self.busy = False
            if not items:
                self._status("info", "No text found", auto_hide=2500)
                return
            self.overlay.show_items(rect, items, dpi)
            self.toolbar.raise_()
            self.last = (rect, items, dpi)
            n = sum(1 for it in items if it.get("translation"))
            self._status("ready", f"Ready · {n} bubble" + ("s" if n != 1 else "") + (" (cached)" if cached else ""), auto_hide=2000)
        elif kind == "error":
            _, gen, msg = ev
            if gen == self.gen:
                self.busy = False
                self._status("error", f"Error: {msg}", auto_hide=8000)

    def _status(self, state, text, auto_hide=None):
        self.toolbar.set_status(state, text, auto_hide)
        # The toolbar is the main indicator; the pill near the page is optional (always for errors)
        if self.s["show_status_pill"] or state == "error" or (self.toolbar.collapsed and state != "info"):
            self.status.set(state, text, self.rect, self.dpi, auto_hide)

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
        self.gen += 1
        if self.cancel:
            self.cancel.set()
        self.cancel = None
        if self.busy:
            self.busy = False
            self.toolbar.set_status("idle", "", hold_ms=1)  # drop "Scanning…"

    # ------------------------------------------------------------ capture region
    def _region(self):
        r = self.s["region"]
        if self.s["capture_mode"] == "region" and isinstance(r, (list, tuple)) and len(r) == 4:
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
        RegionSelector(self.root, self._region_done, current=self.s["region"])

    def _region_done(self, rect):
        self.selecting = False
        if rect:
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

    def set_model(self, model):
        self.s.update(**{f"{self.s['server']}_model": model})
        self.toolbar.refresh()
        self._status("info", "Model: " + short_model(model), auto_hide=1800)

    def set_mode(self, mode):
        if self.s["mode"] != mode:
            self.toggle_mode()

    def set_layout(self, layout):
        if self.s["layout"] != layout:
            self.toggle_layout()

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
        return f"Hotkey: {self.s['hotkey_translate'].upper()} to translate"

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
        if self.paused or self.selecting:
            return
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
            self._status("paused", "Paused · press " + self.s["hotkey_pause"].upper() + " to resume",
                         auto_hide=2500)
            return
        if not self.s.has_credentials() and not self.demo:
            if not auto:
                self._ask_credentials(then=self.translate)
            return
        region = self._region()
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
        gen, cancel = self.gen, threading.Event()
        self.cancel, self.busy = cancel, True
        log.info("Job %d start (%s): rect %s dpi %s", gen, "auto" if auto else "manual", rect, dpi)
        if self.demo:
            self.q.put(("done", gen, rect, dpi, demo_items(rect), False))
            return
        self._status("scanning", "Scanning…")
        self.root.after(CAPTURE_DELAY_MS, lambda: threading.Thread(
            target=self._work, args=(gen, rect, dpi, cancel), daemon=True).start())

    def _work(self, gen, rect, dpi, cancel):
        try:
            if cancel.is_set():
                return
            img = grab(rect)
            items, cached = self.pipeline.process(
                img, cancel, lambda st, msg: self.q.put(("status", gen, st, msg)), scale=dpi / 96.0)
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

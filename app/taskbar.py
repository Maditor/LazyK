"""A taskbar button for LazyK.

Every real window of the app is a tool window or an overlay without a taskbar entry. This is one more
window, kept minimized, whose only job is to be that button:
  * right-click → "Close window" quits the app (WM_DELETE_WINDOW),
  * a click brings the toolbar back (it also shows it again when it was hidden with the toolbar key),
  * while the toolbar is hidden the button is hidden too (set_visible): the tray icon takes over,
  * the hover text is the title: it carries the last error while the toolbar is hidden.
"""
import tkinter as tk


class TaskbarButton:
    def __init__(self, root, on_click, on_close):
        self.on_click = on_click
        self._ready = False
        self.win = tk.Toplevel(root)
        self.win.title("LazyK")
        self.win.geometry("260x60")
        self.win.protocol("WM_DELETE_WINDOW", on_close)
        self.win.bind("<Map>", self._mapped)
        self.win.iconify()
        self.win.after(400, self._arm)

    def _arm(self):
        self._ready = True

    def _mapped(self, _e=None):
        """The user clicked the taskbar button: Windows restored this window. Minimize it again and act."""
        if not self._ready:
            return
        try:
            if self.win.state() != "normal":
                return
            self.win.iconify()
        except tk.TclError:
            return
        self.on_click()

    def set_visible(self, visible):
        """Hide the taskbar button (withdrawn window) while the toolbar is hidden, bring it back after."""
        try:
            if visible:
                if self.win.state() == "withdrawn":
                    self._ready = False  # the restore below must not count as a click
                    self.win.iconify()
                    self.win.after(400, self._arm)
            else:
                self.win.withdraw()
        except tk.TclError:
            pass

    def set_title(self, message=""):
        try:
            self.win.title(f"LazyK — {message[:90]}" if message else "LazyK")
        except tk.TclError:
            pass

    def destroy(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass

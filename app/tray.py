"""System tray icon for LazyK (pystray).

Right-click menu: Show / Hide toolbar (same key as the hotkey) and Quit. A left click does the same as
the first menu entry. pystray runs its own thread, so nothing here touches Tk: every action only
calls the callbacks given by the app, which put an event in the app's queue.
"""
import logging

log = logging.getLogger(__name__)


class TrayIcon:
    def __init__(self, image_path, on_toggle, on_quit, is_hidden, key_text):
        """on_toggle / on_quit: called from the tray thread. is_hidden() -> bool, key_text() -> 'Alt+Shift+H'."""
        self.image_path = image_path
        self.on_toggle, self.on_quit = on_toggle, on_quit
        self.is_hidden, self.key_text = is_hidden, key_text
        self.icon = None

    def _toggle_text(self, _item=None):
        verb = "Show" if self.is_hidden() else "Hide"
        key = self.key_text()
        return f"{verb} toolbar\t{key}" if key else f"{verb} toolbar"

    def start(self) -> bool:
        """False when the tray cannot be created (pystray missing, no Windows shell...)."""
        try:
            import pystray
            from PIL import Image
            img = Image.open(self.image_path).convert("RGBA").resize((64, 64), Image.LANCZOS)
            menu = pystray.Menu(
                pystray.MenuItem(self._toggle_text, lambda: self.on_toggle(), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit LazyK", lambda: self.on_quit()),
            )
            self.icon = pystray.Icon("LazyK", img, "LazyK", menu)
            self.icon.run_detached()
            return True
        except Exception:
            log.warning("Tray icon unavailable (is pystray installed? run setup.bat)", exc_info=True)
            self.icon = None
            return False

    def refresh(self):
        """The menu text depends on the toolbar state: rebuild it."""
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                log.debug("Tray menu update failed", exc_info=True)

    def set_title(self, message=""):
        """Hover text; carries the last error while the toolbar is hidden."""
        if self.icon:
            try:
                self.icon.title = f"LazyK — {message[:90]}" if message else "LazyK"
            except Exception:
                log.debug("Tray title update failed", exc_info=True)

    def stop(self):
        """pystray's thread is not a daemon: without this the process would stay alive after Quit."""
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                log.debug("Tray stop failed", exc_info=True)
            self.icon = None

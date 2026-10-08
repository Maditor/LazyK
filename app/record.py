"""Temporary record of the translations of this session (record-lazyk.txt, next to settings.json).

Only the translated text is kept, one block per scan, so it can be read again. The file belongs to the
session: it is emptied at start and deleted when LazyK quits. Every call is best effort and never raises.
"""
import atexit
import logging
import os
import time

from .config import app_dir

log = logging.getLogger(__name__)
FILE_NAME = "record-lazyk.txt"


class Record:
    def __init__(self, settings):
        self.s = settings
        self.path = os.path.join(app_dir(), FILE_NAME)
        self.count = 0
        self._last = None
        self.clear()  # a file left by a crashed session is not this session's
        atexit.register(self.clear)  # safety net if the app ends without going through quit()

    def add(self, items):
        """Append the translations of one scan. Returns True if something was written."""
        try:
            if not self.s["record_enabled"]:
                return False
            lines = []
            for it in items or []:
                t = " ".join(str(it.get("translation") or "").split())
                if t:
                    lines.append(t)
            if not lines or lines == self._last:  # the same text scanned again is not recorded twice
                return False
            self._last = lines
            self.count += 1
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(f"=== #{self.count} · {time.strftime('%H:%M:%S')} ===\n")
                for i, t in enumerate(lines, 1):
                    f.write(f"{i}. {t}\n" if len(lines) > 1 else f"{t}\n")
                f.write("\n")
            return True
        except Exception:
            log.exception("Could not write the translation record")
            return False

    def exists(self) -> bool:
        return os.path.isfile(self.path)

    def open(self) -> bool:
        """Open the record in the default text editor. False when there is nothing to show."""
        try:
            if not self.exists():
                return False
            os.startfile(self.path)  # Windows
            return True
        except Exception:
            log.exception("Could not open the translation record")
            return False

    def clear(self):
        try:
            if os.path.isfile(self.path):
                os.remove(self.path)
        except OSError as e:
            log.info("Could not delete the translation record: %s", e)
        self._last = None
        self.count = 0

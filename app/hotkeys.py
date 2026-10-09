"""Global hotkeys and scroll watching via pynput, matched by virtual-key code (layout-safe)."""
import logging
import sys

from pynput import keyboard, mouse

log = logging.getLogger(__name__)

MOD_KEYS = {
    "ctrl": {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "alt": {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr},
    "shift": {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r},
    "win": {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
}
NAMED_VK = {
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "enter": 0x0D, "tab": 0x09, "backspace": 0x08,
    "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "insert": 0x2D, "delete": 0x2E,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC,
}
NAMED_VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})
SCROLL_VKS = {0x21, 0x22, 0x23, 0x24, 0x26, 0x28, 0x20}  # PgUp PgDn End Home Up Down Space

# Mouse buttons that can be bound (left / right stay free for normal use).
# mouse4 / mouse5 = the side buttons (back / forward), mouse3 = wheel click.
MOUSE_TOKENS = {"mouse3": "Mouse 3 (wheel click)", "mouse4": "Mouse 4 (side, back)",
                "mouse5": "Mouse 5 (side, forward)"}
_WM_MBUTTONDOWN, _WM_MBUTTONUP = 0x0207, 0x0208
_WM_XBUTTONDOWN, _WM_XBUTTONUP = 0x020B, 0x020C
VK_NAMES = {v: k for k, v in NAMED_VK.items() if k != "escape"}


def pretty(spec: str) -> str:
    """'alt+shift+t' -> 'Alt+Shift+T', 'mouse4' -> 'Mouse 4 (side, back)'."""
    out = []
    for p in str(spec).replace(" ", "").split("+"):
        if not p:
            continue
        p = p.lower()
        out.append(MOUSE_TOKENS.get(p) or {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win",
                                           "esc": "Esc", "pageup": "PgUp", "pagedown": "PgDn"}.get(p, p.upper()))
    return "+".join(out)


def parse_hotkey(spec: str):
    """'alt+shift+t' -> (frozenset({'alt','shift'}), vk). vk is a str ('mouse4') for mouse buttons."""
    parts = [p.strip().lower() for p in str(spec).replace(" ", "").split("+") if p.strip()]
    mods, vk = set(), None
    for p in parts:
        p = {"control": "ctrl", "cmd": "win", "super": "win"}.get(p, p)
        if p in MOD_KEYS:
            mods.add(p)
        elif p in MOUSE_TOKENS:
            vk = p                      # a mouse button instead of a key
        elif p in NAMED_VK:
            vk = NAMED_VK[p]
        elif len(p) == 1 and p.isalnum():
            vk = ord(p.upper())
        else:
            raise ValueError(f"Unknown key '{p}' in hotkey '{spec}'")
    if vk is None:
        raise ValueError(f"Hotkey '{spec}' has no main key")
    return frozenset(mods), vk


def _vk_of(key):
    if isinstance(key, keyboard.KeyCode):
        return key.vk
    try:
        return key.value.vk
    except AttributeError:
        return None


class InputWatcher:
    """Calls on_hotkey(name) for bindings and on_scroll(x, y) for wheel / navigation keys."""

    def __init__(self, bindings: dict, on_hotkey, on_scroll=None):
        self.on_hotkey = on_hotkey
        self.on_scroll = on_scroll
        self.held = set()
        self.bindings = {}
        self._capture = None      # callback(spec | None) while the user picks a new key
        self._swallow_up = set()  # mouse buttons whose release must also be hidden from the browser
        self.set_bindings(bindings)
        self._kb = None
        self._ms = None

    def set_bindings(self, bindings: dict):
        parsed = {}
        for name, spec in bindings.items():
            try:
                parsed[parse_hotkey(spec)] = name
            except ValueError as e:
                log.error("%s", e)
        self.bindings = parsed

    def capture_next(self, callback):
        """The next key (with modifiers) or side / wheel mouse button is not a hotkey but the answer:
        callback(spec) is called from the listener thread; Esc gives callback(None)."""
        self.held.clear()
        self._capture = callback

    def cancel_capture(self):
        self._capture = None

    def _finish_capture(self, spec):
        cb, self._capture = self._capture, None
        if cb:
            cb(spec)

    def _mods(self):
        return frozenset(m for m, keys in MOD_KEYS.items() if self.held & keys)

    def _press(self, key):
        if any(key in keys for keys in MOD_KEYS.values()):
            self.held.add(key)
            return
        vk = _vk_of(key)
        if vk is None:
            return
        mods = self._mods()
        if self._capture:
            if vk == 0x1B and not mods:
                self._finish_capture(None)
                return
            base = VK_NAMES.get(vk) or (chr(vk).lower() if 0x30 <= vk <= 0x5A else None)
            if base:
                order = [m for m in ("ctrl", "alt", "shift", "win") if m in mods]
                self._finish_capture("+".join(order + [base]))
            return
        name = self.bindings.get((mods, vk))
        if name:
            self.on_hotkey(name)
        elif not mods and vk in SCROLL_VKS and self.on_scroll:
            self.on_scroll(None, None)

    def _release(self, key):
        self.held.discard(key)
        if key in MOD_KEYS["alt"]:
            self.held -= MOD_KEYS["alt"]  # AltGr / lost releases

    def _wheel(self, x, y, _dx, _dy):
        if self.on_scroll:
            self.on_scroll(x, y)

    def _mouse_filter(self, msg, data):
        """Windows low-level mouse hook. A bound side / wheel button runs its action and is hidden
        from the browser (otherwise Mouse 4 / 5 would also go Back / Forward). Always returns True
        so pynput's own handlers still see the other events."""
        if msg in (_WM_XBUTTONDOWN, _WM_XBUTTONUP):
            token = {1: "mouse4", 2: "mouse5"}.get((data.mouseData >> 16) & 0xFFFF)
            down = msg == _WM_XBUTTONDOWN
        elif msg in (_WM_MBUTTONDOWN, _WM_MBUTTONUP):
            token, down = "mouse3", msg == _WM_MBUTTONDOWN
        else:
            return True
        if token is None:
            return True
        if not down and token in self._swallow_up:
            self._swallow_up.discard(token)
            self._ms.suppress_event()
        if down:
            if self._capture:
                self._swallow_up.add(token)
                self._finish_capture("+".join([m for m in ("ctrl", "alt", "shift", "win")
                                               if m in self._mods()] + [token]))
                self._ms.suppress_event()
            name = self.bindings.get((self._mods(), token))
            if name:
                self._swallow_up.add(token)
                self.on_hotkey(name)
                self._ms.suppress_event()
        return True

    def start(self):
        self._kb = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._kb.daemon = True
        self._kb.start()
        kw = {"win32_event_filter": self._mouse_filter} if sys.platform == "win32" else {}
        self._ms = mouse.Listener(on_scroll=self._wheel, **kw)
        self._ms.daemon = True
        self._ms.start()

    def ensure_alive(self):
        """Restart a listener whose thread ended (an error inside pynput stops it for good)."""
        restarted = []
        if self._kb is not None and not self._kb.is_alive():
            self._kb = keyboard.Listener(on_press=self._press, on_release=self._release)
            self._kb.daemon = True
            self._kb.start()
            restarted.append("keyboard")
        if self._ms is not None and not self._ms.is_alive():
            kw = {"win32_event_filter": self._mouse_filter} if sys.platform == "win32" else {}
            self._ms = mouse.Listener(on_scroll=self._wheel, **kw)
            self._ms.daemon = True
            self._ms.start()
            restarted.append("mouse")
        return restarted

    def stop(self):
        for l in (self._kb, self._ms):
            if l:
                l.stop()

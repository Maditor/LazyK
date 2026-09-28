"""Global hotkeys and scroll watching via pynput, matched by virtual-key code (layout-safe)."""
import logging

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


def parse_hotkey(spec: str):
    """'alt+shift+t' -> (frozenset({'alt','shift'}), vk)."""
    parts = [p.strip().lower() for p in str(spec).replace(" ", "").split("+") if p.strip()]
    mods, vk = set(), None
    for p in parts:
        p = {"control": "ctrl", "cmd": "win", "super": "win"}.get(p, p)
        if p in MOD_KEYS:
            mods.add(p)
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

    def start(self):
        self._kb = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._kb.daemon = True
        self._kb.start()
        if self.on_scroll:
            self._ms = mouse.Listener(on_scroll=self._wheel)
            self._ms.daemon = True
            self._ms.start()

    def stop(self):
        for l in (self._kb, self._ms):
            if l:
                l.stop()

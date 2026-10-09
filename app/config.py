"""Settings stored in settings.json next to the executable (or main.py)."""
import json
import os
import sys
import threading

APP_NAME = "LazyK"
APP_CREDIT = "LazyK by Maditor"
APP_URL = "https://github.com/Maditor/LazyK"


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def icon_path(on_dark: bool) -> str:
    """Logo that stands out without shouting: light bubble on dark UI, graphite bubble on light UI."""
    return resource_path("assets/icon_on_dark.png" if on_dark else "assets/icon_on_light.png")


def resource_path(rel: str) -> str:
    """Path to a bundled resource (works for PyInstaller and source runs)."""
    base = getattr(sys, "_MEIPASS", app_dir())
    return os.path.join(base, rel)


DEFAULTS = {
    # API servers
    "server": "gemini",             # gemini | cloudflare
    "gemini_api_key": "",
    "gemini_models": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash",
                      "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash-preview"],
    "gemini_model": "gemini-3.5-flash-lite",
    "cf_account_id": "",
    "cf_api_token": "",
    "cloudflare_models": ["@cf/google/gemma-4-26b-a4b-it", "@cf/qwen/qwen3.8-27b"],
    "cloudflare_model": "@cf/google/gemma-4-26b-a4b-it",
    "auto_switch_model": True,      # busy / out of quota -> next model in the list
    "auto_switch_server": True,     # server out of quota / bad key -> the other server
    # Reading the page (OCR)
    "ocr_engine": "ai",             # ai (the server above reads the image) | local (this PC reads it)
    "local_gpu": False,             # local OCR on a graphics card (DirectML); false = CPU (default: small models are faster on the CPU)
    "local_gpu_id": 0,              # which card: DirectML device number (0 = the Windows default card)
    "local_manga_ocr": True,        # Japanese: re-read blocks with manga-ocr when it is downloaded
    "translator": "ai",             # with local OCR: ai (Gemini / Cloudflare) | google (Google Translate, no key)
    # Languages / content
    "source_lang": "auto",          # auto | ja | ko | zh | en
    "target_lang": "Vietnamese",
    "layout": "manga",              # manga (right->left) | webtoon (left->right) | vn (visual novel text box)
    "skip_sfx": True,
    # Trigger mode
    "mode": "auto",                 # auto (translate after scrolling stops) | hotkey
    "scroll_delay_ms": 700,         # quiet time after the last scroll before capturing
    "auto_apps": ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
                  "vivaldi.exe", "browser.exe"],  # browser.exe = Coc Coc / Yandex
    # Hotkeys
    "hotkey_mode": "alt+shift+a",   # switch Auto <-> Hotkey
    "hotkey_translate": "alt+t",
    "hotkey_hide": "esc",
    "hotkey_pause": "alt+shift+t",
    "hotkey_region": "alt+shift+r",  # draw a capture frame
    "hotkey_vn_auto": "alt+shift+v",  # visual novel: auto-scan on / off
    "hotkey_toolbar": "alt+shift+h",  # hide / show the toolbar (every function keeps working)
    "taskbar_icon": True,           # a taskbar button: right-click → Close window quits, click shows the toolbar
    "hotkey_quit": "ctrl+alt+q",    # until the tray icon exists (step 2)
    "hide_on_scroll": True,
    "scroll_watch": True,           # also detect scrolling by watching the page (touchpad, scrollbar drag)
    # Visual novel mode
    "vn_region": None,              # [x, y, w, h] physical px: the game's text box
    "vn_auto": False,               # scan by itself when the text in the box changes (own on / off)
    "vn_poll_ms": 100,              # how often the text box is looked at while auto-scan is on
    "vn_stable_ms": 200,            # text must stay unchanged this long (typewriter effect) before a scan
                                    # (AI reading the image: at least 350, a scan started too early costs quota)
    "vn_change_pct": 0.3,           # % of the box that must change to count as new text (raise it if a big icon blinks)
    "vn_max_width": 1000,           # image width sent to the AI
    "vn_game_colors": True,         # auto-detect the background colour (all layouts: manga, webtoon, visual novel) and paint the translation in it
    # Capture
    "capture_mode": "window",       # window (browser page area) | region (frame drawn by the user)
    "region": None,                 # [x, y, w, h] physical px of the drawn frame
    "browser_top_crop": 0,          # logical px cut from the top when no browser content area is found
    # OCR
    "box_format": "auto",           # auto (detect from pixels) | yxyx | xyxy
    "max_slice_width": 1200,
    "manga_tiles": True,            # manga: send the page as overlapping upscaled tiles (reads small text)
    "ocr_concurrency": 3,
    # Overlay look
    "overlay_bg": "#ffffff",
    "overlay_fg": "#111111",
    "overlay_outline": "",          # e.g. "#cccccc"; empty = none
    "overlay_opacity": 100,         # % of the box background that is solid; lower = the screen shows through
    "overlay_blur": 0,              # px: blur of the screen seen through a see-through box (frosted glass)
    "overlay_shadow": False,
    "hover_hide": True,             # mouse over a translated box hides that box until the mouse leaves
    "developer_mode": False,        # tool windows (toolbar, menus, status, overlay) are visible to OBS & co
    "overlay_in_screenshots": True,  # Print Screen / Snipping Tool can capture the translated page
    "font_family": "Segoe UI",
    "font_bold": True,
    "font_min": 14,                 # reading size in logical px: overlay text never gets smaller
    "font_max": 22,
    "auto_text_size": True,
    "presets": [],                  # [{"name", "values"}]: see presets.py
    "preset_active": "",            # the preset picked last ("" = none)         # text may grow up to 1.6x in roomy boxes; off = always font_min
    "corner_radius": 10,
    "box_padding": 6,
    # Toolbar
    "toolbar_pos": None,            # [x, y] physical px, remembered after dragging
    "toolbar_collapsed": False,
    "show_status_pill": False,      # the toolbar already shows the status
    # Text to speech (Edge voices)
    "tts_enabled": False,           # read the translation aloud after each translation
    "tts_voice": "auto",            # auto = by target_lang, or a voice name such as vi-VN-NamMinhNeural
    "tts_speed": 100,               # % of normal speed (50-200)
    "tts_volume": 100,              # % of the system volume (0-100)
    # Session record of the translations (record-lazyk.txt next to settings.json, deleted when LazyK quits)
    "record_enabled": True,
    # Diagnostics
    "debug_save": False,
}


class Settings:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(app_dir(), "settings.json")
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                self.data.update({k: v for k, v in saved.items() if k in DEFAULTS or k.startswith("_")})
                self.load_migrate(saved)
        except FileNotFoundError:
            self.save()
        except Exception:
            # Corrupt file: keep defaults, keep a backup of the broken one
            try:
                os.replace(self.path, self.path + ".bad")
            except OSError:
                pass
            self.save()

    def save(self):
        with self._lock:
            try:
                from .presets import sync
                sync(self.data)  # the active preset follows every change (no "update" step)
            except Exception:
                pass
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def get(self, key, default=None):
        return self.data.get(key, default)

    def update(self, **kw):
        self.data.update(kw)
        self.save()

    def read_mode(self) -> str:
        """ai: the AI reads and translates | local_ai: this PC reads, AI translates |
        local_google: this PC reads, Google Translate translates (no API key at all)."""
        if self["ocr_engine"] != "local":
            return "ai"
        return "local_google" if self["translator"] == "google" else "local_ai"

    def needs_ai(self) -> bool:
        return self.read_mode() != "local_google"

    def has_credentials(self) -> bool:
        cf = bool(str(self["cf_account_id"]).strip() and str(self["cf_api_token"]).strip())
        return cf or bool(str(self["gemini_api_key"]).strip())

    def load_migrate(self, saved: dict):
        """Older versions stored the Cloudflare model as cf_model and used Cloudflare only."""
        if saved.get("_gpu_cpu_default") != 1:
            # the CPU became the default (DirectML is slower for these small models): switch once, the user can
            # turn the graphics card on again from the OCR device menu
            self.data["local_gpu"] = False
            self.data["_gpu_cpu_default"] = 1
        if saved.get("_vn_timing") != 2:
            # faster visual novel defaults (look 10x a second, scan after 0.2 s of still text): only replace
            # the old defaults, never a value the user chose
            if self.data.get("vn_poll_ms") == 200:
                self.data["vn_poll_ms"] = 100
            if self.data.get("vn_stable_ms") == 350:
                self.data["vn_stable_ms"] = 200
            self.data["_vn_timing"] = 2
        if saved.get("_font_scheme") != 2:
            # older versions shrank text below the chosen size; now font_min is the reading size
            self.data["font_min"] = max(int(self.data.get("font_min", 14)), 13)
            self.data["_font_scheme"] = 2
        if self.data.get("layout") not in ("manga", "webtoon", "vn"):
            self.data["layout"] = "manga"
        if self.data.get("ocr_engine") not in ("ai", "local"):
            self.data["ocr_engine"] = "ai"
        if self.data.get("translator") not in ("ai", "google"):
            self.data["translator"] = "ai"
        if self.data.get("server") not in ("gemini", "cloudflare"):
            self.data["server"] = "gemini"  # the local server option was removed
        if "cf_model" in saved and "cloudflare_model" not in saved:
            self.data["cloudflare_model"] = saved["cf_model"]
        if "server" not in saved and str(saved.get("cf_api_token", "")).strip() \
                and not str(saved.get("gemini_api_key", "")).strip():
            self.data["server"] = "cloudflare"

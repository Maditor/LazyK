"""Presets: named setups of how LazyK reads, translates and looks, picked from the toolbar.

* "Default" always exists and cannot be renamed or deleted.
* The active preset follows every change automatically: Settings.save() copies the current values into
  it (sync), so there is no "update" step. Picking another preset loads its values.
* A preset stores only the keys below (never API keys, hotkeys or window positions). They live in
  settings.json under "presets" as [{"name": ..., "values": {...}}]; "preset_active" is the one in use.
"""
import copy

DEFAULT = "Default"
KEYS = [
    # reading
    "layout", "mode", "capture_mode", "region", "vn_region", "vn_auto",
    # languages and engines
    "source_lang", "target_lang", "ocr_engine", "translator", "server", "local_gpu", "local_gpu_id",
    # look
    "font_family", "font_bold", "font_min", "auto_text_size", "overlay_fg", "overlay_bg", "vn_game_colors",
    "overlay_opacity", "overlay_blur", "hover_hide", "text_box", "text_box_rect",
    # text to speech
    "tts_enabled", "tts_engine", "tts_speed", "tts_volume", "tts_voice",
]
MAX_NAME = 32


def snapshot_data(data):
    return {k: copy.deepcopy(data.get(k)) for k in KEYS}


def sync(data):
    """Called on every save (raw settings dict): make sure Default exists and that the active preset
    holds the current values."""
    lst = [p for p in (data.get("presets") or []) if isinstance(p, dict) and p.get("name")]
    if not any(p["name"] == DEFAULT for p in lst):
        lst.insert(0, {"name": DEFAULT, "values": snapshot_data(data)})
    active = data.get("preset_active") or DEFAULT
    if not any(p["name"] == active for p in lst):
        active = DEFAULT
    for p in lst:
        if p["name"] == active:
            p["values"] = snapshot_data(data)
    data["presets"], data["preset_active"] = lst, active


def all_(s):
    """Default first, then the user's presets in the order they were made."""
    lst = [p for p in (s["presets"] or []) if isinstance(p, dict) and p.get("name")]
    return sorted(lst, key=lambda p: p["name"] != DEFAULT)


def active(s):
    name = s["preset_active"] or DEFAULT
    return name if get(s, name) else DEFAULT


def get(s, name):
    return next((p for p in all_(s) if p["name"] == name), None)


def clean_name(name):
    return " ".join(str(name or "").split())[:MAX_NAME]


def create(s, name):
    """A new preset holding the current setup; it becomes the active one."""
    name = clean_name(name)
    lst = [p for p in all_(s) if p["name"] != name]
    lst.append({"name": name, "values": snapshot_data(s.data)})
    s.update(presets=lst, preset_active=name)
    return name


def rename(s, old, new):
    if old == DEFAULT:
        return old
    new = clean_name(new)
    lst = all_(s)
    for p in lst:
        if p["name"] == old:
            p["name"] = new
    s.update(presets=lst, preset_active=new if s["preset_active"] == old else s["preset_active"])
    return new


def delete(s, name):
    if name == DEFAULT:
        return
    lst = [p for p in all_(s) if p["name"] != name]
    s.data["presets"] = lst  # the caller switches to Default (which also saves)

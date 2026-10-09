"""Target languages: one table for the menu, Google Translate, the AI prompt and the text-to-speech voice.
target_lang in settings.json stores the English name (it goes into the AI prompt as is)."""

# name (stored + used in the AI prompt), menu label, short code, Google code, Edge voice
TARGETS = [
    ("Vietnamese", "Tiếng Việt", "VI", "vi", "vi-VN-HoaiMyNeural"),
    ("English", "English", "EN", "en", "en-US-AriaNeural"),
    ("Japanese", "日本語", "JA", "ja", "ja-JP-NanamiNeural"),
    ("Korean", "한국어", "KO", "ko", "ko-KR-SunHiNeural"),
    ("Chinese (Simplified)", "中文 (简体)", "ZH", "zh-CN", "zh-CN-XiaoxiaoNeural"),
    ("Chinese (Traditional)", "中文 (繁體)", "ZH-TW", "zh-TW", "zh-TW-HsiaoChenNeural"),
    ("Thai", "ไทย", "TH", "th", "th-TH-PremwadeeNeural"),
    ("Indonesian", "Bahasa Indonesia", "ID", "id", "id-ID-GadisNeural"),
    ("Spanish", "Español", "ES", "es", "es-ES-ElviraNeural"),
    ("French", "Français", "FR", "fr", "fr-FR-DeniseNeural"),
    ("German", "Deutsch", "DE", "de", "de-DE-KatjaNeural"),
    ("Portuguese", "Português", "PT", "pt", "pt-BR-FranciscaNeural"),
    ("Russian", "Русский", "RU", "ru", "ru-RU-SvetlanaNeural"),
]
_BY_NAME = {t[0].lower(): t for t in TARGETS}
_BY_NAME["chinese"] = _BY_NAME["chinese (simplified)"]  # older settings stored just "Chinese"

SOURCES = [("auto", "Any (auto detect)", "Any"), ("ja", "Japanese", "JA"), ("ko", "Korean", "KO"),
           ("zh", "Chinese", "ZH"), ("en", "English", "EN")]


def target(name):
    """Row of TARGETS for a stored target_lang (Vietnamese when unknown)."""
    return _BY_NAME.get(str(name or "").strip().lower(), TARGETS[0])


def google_code(name):
    return target(name)[3]


def voice(name):
    return target(name)[4]


def short(name):
    return target(name)[2]


def source_short(code):
    return next((s[2] for s in SOURCES if s[0] == code), str(code).upper())

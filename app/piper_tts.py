"""Local read-aloud with Piper: a small neural voice that runs on this PC (no internet, no waiting).

The voice model is downloaded once (like the local OCR models) into the same models folder.
Piper reads one sentence at a time: the first sentence is ready in a few hundred ms and plays while the
next ones are made.
"""
import logging
import threading
import time

import numpy as np

from . import local_ocr

log = logging.getLogger(__name__)

# language (first two letters of the voice) -> Piper voice in rhasspy/piper-voices (all "medium").
# Japanese, Chinese and Thai voices need extra word-splitting libraries, so they use the online voice.
_VOICES = {
    "vi": ("vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium", "63 MB"),
    "en": ("en/en_US/lessac/medium/en_US-lessac-medium", "63 MB"),
    "ko": ("ko/ko_KR/kss/medium/ko_KR-kss-medium", "~65 MB"),
    "id": ("id/id_ID/news_tts/medium/id_ID-news_tts-medium", "~65 MB"),
    "es": ("es/es_ES/davefx/medium/es_ES-davefx-medium", "~65 MB"),
    "fr": ("fr/fr_FR/siwis/medium/fr_FR-siwis-medium", "~65 MB"),
    "de": ("de/de_DE/thorsten/medium/de_DE-thorsten-medium", "63 MB"),
    "pt": ("pt/pt_BR/faber/medium/pt_BR-faber-medium", "~65 MB"),
    "ru": ("ru/ru_RU/irina/medium/ru_RU-irina-medium", "~65 MB"),
}
_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
# language -> (pack, model file, size)
VOICES = {}
for _lang, (_path, _size) in _VOICES.items():
    _model = f"piper_{_lang}.onnx"
    local_ocr.FILES[_model] = [(_HF + _path + ".onnx", None)]
    local_ocr.FILES[_model + ".json"] = [(_HF + _path + ".onnx.json", None)]
    local_ocr.PACKS[f"piper_{_lang}"] = {"name": f"Local voice ({_lang})", "files": [_model, _model + ".json"],
                                         "size": _size}
    VOICES[_lang] = (f"piper_{_lang}", _model, _size)


def installed() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


PIP_ARGS = ["install", "--no-deps", "--disable-pip-version-check", "piper-tts==1.8.0", "pathvalidate"]


def can_install() -> bool:
    """Piper can be installed from inside the app when LazyK runs from Python (not the built exe)."""
    import sys
    return not getattr(sys, "frozen", False)


def install():
    """pip-install Piper into the Python LazyK runs on (--no-deps: no second onnxruntime). ~20 MB."""
    import importlib
    import subprocess
    import sys
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "pip"] + PIP_ARGS, capture_output=True, text=True,
                       creationflags=flags, timeout=600)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
        raise RuntimeError("pip failed: " + " | ".join(tail))
    importlib.invalidate_caches()
    log.info("TTS: Piper installed in %.1fs", time.time() - t0)
    if not installed():
        raise RuntimeError("Piper was installed but cannot be loaded")


def voice_for(lang: str):
    """(pack, model file, size) for a language, or None when there is no local voice for it."""
    return VOICES.get((lang or "")[:2].lower())


def ready(lang: str) -> bool:
    v = voice_for(lang)
    return bool(v) and local_ocr.pack_ready(v[0])


class Engine:
    def __init__(self):
        self._voices = {}             # model file -> PiperVoice
        self._lock = threading.Lock()  # espeak-ng and the model: one sentence at a time

    def _voice(self, lang):
        v = voice_for(lang)
        if not v:
            raise LookupError(f"no local voice for '{lang}'")
        if not local_ocr.pack_ready(v[0]):
            raise FileNotFoundError("the local voice is not downloaded")
        model = local_ocr.path(v[1])
        if model not in self._voices:
            from piper import PiperVoice
            t0 = time.time()
            self._voices[model] = PiperVoice.load(model, config_path=model + ".json")
            log.info("TTS: local voice loaded in %.2fs", time.time() - t0)
        return self._voices[model]

    def warm(self, lang):
        """Load the voice and make one short sound, so the first real sentence is fast."""
        from .tts import SAMPLES
        with self._lock:
            voice = self._voice(lang)
            for _ in voice.synthesize(SAMPLES.get(lang, "Hello.").split(",")[0]):
                pass

    def sentences(self, text, lang, speed_pct=100):
        """Yield (int16 samples, sample rate) one sentence at a time."""
        from piper import SynthesisConfig
        with self._lock:
            voice = self._voice(lang)
        base = voice.config.length_scale or 1.0
        cfg = SynthesisConfig(length_scale=base * 100.0 / max(50, min(200, speed_pct)))
        it = iter(voice.synthesize(text, syn_config=cfg))
        while True:
            with self._lock:
                try:
                    chunk = next(it)
                except StopIteration:
                    return
            yield chunk.audio_int16_array, chunk.sample_rate


ENGINE = Engine()


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    """int16 mono from src Hz to dst Hz (linear: fine for speech)."""
    if src == dst or not len(x):
        return x
    n = int(round(len(x) * dst / src))
    t = np.linspace(0, len(x) - 1, n)
    return np.interp(t, np.arange(len(x)), x.astype(np.float32)).astype(np.int16)


def write_wav(path, samples: np.ndarray, rate: int):
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype(np.int16).tobytes())


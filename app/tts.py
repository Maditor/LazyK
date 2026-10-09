"""Text to speech: read the translation aloud (optional, off by default).

Two voices: Piper on this PC (piper_tts.py, fast and steady) or Microsoft Edge's online neural voices
through the `edge-tts` package (free, no key, nicer but slow to answer). Sound goes out through miniaudio
(gapless), or the Windows MCI API when miniaudio is missing.

Everything here is best effort: a missing package, no network or no sound device only logs a warning and
(once) shows a short message. It never raises into the caller, so translation keeps working.
"""
import asyncio
import logging
import os
import re
import sys
import tempfile
import threading
import time
import unicodedata

log = logging.getLogger(__name__)

# The default voice follows target_lang (langs.TARGETS); "tts_voice" in settings.json overrides it.
_HAS_SPEECH = re.compile(r"\w", re.UNICODE)


def pick_voice(settings) -> str:
    v = str(settings["tts_voice"] or "").strip()
    if v and v.lower() != "auto":
        return v
    from .langs import voice
    return voice(settings["target_lang"])


def clean_texts(items) -> list:
    """Translations in the order given, skipping empty ones and lines with no letters / digits."""
    out = []
    for it in items or []:
        t = " ".join(str(it.get("translation") or "").split())
        if t and _HAS_SPEECH.search(t):
            out.append(t)
    return out


# ---------------------------------------------------------------- playback (Windows MCI)
class McPlayer:
    """Plays one mp3 file and returns when it ends or `stop` is set. Used from one thread only."""
    ALIAS = "lazyk_tts"

    def __init__(self):
        self._mci = None
        if sys.platform == "win32":
            import ctypes
            self._mci = ctypes.windll.winmm.mciSendStringW

    @property
    def available(self) -> bool:
        return self._mci is not None

    def _send(self, cmd: str) -> int:
        return self._mci(cmd, None, 0, None)

    def _status_mode(self) -> str:
        import ctypes
        buf = ctypes.create_unicode_buffer(64)
        self._mci(f"status {self.ALIAS} mode", buf, 63, None)
        return buf.value

    def warm(self, path: str):
        """Open and close a file once without playing it: Windows loads its mp3 decoder now."""
        if not self._mci:
            return
        try:
            alias = self.ALIAS + "_warm"
            if self._mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, None) == 0:
                self._mci(f"close {alias}", None, 0, None)
        except Exception:  # noqa: BLE001
            pass

    def play(self, path: str, stop: threading.Event, volume: int = 100):
        """volume: 0-100 (% of the system volume)."""
        if not self._mci:
            raise RuntimeError("Audio playback needs Windows")
        self._send(f"close {self.ALIAS}")
        if self._send(f'open "{path}" type mpegvideo alias {self.ALIAS}') != 0:
            raise RuntimeError("Could not open the audio file")
        try:
            self._send(f"setaudio {self.ALIAS} volume to {max(0, min(100, int(volume))) * 10}")  # best effort
            if self._send(f"play {self.ALIAS}") != 0:
                raise RuntimeError("Could not play the audio")
            time.sleep(0.05)
            while not stop.is_set() and self._status_mode() == "playing":
                time.sleep(0.04)
        finally:
            self._send(f"stop {self.ALIAS}")
            self._send(f"close {self.ALIAS}")


# ---------------------------------------------------------------- gapless playback (miniaudio)
try:
    import miniaudio as _ma
except Exception:  # noqa: BLE001  (not installed: the Windows MCI player is used)
    _ma = None


class PcmPlayer:
    """Plays 16-bit mono sound blocks back to back without gaps. The sound device stays open between
    readings (silence) and closes after IDLE_S without sound, so a reading starts without delay."""
    RATE = 24000
    IDLE_S = 300

    def __init__(self):
        if _ma is None:
            raise ImportError("miniaudio is not installed")
        self._ma = _ma
        self._dev = None
        self._lock = threading.Lock()
        self._pcm = []            # numpy int16 blocks waiting to be played
        self._last_sound = 0.0
        self._watch = None

    def _gen(self):
        import numpy as np
        need = yield b""
        while True:
            out = np.zeros(need, dtype=np.int16)
            got = 0
            with self._lock:
                while got < need and self._pcm:
                    blk = self._pcm[0]
                    k = min(need - got, len(blk))
                    out[got:got + k] = blk[:k]
                    got += k
                    if k == len(blk):
                        self._pcm.pop(0)
                    else:
                        self._pcm[0] = blk[k:]
                if got:
                    self._last_sound = time.time()
            need = yield out.tobytes()

    def open(self):
        with self._lock:
            if self._dev is not None:
                self._last_sound = max(self._last_sound, time.time())
                return
        ma = self._ma
        dev = ma.PlaybackDevice(output_format=ma.SampleFormat.SIGNED16, nchannels=1, sample_rate=self.RATE,
                                buffersize_msec=80, app_name="LazyK")
        g = self._gen()
        next(g)
        dev.start(g)
        with self._lock:
            if self._dev is not None:  # opened by another thread meanwhile
                dev.close()
                return
            self._dev = dev
            self._last_sound = time.time()
        if self._watch is None or not self._watch.is_alive():
            self._watch = threading.Thread(target=self._idle_close, daemon=True, name="tts-idle")
            self._watch.start()

    def _idle_close(self):
        while True:
            time.sleep(2)
            with self._lock:
                if self._dev is None:
                    return
                if self._pcm or time.time() - self._last_sound < self.IDLE_S:
                    continue
                dev, self._dev = self._dev, None
            try:
                dev.close()
            except Exception:  # noqa: BLE001
                pass
            return

    def push(self, samples, rate, volume=100, stop=None):
        """Queue int16 samples (any rate: converted to RATE). Nothing is queued once `stop` is set."""
        import numpy as np
        if not len(samples):
            return
        if rate != self.RATE:
            from .piper_tts import resample
            samples = resample(samples, rate, self.RATE)
        gain = max(0, min(100, int(volume))) / 100.0
        if gain < 0.999:
            samples = (samples.astype(np.float32) * gain).astype(np.int16)
        self.open()
        with self._lock:
            if stop is None or not stop.is_set():
                self._pcm.append(np.ascontiguousarray(samples, dtype=np.int16))

    def clear(self):
        with self._lock:
            self._pcm.clear()

    def drain(self, stop: threading.Event):
        """Wait until everything queued was heard, or `stop` (whoever stops also clears the queue)."""
        while not stop.is_set():
            with self._lock:
                if not self._pcm:
                    break
            time.sleep(0.03)
        if not stop.is_set():
            time.sleep(0.1)  # the device's own short buffer


def decode_mp3(path):
    """mp3 file -> int16 numpy samples at PcmPlayer.RATE."""
    import numpy as np
    d = _ma.decode_file(path, output_format=_ma.SampleFormat.SIGNED16, nchannels=1,
                        sample_rate=PcmPlayer.RATE)
    return np.frombuffer(d.samples.tobytes(), dtype=np.int16)


# ---------------------------------------------------------------- online voice (Microsoft Edge)
async def _synth(text, voice, rate, path):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate).save(path)


def synth_to_file(text, voice, rate, path):
    """One piece of text -> mp3 file. A network hiccup is retried once."""
    from edge_tts.exceptions import NoAudioReceived
    try:
        asyncio.run(_synth(text, voice, rate, path))
    except NoAudioReceived:
        raise
    except Exception as e:  # noqa: BLE001
        log.info("TTS: online request failed (%s: %s), trying again", type(e).__name__, e)
        asyncio.run(_synth(text, voice, rate, path))


_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
           "…": "...", " ": " "}


def sanitize(text: str) -> str:
    """Plain letters, digits and ordinary punctuation only: the service sometimes returns no audio for
    other symbols, emoji or invisible characters."""
    text = unicodedata.normalize("NFC", text)
    text = "".join(_QUOTES.get(c, c) for c in text)
    text = "".join(c for c in text if unicodedata.category(c)[0] not in "CS" or c in "+=%$")
    return " ".join(text.split())


def split_sentences(text: str) -> list:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text)]
    return [p for p in parts if p and _HAS_SPEECH.search(p)]


def synth_robust(text, voice, rate, path):
    """Like synth_to_file, but when the service answers "no audio" (it does that for some texts and
    sometimes at random) retry with cleaned text, then sentence by sentence."""
    from edge_tts.exceptions import NoAudioReceived
    try:
        return synth_to_file(text, voice, rate, path)
    except NoAudioReceived as e:
        log.warning("TTS: no audio for %r (%s); retrying with cleaned text", text[:200], voice)
        first = e
    clean = sanitize(text)
    if clean and _HAS_SPEECH.search(clean):
        try:
            return synth_to_file(clean, voice, rate, path)
        except NoAudioReceived:
            pass
    pieces = split_sentences(clean or text)
    if len(pieces) < 2 and clean:
        pieces = [clean]
    data = b""
    part = path + ".part"
    try:
        for p in pieces:
            try:
                synth_to_file(p, voice, rate, part)
            except NoAudioReceived:
                log.warning("TTS: skipped a sentence the service would not read: %r", p[:120])
                continue
            with open(part, "rb") as f:
                data += f.read()
    finally:
        try:
            os.remove(part)
        except OSError:
            pass
    if not data:
        raise first
    with open(path, "wb") as f:
        f.write(data)


def _cut(text: str, limit: int):
    """Split at the last comma / space before `limit` (or at `limit`)."""
    window = text[:limit]
    k = max(window.rfind(", "), window.rfind("; "), window.rfind(": "))
    if k < limit * 0.4:
        k = window.rfind(" ")
    if k < limit * 0.3:
        return text[:limit].strip(), text[limit:].strip()
    return text[:k + 1].strip(), text[k + 1:].strip()


def group_text(text: str, max_len: int = 400) -> list:
    """Whole sentences joined into pieces of up to max_len characters: one request per piece, so the
    voice keeps its natural flow and there are few waits between pieces."""
    pieces, cur = [], ""
    for sent in split_sentences(text) or [text]:
        while len(sent) > max_len:
            head, sent = _cut(sent, max_len)
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(head)
        if cur and len(cur) + 1 + len(sent) > max_len:
            pieces.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        pieces.append(cur)
    return [p for p in pieces if _HAS_SPEECH.search(p)]


def _int(value, default, lo, hi):
    try:
        v = int(float(str(value).strip().rstrip("%")))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def speed_pct(settings) -> int:
    return _int(settings["tts_speed"], 100, 50, 200)


def volume_pct(settings) -> int:
    return _int(settings["tts_volume"], 100, 0, 100)


SAMPLES = {"vi": "Xin chào, đây là giọng đọc thử.", "en": "Hello, this is a voice test.",
           "ja": "こんにちは、音声のテストです。", "ko": "안녕하세요, 음성 테스트입니다.", "zh": "你好，这是语音测试。",
           "th": "สวัสดี นี่คือการทดสอบเสียง", "id": "Halo, ini adalah tes suara.", "es": "Hola, esta es una prueba de voz.",
           "fr": "Bonjour, ceci est un test de voix.", "de": "Hallo, das ist ein Stimmtest.",
           "pt": "Olá, este é um teste de voz.", "ru": "Привет, это проверка голоса."}


def sample_text(settings) -> str:
    return SAMPLES.get(pick_voice(settings)[:2].lower(), SAMPLES["en"])


WINDOW = 3  # online pieces requested ahead of the one being played


class Speaker:
    """speak(items) replaces whatever is being read; stop() cuts it off at once.

    Two voices (settings "tts_engine"):
    - "local": Piper on this PC. Starts in a few hundred ms, no internet, same speed every time.
    - "online": Microsoft Edge voices. Nicer, but the service takes a few seconds per request, so each
      translation is asked in one piece and played only once it is complete: a later start, no stutter.
    `on_error(message)` is called (at most once per speak) when nothing at all could be read."""

    def __init__(self, settings, on_error=None, player=None, synth=synth_robust, on_need_local=None):
        self.s = settings
        self.on_error = on_error
        self.on_need_local = on_need_local  # starts installing / downloading the local voice
        self.player = player or McPlayer()
        self.pcm = None
        if player is None:
            try:
                self.pcm = PcmPlayer()
            except Exception as e:  # noqa: BLE001
                log.info("TTS: gapless playback not available (%s), using the Windows player", e)
        self.synth = synth
        self._lock = threading.Lock()
        self._gen = 0
        self._stop = threading.Event()
        self._tmp = None
        self._thread = None
        self._warmed = set()
        self._told = set()

    # -- public
    def engine(self) -> str:
        return "local" if str(self.s["tts_engine"]).lower() == "local" else "online"

    def _lang(self):
        return pick_voice(self.s)[:2].lower()

    def local_usable(self) -> bool:
        from . import piper_tts
        return self.engine() == "local" and piper_tts.ready(self._lang()) and piper_tts.installed()

    def warm(self):
        """Get the chosen voice ready in the background, so the first reading is not slow."""
        key = (self.engine(), self._lang())
        if key in self._warmed:
            return
        self._warmed.add(key)

        def work():
            from . import winapi
            winapi.lower_this_thread()
            try:
                if self.local_usable():
                    from . import piper_tts
                    piper_tts.ENGINE.warm(self._lang())
                else:
                    import edge_tts  # noqa: F401  (the first import takes a second or two)
                if self.pcm is not None:
                    self.pcm.open()
            except Exception as e:  # noqa: BLE001
                log.info("TTS warm-up skipped: %s", e)
        threading.Thread(target=work, daemon=True).start()

    def prepare(self):
        """A translation is on its way: have the voice and the sound device ready."""
        self.warm()
        if self.pcm is not None:
            threading.Thread(target=self._open_pcm, daemon=True).start()

    def _open_pcm(self):
        try:
            self.pcm.open()
        except Exception:  # noqa: BLE001
            log.debug("TTS: sound device not opened", exc_info=True)

    def speak(self, items_or_texts):
        try:
            texts = [t for t in items_or_texts if isinstance(t, str)] if items_or_texts and \
                isinstance(items_or_texts[0], str) else clean_texts(items_or_texts)
            texts = [" ".join(t.split()) for t in texts if t and _HAS_SPEECH.search(t)]
            if not texts:
                return
            with self._lock:
                self._gen += 1
                gen = self._gen
                self._stop.set()           # cut the previous reading
                self._stop = stop = threading.Event()
            if self.pcm is not None:
                self.pcm.clear()
            self._thread = threading.Thread(target=self._run, args=(gen, stop, texts, pick_voice(self.s)),
                                            daemon=True, name="tts")
            self._thread.start()
        except Exception:
            log.exception("TTS speak failed")

    def wait(self):
        """Block until the current reading ends (used by `main.py --tts`)."""
        th = self._thread
        if th:
            th.join()

    def stop(self):
        try:
            with self._lock:
                self._gen += 1
                self._stop.set()
            if self.pcm is not None:
                self.pcm.clear()
        except Exception:
            log.exception("TTS stop failed")

    # -- internals
    def _rate(self) -> str:
        return f"{speed_pct(self.s) - 100:+d}%"

    def _tmpdir(self):
        if not self._tmp or not os.path.isdir(self._tmp):
            self._tmp = tempfile.mkdtemp(prefix="lazyk_tts_")
        return self._tmp

    def _current(self, gen):
        return gen == self._gen

    def _tell_once(self, key, msg):
        if key not in self._told:
            self._told.add(key)
            if self.on_error:
                try:
                    self.on_error(msg)
                except Exception:  # noqa: BLE001
                    log.exception("TTS on_error failed")

    def _run(self, gen, stop, texts, voice):
        if self.engine() == "local":
            from . import piper_tts
            lang = voice[:2].lower()
            if not piper_tts.voice_for(lang):
                log.info("TTS: no local voice for '%s', using the online voice", lang)
            elif not piper_tts.installed() or not piper_tts.ready(lang):
                log.info("TTS: local voice not ready yet (Piper installed: %s, voice downloaded: %s): "
                         "online voice meanwhile", piper_tts.installed(), piper_tts.ready(lang))
                if self.on_need_local is not None:
                    try:
                        self.on_need_local()
                    except Exception:  # noqa: BLE001
                        log.exception("TTS: local voice setup could not start")
                else:
                    self._tell_once("dl", "Local voice not set up: Settings → Text to speech → Local voice")
            else:
                try:
                    self._run_local(gen, stop, texts, lang)
                    return
                except Exception as e:  # noqa: BLE001
                    log.warning("TTS: local voice failed (%s: %s), using the online voice", type(e).__name__, e,
                                exc_info=True)
                if stop.is_set() or not self._current(gen):
                    return
        self._run_online(gen, stop, texts, voice)

    # -- local (Piper)
    def _run_local(self, gen, stop, texts, lang):
        from . import piper_tts
        t0 = time.time()
        first = True
        speed, vol = speed_pct(self.s), volume_pct(self.s)
        # The voice is made a sentence at a time: a long first sentence is cut at a comma so the first
        # sound comes sooner (the rest is made while it plays, with no gap).
        sents = split_sentences(texts[0]) or [texts[0]]
        if len(sents[0]) > 90:
            head, tail = _cut(sents[0], 60)
            texts = [head, " ".join([tail] + sents[1:])] + list(texts[1:])
        for text in texts:
            parts = []
            for samples, rate in piper_tts.ENGINE.sentences(text, lang, speed):
                if stop.is_set() or not self._current(gen):
                    return
                if first:
                    log.info("TTS: first sound after %.2fs (local)", time.time() - t0)
                    first = False
                if self.pcm is not None:
                    self.pcm.push(samples, rate, vol, stop)
                else:
                    parts.append((samples, rate))
            if parts:  # no gapless player: one wav per translation, played by Windows
                import numpy as np
                path = os.path.join(self._tmpdir(), f"{gen}_local.wav")
                piper_tts.write_wav(path, np.concatenate([p for p, _ in parts]), parts[0][1])
                try:
                    self.player.play(path, stop, vol)
                finally:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        if self.pcm is not None:
            self.pcm.drain(stop)

    # -- online (Edge)
    def _run_online(self, gen, stop, texts, voice):
        chunks = [c for t in texts for c in group_text(t)]
        files, jobs = [], {}
        played = 0
        last_err = None
        t0 = time.time()
        try:
            def start(i):
                if i >= len(chunks) or i in jobs:
                    return
                path = os.path.join(self._tmpdir(), f"{gen}_{i}.mp3")
                files.append(path)
                box = {}
                rate = self._rate()

                def work():
                    try:
                        if not stop.is_set():
                            self.synth(chunks[i], voice, rate, path)
                    except Exception as e:  # noqa: BLE001
                        box["err"] = e
                th = threading.Thread(target=work, daemon=True)
                th.start()
                jobs[i] = (path, th, box)

            for k in range(WINDOW):
                start(k)
            for i in range(len(chunks)):
                start(i + WINDOW)
                path, th, box = jobs.pop(i)
                while th.is_alive() and not stop.is_set():
                    th.join(0.05)
                if stop.is_set() or not self._current(gen):
                    return
                if "err" in box:
                    if isinstance(box["err"], ImportError):
                        raise box["err"]
                    last_err = box["err"]
                    log.warning("TTS: skipped a piece (%s): %r", box["err"], chunks[i][:120])
                    continue
                if not played:
                    log.info("TTS: first sound after %.2fs (online)", time.time() - t0)
                if self.pcm is not None:
                    try:
                        self.pcm.push(decode_mp3(path), PcmPlayer.RATE, volume_pct(self.s), stop)
                    except Exception as e:  # noqa: BLE001
                        log.info("TTS: gapless playback failed (%s), using the Windows player", e)
                        self.pcm = None
                if self.pcm is None:
                    self.player.play(path, stop, volume_pct(self.s))
                played += 1
                if stop.is_set() or not self._current(gen):
                    return
            if self.pcm is not None and played:
                self.pcm.drain(stop)
            if not played and last_err:
                raise last_err
        except ImportError:
            log.warning("TTS: the 'edge-tts' package is not installed")
            self._fail(gen, "Text to speech: install edge-tts (run setup.bat)")
        except Exception as e:  # noqa: BLE001
            log.warning("TTS failed (%s): %s | text: %r", type(e).__name__, e, " | ".join(chunks)[:300])
            self._fail(gen, "Text to speech failed (check the internet connection)")
        finally:
            for p in files:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def _fail(self, gen, msg):
        if self.on_error and self._current(gen):
            try:
                self.on_error(msg)
            except Exception:
                log.exception("TTS on_error failed")

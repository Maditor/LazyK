"""Text to speech: read the translation aloud (optional, off by default).

Voices come from Microsoft Edge's online neural voices through the `edge-tts` package (free, no key).
Playback uses the Windows MCI API through ctypes, so no audio library is needed.

Everything here is best effort: a missing package, no network or no sound device only logs a warning and
(once) shows a short message. It never raises into the caller, so translation keeps working.
"""
import asyncio
import logging
import os
import queue
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


# ---------------------------------------------------------------- streaming playback (miniaudio)
try:
    import miniaudio as _ma
    _Source = _ma.StreamableSource
except Exception:  # noqa: BLE001  (not installed: StreamPlayer is not used)
    _ma, _Source = None, object


class Mp3Pipe(_Source):
    """mp3 bytes flowing from the network to the decoder. read() waits for data instead of ending."""

    def __init__(self, stop: threading.Event):
        self.stop = stop
        self._buf = bytearray()
        self._cond = threading.Condition()
        self._done = False

    def write(self, data: bytes):
        with self._cond:
            self._buf += data
            self._cond.notify_all()

    def finish(self):
        with self._cond:
            self._done = True
            self._cond.notify_all()

    def read(self, n: int) -> bytes:
        with self._cond:
            while not self._buf and not self._done and not self.stop.is_set():
                self._cond.wait(0.05)
            if self.stop.is_set():
                return b""
            out = bytes(self._buf[:n])
            del self._buf[:n]
            return out


class StreamPlayer:
    """Plays mp3 while it is still downloading: the voice starts with the first audio packet, and the
    pieces of one reading follow each other without a gap. The sound device stays open between readings
    (silence) and closes after IDLE_S without sound."""
    RATE = 24000   # Edge voices: 24 kHz mono
    IDLE_S = 30

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
        """Start the sound device now (a reading is coming), so the first sound is not delayed."""
        with self._lock:
            if self._dev is not None:
                self._last_sound = max(self._last_sound, time.time())
                return
        ma = self._ma
        dev = ma.PlaybackDevice(output_format=ma.SampleFormat.SIGNED16, nchannels=1, sample_rate=self.RATE,
                                buffersize_msec=60, app_name="LazyK")
        g = self._gen()
        next(g)
        dev.start(g)
        with self._lock:
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

    def play_stream(self, pipe: Mp3Pipe, stop: threading.Event, volume: int = 100):
        """Decode `pipe` and play it; returns when everything was heard or `stop` is set."""
        import numpy as np
        self.open()
        ma = self._ma
        gain = max(0, min(100, int(volume))) / 100.0
        gen = ma.stream_any(pipe, source_format=ma.FileFormat.MP3, output_format=ma.SampleFormat.SIGNED16,
                            nchannels=1, sample_rate=self.RATE, frames_to_read=1024)
        try:
            frames = next(gen)
            while not stop.is_set():
                if len(frames):
                    blk = np.frombuffer(frames, dtype=np.int16)
                    if gain < 0.999:
                        blk = (blk.astype(np.float32) * gain).astype(np.int16)
                    with self._lock:
                        self._pcm.append(blk.copy())
                frames = gen.send(1024)
        except StopIteration:
            pass
        finally:
            gen.close()
        # let the device play what is queued
        while not stop.is_set():
            with self._lock:
                if not self._pcm:
                    break
            time.sleep(0.03)
        if stop.is_set():
            with self._lock:
                self._pcm.clear()
        time.sleep(0.08)  # the device's own short buffer


# ---------------------------------------------------------------- the speaker
async def _synth(text, voice, rate, path):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate).save(path)


_FAST = {"ok": True}


def synth_to_file(text, voice, rate, path):
    """Over the kept-open connection (edge_fast) when possible: much shorter wait before each piece.
    Plain edge-tts (a new connection per piece) when that is not possible."""
    if _FAST["ok"]:
        from . import edge_fast
        try:
            return edge_fast.CLIENT.synth(text, voice, rate, path)
        except edge_fast.Unsupported as e:
            _FAST["ok"] = False
            log.info("TTS: fast connection not available with this edge-tts (%s)", e)
        except Exception as e:  # noqa: BLE001
            try:
                from edge_tts.exceptions import NoAudioReceived
                if isinstance(e, NoAudioReceived):
                    raise
            except ImportError:
                pass
            log.info("TTS: fast connection failed (%s: %s), using plain edge-tts", type(e).__name__, e)
    asyncio.run(_synth(text, voice, rate, path))


_QUOTES = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
           "\u2026": "...", "\u00a0": " "}


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
    try:
        from edge_tts.exceptions import NoAudioReceived
    except ImportError:
        raise
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


def chunk_text(text: str, first_max: int = 40, max_len: int = 160) -> list:
    """Short pieces to synthesise and play one after another. The first piece is small, so the voice
    starts quickly; the rest is synthesised while it plays."""
    pieces = []
    for sent in split_sentences(text) or [text]:
        while len(sent) > max_len:
            head, sent = _cut(sent, max_len)
            pieces.append(head)
        if sent:
            pieces.append(sent)
    if pieces and len(pieces[0]) > first_max:
        head, tail = _cut(pieces[0], first_max)
        pieces[0:1] = [p for p in (head, tail) if p]
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


WINDOW = 3  # chunks synthesised ahead of the one being played


class Speaker:
    """speak(items) replaces whatever is being read; stop() cuts it off at once (within ~40 ms).

    Each translation is cut into short chunks. The first one is small so the voice starts quickly, and the
    next WINDOW chunks are synthesised in parallel while one plays. `on_error(message)` is called (at most
    once per speak) from the worker thread when nothing at all could be read."""

    def __init__(self, settings, on_error=None, player=None, synth=synth_robust):
        self.s = settings
        self.on_error = on_error
        self.player = player or McPlayer()
        self.streamer = None
        if player is None:
            try:
                self.streamer = StreamPlayer()  # plays while downloading (miniaudio)
            except Exception as e:  # noqa: BLE001
                log.info("TTS: streaming playback not available (%s), using the Windows player", e)
        self.synth = synth
        self._lock = threading.Lock()
        self._gen = 0
        self._stop = threading.Event()
        self._tmp = None
        self._thread = None
        self._warmed = False

    # -- public
    def warm(self):
        """Load edge-tts and open a first connection in the background, so the first reading is not slow."""
        if self._warmed:
            return
        self._warmed = True

        def work():
            from . import winapi
            winapi.lower_this_thread()
            try:
                import edge_tts  # noqa: F401  (the first import takes a second or two)
                path = os.path.join(self._tmpdir(), "warm.mp3")
                self.synth("Xin chào.", pick_voice(self.s), "+0%", path)
                self.player.warm(path)  # the first audio open is slow: do it now, silently
                os.remove(path)
            except Exception as e:  # noqa: BLE001
                log.info("TTS warm-up skipped: %s", e)
        threading.Thread(target=work, daemon=True).start()

    def prepare(self):
        """A translation is on its way: open the voice connection and the sound device now."""
        try:
            from . import edge_fast
            if _FAST["ok"]:
                edge_fast.CLIENT.prepare()
            if self.streamer is not None:
                threading.Thread(target=self.streamer.open, daemon=True).start()
        except Exception:  # noqa: BLE001
            log.debug("TTS prepare failed", exc_info=True)

    def speak(self, items_or_texts):
        try:
            texts = [t for t in items_or_texts if isinstance(t, str)] if items_or_texts and \
                isinstance(items_or_texts[0], str) else clean_texts(items_or_texts)
            chunks = [c for t in texts for c in chunk_text(t)]
            if not chunks:
                return
            with self._lock:
                self._gen += 1
                gen = self._gen
                self._stop.set()           # cut the previous reading
                self._stop = stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(gen, stop, chunks, pick_voice(self.s)),
                                            daemon=True)
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

    def _run(self, gen, stop, chunks, voice):
        if self.streamer is not None and _FAST["ok"]:
            try:
                if self._run_stream(gen, stop, chunks, voice):
                    return
            except Exception as e:  # noqa: BLE001
                log.info("TTS: streaming failed (%s: %s), using files", type(e).__name__, e)
            if stop.is_set() or not self._current(gen):
                return
        self._run_files(gen, stop, chunks, voice)

    def _run_stream(self, gen, stop, chunks, voice) -> bool:
        """Fetch the pieces one after another over the open connection and play the audio as it comes.
        False = nothing could be streamed (the caller falls back to the file way)."""
        from . import edge_fast
        from edge_tts.exceptions import NoAudioReceived
        pipe = Mp3Pipe(stop)
        t0 = time.time()
        first = {}
        got = {"n": 0}

        def on_audio(data):
            if not first:
                first["t"] = time.time() - t0
            got["n"] += len(data)
            pipe.write(data)

        player = threading.Thread(target=self.streamer.play_stream, args=(pipe, stop, volume_pct(self.s)),
                                  daemon=True, name="tts-play")
        player.start()
        try:
            for i, text in enumerate(chunks):
                if stop.is_set() or not self._current(gen):
                    return True
                rate = self._rate()
                try:
                    edge_fast.CLIENT.stream(text, voice, rate, on_audio)
                except NoAudioReceived:
                    pass_no_audio = True
                except Exception:
                    if got["n"]:  # part of the reading was heard: stop here rather than start over
                        log.warning("TTS: connection lost in the middle of a reading", exc_info=True)
                        break
                    raise
                else:
                    pass_no_audio = False
                if pass_no_audio:
                    clean = sanitize(text)
                    try:
                        if clean and clean != text and _HAS_SPEECH.search(clean):
                            edge_fast.CLIENT.stream(clean, voice, rate, on_audio)
                        else:
                            raise NoAudioReceived("no audio")
                    except NoAudioReceived:
                        log.warning("TTS: skipped a piece the service would not read: %r", text[:120])
                if i == 0 and first:
                    log.info("TTS: first sound after %.2fs", first["t"])
        finally:
            pipe.finish()
        if not got["n"]:
            stop_now = threading.Event()
            pipe.stop = stop_now
            stop_now.set()
            player.join(1)
            return False
        player.join()
        return True

    def _run_files(self, gen, stop, chunks, voice):
        files, jobs = [], {}
        played = 0
        last_err = None
        try:
            def start(i):
                if i >= len(chunks) or i in jobs:
                    return
                path = os.path.join(self._tmpdir(), f"{gen}_{i}.mp3")
                files.append(path)
                box = {}
                rate = self._rate()  # the speed set now is used for chunks synthesised from now on

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
                th.join()
                if stop.is_set() or not self._current(gen):
                    return
                if "err" in box:
                    if isinstance(box["err"], ImportError):
                        raise box["err"]
                    last_err = box["err"]
                    log.warning("TTS: skipped a piece (%s): %r", box["err"], chunks[i][:120])
                    continue
                self.player.play(path, stop, volume_pct(self.s))
                played += 1
                if stop.is_set() or not self._current(gen):
                    return
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

"""Faster Edge read-aloud: one websocket kept open and reused for every piece.

edge-tts opens a brand-new secure websocket for each piece of text (DNS, TCP, TLS, websocket upgrade,
voice config): that setup is most of the wait before a short sentence starts. Here the connection is
opened ahead of time (when a scan starts) and every request goes over it; the service answers each
request with audio and a 'turn.end', and the connection stays usable for the next one.

If anything about the reuse fails (the service closed it, a newer edge-tts changed its internals),
the caller falls back to plain edge-tts, so reading aloud never breaks because of this module.
"""
import asyncio
import logging
import threading
import time
import uuid

log = logging.getLogger(__name__)

IDLE_S = 120     # a connection unused this long is not trusted any more: open a fresh one
TIMEOUT_S = 20   # one request must be answered within this
REUSE_WAIT_S = 4  # a reused connection that says nothing this long is dropped and a new one is opened


class Unsupported(Exception):
    """The installed edge-tts does not have what this module needs: use plain edge-tts."""


def _parts():
    try:
        import aiohttp
        from edge_tts import communicate as C
        from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL
        from edge_tts.data_classes import TTSConfig
        from edge_tts.drm import DRM
        from edge_tts.exceptions import NoAudioReceived
        from xml.sax.saxutils import escape
        return dict(aiohttp=aiohttp, C=C, VER=SEC_MS_GEC_VERSION, HEADERS=WSS_HEADERS, URL=WSS_URL,
                    TTSConfig=TTSConfig, DRM=DRM, NoAudio=NoAudioReceived, escape=escape,
                    ssl=getattr(C, "_SSL_CTX", None))
    except Exception as e:  # noqa: BLE001
        raise Unsupported(str(e)) from e


class EdgeClient:
    """Thread-safe: synth() can be called from any thread; the websocket lives on a private event loop."""

    def __init__(self):
        self._p = None
        self._loop = None
        self._thread = None
        self._session = None
        self._ws = None
        self._last_used = 0.0
        self._lock = None          # asyncio.Lock: one request at a time on the connection
        self._start_lock = threading.Lock()
        self._streamed = False

    # ---------------------------------------------------------------- loop
    def _ensure_loop(self):
        with self._start_lock:
            if self._loop is not None:
                return
            self._p = _parts()
            self._loop = asyncio.new_event_loop()
            ready = threading.Event()

            def run():
                asyncio.set_event_loop(self._loop)
                self._lock = asyncio.Lock()
                ready.set()
                self._loop.run_forever()
            self._thread = threading.Thread(target=run, daemon=True, name="edge-tts")
            self._thread.start()
            ready.wait(5)

    def _call(self, coro, timeout):
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    # ---------------------------------------------------------------- connection
    async def _close(self):
        ws, sess, self._ws, self._session = self._ws, self._session, None, None
        for x in (ws, sess):
            try:
                if x is not None:
                    await x.close()
            except Exception:  # noqa: BLE001
                pass

    async def _connect(self):
        p = self._p
        await self._close()
        aiohttp, DRM = p["aiohttp"], p["DRM"]
        t0 = time.time()
        self._session = aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(
            total=None, sock_connect=10, sock_read=TIMEOUT_S))
        url = (f"{p['URL']}&ConnectionId={uuid.uuid4().hex}"
               f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}&Sec-MS-GEC-Version={p['VER']}")
        kw = {"compress": 15, "headers": DRM.headers_with_muid(p["HEADERS"])}
        if p["ssl"] is not None:
            kw["ssl"] = p["ssl"]
        try:
            self._ws = await self._session.ws_connect(url, **kw)
        except aiohttp.ClientResponseError as e:
            if e.status != 403:
                raise
            DRM.handle_client_response_error(e)  # clock skew: edge-tts' own fix, then once more
            url = (f"{p['URL']}&ConnectionId={uuid.uuid4().hex}"
                   f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}&Sec-MS-GEC-Version={p['VER']}")
            self._ws = await self._session.ws_connect(url, **kw)
        await self._ws.send_str(
            f"X-Timestamp:{p['C'].date_to_string()}\r\n"
            "Content-Type:application/json; charset=utf-8\r\n"
            "Path:speech.config\r\n\r\n"
            '{"context":{"synthesis":{"audio":{"metadataoptions":{'
            '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},'
            '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n')
        self._last_used = time.time()
        log.info("TTS: connection open in %.2fs", time.time() - t0)

    def _fresh(self):
        return self._ws is not None and not self._ws.closed and time.time() - self._last_used < IDLE_S

    async def _prepare(self):
        async with self._lock:
            if not self._fresh():
                await self._connect()

    def prepare(self):
        """Open the connection in the background (call it when a reading is about to come)."""
        try:
            self._ensure_loop()
            asyncio.run_coroutine_threadsafe(self._prepare(), self._loop)
        except Exception as e:  # noqa: BLE001
            log.info("TTS: could not pre-connect: %s", e)

    # ---------------------------------------------------------------- request
    async def _request(self, text, voice, rate, reused=False, on_audio=None):
        """Audio of one text. on_audio(bytes) gets each packet the moment it arrives (streaming);
        without it the whole mp3 is returned."""
        p = self._p
        C = p["C"]
        tc = p["TTSConfig"](voice, rate, "+0%", "+0Hz", "SentenceBoundary")
        body = p["escape"](C.remove_incompatible_characters(text))
        req_id = uuid.uuid4().hex
        await self._ws.send_str(C.ssml_headers_plus_data(req_id, C.date_to_string(), C.mkssml(tc, body)))
        audio = bytearray()
        aiohttp = p["aiohttp"]
        first = True
        while True:
            msg = await asyncio.wait_for(self._ws.receive(), REUSE_WAIT_S if (first and reused) else TIMEOUT_S)
            first = False
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = msg.data.encode("utf-8")
                head = data[:data.find(b"\r\n\r\n")]
                if b"Path:turn.end" in head:
                    break
            elif msg.type == aiohttp.WSMsgType.BINARY:
                if len(msg.data) < 2:
                    continue
                hl = int.from_bytes(msg.data[:2], "big")
                headers, payload = C.get_headers_and_data(msg.data, hl)
                if headers.get(b"Path") == b"audio" and headers.get(b"Content-Type") == b"audio/mpeg":
                    if on_audio is not None:
                        on_audio(payload)
                        self._streamed = True
                    audio += payload
            else:  # closed / error: the service dropped the connection
                raise ConnectionError(f"connection ended ({msg.type})")
        self._last_used = time.time()
        if not audio:
            raise p["NoAudio"]("No audio was received.")
        return bytes(audio)

    async def _synth(self, text, voice, rate, on_audio=None):
        async with self._lock:
            self._streamed = False
            for attempt in range(2):
                reused = not attempt and self._fresh()
                if not reused:
                    await self._connect()
                try:
                    return await self._request(text, voice, rate, reused, on_audio)
                except self._p["NoAudio"]:
                    raise
                except Exception as e:  # noqa: BLE001
                    if attempt or self._streamed:
                        raise  # part of it was already played: asking again would repeat it
                    log.info("TTS: reconnecting (%s: %s)", type(e).__name__, e)
                    await self._close()

    def stream(self, text, voice, rate, on_audio):
        """Speak `text`: on_audio(bytes) is called (on the client's thread) with every mp3 packet as soon
        as it arrives. Returns when the service has sent all of it."""
        self._call(self._synth(text, voice, rate, on_audio), TIMEOUT_S * 2 + 15)

    def synth(self, text, voice, rate, path):
        data = self._call(self._synth(text, voice, rate), TIMEOUT_S * 2 + 15)
        with open(path, "wb") as f:
            f.write(data)


CLIENT = EdgeClient()

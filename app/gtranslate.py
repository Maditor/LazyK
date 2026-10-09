"""Google Translate without a key (the endpoint Chrome's translate extension uses, as in Japo).

Used with Local OCR: the page is read on this PC and translated here, so no AI and no API quota.
Each bubble is translated on its own (4 at a time), so there is no story context.
"""
import logging
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import requests

from .api import Cancelled

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
SOURCES = {"auto": "auto", "ja": "ja", "ko": "ko", "zh": "zh-CN", "en": "en"}
_rest_until = {}  # endpoint -> time it may be used again (blocked: 429/403 -> 5 min)
_session = None
_session_lock = threading.Lock()
_cache = OrderedDict()  # (text, sl, tl) -> translation: the same line is never sent twice
_cache_lock = threading.Lock()
CACHE_MAX = 500
BATCH_CHARS = 1800   # characters per request: a whole page usually goes in ONE request
_last_used = [0.0]   # when Google last answered: an idle connection is reopened before the next page
_batch_ok = [True]   # False once the endpoint refused several lines in one request: one per line then


def _sess():
    """One shared session: the connection to Google stays open between lines, so a translation does not
    pay for a new TCP + TLS handshake every time (usually 100-300 ms)."""
    global _session
    with _session_lock:
        if _session is None:
            from requests.adapters import HTTPAdapter
            s = requests.Session()
            s.headers["User-Agent"] = UA
            s.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=4))
            _session = s
        return _session


def _reset_session():
    global _session
    with _session_lock:
        if _session is not None:
            try:
                _session.close()
            except Exception:
                pass
        _session = None


def prewarm(idle_s=20):
    """A page is being scanned: if the connection to Google may have gone idle, reopen it now (in the
    background), so the translation does not wait for a new TLS handshake."""
    if time.time() - _last_used[0] > idle_s:
        warm()


def warm():
    """Open the connection in the background (call at start), so the first translation is not slower."""
    _last_used[0] = time.time()

    def work():
        from . import winapi
        winapi.lower_this_thread()
        try:
            _sess().get("https://clients5.google.com/translate_a/t",
                        params={"client": "dict-chrome-ex", "sl": "en", "tl": "vi", "q": "a"}, timeout=8)
        except Exception as e:  # noqa: BLE001
            log.info("Google warm-up skipped: %s", e)
    threading.Thread(target=work, daemon=True).start()


class TranslateError(Exception):
    pass


def _first_text(data):
    """The translated string, whatever shape the endpoint answered with."""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        if "sentences" in data:
            return "".join(s.get("trans", "") for s in data["sentences"])
        return data.get("text") or data.get("translatedText") or ""
    if isinstance(data, list) and data:
        return data[0] if all(isinstance(x, str) for x in data) else _first_text(data[0])
    return ""


def _prepare(text):
    """One clean line; ALL CAPS comic lettering becomes sentence case (translates much better)."""
    t = re.sub(r"(?<=[　-鿿＀-￯])\s*\n\s*(?=[　-鿿＀-￯])", "", str(text or ""))
    t = re.sub(r"\s*\n\s*", " ", t).strip()
    letters = [c for c in t if c.isascii() and c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters):
        t = re.sub(r"(^|[.!?…]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t.lower())
        t = re.sub(r"\bi\b", "I", t)
    return t


def _get(name, url, params):
    if _rest_until.get(name, 0) > time.time():
        raise TranslateError(f"{name} is resting after a block")
    for attempt in range(2):
        try:
            r = _sess().get(url, params=params, timeout=8)
        except requests.RequestException as e:
            # a kept-open connection the server already closed fails once: retry at once on a fresh one
            _reset_session()
            if attempt:
                raise TranslateError("Google Translate: network error") from e
            continue
        if r.status_code in (403, 429):
            _rest_until[name] = time.time() + 300
        if not r.ok:
            raise TranslateError(f"Google Translate: HTTP {r.status_code}")
        _last_used[0] = time.time()
        try:
            return r.json()
        except ValueError:
            return r.text
    raise TranslateError("Google Translate: no answer")


def _one(text, sl, tl):
    try:
        return _first_text(_get("google", "https://clients5.google.com/translate_a/t",
                                {"client": "dict-chrome-ex", "sl": sl, "tl": tl, "q": text}))
    except TranslateError as e:
        log.info("Chrome endpoint failed (%s), trying client=gtx", e)
        data = _get("google-gtx", "https://translate.googleapis.com/translate_a/single",
                    {"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": text})
        if isinstance(data, list) and data and isinstance(data[0], list):
            return "".join(p[0] for p in data[0] if p and p[0])
        return _first_text(data)


def _batch(texts, sl, tl):
    """Several lines in ONE request (repeated q=): one round trip for a whole page instead of one per
    bubble. Raises TranslateError when the answer does not have one translation per line."""
    params = [("client", "dict-chrome-ex"), ("sl", sl), ("tl", tl)] + [("q", t) for t in texts]
    data = _get("google", "https://clients5.google.com/translate_a/t", params)
    if isinstance(data, list) and len(data) == len(texts):
        out = [d if isinstance(d, str) else _first_text(d) for d in data]
        if all(isinstance(x, str) for x in out):
            return out
    raise TranslateError(f"batch answer has a different shape ({type(data).__name__}, "
                         f"{len(data) if isinstance(data, list) else '-'} for {len(texts)})")


def _groups(idx, texts):
    """Split line indexes into requests of at most BATCH_CHARS characters."""
    groups, cur, size = [], [], 0
    for i in idx:
        n = len(texts[i]) + 3
        if cur and size + n > BATCH_CHARS:
            groups.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += n
    if cur:
        groups.append(cur)
    return groups


def _translate_many(todo, texts, sl, tl):
    """Translations for the lines in `todo` (indexes into texts), as few requests as possible."""
    if len(todo) == 1:
        return [_one(texts[todo[0]], sl, tl)]
    if _batch_ok[0] and _rest_until.get("google", 0) <= time.time():
        groups = _groups(todo, texts)
        try:
            if len(groups) == 1:
                parts = [_batch([texts[i] for i in groups[0]], sl, tl)]
            else:
                with ThreadPoolExecutor(max_workers=min(4, len(groups))) as ex:
                    parts = list(ex.map(lambda g: _batch([texts[i] for i in g], sl, tl), groups))
            return [t for part in parts for t in part]
        except TranslateError as e:
            if "shape" in str(e):
                _batch_ok[0] = False  # this endpoint does not batch: stop trying for this session
            log.info("Google batch failed (%s), one request per line", e)
    with ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(lambda i: _one(texts[i], sl, tl), todo))


def translate(lines, source_lang, target_lang, cancel=None):
    """lines -> translated lines (same length; an empty line stays empty)."""
    sl = SOURCES.get(source_lang, "auto")
    from .langs import google_code
    tl = google_code(target_lang)
    texts = [_prepare(l) for l in lines]
    todo = [i for i, t in enumerate(texts) if t]
    out = [""] * len(lines)
    if not todo:
        return out
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    with _cache_lock:
        for i in todo:
            hit = _cache.get((texts[i], sl, tl))
            if hit:
                out[i] = hit
                _cache.move_to_end((texts[i], sl, tl))
    todo = [i for i in todo if not out[i]]
    if todo:
        t0 = time.time()
        got = _translate_many(todo, texts, sl, tl)
        log.info("Google: %d line(s) in %.2fs", len(todo), time.time() - t0)
        with _cache_lock:
            for i, t in zip(todo, got):
                out[i] = (t or "").strip()
                if out[i]:
                    _cache[(texts[i], sl, tl)] = out[i]
            while len(_cache) > CACHE_MAX:
                _cache.popitem(last=False)
    if not any(out):
        raise TranslateError("Google Translate returned nothing")
    return out


def test(settings):
    """Translate one sample sentence. Returns (ok, message, seconds)."""
    samples = {"ja": "今日はいい天気ですね！", "ko": "오늘 날씨가 좋네요!", "zh": "今天天气真好！", "en": "What a nice day today!"}
    src = settings["source_lang"] if settings["source_lang"] in samples else "ja"
    _rest_until.clear()
    t0 = time.time()
    try:
        out = translate([samples[src]], src, settings["target_lang"])[0]
        return True, f"“{samples[src]}” → “{out[:40]}”", time.time() - t0
    except Exception as e:
        return False, str(e)[:200], time.time() - t0

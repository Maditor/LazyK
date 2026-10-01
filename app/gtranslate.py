"""Google Translate without a key (the endpoint Chrome's translate extension uses, as in Japo).

Used with Local OCR: the page is read on this PC and translated here, so no AI and no API quota.
Each bubble is translated on its own (4 at a time), so there is no story context.
"""
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from .api import Cancelled

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
TARGETS = {"vietnamese": "vi", "english": "en", "japanese": "ja", "korean": "ko", "chinese": "zh-CN"}
SOURCES = {"auto": "auto", "ja": "ja", "ko": "ko", "zh": "zh-CN", "en": "en"}
_rest_until = {}  # endpoint -> time it may be used again (blocked: 429/403 -> 5 min)


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
            r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=8)
        except requests.RequestException as e:
            if attempt:
                raise TranslateError("Google Translate: network error") from e
            time.sleep(1)
            continue
        if r.status_code in (403, 429):
            _rest_until[name] = time.time() + 300
        if not r.ok:
            raise TranslateError(f"Google Translate: HTTP {r.status_code}")
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


def translate(lines, source_lang, target_lang, cancel=None):
    """lines -> translated lines (same length; an empty line stays empty)."""
    sl = SOURCES.get(source_lang, "auto")
    tl = TARGETS.get(str(target_lang).strip().lower(), "vi")
    texts = [_prepare(l) for l in lines]
    todo = [i for i, t in enumerate(texts) if t]
    out = [""] * len(lines)
    if not todo:
        return out
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    with ThreadPoolExecutor(max_workers=4) as ex:
        got = list(ex.map(lambda i: _one(texts[i], sl, tl), todo))
    for i, t in zip(todo, got):
        out[i] = (t or "").strip()
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

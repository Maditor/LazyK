"""AI servers: Cloudflare Workers AI and Google Gemini, behind one Router.

All clients take OpenAI-style content: a str (text only) or a list of parts
[{"type": "text", ...}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}].

Busy / quota handling:
  * model busy (503) or rate limited (429): short retry, then (if auto_switch_model) the next model
    of that server's list is used and remembered in settings
  * a server out of quota (Cloudflare daily neurons, Gemini all models exhausted, bad key):
    QuotaExceeded -> the Router switches to the other server when it has a key (auto_switch_server)
"""
import logging
import re
import threading
import time

import requests

log = logging.getLogger(__name__)

CF_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TIMEOUT = (10, 120)  # connect, read
SERVERS = ("gemini", "cloudflare")
SERVER_NAMES = {"gemini": "Google Gemini", "cloudflare": "Cloudflare Workers AI"}
SERVER_SHORT = {"gemini": "Gemini", "cloudflare": "Cloudflare"}
KEY_URLS = {"gemini": "https://aistudio.google.com/api-keys",
            "cloudflare": "https://dash.cloudflare.com/profile/api-tokens"}


class Cancelled(Exception):
    pass


class ApiError(Exception):
    pass


class QuotaExceeded(ApiError):
    """This server cannot serve more requests right now (quota, all models busy, bad key)."""


def _strip_think(text: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", text or "", flags=re.I).strip()


def _error_message(resp) -> str:
    try:
        j = resp.json()
        if isinstance(j, list) and j:
            j = j[0]
        errs = j.get("errors") or []
        if errs and isinstance(errs[0], dict) and errs[0].get("message"):
            return errs[0]["message"]
        err = j.get("error")
        if isinstance(err, dict):
            return err.get("message") or str(err)
        if err:
            return str(err)
    except Exception:
        pass
    return f"HTTP {resp.status_code}: {resp.text[:200]}"


def _wait(cancel, seconds):
    if cancel.wait(seconds):
        raise Cancelled()


class _Base:
    server = ""

    def __init__(self, settings, on_status=None):
        self.s = settings
        self.on_status = on_status or (lambda msg: None)
        self._local = threading.local()
        self._lock = threading.Lock()

    def _session(self):
        sess = getattr(self._local, "s", None)
        if sess is None:
            sess = self._local.s = requests.Session()
        return sess

    # model list handling (shared by both servers)
    @property
    def models(self):
        return [m for m in (self.s[f"{self.server}_models"] or []) if m]

    @property
    def model(self):
        return self.s[f"{self.server}_model"] or (self.models[0] if self.models else "")

    def _next_model(self, tried):
        lst = self.models
        if not lst:
            return None
        start = lst.index(self.model) if self.model in lst else -1
        for k in range(1, len(lst) + 1):
            cand = lst[(start + k) % len(lst)]
            if cand not in tried:
                return cand
        return None

    def _switch_model(self, tried, why):
        """Move to the next untried model. Returns True if switched."""
        if getattr(self, "no_switch", False) or not self.s["auto_switch_model"]:
            return False
        with self._lock:
            nxt = self._next_model(tried)
            if not nxt:
                return False
            old = self.model
            self.s.update(**{f"{self.server}_model": nxt})
        log.warning("%s: %s is %s, switching to %s", self.server, old, why, nxt)
        self.on_status(f"{old} {why} → {nxt}")
        return True


class CloudflareClient(_Base):
    server = "cloudflare"

    def __init__(self, settings, on_status=None):
        super().__init__(settings, on_status)
        self._thinking_param_ok = True

    def has_key(self):
        return bool(str(self.s["cf_account_id"]).strip() and str(self.s["cf_api_token"]).strip())

    def chat(self, content, temperature=0.2, max_tokens=4096, cancel=None):
        cancel = cancel or threading.Event()
        url = CF_URL.format(account=str(self.s["cf_account_id"]).strip())
        token = str(self.s["cf_api_token"]).strip()
        tried, attempt, net_errors = set(), 0, 0
        while True:
            if cancel.is_set():
                raise Cancelled()
            model = self.model
            body = {"model": model, "messages": [{"role": "user", "content": content}],
                    "temperature": temperature, "max_tokens": max_tokens}
            if self._thinking_param_ok:
                body["chat_template_kwargs"] = {"enable_thinking": False}
            try:
                resp = self._session().post(url, json=body, timeout=TIMEOUT,
                                            headers={"Authorization": f"Bearer {token}"})
            except requests.RequestException as e:
                net_errors += 1
                if net_errors <= 2:
                    self.on_status("Network error, retrying…")
                    _wait(cancel, 3)
                    continue
                raise ApiError(f"Network error: {e}") from e
            if cancel.is_set():
                raise Cancelled()
            msg = "" if resp.ok else _error_message(resp)
            low = msg.lower()

            if resp.status_code == 400 and self._thinking_param_ok and any(
                    k in low for k in ("chat_template_kwargs", "enable_thinking", "additional properties", "unknown")):
                log.info("Model rejected enable_thinking, resending without it")
                self._thinking_param_ok = False
                continue
            if resp.status_code in (401, 403):
                raise QuotaExceeded("Cloudflare rejected the token: " + msg)
            # Daily free allocation used up: waiting will not help
            if any(k in low for k in ("neuron", "daily", "allocation", "quota", "exceeded your")):
                raise QuotaExceeded("Cloudflare quota used up: " + msg)
            if resp.status_code in (429, 503, 500, 502, 504):
                attempt += 1
                if attempt >= 2:
                    tried.add(model)
                    if self._switch_model(tried, "busy"):
                        attempt = 0
                        continue
                if attempt > 4:
                    raise QuotaExceeded(f"Cloudflare busy (HTTP {resp.status_code}): {msg}")
                wait = (4, 8, 15, 25)[attempt - 1]
                self.on_status(f"Busy, retry in {wait}s…")
                _wait(cancel, wait)
                continue
            if not resp.ok:
                raise ApiError(msg)

            data = resp.json()
            if "choices" not in data and isinstance(data.get("result"), dict):
                data = data["result"]
            choices = data.get("choices") or []
            m = choices[0].get("message", {}) if choices else {}
            text = m.get("content")
            if isinstance(text, list):
                text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
            if not text and isinstance(data.get("response"), str):
                text = data["response"]
            return _strip_think(text or "")


class GeminiClient(_Base):
    server = "gemini"
    # Thinking off first (faster, cleaner JSON); older/newer models accept different knobs
    THINKING_VARIANTS = [{"thinkingBudget": 0}, {"thinkingLevel": "low"}, None]

    def __init__(self, settings, on_status=None):
        super().__init__(settings, on_status)
        self._thinking_idx = {}

    def has_key(self):
        return bool(str(self.s["gemini_api_key"]).strip())

    @staticmethod
    def _parts(content):
        if isinstance(content, str):
            return [{"text": content}]
        parts = []
        for p in content:
            if p.get("type") == "text":
                parts.append({"text": p["text"]})
            elif p.get("type") == "image_url":
                url = p["image_url"]["url"]
                mime, b64 = url[5:].split(";base64,", 1)
                parts.append({"inline_data": {"mime_type": mime, "data": b64}})
        return parts

    def chat(self, content, temperature=0.2, max_tokens=4096, cancel=None):
        cancel = cancel or threading.Event()
        key = str(self.s["gemini_api_key"]).strip()
        parts = self._parts(content)
        tried, busy, rate, net_errors = set(), 0, 0, 0
        while True:
            if cancel.is_set():
                raise Cancelled()
            model = self.model
            idx = self._thinking_idx.get(model, 0)
            gen = {"temperature": temperature, "maxOutputTokens": max_tokens}
            if self.THINKING_VARIANTS[idx]:
                gen["thinkingConfig"] = self.THINKING_VARIANTS[idx]
            body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen}
            try:
                resp = self._session().post(GEMINI_URL.format(model=model), json=body, timeout=TIMEOUT,
                                            headers={"x-goog-api-key": key})
            except requests.RequestException as e:
                net_errors += 1
                if net_errors <= 2:
                    self.on_status("Network error, retrying…")
                    _wait(cancel, 3)
                    continue
                raise ApiError(f"Network error: {e}") from e
            if cancel.is_set():
                raise Cancelled()
            msg = "" if resp.ok else _error_message(resp)
            low = msg.lower()

            if resp.status_code == 400 and "thinking" in low and idx + 1 < len(self.THINKING_VARIANTS):
                self._thinking_idx[model] = idx + 1
                continue
            if resp.status_code in (401, 403) or (resp.status_code == 400 and "api key" in low):
                raise QuotaExceeded("Gemini rejected the API key: " + msg)
            if resp.status_code == 404:
                # Model name not available for this key: try the next one
                tried.add(model)
                if self._switch_model(tried, "not available"):
                    continue
                raise ApiError(f"Model {model} not found: {msg}")
            if resp.status_code == 429:
                # Free-tier quotas are per model: another model usually still works
                tried.add(model)
                if self._switch_model(tried, "out of quota"):
                    continue
                rate += 1
                if rate > 2 or "quota" in low:
                    raise QuotaExceeded("Gemini quota reached: " + msg)
                self.on_status("Rate limited, retry in 10s…")
                _wait(cancel, 10)
                continue
            if resp.status_code in (500, 502, 503, 504):
                busy += 1
                if busy >= 2:  # one quick retry, then change model (like VisionBox)
                    tried.add(model)
                    if self._switch_model(tried, "busy"):
                        busy = 0
                        continue
                if busy > 3:
                    raise QuotaExceeded(f"Gemini overloaded (HTTP {resp.status_code}): {msg}")
                self.on_status(f"{model} busy, retry in 4s…")
                _wait(cancel, 4)
                continue
            if not resp.ok:
                raise ApiError(msg)

            data = resp.json()
            fb = data.get("promptFeedback") or {}
            if fb.get("blockReason"):
                raise ApiError(f"Gemini declined this page ({fb['blockReason']})")
            cands = data.get("candidates") or []
            if not cands:
                raise ApiError("Gemini returned no answer")
            c0 = cands[0]
            text = "".join(p.get("text", "") for p in (c0.get("content") or {}).get("parts", [])
                           if isinstance(p, dict) and not p.get("thought"))
            if not text and c0.get("finishReason") not in (None, "STOP", "MAX_TOKENS"):
                raise ApiError(f"Gemini stopped: {c0.get('finishReason')}")
            return _strip_think(text)


class Router:
    """Uses the selected server; on QuotaExceeded moves to the other server if it has a key."""

    def __init__(self, settings, on_status=None):
        self.s = settings
        self.on_status = on_status or (lambda msg: None)
        self.clients = {"gemini": GeminiClient(settings, self.on_status),
                        "cloudflare": CloudflareClient(settings, self.on_status)}
        self._lock = threading.Lock()

    @property
    def server(self):
        srv = self.s["server"]
        return srv if srv in self.clients else "gemini"

    def available(self):
        return [k for k, c in self.clients.items() if c.has_key()]

    def chat(self, content, temperature=0.2, max_tokens=4096, cancel=None):
        tried = set()
        while True:
            srv = self.server
            client = self.clients[srv]
            if not client.has_key():
                others = [k for k in self.available() if k not in tried]
                if others and self.s["auto_switch_server"]:
                    self._switch(others[0], f"{SERVER_NAMES[srv]} has no key")
                    continue
                raise ApiError(f"No API key for {SERVER_NAMES[srv]}. Open API settings (key icon).")
            try:
                return client.chat(content, temperature, max_tokens, cancel)
            except QuotaExceeded as e:
                tried.add(srv)
                others = [k for k in self.available() if k not in tried]
                if others and self.s["auto_switch_server"]:
                    log.warning("%s", e)
                    self._switch(others[0], f"{SERVER_NAMES[srv]} unavailable")
                    continue
                raise

    def _switch(self, srv, why):
        with self._lock:
            if self.s["server"] != srv:
                self.s.update(server=srv)
                log.warning("%s -> switching server to %s", why, srv)
                self.on_status(f"{why} → {SERVER_NAMES[srv]}")


def make_client(settings, on_status=None):
    return Router(settings, on_status)


def test_connection(settings, server, timeout_cancel=None):
    """Tiny text request to check a key/model. Returns (ok, message, seconds)."""
    client = {"gemini": GeminiClient, "cloudflare": CloudflareClient}[server](settings)
    client.no_switch = True  # test exactly the chosen model
    if not client.has_key():
        return False, "No key entered", 0.0
    t0 = time.time()
    try:
        out = client.chat("Reply with exactly: OK", temperature=0, max_tokens=20,
                          cancel=timeout_cancel or threading.Event())
        return True, f"{client.model} answered “{out.strip()[:30]}”", time.time() - t0
    except Exception as e:
        return False, str(e)[:200], time.time() - t0

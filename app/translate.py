"""Translate a whole page in one text-only call, numbered lines in / numbered lines out."""
import logging
import re

log = logging.getLogger(__name__)

TRANSLATE_MAX_TOKENS = 4096
LANG_NAMES = {"auto": "the source language", "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "en": "English"}


def build_prompt(lines, source_lang, target, context_lines, budgets=None):
    S = LANG_NAMES.get(source_lang, source_lang)
    ctx = ""
    if context_lines:
        ctx = ("\nPrevious page, for story context only (do NOT translate it):\n"
               + "\n".join(f"- {l}" for l in context_lines) + "\n")
    vi_rules = ""
    if target.lower().startswith("viet"):
        vi_rules = ("\n7. Vietnamese pronouns: pick tôi/tao/tớ/mình/anh/em/cậu/mày/ông/bà/ngài... from the "
                    "speakers' age, relationship and mood; keep them consistent with the previous page.")
    return f"""You are a professional comic translator. Translate {S} comic dialogue into natural {target}.
{ctx}
Lines to translate (each line is one speech bubble, in reading order{", with the room its bubble has" if budgets else ""}):
{chr(10).join(f"[{i + 1}] {f'(max {budgets[i]} chars) ' if budgets and budgets[i] else ''}{l}" for i, l in enumerate(lines))}

Rules:
1. Output exactly {len(lines)} lines, in the same order, each starting with its number in brackets: [1] ..., [2] ...
2. One source line = one output line. Never merge, split, skip or add lines.
   A sentence often runs across several bubbles ([3] stops mid-sentence and [4] finishes it). Then split
   your {target} sentence at the same point: the first part goes in [3], the rest in [4]. Never move one
   bubble's words into another line, and never leave a line empty.
3. Write natural, spoken {target} like a professionally translated comic, not word-for-word. Keep it short: it must fit back into the same bubble.{" Stay within each line's (max N chars): drop filler words and choose the shortest natural phrasing, but keep the meaning and the tone. Do not repeat the (max N chars) note." if budgets else ""}
4. Keep the emotion and punctuation style (…, ?!, !!!).
5. A standalone sound effect gets a brief {target} sound effect. ALL CAPS in the source is only the comic font: use normal sentence case. The wave dash "〜" means a drawn-out playful sound, not "...".
6. Output ONLY the numbered {target} lines. No notes, no original text, never placeholders like "(blank)".{vi_rules}"""


def parse_numbered(text: str, n: int):
    clean = re.sub(r"<think>[\s\S]*?</think>", "", text or "", flags=re.I)
    clean = re.sub(r"```[a-z]*", "", clean)
    found = {}
    for raw in clean.split("\n"):
        m = re.match(r"^\s*[\[(]?(\d{1,3})[\])\.:：]\s*(.*)$", raw)
        if not m:
            continue
        k = int(m.group(1))
        if 1 <= k <= n and k not in found:
            found[k] = re.sub(r"^\(max \d+ chars\)\s*", "", m.group(2).strip())
    if not found:
        plain = [l.strip() for l in clean.split("\n") if l.strip()]
        while len(plain) > n and re.search(r"[:：]$", plain[0]):
            plain.pop(0)
        return [plain[i] if i < len(plain) else "" for i in range(n)]
    return [found.get(i + 1, "") for i in range(n)]


def translate_lines(client, lines, settings, cancel, context_lines=None, budgets=None):
    if not lines:
        return []
    prompt = build_prompt(lines, settings["source_lang"], settings["target_lang"], context_lines or [], budgets)
    out = None
    ask = prompt
    for attempt in range(2):
        raw = client.chat(ask, temperature=0.5 if attempt == 0 else 0.3,
                          max_tokens=TRANSLATE_MAX_TOKENS, cancel=cancel)
        got = parse_numbered(raw, len(lines))
        if out is None or sum(map(bool, got)) >= sum(map(bool, out)):
            # the newer answer is at least as complete: use it (the old one may hold merged lines)
            out = [g or o for g, o in zip(got, out or got)]
        else:
            out = [o or g for o, g in zip(out, got)]
        missing = [i + 1 for i, l in enumerate(out) if not l]
        if not missing or attempt == 1:
            break
        log.warning("Translation missing lines %s, asking again", missing)
        # Usually the model merged a sentence that runs across bubbles into one line
        ask = (prompt + "\n\nYour previous answer left out " + ", ".join(f"[{m}]" for m in missing)
               + ". Each of those bubbles needs its own line: split sentences that run across bubbles "
                 "so every line gets its part. Output all lines again.")
    # Still missing: leave that bubble untouched (drawing the original text again would look untranslated)
    return [l or "" for l in out]

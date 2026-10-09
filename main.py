"""LazyK – translate comic pages on screen and paint the translation over the bubbles.

Usage:
  python main.py                 normal run (hotkey mode)
  python main.py --demo          calibration boxes, no API calls (checks DPI / capture area)
  python main.py --image p.png   offline test: OCR + translate one image, writes p_translated.png
  python main.py --tts "xin chào"  test the read-aloud voice (needs internet), then exit
"""
import argparse
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

from app import winapi

# Must happen before Tk / mss create any window
winapi.set_dpi_awareness()

from app.config import Settings, app_dir  # noqa: E402


def fix_streams():
    """A windowed exe has no console: libraries that print (progress bars, warnings) must not crash."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def setup_logging():
    log_dir = os.path.join(app_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    handlers = [RotatingFileHandler(os.path.join(log_dir, "lazyk.log"),
                                    maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr and not getattr(sys, "frozen", False):
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def excepthook(*args):
        logging.getLogger("crash").critical("Unhandled exception", exc_info=args if len(args) == 3 else None)
    sys.excepthook = excepthook
    threading.excepthook = lambda a: logging.getLogger("crash").critical(
        "Unhandled thread exception", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


def run_image(path, settings):
    from PIL import Image
    from app.pipeline import Pipeline
    from app.preview import render_preview

    img = Image.open(path).convert("RGB")
    items, _ = Pipeline(settings).process(img, threading.Event(), lambda st, m: print(f"[{st}] {m}"))
    for i, it in enumerate(items, 1):
        print(f"{i:>2}. {it['box']}\n    {it['text']}\n    -> {it.get('translation', '')}")
    out = os.path.splitext(path)[0] + "_translated.png"
    render_preview(img, items, settings).save(out)
    print("Saved", out)


def run_tts(text, settings):
    from app import tts
    print("Voice:", tts.pick_voice(settings))
    errors = []
    sp = tts.Speaker(settings, on_error=errors.append)
    sp.speak([text])
    sp.wait()
    print("Error: " + errors[0] if errors else "Done")


def main():
    ap = argparse.ArgumentParser(description="LazyK")
    ap.add_argument("--demo", action="store_true", help="show calibration boxes, no API")
    ap.add_argument("--image", help="translate one image file and save a preview")
    ap.add_argument("--list-gpus", metavar="FILE", help=argparse.SUPPRESS)  # used by the app: lists graphics cards
    ap.add_argument("--tts", metavar="TEXT", help="read TEXT aloud with the configured voice, then exit")
    args = ap.parse_args()

    fix_streams()
    if args.list_gpus:  # child process of the OCR device menu: no logging, no settings, no window
        from app import gpus
        gpus.write_listing(args.list_gpus)
        return
    setup_logging()
    settings = Settings()
    logging.info("Start (settings: %s)", settings.path)

    if args.tts:
        run_tts(args.tts, settings)
        return

    if args.image:
        if settings.needs_ai() and not settings.has_credentials():
            sys.exit("Add a Gemini key or Cloudflare token first (run the app and click the gear icon).")
        run_image(args.image, settings)
        return

    from app.controller import App
    App(settings, demo=args.demo).run()


if __name__ == "__main__":
    main()

"""Render the overlay result onto an image with PIL (offline test: main.py --image page.png)."""
import os

from PIL import Image, ImageDraw, ImageFont

from .textfit import layout_items

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font_path():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def render_preview(img: Image.Image, items, settings, scale=1.0) -> Image.Image:
    path = _font_path()
    fonts = {}

    def font(size):
        if size not in fonts:
            fonts[size] = ImageFont.truetype(path, size) if path else ImageFont.load_default()
        return fonts[size]

    def metrics(size):
        f = font(size)
        asc, desc = f.getmetrics()
        return (lambda s: f.getlength(s)), asc + desc

    out = img.convert("RGB").copy()
    dr = ImageDraw.Draw(out)
    r = settings["corner_radius"] * scale
    boxes = layout_items(items, img.width, img.height, settings, scale, metrics)
    for b in boxes:
        for c in b.get("covers") or ():
            dr.rectangle(c, fill=b.get("fill", settings["overlay_bg"]))
        if b["kind"] == "poly":
            pts = b["poly"]
            dr.polygon(list(zip(pts[0::2], pts[1::2])), fill=b["fill"])
        elif b["kind"] == "free":
            if b["patch"]:
                dr.rounded_rectangle(b["patch"], radius=min(r, 4 * scale), fill=b["fill"])
            dr.rounded_rectangle(b["rect"], radius=min(r, 4 * scale), fill=b["fill"])
        else:
            dr.rounded_rectangle(b["rect"], radius=r, fill=b.get("fill", settings["overlay_bg"]),
                                 outline=settings["overlay_outline"] or None)
    for b in boxes:  # all text above all boxes
        f = font(b["size"])
        for line, cx, cy in b["lines"]:
            dr.text((cx, cy), line, font=f, fill=b.get("ink", settings["overlay_fg"]), anchor="mm")
    return out

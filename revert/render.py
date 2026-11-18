"""Post designer — retro film look matched to the Revert Media logo, with many layouts and colour themes.

Every image is 1080x1350 (4:5) JPEG. Each post gets a cover template + colour theme + slide layouts,
picked so the same combination doesn't appear twice in a row.
"""
from __future__ import annotations

import math
import random
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .util import ASSETS

W, H = 1080, 1350
CREAM = (246, 242, 230)
INK = (16, 18, 13)
PINK = (242, 170, 180)
ORANGE = (255, 146, 40)
RED = (226, 64, 58)
WHITE = (252, 250, 244)
FONTS = ASSETS / "fonts"

# ─────────────────────────── colour themes ───────────────────────────
THEMES = {
    "olive":  dict(bg=(16, 18, 13), bg2=(32, 36, 26), text=CREAM, accent=PINK, accent2=ORANGE, on_accent=INK,
                   tint=(1.03, 1.02, 0.90), paper=False),
    "sunset": dict(bg=(24, 13, 9), bg2=(56, 26, 14), text=(255, 238, 214), accent=(255, 150, 46),
                   accent2=(255, 206, 70), on_accent=INK, tint=(1.08, 1.0, 0.86), paper=False),
    "teal":   dict(bg=(7, 19, 23), bg2=(14, 40, 46), text=(232, 248, 245), accent=(72, 222, 204),
                   accent2=(255, 96, 166), on_accent=INK, tint=(0.93, 1.02, 1.06), paper=False),
    "plum":   dict(bg=(30, 13, 20), bg2=(66, 28, 42), text=CREAM, accent=PINK, accent2=(255, 214, 120),
                   on_accent=INK, tint=(1.04, 0.97, 1.0), paper=False),
    "mono":   dict(bg=(12, 12, 12), bg2=(36, 36, 36), text=(242, 242, 236), accent=RED, accent2=WHITE,
                   on_accent=WHITE, tint=(1, 1, 1), mono=True, paper=False),
    "cream":  dict(bg=(238, 230, 212), bg2=(222, 210, 184), text=INK, accent=(212, 62, 50), accent2=(32, 36, 26),
                   on_accent=WHITE, tint=(1.04, 1.0, 0.9), paper=True),
    "newsprint": dict(bg=(232, 230, 222), bg2=(212, 208, 196), text=INK, accent=INK, accent2=RED,
                      on_accent=WHITE, tint=(1, 1, 1), mono=True, paper=True),
}
DARK = [k for k, t in THEMES.items() if not t["paper"]]
PAPER = [k for k, t in THEMES.items() if t["paper"]]

# cover templates: which themes and post kinds they suit, and whether they need a photo
TEMPLATES = {
    "fade":     dict(themes=DARK, kinds={"news", "community"}, photo=False),
    "boxes":    dict(themes=DARK, kinds={"news", "community"}, photo=True),
    "split":    dict(themes=DARK + PAPER, kinds={"news"}, photo=False),
    "magazine": dict(themes=PAPER, kinds={"news", "throwback"}, photo=True),
    "sticker":  dict(themes=DARK, kinds={"news", "community", "throwback"}, photo=True),
    "ticker":   dict(themes=["olive", "mono", "teal", "plum"], kinds={"news"}, photo=True),
    "vhs":      dict(themes=["olive", "teal", "sunset", "mono"], kinds={"throwback"}, photo=True),
    "polaroid": dict(themes=["olive", "plum", "cream", "teal"], kinds={"throwback", "community"}, photo=True),
}
DETAIL_LAYOUTS = ["panel", "card", "numbered"]
STAT_LAYOUTS = ["glow", "block"]

TAG_TEXT = {"ONLY_IN_UAE": "ONLY IN THE UAE", "SPOTTED": "SPOTTED"}


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    files = {"head": "anton-400-normal.ttf", "cond": "barlow-condensed-700-normal.ttf",
             "cond8": "barlow-condensed-800-normal.ttf", "cond6": "barlow-condensed-600-normal.ttf",
             "body": "barlow-600-normal.ttf", "body5": "barlow-500-normal.ttf",
             "script": "yellowtail-400-normal.ttf", "vhs": "vt323-400-normal.ttf"}
    return ImageFont.truetype(str(FONTS / files[name]), size)


# ─────────────────────────── photo treatment ───────────────────────────

def smart_crop(im: Image.Image, tw: int, th: int) -> Image.Image:
    """Cover-crop to tw x th, sliding the window to where the most detail (the car) is."""
    im = im.convert("RGB")
    scale = max(tw / im.width, th / im.height)
    im = im.resize((max(tw, round(im.width * scale)), max(th, round(im.height * scale))), Image.LANCZOS)
    edges = np.asarray(im.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    if im.width > tw:
        csum = np.concatenate([[0], np.cumsum(edges.sum(axis=0))])
        win = csum[tw:] - csum[:-tw]
        x = int(np.argmax(win * (1 - 0.25 * np.abs(np.linspace(-1, 1, len(win))))))
        return im.crop((x, 0, x + tw, th))
    csum = np.concatenate([[0], np.cumsum(edges.sum(axis=1))])
    win = csum[th:] - csum[:-th]
    y = int(np.argmax(win * (1 - 0.35 * np.abs(np.linspace(-1, 1, len(win))))))
    return im.crop((0, y, tw, y + th))


def filmify(im: Image.Image, theme: dict, strength: float = 1.0, seed: int = 0) -> Image.Image:
    """Faded film look: lifted blacks, theme tint, grain, vignette, slight colour fringing."""
    rng = np.random.default_rng(seed)
    if theme.get("mono"):
        im = ImageOps.grayscale(im).convert("RGB")
        im = ImageEnhance.Contrast(im).enhance(1.15)
    else:
        im = ImageEnhance.Color(im).enhance(1 - 0.18 * strength)
    a = np.asarray(im, dtype=np.float32)
    h, w = a.shape[:2]
    a = a * (1 - 0.10 * strength) + 16 * strength
    a = a * (1 + (np.array(theme["tint"]) - 1) * strength)
    shift = int(2 * strength)
    if shift and not theme.get("mono"):
        a[:, shift:, 0] = a[:, :-shift, 0]
        a[:, :-shift, 2] = a[:, shift:, 2]
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    a *= (1 - 0.38 * strength * np.clip(d - 0.55, 0, 1) ** 1.4)[..., None]
    a = np.clip(a + rng.normal(0, 9 * strength, (h, w))[..., None], 0, 255).astype(np.uint8)
    return Image.fromarray(a)


def scanlines(im: Image.Image, alpha: int = 34) -> Image.Image:
    over = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for y in range(0, im.height, 4):
        d.line([(0, y), (im.width, y)], fill=(0, 0, 0, alpha), width=2)
    return Image.alpha_composite(im.convert("RGBA"), over).convert("RGB")


def textured(color, size=(W, H), seed=0, grad=0.35, noise=7) -> Image.Image:
    rng = np.random.default_rng(seed)
    w, h = size
    yy = np.linspace(0, 1, h)[:, None, None]
    base = np.array(color, dtype=np.float32) * (1 + grad / 3 - grad * yy)
    a = np.broadcast_to(base, (h, w, 3)).copy() + rng.normal(0, noise, (h, w, 1))
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def paper_bg(theme, seed=0) -> Image.Image:
    """Aged paper: flat colour, fibres, soft blotches."""
    rng = np.random.default_rng(seed)
    a = np.broadcast_to(np.array(theme["bg"], np.float32), (H, W, 3)).copy()
    blot = Image.fromarray((rng.random((H // 40, W // 40)) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
    a -= (np.asarray(blot, np.float32) / 255.0 * 14)[..., None]
    a += rng.normal(0, 6, (H, W, 1))
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# ─────────────────────────── drawing helpers ───────────────────────────

def comp(base: Image.Image, layer: Image.Image, xy=(0, 0)) -> Image.Image:
    out = base.convert("RGBA")
    out.alpha_composite(layer, (int(xy[0]), int(xy[1])))
    return out.convert("RGB")


def vertical_fade(im, start, end, color, max_alpha=245, power=1.3):
    over = Image.new("RGBA", im.size, tuple(color) + (0,))
    ramp = np.clip((np.arange(im.height) - start) / max(1, end - start), 0, 1) ** power
    a = np.repeat((ramp * max_alpha)[:, None], im.width, axis=1)
    over.putalpha(Image.fromarray(a.astype(np.uint8)))
    return Image.alpha_composite(im.convert("RGBA"), over).convert("RGB")


def halftone(size, color, max_r=9, step=22, direction="diag", alpha=255) -> Image.Image:
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for y in range(0, h + step, step):
        for x in range(0, w + step, step):
            ox = (step // 2) if (y // step) % 2 else 0
            if direction == "diag":
                t = ((x / w) + (1 - y / h)) / 2
            elif direction == "radial":
                t = 1 - min(1, math.hypot(x / w - 0.5, y / h - 0.5) * 2)
            else:
                t = 1 - y / h
            r = max_r * max(0.0, min(1.0, t)) ** 1.2
            if r > 0.8:
                d.ellipse([x + ox - r, y - r, x + ox + r, y + r], fill=tuple(color) + (alpha,))
    return layer


def wrap(draw, text, fnt, max_w) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        test = (cur + " " + w_).strip()
        if draw.textlength(test, font=fnt) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def balanced(draw, text, fnt, max_w) -> list[str]:
    """Wrap so lines are roughly even (no lonely last word)."""
    lines = wrap(draw, text, fnt, max_w)
    n = len(lines)
    if n < 2:
        return lines
    lo, hi = max_w * 0.4, max_w
    for _ in range(14):
        mid = (lo + hi) / 2
        if len(wrap(draw, text, fnt, mid)) <= n:
            hi = mid
        else:
            lo = mid
    return wrap(draw, text, fnt, hi)


def fit_text(draw, text, fname, max_w, max_lines, start, minimum):
    size = start
    while size > minimum:
        f = font(fname, size)
        lines = wrap(draw, text, f, max_w)
        if len(lines) <= max_lines and all(draw.textlength(l, font=f) <= max_w for l in lines):
            return f, balanced(draw, text, f, max_w)
        size -= 4
    f = font(fname, minimum)
    return f, wrap(draw, text, f, max_w)[:max_lines]


def cap_height(fnt) -> int:
    return -fnt.getbbox("H", anchor="ls")[1]


def glow_text(base, xy_lines, fnt, fill, glow=None, radius=14, glow_alpha=150, anchor="la", shadow=True):
    glow = glow or fill
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for (x, y), line in xy_lines:
        d.text((x, y), line, font=fnt, fill=tuple(glow) + (glow_alpha,), anchor=anchor)
    blurred = layer.filter(ImageFilter.GaussianBlur(radius))
    out = Image.alpha_composite(base.convert("RGBA"), blurred)
    out = Image.alpha_composite(out, blurred)
    d2 = ImageDraw.Draw(out)
    for (x, y), line in xy_lines:
        if shadow:
            d2.text((x + 3, y + 4), line, font=fnt, fill=(0, 0, 0, 110), anchor=anchor)
        d2.text((x, y), line, font=fnt, fill=fill, anchor=anchor)
    return out.convert("RGB")


def plain_text(im, xy_lines, fnt, fill, anchor="la"):
    d = ImageDraw.Draw(im)
    for (x, y), line in xy_lines:
        d.text((x, y), line, font=fnt, fill=fill, anchor=anchor)
    return im


def spaced(draw, xy, text, fnt, fill, tracking=3):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + tracking
    return x


def spaced_width(draw, text, fnt, tracking=3):
    return sum(draw.textlength(c, font=fnt) + tracking for c in text) - tracking


def pill(im, text, right_x, top_y, bg, fg, size=34):
    d = ImageDraw.Draw(im)
    f = font("cond8", size)
    tw = spaced_width(d, text, f, 4)
    pad_x, h = 22, size + 22
    x0 = right_x - tw - 2 * pad_x
    d.rounded_rectangle([x0 + 5, top_y + 6, right_x + 5, top_y + h + 6], radius=h // 2, fill=(0, 0, 0))
    d.rounded_rectangle([x0, top_y, right_x, top_y + h], radius=h // 2, fill=bg)
    spaced(d, (x0 + pad_x, top_y + 7), text, f, fg, 4)
    return x0


_logo_cache = {}


def logo_badge(size: int) -> Image.Image:
    if size not in _logo_cache:
        lg = ImageOps.fit(Image.open(ASSETS / "logo.png").convert("RGB"), (size, size), Image.LANCZOS)
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
        mask = mask.resize((size, size), Image.LANCZOS)
        ring = size + 12
        badge = Image.new("RGBA", (ring + 16, ring + 16), (0, 0, 0, 0))
        sh = Image.new("RGBA", badge.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse([10, 12, ring + 10, ring + 12], fill=(0, 0, 0, 150))
        badge = Image.alpha_composite(badge, sh.filter(ImageFilter.GaussianBlur(6)))
        ImageDraw.Draw(badge).ellipse([2, 2, ring + 2, ring + 2], fill=CREAM)
        badge.paste(lg, (8, 8), mask)
        _logo_cache[size] = badge
    return _logo_cache[size]


def paste_badge(im, size=118, xy=(48, 48)):
    return comp(im, logo_badge(size), xy)


def footer(im, left: str, right: str, color, accent, y=H - 74, rule=True):
    d = ImageDraw.Draw(im)
    f = font("cond6", 27)
    spaced(d, (64, y), left.upper(), f, color, 3)
    rw = spaced_width(d, right.upper(), f, 3)
    spaced(d, (W - 64 - rw, y), right.upper(), f, accent if "SWIPE" in right.upper() else color, 3)
    if rule:
        d.line([(64, y - 22), (W - 64, y - 22)], fill=color, width=1)
    return im


def play_icon(d, x, y, s=22, fill=CREAM):
    d.polygon([(x, y), (x, y + s), (x + s * 0.9, y + s / 2)], fill=fill)


def framed(photo: Image.Image, border=18, bottom=None, color=WHITE, shadow=26, angle=0.0) -> Image.Image:
    """Photo with a print border + soft shadow, optionally rotated. Returns RGBA."""
    bottom = border if bottom is None else bottom
    fw, fh = photo.width + 2 * border, photo.height + border + bottom
    card = Image.new("RGBA", (fw, fh), tuple(color) + (255,))
    card.paste(photo, (border, border))
    pad = shadow * 2
    out = Image.new("RGBA", (fw + 2 * pad, fh + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([pad + 8, pad + 14, pad + fw + 8, pad + fh + 14], fill=(0, 0, 0, 150))
    out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(shadow / 2)))
    out.alpha_composite(card, (pad, pad))
    return out.rotate(angle, resample=Image.BICUBIC, expand=True) if angle else out


def starburst(size, spikes=20, inner=0.86, seed=0) -> Image.Image:
    """Jagged burst mask, like the shape behind the car in the logo."""
    rng = random.Random(seed)
    w, h = size
    pts = []
    for i in range(spikes * 2):
        a = math.pi * 2 * i / (spikes * 2)
        r = (1.0 if i % 2 == 0 else inner) * (0.97 + rng.random() * 0.06)
        pts.append((w / 2 + math.cos(a) * w / 2 * r, h / 2 + math.sin(a) * h / 2 * r))
    big = Image.new("L", (w * 2, h * 2), 0)
    ImageDraw.Draw(big).polygon([(x * 2, y * 2) for x, y in pts], fill=255)
    return big.resize(size, Image.LANCZOS)


def tag_for(post) -> str:
    if post.get("is_rumour"):
        return "UNCONFIRMED"
    c = post.get("category", "NEWS")
    return TAG_TEXT.get(c, c)


def tag_colors(post, th):
    if post.get("is_rumour"):
        return RED, WHITE
    return th["accent"], th["on_accent"]


# ─────────────────────────── text blocks ───────────────────────────

def headline_block(im, post, th, x, bottom, max_w, max_lines=3, start=132, minimum=70, glow=True,
                   kicker_color=None, upper=True, bar=True):
    """Draw headline + kicker so the kicker's last line ends at `bottom`. Returns top y."""
    d = ImageDraw.Draw(im)
    text = post["headline"].upper() if upper else post["headline"]
    head_f, head_lines = fit_text(d, text, "head", max_w, max_lines, start, minimum)
    kick_f = font("body5", 38)
    kick_lines = balanced(d, post.get("kicker", ""), kick_f, max_w)[:2] if post.get("kicker") else []
    cap = cap_height(head_f)
    lh = int(cap * 1.24)
    block_h = cap + (len(head_lines) - 1) * lh + (36 + len(kick_lines) * 50 if kick_lines else 0)
    y0 = bottom - block_h
    if bar:
        d.rectangle([x, y0 - 40, x + 90, y0 - 32], fill=th["accent"])
    xy = [((x, y0 + cap + i * lh), l) for i, l in enumerate(head_lines)]
    im = glow_text(im, xy, head_f, th["text"], radius=14, glow_alpha=110, anchor="ls") if glow else \
        plain_text(im, xy, head_f, th["text"], anchor="ls")
    d = ImageDraw.Draw(im)
    ky = y0 + cap + (len(head_lines) - 1) * lh + 30
    for i, l in enumerate(kick_lines):
        d.text((x, ky + i * 50), l, font=kick_f, fill=kicker_color or th["text"])
    return im, y0


# ─────────────────────────── cover templates ───────────────────────────

def photo_fill(photo, th, w, h, seed, strength=1.0):
    if photo is None:
        bg = textured(th["bg2"], (w, h), seed)
        return comp(bg, halftone((w, h), th["accent"], 12, 28, "diag", 70))
    return filmify(smart_crop(photo, w, h), th, strength, seed)


def cover_fade(post, photo, ctx):
    th, seed = ctx["theme"], ctx["seed"]
    im = textured(th["bg"], seed=seed)
    ph = photo_fill(photo, th, W, 980, seed)
    im.paste(ph, (0, 0))
    im = vertical_fade(im, 490, 980, th["bg"], 255)
    im = comp(im, halftone((380, 260), th["accent"], 7, 20, "diag", 55).transpose(Image.FLIP_TOP_BOTTOM),
              (W - 380, H - 420))
    im = paste_badge(im)
    pill(im, tag_for(post), W - 52, 70, *tag_colors(post, th))
    im, _ = headline_block(im, post, th, 64, H - 128, W - 128, kicker_color=th["text"])
    return footer(im, ctx["left"], ctx["right"], th["text"], th["accent"])


def cover_boxes(post, photo, ctx):
    """Full-bleed photo; headline on stacked, slightly tilted colour strips."""
    th, seed = ctx["theme"], ctx["seed"]
    im = filmify(smart_crop(photo, W, H), th, 1.0, seed)
    im = vertical_fade(im, int(H * 0.45), H, (0, 0, 0), 215)
    im = paste_badge(im)
    pill(im, tag_for(post), W - 52, 70, *tag_colors(post, th))
    d = ImageDraw.Draw(im)
    f, lines = fit_text(d, post["headline"].upper(), "head", W - 220, 4, 112, 64)
    cap = cap_height(f)
    pad_x, pad_y, gap = 22, 16, 12
    rows = [(l, d.textlength(l, font=f)) for l in lines]
    lw = int(max(w for _, w in rows) + 2 * pad_x + 40)
    lh = cap + 2 * pad_y
    layer = Image.new("RGBA", (lw, len(rows) * (lh + gap) + 20), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i, (l, w) in enumerate(rows):
        y = i * (lh + gap)
        x = 10 + (i % 2) * 18
        ld.rectangle([x + 7, y + 8, x + w + 2 * pad_x + 7, y + lh + 8], fill=(0, 0, 0, 160))
        ld.rectangle([x, y, x + w + 2 * pad_x, y + lh], fill=th["accent"] + (255,))
        ld.text((x + pad_x, y + pad_y + cap), l, font=f, fill=th["on_accent"], anchor="ls")
    layer = layer.rotate(3, resample=Image.BICUBIC, expand=True)
    kick_f = font("body", 38)
    kick = balanced(d, post.get("kicker", ""), kick_f, W - 128)[:2]
    ky = H - 130 - len(kick) * 50
    im = comp(im, layer, (40, ky - layer.height - 26))
    d = ImageDraw.Draw(im)
    for i, l in enumerate(kick):
        d.text((66, ky + i * 50 + 3), l, font=kick_f, fill=(0, 0, 0))
        d.text((64, ky + i * 50), l, font=kick_f, fill=WHITE)
    return footer(im, ctx["left"], ctx["right"], WHITE, th["accent"])


def cover_split(post, photo, ctx):
    """Colour band with a huge headline on top, photo underneath with a slanted edge."""
    th, seed = ctx["theme"], ctx["seed"]
    band_h = 560
    band_col = th["accent"] if not th["paper"] else th["bg"]
    ink = th["on_accent"] if not th["paper"] else th["text"]
    im = textured(band_col, seed=seed, grad=0.12, noise=5)
    ph = photo_fill(photo, th, W, H - band_h + 60, seed)
    mask = Image.new("L", (W, H - band_h + 60), 255)
    ImageDraw.Draw(mask).polygon([(0, 0), (W, 0), (W, 0), (0, 60)], fill=0)
    im.paste(ph, (0, band_h - 60), mask)
    im = comp(im, halftone((W, band_h - 60), ink, 5, 18, "radial", 40))
    im = vertical_fade(im, H - 380, H, (0, 0, 0), 230)
    im = paste_badge(im, 100, (44, 40))
    tbg, tfg = (RED, WHITE) if post.get("is_rumour") else (ink, band_col)
    pill(im, tag_for(post), W - 52, 56, tbg, tfg)
    d = ImageDraw.Draw(im)
    avail = band_h - 60 - 170 - 30
    start = 150
    while True:
        f, lines = fit_text(d, post["headline"].upper(), "head", W - 128, 3, start, 64)
        cap = cap_height(f)
        lh = int(cap * 1.18)
        total = cap + (len(lines) - 1) * lh
        if total <= avail or start <= 68:
            break
        start = f.size - 6
    top = 170 + (avail - total) // 2
    for i, l in enumerate(lines):
        d.text((64, top + cap + i * lh), l, font=f, fill=ink, anchor="ls")
    kick_f = font("body", 38)
    kick = balanced(d, post.get("kicker", ""), kick_f, W - 128)[:2]
    ky = H - 130 - len(kick) * 50
    for i, l in enumerate(kick):
        d.text((64, ky + i * 50), l, font=kick_f, fill=WHITE)
    return footer(im, ctx["left"], ctx["right"], WHITE, th["accent"])


def cover_magazine(post, photo, ctx):
    """Retro car-magazine cover: paper, masthead, framed print, ink headline."""
    th, seed = ctx["theme"], ctx["seed"]
    rng = random.Random(seed)
    im = paper_bg(th, seed)
    d = ImageDraw.Draw(im)
    im = glow_text(im, [((60, 150), "Revert")], font("script", 140), th["accent"], radius=1, glow_alpha=0,
                   anchor="ls", shadow=False)
    d = ImageDraw.Draw(im)
    spaced(d, (420, 104), "MEDIA", font("head", 52), th["text"], 6)
    issue = datetime.now().strftime("%b %Y").upper()
    d.text((W - 60, 86), f"NO. {ctx['issue']:03d}", font=font("vhs", 44), fill=th["text"], anchor="ra")
    d.text((W - 60, 128), issue, font=font("vhs", 44), fill=th["text"], anchor="ra")
    d.rectangle([60, 178, W - 60, 184], fill=th["text"])
    d.rectangle([60, 192, W - 60, 194], fill=th["text"])
    pic = filmify(smart_crop(photo, 880, 600), th, 0.8, seed)
    fr = framed(pic, 16, color=WHITE, angle=rng.uniform(-2.2, 2.2))
    im = comp(im, fr, ((W - fr.width) // 2, 218))
    tb, tf = tag_colors(post, th)
    pill(im, tag_for(post), W - 70, 236, tb, tf)
    th_ink = dict(th, text=th["text"])
    im, _ = headline_block(im, post, th_ink, 64, H - 128, W - 128, max_lines=3, start=104, minimum=60,
                           glow=False, kicker_color=th["text"])
    return footer(im, ctx["left"], ctx["right"], th["text"], th["accent"])


def cover_sticker(post, photo, ctx):
    """Blurred background, photo cut into a jagged burst with a white edge (logo style)."""
    th, seed = ctx["theme"], ctx["seed"]
    bg = filmify(smart_crop(photo, W, H), th, 1.0, seed).filter(ImageFilter.GaussianBlur(22))
    im = Image.blend(bg, Image.new("RGB", (W, H), th["bg"]), 0.55)
    sw, sh = 980, 700
    mask = starburst((sw, sh), 22, 0.88, seed)
    burst_bg = starburst((sw + 120, sh + 100), 16, 0.8, seed + 1)
    dots = halftone((sw + 120, sh + 100), th["accent"], 9, 20, "radial", 230)
    dots.putalpha(Image.fromarray(np.minimum(np.asarray(dots.split()[3]), np.asarray(burst_bg))))
    im = comp(im, dots, ((W - sw - 120) // 2 + 30, 200))
    outline = mask.filter(ImageFilter.MaxFilter(15))
    sticker = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    sticker.paste(Image.new("RGB", (sw, sh), WHITE), (0, 0), outline)
    pic = filmify(smart_crop(photo, sw, sh), th, 0.9, seed)
    sticker.paste(pic, (0, 0), mask)
    shadow = Image.new("RGBA", (sw + 40, sh + 40), (0, 0, 0, 0))
    shadow.paste(Image.new("RGB", (sw, sh), (0, 0, 0)), (24, 28), outline)
    shadow.putalpha(shadow.split()[3].point(lambda v: v * 0.55).filter(ImageFilter.GaussianBlur(10)))
    rot = random.Random(seed).uniform(-4, 4)
    im = comp(im, shadow.rotate(rot, expand=True, resample=Image.BICUBIC), ((W - sw) // 2 - 30, 210))
    im = comp(im, sticker.rotate(rot, expand=True, resample=Image.BICUBIC), ((W - sw) // 2 - 30, 210))
    im = vertical_fade(im, 880, H, th["bg"], 235)
    im = paste_badge(im)
    pill(im, tag_for(post), W - 52, 70, *tag_colors(post, th))
    script = post.get("category") in ("THROWBACK", "SPOTTED")
    if script:
        d = ImageDraw.Draw(im)
        f, lines = fit_text(d, post["headline"], "script", W - 140, 2, 130, 76)
        lh = int(f.size * 0.95)
        base = H - 150 - (50 if post.get("kicker") else 0)
        xy = [((64, base - (len(lines) - 1 - i) * lh), l) for i, l in enumerate(lines)]
        im = glow_text(im, xy, f, th["text"], radius=16, glow_alpha=160, anchor="ls")
        if post.get("kicker"):
            ImageDraw.Draw(im).text((66, H - 140), post["kicker"].upper()[:60], font=font("cond8", 36),
                                    fill=th["accent"])
    else:
        im, _ = headline_block(im, post, th, 64, H - 128, W - 128, max_lines=2, start=110, minimum=64, bar=False)
    return footer(im, ctx["left"], ctx["right"], th["text"], th["accent"])


def cover_ticker(post, photo, ctx):
    """TV lower-third: full photo, letterbox bars, label strip + headline box + crawl line."""
    th, seed = ctx["theme"], ctx["seed"]
    im = filmify(smart_crop(photo, W, H), th, 1.0, seed)
    im = vertical_fade(im, int(H * 0.5), H, (0, 0, 0), 200)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 104], fill=(8, 8, 8))
    vf = font("vhs", 46)
    d.ellipse([200, 36, 228, 64], fill=RED)
    d.text((240, 28), "REVERT MEDIA", font=vf, fill=WHITE)
    d.text((W - 48, 28), datetime.now().strftime("%d.%m.%Y"), font=vf, fill=WHITE, anchor="ra")
    im = paste_badge(im, 104, (36, 20))
    d = ImageDraw.Draw(im)
    f, lines = fit_text(d, post["headline"].upper(), "head", W - 140, 3, 96, 58)
    cap = cap_height(f)
    lh = int(cap * 1.26)
    box_h = cap + (len(lines) - 1) * lh + 60
    crawl_h = 64
    box_top = H - 120 - crawl_h - box_h
    label = tag_for(post)
    lf = font("cond8", 40)
    lw = spaced_width(d, label, lf, 4) + 48
    lb, lfg = tag_colors(post, th)
    d.rectangle([40, box_top - 62, 40 + lw, box_top], fill=lb)
    spaced(d, (64, box_top - 56), label, lf, lfg, 4)
    d.rectangle([40, box_top, W - 40, box_top + box_h], fill=(250, 248, 240))
    for i, l in enumerate(lines):
        d.text((70, box_top + 30 + cap + i * lh), l, font=f, fill=INK, anchor="ls")
    d.rectangle([40, box_top + box_h, W - 40, box_top + box_h + crawl_h], fill=(10, 10, 10))
    crawl = ("  >>  " + (post.get("kicker") or "") + "  >>  ").upper()
    cf = font("vhs", 42)
    while d.textlength(crawl, font=cf) > W - 110 and len(crawl) > 10:
        crawl = crawl[:-5] + "..."
    d.text((60, box_top + box_h + 10), crawl, font=cf, fill=th["accent"] if not th.get("mono") else WHITE)
    return footer(im, ctx["left"], ctx["right"], WHITE, th["accent"], rule=False)


def cover_vhs(post, photo, ctx):
    th, seed = ctx["theme"], ctx["seed"]
    im = textured(th["bg"], seed=seed)
    im.paste(filmify(smart_crop(photo, W, 980), th, 1.25, seed), (0, 0))
    im = scanlines(vertical_fade(im, 490, 980, th["bg"], 255))
    im = comp(im, halftone((380, 260), th["accent"], 7, 20, "diag", 55).transpose(Image.FLIP_TOP_BOTTOM),
              (W - 380, H - 420))
    im = paste_badge(im)
    pill(im, "THROWBACK", W - 52, 70, th["accent2"] if not th.get("mono") else RED, INK if not th.get("mono") else WHITE)
    d = ImageDraw.Draw(im)
    f = font("vhs", 46)
    play_icon(d, 64, 205, 26, th["text"])
    d.text((100, 196), "PLAY", font=f, fill=th["text"])
    d.text((W - 64, 196), "SP", font=f, fill=th["text"], anchor="ra")
    name_f, name_lines = fit_text(d, post["headline"], "script", W - 140, 2, 150, 80)
    tag_f, tag_lines = fit_text(d, post.get("kicker", "").upper(), "head", W - 140, 2, 64, 40)
    y = H - 150 - len(tag_lines) * (tag_f.size + 8)
    tag_xy = [((64, y + i * (tag_f.size + 8)), line) for i, line in enumerate(tag_lines)]
    y_name = y - 30 - len(name_lines) * name_f.size
    name_xy = [((58, y_name + i * name_f.size), l) for i, l in enumerate(name_lines)]
    im = glow_text(im, name_xy, name_f, th["text"], radius=16, glow_alpha=170)
    im = glow_text(im, tag_xy, tag_f, th["accent"], radius=10, glow_alpha=90)
    if post.get("year"):
        im = glow_text(im, [((W - 64, y_name - 40), post["year"])], font("vhs", 120), ORANGE,
                       radius=12, glow_alpha=150, anchor="rs")
    return footer(im, ctx["left"], ctx["right"], th["text"], th["accent"])


def cover_polaroid(post, photo, ctx):
    """An instant photo on a textured background, handwritten caption, bit of tape."""
    th, seed = ctx["theme"], ctx["seed"]
    rng = random.Random(seed)
    im = paper_bg(th, seed) if th["paper"] else textured(th["bg2"], seed=seed, grad=0.5)
    if not th["paper"]:
        im = comp(im, halftone((W, H), th["accent"], 10, 30, "radial", 45))
    pic = filmify(smart_crop(photo, 760, 660), th, 1.1, seed)
    cw, chh = 820, 900
    card = Image.new("RGB", (cw, chh), (250, 248, 240))
    card.paste(pic, (30, 30))
    cd = ImageDraw.Draw(card)
    text_w = cw - 80 - (170 if post.get("year") else 0)
    f, lines = fit_text(cd, post["headline"], "script", text_w, 2, 92, 52)
    lh = int(f.size * 0.92)
    zone_top, zone_bot = 690, chh - 22                     # the white strip under the photo
    block = f.size * 0.75 + (len(lines) - 1) * lh
    base = zone_top + (zone_bot - zone_top - block) / 2 + f.size * 0.75
    for i, l in enumerate(lines):
        cd.text((44, base + i * lh), l, font=f, fill=(30, 30, 40), anchor="ls")
    if post.get("year"):
        cd.text((cw - 36, zone_bot - 40), post["year"], font=font("vhs", 70), fill=(210, 60, 40), anchor="rs")
    angle = rng.uniform(-4, 4)
    fr = framed(card, 0, color=(250, 248, 240), shadow=30, angle=angle)
    im = comp(im, fr, ((W - fr.width) // 2, 40))
    tape = Image.new("RGBA", (220, 70), (240, 232, 200, 170))
    tape = tape.rotate(angle + rng.uniform(-12, 12), expand=True, resample=Image.BICUBIC)
    im = comp(im, tape, (W // 2 - tape.width // 2, 70))
    im = paste_badge(im, 100, (40, 1080))
    pill(im, tag_for(post), W - 52, 1090, th["accent"], th["on_accent"])
    d = ImageDraw.Draw(im)
    kick = post.get("kicker", "").upper()
    col = th["text"]
    if kick:
        kf, kl = fit_text(d, kick, "head", W - 230, 2, 46, 30)
        for i, l in enumerate(kl[:2]):
            d.text((172, 1170 + i * (kf.size + 6)), l, font=kf, fill=col)
    return footer(im, ctx["left"], ctx["right"], col, th["accent"], rule=False)


COVERS = {"fade": cover_fade, "boxes": cover_boxes, "split": cover_split, "magazine": cover_magazine,
          "sticker": cover_sticker, "ticker": cover_ticker, "vhs": cover_vhs, "polaroid": cover_polaroid}


# ─────────────────────────── inner slides ───────────────────────────

def slide_header(im, th, idx, total, color=None):
    im = paste_badge(im, 86, (48, 48))
    ImageDraw.Draw(im).text((W - 60, 66), f"{idx:02d}/{total:02d}", font=font("vhs", 54),
                            fill=color or th["text"], anchor="ra")
    return im


def detail_panel(post, slide, photo, idx, total, th, seed):
    im = textured(th["bg"], seed=seed + idx)
    if not th["paper"]:
        im.paste(photo_fill(photo, th, W, 820, seed + idx), (0, 0))
        im = vertical_fade(im, 410, 820, th["bg"], 255)
    else:
        im = paper_bg(th, seed + idx)
        im = comp(im, framed(photo_fill(photo, th, 900, 560, seed + idx), 14, angle=-1.5), (60, 150))
    if post.get("category") == "THROWBACK":
        im = scanlines(im)
    im = slide_header(im, th, idx, total)
    return text_points(im, post, slide, th, 64, H - 110, W - 128, th["text"], th["accent"], glow=not th["paper"])


def detail_card(post, slide, photo, idx, total, th, seed):
    base = photo_fill(photo, th, W, H, seed + idx)
    im = Image.blend(base, Image.new("RGB", (W, H), (0, 0, 0)), 0.35)
    im = slide_header(im, th, idx, total, WHITE)
    card_col = (248, 245, 236) if not th["paper"] else th["bg"]
    d = ImageDraw.Draw(im)
    # measure content first
    tf, tl = fit_text(d, slide["title"].upper(), "head", W - 260, 2, 90, 56)
    pf = font("body", 38)
    pts = [wrap(d, p, pf, W - 300)[:3] for p in slide["points"][:3]]
    cap = cap_height(tf)
    content_h = cap + (len(tl) - 1) * int(cap * 1.24) + 40 + sum(len(p) * 50 + 22 for p in pts)
    top = H - 120 - content_h - 70
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle([70, top + 12, W - 50, H - 98], 28, fill=(0, 0, 0, 140))
    ld.rounded_rectangle([60, top, W - 60, H - 110], 28, fill=card_col + (255,))
    ld.rectangle([60, top, 76, H - 110], fill=th["accent"] + (255,))
    im = comp(im, layer)
    ink = INK if not th["paper"] else th["text"]
    acc = th["accent"] if th["accent"] != card_col else RED
    return text_points(im, post, slide, th, 120, H - 150, W - 240, ink, acc, glow=False, fonts=(tf, tl))


def detail_numbered(post, slide, photo, idx, total, th, seed):
    im = paper_bg(th, seed) if th["paper"] else textured(th["bg"], seed=seed + idx)
    ph = photo_fill(photo, th, W, 520, seed + idx)
    mask = Image.new("L", (W, 520), 255)
    ImageDraw.Draw(mask).polygon([(0, 520), (W, 440), (W, 520)], fill=0)
    im.paste(ph, (0, 0), mask)
    im = slide_header(im, th, idx, total, WHITE)
    d = ImageDraw.Draw(im)
    tf, tl = fit_text(d, slide["title"].upper(), "head", W - 128, 2, 96, 60)
    cap = cap_height(tf)
    y = 560
    for i, l in enumerate(tl):
        d.text((64, y + cap + i * int(cap * 1.24)), l, font=tf, fill=th["text"], anchor="ls")
    y += cap + (len(tl) - 1) * int(cap * 1.24) + 50
    nf, pf = font("head", 76), font("body", 40)
    for n, p in enumerate(slide["points"][:3], 1):
        lines = wrap(d, p, pf, W - 128 - 140)[:3]
        d.text((64, y - 8), f"{n:02d}", font=nf, fill=th["accent"])
        for j, l in enumerate(lines):
            d.text((64 + 140, y + 10 + j * 50), l, font=pf, fill=th["text"])
        y += max(100, len(lines) * 50 + 40)
    return im


def text_points(im, post, slide, th, x, bottom, max_w, color, accent, glow=True, fonts=None):
    d = ImageDraw.Draw(im)
    title_f, title_lines = fonts or fit_text(d, slide["title"].upper(), "head", max_w, 2, 104, 64)
    pf = font("body", 40 if glow else 38)
    lh_p = 52 if glow else 50
    points = [wrap(d, p, pf, max_w - 50)[:3] for p in slide["points"][:3]]
    cap = cap_height(title_f)
    lh = int(cap * 1.24)
    pts_h = sum(len(p) * lh_p + 22 for p in points)
    title_h = cap + (len(title_lines) - 1) * lh
    y0 = bottom - pts_h - title_h - 40
    xy = [((x, y0 + cap + i * lh), l) for i, l in enumerate(title_lines)]
    im = glow_text(im, xy, title_f, color, radius=12, glow_alpha=110, anchor="ls") if glow else \
        plain_text(im, xy, title_f, color, anchor="ls")
    d = ImageDraw.Draw(im)
    y = y0 + title_h + 36
    for lines in points:
        d.rectangle([x, y + 16, x + 16, y + 32], fill=accent)
        for j, l in enumerate(lines):
            d.text((x + 42, y + j * lh_p), l, font=pf, fill=color)
        y += len(lines) * lh_p + 22
    return im


def stat_glow(post, photo, idx, total, th, seed):
    base = photo_fill(photo, th, W, H, seed + 50)
    im = Image.blend(base, Image.new("RGB", (W, H), th["bg"] if not th["paper"] else INK), 0.6)
    im = comp(im, halftone((W, 520), th["accent"], 10, 24, "diag", 70), (0, H - 520))
    im = slide_header(im, th, idx, total, WHITE)
    return stat_text(im, post, WHITE, th["accent"], glow=True)


def stat_block(post, photo, idx, total, th, seed):
    im = textured(th["accent"], seed=seed, grad=0.15, noise=5)
    im = comp(im, halftone((W, H), th["on_accent"], 7, 22, "radial", 45))
    if photo is not None:
        circ = 300
        pic = filmify(smart_crop(photo, circ, circ), th, 0.9, seed)
        m = Image.new("L", (circ * 3, circ * 3), 0)
        ImageDraw.Draw(m).ellipse([0, 0, circ * 3, circ * 3], fill=255)
        ring = Image.new("RGBA", (circ + 20, circ + 20), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse([0, 0, circ + 19, circ + 19], fill=th["on_accent"] + (255,))
        ring.paste(pic, (10, 10), m.resize((circ, circ), Image.LANCZOS))
        im = comp(im, ring, ((W - circ) // 2 - 10, 170))
    im = slide_header(im, th, idx, total, th["on_accent"])
    return stat_text(im, post, th["on_accent"], th["on_accent"], glow=False, top_offset=170)


def stat_text(im, post, color, label_color, glow=True, top_offset=0):
    d = ImageDraw.Draw(im)
    vf, vlines = fit_text(d, post["stat"]["value"].upper(), "head", W - 120, 2, 250, 110)
    cap = cap_height(vf)
    lh = int(cap * 1.2)
    block = cap + (len(vlines) - 1) * lh
    y0 = H // 2 - block // 2 - 60 + top_offset
    xy = [((W // 2, y0 + cap + i * lh), l) for i, l in enumerate(vlines)]
    im = glow_text(im, xy, vf, color, radius=20, glow_alpha=170, anchor="ms") if glow else \
        plain_text(im, xy, vf, color, anchor="ms")
    d = ImageDraw.Draw(im)
    lf, llines = fit_text(d, post["stat"]["label"].upper(), "cond8", W - 160, 2, 50, 34)
    ly = y0 + block + 50
    for l in llines:
        lw = spaced_width(d, l, lf, 5)
        spaced(d, ((W - lw) / 2, ly), l, lf, label_color, 5)
        ly += lf.size + 12
    return im


def outro_slide(handle: str, th, seed: int = 0) -> Image.Image:
    im = paper_bg(th, seed) if th["paper"] else textured(th["bg2"], seed=seed + 99)
    im = comp(im, halftone((W, 700), th["accent"], 12, 26, "diag", 110))
    if not th["paper"]:
        im = vertical_fade(im, 300, 1100, th["bg"], 230)
    big = logo_badge(560)
    im = comp(im, big, ((W - big.width) // 2, 170))
    im = glow_text(im, [((W // 2, 850), "FOLLOW FOR MORE")], font("head", 74), th["text"], anchor="ma",
                   radius=14, glow_alpha=0 if th["paper"] else 140, shadow=not th["paper"])
    d = ImageDraw.Draw(im)
    hf = font("cond8", 52)
    t = "@" + handle.upper()
    tw = spaced_width(d, t, hf, 4)
    spaced(d, ((W - tw) / 2, 955), t, hf, th["accent"], 4)
    d.text((W // 2, 1050), "Car news, crazy UAE stuff & throwbacks", font=font("body5", 36), fill=th["text"],
           anchor="ma")
    return im if th["paper"] else scanlines(im, 20)


DETAILS = {"panel": detail_panel, "card": detail_card, "numbered": detail_numbered}
STATS = {"glow": stat_glow, "block": stat_block}


# ─────────────────────────── choosing a style ───────────────────────────

def choose_style(kind: str, has_photo: bool, recent: list[dict], rng: random.Random) -> dict:
    """Pick template + theme + inner layouts, avoiding what the last few posts used."""
    recent_t = [r.get("template") for r in recent[-3:]]
    recent_th = [r.get("theme") for r in recent[-3:]]
    options = [n for n, t in TEMPLATES.items() if kind in t["kinds"] and (has_photo or not t["photo"])]
    if not options:
        options = ["fade"] if kind != "throwback" or not has_photo else ["vhs"]
    fresh = [o for o in options if o not in recent_t] or options
    template = rng.choice(fresh)
    themes = TEMPLATES[template]["themes"]
    fresh_th = [t for t in themes if t not in recent_th] or themes
    theme = rng.choice(fresh_th)
    return {"template": template, "theme": theme,
            "detail": rng.choice(DETAIL_LAYOUTS), "stat": rng.choice(STAT_LAYOUTS)}


# ─────────────────────────── build a full post ───────────────────────────

def render_post(post: dict, photos: list[Path], source: str, handle: str, out_dir: Path, prefix: str,
                carousel: bool, outro: bool = True, recent: list | None = None, kind: str = "news",
                credit: str = "", issue: int = 1, style: dict | None = None) -> tuple[list[Path], dict]:
    seed = random.randint(0, 10_000)
    rng = random.Random(seed)
    imgs = [Image.open(p).convert("RGB") for p in photos]
    first = imgs[0] if imgs else None
    style = style or choose_style(kind, first is not None, recent or [], rng)
    th = THEMES[style["theme"]]
    left = credit or f"Source: {source}"
    ctx = {"theme": th, "seed": seed, "issue": issue, "left": left,
           "right": "SWIPE  >>" if carousel else "@" + handle}
    slides = [COVERS[style["template"]](post, first, ctx)]
    if carousel:
        details = post.get("slides", [])
        has_stat = bool(post.get("stat", {}).get("value"))
        total = 1 + len(details) + int(has_stat) + int(outro)
        n = 2
        if has_stat:
            slides.append(STATS[style["stat"]](post, imgs[1 % len(imgs)] if imgs else None, n, total, th, seed))
            n += 1
        layouts = [style["detail"]] + [l for l in DETAIL_LAYOUTS if l != style["detail"]]
        for i, s in enumerate(details):
            ph = imgs[(i + 2) % len(imgs)] if len(imgs) > 1 else first
            slides.append(DETAILS[layouts[i % 2]](post, s, ph, n, total, th, seed))   # alternate 2 layouts
            n += 1
        if outro:
            slides.append(outro_slide(handle, th, seed))
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, s in enumerate(slides):
        p = out_dir / f"{prefix}_{i + 1}.jpg"
        s.save(p, "JPEG", quality=90, optimize=True)
        paths.append(p)
    return paths, style

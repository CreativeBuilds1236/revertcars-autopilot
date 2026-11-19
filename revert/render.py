"""Post designer — clean, editorial house style for Revert Media.

Rules:
  • Photos are real press/article photos and are NEVER filtered or altered — only cropped/resized.
    (Gradients sit on top of the photo where text needs contrast.)
  • One typeface family (Anton headlines, Barlow text), one accent colour (the logo's pink).
  • Same structure on every post: logo top-left, tag top-right, headline bottom-left, source in the footer.
  • As much real information per slide as fits cleanly: key-spec tables, 3-4 detailed points.

Every image is 1080x1350 (4:5) JPEG.
"""
from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .util import ASSETS

W, H = 1080, 1350
M = 64                                  # outer margin
CREAM = (246, 242, 230)
INK = (16, 18, 13)
PINK = (242, 170, 180)
RED = (226, 64, 58)
WHITE = (252, 250, 244)
MUTED = (190, 186, 172)
FONTS = ASSETS / "fonts"

# ─────────────────────────── colour themes ───────────────────────────
THEMES = {
    "olive":    dict(bg=(17, 19, 14), bg2=(30, 34, 26), text=CREAM, muted=MUTED, accent=PINK, on_accent=INK,
                     rule=(70, 74, 62), paper=False),
    "graphite": dict(bg=(14, 14, 15), bg2=(30, 30, 32), text=WHITE, muted=(176, 176, 172), accent=PINK,
                     on_accent=INK, rule=(66, 66, 68), paper=False),
    "cream":    dict(bg=(240, 234, 220), bg2=(226, 217, 196), text=INK, muted=(96, 92, 80), accent=(200, 70, 88),
                     on_accent=WHITE, rule=(190, 180, 160), paper=True),
}

# cover layouts: which post kinds they suit, which themes, whether they need a photo
TEMPLATES = {
    "full":     dict(themes=["olive", "graphite"], kinds={"news", "community", "throwback"}, photo=True),
    "fade":     dict(themes=["olive", "graphite"], kinds={"news", "community"}, photo=False),
    "split":    dict(themes=["olive", "cream"], kinds={"news"}, photo=False),
    "magazine": dict(themes=["cream"], kinds={"news", "throwback"}, photo=True),
}
DETAIL_LAYOUTS = ["panel"]
STAT_LAYOUTS = ["clean"]
TAG_TEXT = {"ONLY_IN_UAE": "ONLY IN THE UAE", "SPOTTED": "SPOTTED"}


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    files = {"head": "anton-400-normal.ttf", "cond": "barlow-condensed-700-normal.ttf",
             "cond8": "barlow-condensed-800-normal.ttf", "cond6": "barlow-condensed-600-normal.ttf",
             "body": "barlow-600-normal.ttf", "body5": "barlow-500-normal.ttf"}
    return ImageFont.truetype(str(FONTS / files[name]), size)


# ─────────────────────────── photos (crop only) ───────────────────────────

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


def filmify(im: Image.Image, theme=None, strength: float = 1.0, seed: int = 0) -> Image.Image:
    """Kept for compatibility: photos are deliberately NOT filtered any more."""
    return im


def photo(img: Image.Image | None, w: int, h: int, th: dict) -> Image.Image:
    if img is None:
        return Image.new("RGB", (w, h), th["bg2"])
    return smart_crop(img, w, h)


# ─────────────────────────── drawing helpers ───────────────────────────

def comp(base: Image.Image, layer: Image.Image, xy=(0, 0)) -> Image.Image:
    out = base.convert("RGBA")
    out.alpha_composite(layer, (int(xy[0]), int(xy[1])))
    return out.convert("RGB")


def vertical_fade(im, start, end, color, max_alpha=245, power=1.4):
    over = Image.new("RGBA", im.size, tuple(color) + (0,))
    ramp = np.clip((np.arange(im.height) - start) / max(1, end - start), 0, 1) ** power
    a = np.repeat((ramp * max_alpha)[:, None], im.width, axis=1)
    over.putalpha(Image.fromarray(a.astype(np.uint8)))
    return Image.alpha_composite(im.convert("RGBA"), over).convert("RGB")


def top_shade(im, height=260, alpha=130):
    return vertical_fade(im.transpose(Image.FLIP_TOP_BOTTOM), im.height - height, im.height, (0, 0, 0),
                         alpha).transpose(Image.FLIP_TOP_BOTTOM)


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


def shadow_text(im, xy_lines, fnt, fill, anchor="ls", shadow=True):
    """Crisp text with a soft drop shadow (for legibility on photos)."""
    if shadow:
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for (x, y), line in xy_lines:
            d.text((x + 2, y + 3), line, font=fnt, fill=(0, 0, 0, 150), anchor=anchor)
        im = Image.alpha_composite(im.convert("RGBA"), layer.filter(ImageFilter.GaussianBlur(3))).convert("RGB")
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


def pill(im, text, right_x, top_y, bg, fg, size=30):
    d = ImageDraw.Draw(im)
    f = font("cond8", size)
    tw = spaced_width(d, text, f, 3)
    pad_x, h = 18, size + 18
    x0 = right_x - tw - 2 * pad_x
    d.rounded_rectangle([x0, top_y, right_x, top_y + h], radius=6, fill=bg)
    spaced(d, (x0 + pad_x, top_y + 6), text, f, fg, 3)
    return x0


_logo_cache = {}


def logo_badge(size: int) -> Image.Image:
    if size not in _logo_cache:
        lg = ImageOps.fit(Image.open(ASSETS / "logo.png").convert("RGB"), (size, size), Image.LANCZOS)
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
        mask = mask.resize((size, size), Image.LANCZOS)
        ring = size + 8
        badge = Image.new("RGBA", (ring + 12, ring + 12), (0, 0, 0, 0))
        sh = Image.new("RGBA", badge.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse([6, 8, ring + 6, ring + 8], fill=(0, 0, 0, 110))
        badge = Image.alpha_composite(badge, sh.filter(ImageFilter.GaussianBlur(4)))
        ImageDraw.Draw(badge).ellipse([2, 2, ring + 2, ring + 2], fill=CREAM)
        badge.paste(lg, (6, 6), mask)
        _logo_cache[size] = badge
    return _logo_cache[size]


def paste_badge(im, size=96, xy=(56, 56)):
    return comp(im, logo_badge(size), xy)


def footer(im, left: str, right: str, color, accent, rule_color=None, y=H - 72):
    d = ImageDraw.Draw(im)
    f = font("cond6", 26)
    d.line([(M, y - 20), (W - M, y - 20)], fill=rule_color or color, width=1)
    spaced(d, (M, y), left.upper(), f, color, 2)
    rw = spaced_width(d, right.upper(), f, 2)
    spaced(d, (W - M - rw, y), right.upper(), f, accent if "SWIPE" in right.upper() else color, 2)
    return im


def tag_for(post) -> str:
    if post.get("is_rumour"):
        return "UNCONFIRMED"
    c = post.get("category", "NEWS")
    return TAG_TEXT.get(c, c).replace("_", " ")


def tag_colors(post, th):
    return (RED, WHITE) if post.get("is_rumour") else (th["accent"], th["on_accent"])


def headline_block(im, post, th, bottom, on_photo=True, max_lines=3, start=112, minimum=62,
                   kicker_lines=3, text=None, muted=None):
    """Headline + kicker, bottom-aligned at `bottom`. Returns (image, top_y)."""
    d = ImageDraw.Draw(im)
    text_col = text or th["text"]
    head_f, head_lines = fit_text(d, post["headline"].upper(), "head", W - 2 * M, max_lines, start, minimum)
    kick_f = font("body5", 36)
    kick = balanced(d, post.get("kicker", ""), kick_f, W - 2 * M)[:kicker_lines] if post.get("kicker") else []
    cap = cap_height(head_f)
    lh = int(cap * 1.22)
    year = post.get("year") if post.get("category") == "THROWBACK" else ""
    year_h = 64 if year else 0
    block = year_h + cap + (len(head_lines) - 1) * lh + (30 + len(kick) * 48 if kick else 0)
    y0 = bottom - block
    if year:
        d.text((M, y0), year, font=font("cond8", 52), fill=th["accent"])
    hy = y0 + year_h
    if not year:                                   # the pink year already marks the block on throwbacks
        d.rectangle([M, hy - 26, M + 72, hy - 20], fill=th["accent"])
    im = shadow_text(im, [((M, hy + cap + i * lh), l) for i, l in enumerate(head_lines)], head_f, text_col,
                     shadow=on_photo)
    d = ImageDraw.Draw(im)
    ky = hy + cap + (len(head_lines) - 1) * lh + 24
    for i, l in enumerate(kick):
        d.text((M, ky + i * 48), l, font=kick_f, fill=muted or th["muted"])
    return im, y0


# ─────────────────────────── covers ───────────────────────────

def cover_full(post, img, ctx):
    """Full-bleed photo, dark gradient at the bottom for the text."""
    th = ctx["theme"]
    im = photo(img, W, H, th)
    im = vertical_fade(im, int(H * 0.40), H, (10, 11, 9), 238, power=1.5)
    im = top_shade(im)
    im = paste_badge(im)
    pill(im, tag_for(post), W - 56, 74, *tag_colors(post, th))
    im, _ = headline_block(im, post, dict(th, text=CREAM, muted=(222, 218, 206)), H - 124)
    return footer(im, ctx["left"], ctx["right"], (210, 206, 194), th["accent"], (120, 118, 110))


def cover_fade(post, img, ctx):
    """Photo in the top two-thirds, fading into a solid panel that carries the text."""
    th = ctx["theme"]
    im = Image.new("RGB", (W, H), th["bg"])
    ph_h = 900
    im.paste(photo(img, W, ph_h, th), (0, 0))
    im = vertical_fade(im, int(ph_h * 0.55), ph_h, th["bg"], 255, power=1.3)
    im = top_shade(im)
    im = paste_badge(im)
    pill(im, tag_for(post), W - 56, 74, *tag_colors(post, th))
    im, _ = headline_block(im, post, th, H - 124)
    return footer(im, ctx["left"], ctx["right"], th["muted"], th["accent"], th["rule"])


def cover_split(post, img, ctx):
    """Headline panel on top, photo underneath (newspaper-style)."""
    th = ctx["theme"]
    band = 560
    im = Image.new("RGB", (W, H), th["bg2"] if not th["paper"] else th["bg"])
    im.paste(photo(img, W, H - band, th), (0, band))
    d = ImageDraw.Draw(im)
    d.rectangle([0, band - 6, W, band], fill=th["accent"])
    im = vertical_fade(im, H - 300, H, (10, 11, 9), 220)
    im = paste_badge(im)
    pill(im, tag_for(post), W - 56, 74, *tag_colors(post, th))
    d = ImageDraw.Draw(im)
    avail_top, avail_bot = 190, band - 40
    kick_f = font("body5", 34)
    start = 120
    while True:
        f, lines = fit_text(d, post["headline"].upper(), "head", W - 2 * M, 3, start, 58)
        kick = balanced(d, post.get("kicker", ""), kick_f, W - 2 * M)[:2] if post.get("kicker") else []
        cap = cap_height(f)
        lh = int(cap * 1.2)
        total = cap + (len(lines) - 1) * lh + (24 + len(kick) * 44 if kick else 0)
        if total <= avail_bot - avail_top or start <= 62:
            break
        start = f.size - 6
    y = avail_top + (avail_bot - avail_top - total) // 2
    for i, l in enumerate(lines):
        d.text((M, y + cap + i * lh), l, font=f, fill=th["text"], anchor="ls")
    ky = y + cap + (len(lines) - 1) * lh + 22
    for i, l in enumerate(kick):
        d.text((M, ky + i * 44), l, font=kick_f, fill=th["muted"])
    return footer(im, ctx["left"], ctx["right"], (210, 206, 194), th["accent"], (120, 118, 110))


def cover_magazine(post, img, ctx):
    """Print-magazine cover: paper, masthead, the photo as a clean print, ink headline."""
    th = ctx["theme"]
    im = Image.new("RGB", (W, H), th["bg"])
    im = paste_badge(im, 84, (M - 6, 42))
    d = ImageDraw.Draw(im)
    spaced(d, (M + 100, 58), "REVERT MEDIA", font("head", 50), th["text"], 4)
    sf = font("cond6", 28)
    d.text((W - M, 62), f"NO. {ctx['issue']:03d}", font=sf, fill=th["muted"], anchor="ra")
    d.text((W - M, 94), datetime.now().strftime("%B %Y").upper(), font=sf, fill=th["muted"], anchor="ra")
    d.rectangle([M, 150, W - M, 154], fill=th["text"])
    im.paste(photo(img, W - 2 * M, 620, th), (M, 180))
    pill(im, tag_for(post), W - M - 16, 196, *tag_colors(post, th))
    im, _ = headline_block(im, post, th, H - 124, on_photo=False, max_lines=3, start=96, minimum=56,
                           kicker_lines=2)
    return footer(im, ctx["left"], ctx["right"], th["muted"], th["accent"], th["rule"])


COVERS = {"full": cover_full, "fade": cover_fade, "split": cover_split, "magazine": cover_magazine}


# ─────────────────────────── inner slides ───────────────────────────

def inner_base(img, th, ph_h):
    im = Image.new("RGB", (W, H), th["bg"])
    if img is not None and ph_h:
        im.paste(photo(img, W, ph_h, th), (0, 0))
        im = vertical_fade(im, int(ph_h * 0.45), ph_h, th["bg"], 255, power=1.2)
        im = top_shade(im, 200, 110)
    return im


def slide_header(im, th, idx, total, on_photo=True):
    im = paste_badge(im, 72, (56, 56))
    d = ImageDraw.Draw(im)
    col = CREAM if on_photo else th["text"]
    d.text((W - M, 78), f"{idx:02d} / {total:02d}", font=font("cond6", 34), fill=col, anchor="ra")
    return im


def slide_footer(im, th, ctx):
    return footer(im, ctx["left"], "@" + ctx["handle"], th["muted"], th["accent"], th["rule"])


def fit_points(d, title, points, max_w, avail_h):
    """Largest title/point sizes that fit the available height."""
    for tsize, psize in ((92, 40), (84, 38), (76, 36), (70, 34), (64, 32), (58, 30), (54, 28)):
        tf, tl = fit_text(d, title.upper(), "head", max_w, 2, tsize, tsize - 12)
        pf = font("body", psize)
        lh = int(psize * 1.32)
        wrapped = [wrap(d, p, pf, max_w - 44)[:4] for p in points]
        cap = cap_height(tf)
        h = cap + (len(tl) - 1) * int(cap * 1.22) + 40 + sum(len(w) * lh + 24 for w in wrapped)
        if h <= avail_h:
            break
    return tf, tl, pf, lh, wrapped, h


def detail_slide(post, slide, img, idx, total, th, ctx):
    ph_h = 640 if img is not None else 0
    im = inner_base(img, th, ph_h)
    im = slide_header(im, th, idx, total, on_photo=img is not None)
    d = ImageDraw.Draw(im)
    top = max(ph_h - 120, 190)
    bottom = H - 120
    tf, tl, pf, lh, wrapped, h = fit_points(d, slide["title"], slide["points"][:4], W - 2 * M, bottom - top)
    y = bottom - h if img is not None else top + max(0, (bottom - top - h) // 3)
    cap = cap_height(tf)
    tlh = int(cap * 1.22)
    for i, l in enumerate(tl):
        d.text((M, y + cap + i * tlh), l, font=tf, fill=th["text"], anchor="ls")
    y += cap + (len(tl) - 1) * tlh + 40
    for lines in wrapped:
        d.rectangle([M, y + lh // 2 - 6, M + 12, y + lh // 2 + 6], fill=th["accent"])
        for j, l in enumerate(lines):
            d.text((M + 44, y + j * lh), l, font=pf, fill=th["text"])
        y += len(lines) * lh + 24
    return slide_footer(im, th, ctx)


def specs_slide(post, img, idx, total, th, ctx):
    """'Key specs' table — label on the left, value on the right, hairline rules between rows."""
    specs = [s for s in post.get("specs", []) if s.get("label") and s.get("value")][:7]
    ph_h = 420 if img is not None else 0
    im = inner_base(img, th, ph_h)
    im = slide_header(im, th, idx, total, on_photo=img is not None)
    d = ImageDraw.Draw(im)
    title_f = font("head", 88)
    cap = cap_height(title_f)
    y = max(ph_h - 90, 180)
    d.text((M, y + cap), "KEY SPECS", font=title_f, fill=th["text"], anchor="ls")
    y += cap + 44
    avail = (H - 140) - y
    # fewer specs → bigger rows, so the table fills the slide
    vsize = 46 if len(specs) <= 4 else 42 if len(specs) <= 6 else 38
    lf, vf = font("cond6", vsize - 10), font("body", vsize)
    vlh = int(vsize * 1.25)
    rows = []
    for s in specs:
        vlines = wrap(d, s["value"], vf, 620)[:2]
        rows.append((s["label"].upper(), vlines, len(vlines) * vlh))
    pad = max(28, min(70, (avail - sum(r[2] for r in rows)) // max(1, len(rows))))
    d.line([(M, y), (W - M, y)], fill=th["rule"], width=2)
    for label, vlines, body_h in rows:
        rh = body_h + pad
        spaced(d, (M, y + pad // 2 + (vlh - (vsize - 10)) // 2), label, lf, th["muted"], 2)
        for j, l in enumerate(vlines):
            d.text((W - M, y + pad // 2 + j * vlh), l, font=vf, fill=th["text"], anchor="ra")
        y += rh
        d.line([(M, y), (W - M, y)], fill=th["rule"], width=1)
    return slide_footer(im, th, ctx)


def stat_slide(post, img, idx, total, th, ctx):
    ph_h = 560 if img is not None else 0
    im = inner_base(img, th, ph_h)
    im = slide_header(im, th, idx, total, on_photo=img is not None)
    d = ImageDraw.Draw(im)
    vf, vlines = fit_text(d, post["stat"]["value"].upper(), "head", W - 2 * M, 2, 230, 100)
    cap = cap_height(vf)
    lh = int(cap * 1.18)
    y = max(ph_h, 300) + 40
    for i, l in enumerate(vlines):
        d.text((M, y + cap + i * lh), l, font=vf, fill=th["text"], anchor="ls")
    y += cap + (len(vlines) - 1) * lh + 40
    d.rectangle([M, y, M + 72, y + 6], fill=th["accent"])
    lf, ll = fit_text(d, post["stat"]["label"], "body", W - 2 * M, 2, 44, 32)
    for i, l in enumerate(ll):
        d.text((M, y + 30 + i * 56), l, font=lf, fill=th["muted"])
    return slide_footer(im, th, ctx)


def outro_slide(handle: str, th, seed: int = 0) -> Image.Image:
    im = Image.new("RGB", (W, H), th["bg"])
    big = logo_badge(440)
    im = comp(im, big, ((W - big.width) // 2, 250))
    d = ImageDraw.Draw(im)
    d.text((W // 2, 830), "FOLLOW FOR MORE", font=font("head", 72), fill=th["text"], anchor="ma")
    hf = font("cond8", 48)
    t = "@" + handle.upper()
    spaced(d, ((W - spaced_width(d, t, hf, 3)) / 2, 928), t, hf, th["accent"], 3)
    d.text((W // 2, 1010), "Car news, UAE stories & throwbacks", font=font("body5", 34), fill=th["muted"],
           anchor="ma")
    return im


# ─────────────────────────── choosing a style ───────────────────────────

def choose_style(kind: str, has_photo: bool, recent: list[dict], rng: random.Random) -> dict:
    """Pick cover layout + theme, avoiding what the last couple of posts used."""
    recent_t = [r.get("template") for r in recent[-2:]]
    recent_th = [r.get("theme") for r in recent[-2:]]
    options = [n for n, t in TEMPLATES.items() if kind in t["kinds"] and (has_photo or not t["photo"])]
    if not options:
        options = ["fade"]
    fresh = [o for o in options if o not in recent_t] or options
    template = rng.choice(fresh)
    themes = TEMPLATES[template]["themes"]
    fresh_th = [t for t in themes if t not in recent_th] or themes
    return {"template": template, "theme": rng.choice(fresh_th), "detail": "panel", "stat": "clean"}


# ─────────────────────────── build a full post ───────────────────────────

def render_post(post: dict, photos: list[Path], source: str, handle: str, out_dir: Path, prefix: str,
                carousel: bool, outro: bool = True, recent: list | None = None, kind: str = "news",
                credit: str = "", issue: int = 1, style: dict | None = None,
                min_total: int = 0) -> tuple[list[Path], dict]:
    seed = random.randint(0, 10_000)
    rng = random.Random(seed)
    imgs = [Image.open(p).convert("RGB") for p in photos]
    first = imgs[0] if imgs else None
    style = style or choose_style(kind, first is not None, recent or [], rng)
    if style.get("template") not in COVERS:                      # old style names → nearest clean one
        style = dict(style, template="full" if first is not None else "fade")
    if style.get("theme") not in THEMES:
        style = dict(style, theme="olive")
    th = THEMES[style["theme"]]
    ctx = {"theme": th, "seed": seed, "issue": issue, "handle": handle,
           "left": credit or f"Source: {source}", "right": "SWIPE  >>" if carousel else "@" + handle}
    slides = [COVERS[style["template"]](post, first, ctx)]
    if carousel:
        details = post.get("slides", [])
        specs = [s for s in post.get("specs", []) if s.get("label") and s.get("value")]
        has_specs = len(specs) >= 3
        has_stat = not has_specs and bool(post.get("stat", {}).get("value"))
        total = max(1 + int(has_specs or has_stat) + len(details) + int(outro), min_total)
        n = 2

        def pic(i):
            return imgs[i % len(imgs)] if imgs else None
        if has_specs:
            slides.append(specs_slide(post, pic(1), n, total, th, ctx))
            n += 1
        elif has_stat:
            slides.append(stat_slide(post, pic(1), n, total, th, ctx))
            n += 1
        for i, s in enumerate(details):
            slides.append(detail_slide(post, s, pic(i + 2) if len(imgs) > 1 else first, n, total, th, ctx))
            n += 1
        if outro:
            slides.append(outro_slide(handle, th, seed))
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, s in enumerate(slides):
        p = out_dir / f"{prefix}_{i + 1}.jpg"
        s.save(p, "JPEG", quality=92, optimize=True)
        paths.append(p)
    return paths, style

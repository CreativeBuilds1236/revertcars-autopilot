"""Read the full article behind a story and download its best photos."""
from __future__ import annotations

import io
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from PIL import Image

from .util import BOT_UA, clean_text, http, log

try:
    import trafilatura
except Exception:  # optional
    trafilatura = None


# Pictures that aren't real photographs: speculative renderings, illustrations, AI-made or edited images.
NOT_A_PHOTO = re.compile(r"render|illustrat|ai[- ]?generated|generated (by|with) ai|midjourney|dall-?e|"
                         r"stable diffusion|firefly|artist'?s? (impression|rendering)|imagined|speculative|"
                         r"photoshop|mock-?up|concept art|digital art|cgi by", re.I)
# Credit lines that mean the article's lead image is a rendering/illustration
RENDER_CREDIT = re.compile(r"(illustrations?|renderings?|renders?|images? generated)\s*(by|:|courtesy)|"
                           r"ai[- ]generated (image|illustration|picture)", re.I)


def resolve_google_news(url: str) -> str | None:
    """Google News RSS links are redirect tokens; turn them into the publisher's real URL."""
    if "news.google.com" not in url:
        return url
    try:
        from googlenewsdecoder import gnewsdecoder
        res = gnewsdecoder(url, interval=1)
        if res.get("status"):
            return res["decoded_url"]
    except Exception as ex:
        log.info("Could not decode Google News link: %s", ex)
    return None


def fetch_article(url: str) -> dict:
    """Returns {"text": str, "images": [urls], "title": str}. Never raises."""
    out = {"text": "", "images": [], "title": ""}
    try:
        r = http().get(url, timeout=25)
        r.raise_for_status()
        html = r.text
    except Exception as ex:
        log.info("Article fetch failed (%s): %s", url, ex)
        return out

    if trafilatura:
        try:
            out["text"] = trafilatura.extract(html, include_comments=False, include_tables=False,
                                              favor_precision=True) or ""
        except Exception:
            pass
    soup = BeautifulSoup(html, "html.parser")
    if not out["text"]:
        body = soup.find("article") or soup
        out["text"] = "\n".join(clean_text(p.get_text(" ")) for p in body.find_all("p") if len(p.get_text()) > 40)
    out["title"] = clean_text((soup.find("meta", property="og:title") or {}).get("content", "")) if soup else ""

    imgs = []
    page_has_renders = bool(RENDER_CREDIT.search(out["text"]))
    if not page_has_renders:          # the lead image may be the rendering — only trust it on clean pages
        for prop in ("og:image", "og:image:secure_url", "twitter:image"):
            m = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
            if m and m.get("content") and not NOT_A_PHOTO.search(m["content"]):
                imgs.append(urljoin(url, m["content"]))
    scope = soup.find("article") or soup.find("main") or soup
    for im in scope.find_all("img"):
        fig = im.find_parent("figure")
        caption = " ".join(filter(None, [im.get("alt"), im.get("title"), " ".join(im.get("class") or []),
                                         fig.get_text(" ") if fig else ""]))
        if NOT_A_PHOTO.search(caption) or (page_has_renders and not caption.strip()):
            out["skipped_images"] = out.get("skipped_images", 0) + 1
            continue
        cand = None
        srcset = im.get("srcset") or im.get("data-srcset")
        if srcset:
            parts = [p.strip().split(" ") for p in srcset.split(",") if p.strip()]
            parts = [(p[0], int(re.sub(r"\D", "", p[1]) or 0) if len(p) > 1 else 0) for p in parts]
            cand = max(parts, key=lambda x: x[1])[0] if parts else None
        cand = cand or im.get("data-src") or im.get("src")
        if cand and not cand.startswith("data:") and not NOT_A_PHOTO.search(cand):
            imgs.append(urljoin(url, cand))
    seen, uniq = set(), []
    for u in imgs:
        key = re.sub(r"[?#].*$", "", u)
        if key not in seen and not re.search(r"(logo|avatar|icon|sprite|author|badge|\.svg|\.gif)", u, re.I):
            seen.add(key)
            uniq.append(u)
    out["images"] = uniq[:15]
    return out


def _dhash(im: Image.Image) -> int:
    g = im.convert("L").resize((9, 8))
    px = list(g.getdata())
    return sum(1 << i for i in range(64) if px[(i // 8) * 9 + i % 8] > px[(i // 8) * 9 + i % 8 + 1])


def download_images(urls: list[str], dest: Path, prefix: str, max_n: int = 5,
                    min_w: int = 800, min_h: int = 450) -> list[Path]:
    """Download, filter out small/duplicate images, save as high-quality JPEG."""
    dest.mkdir(parents=True, exist_ok=True)
    saved, hashes = [], []
    for u in urls:
        if len(saved) >= max_n:
            break
        try:
            wm = "wikimedia.org" in u or "wikipedia.org" in u
            r = http().get(u, timeout=25, headers={"User-Agent": BOT_UA} if wm else None)
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content))
            im.load()
            im = im.convert("RGB")
        except Exception as ex:
            log.info("Photo download failed (%s): %s", str(ex)[:80], u[:120])
            continue
        w, h = im.size
        if w < min_w or h < min_h or w / h > 3 or h / w > 2:
            continue
        hsh = _dhash(im)
        if any(bin(hsh ^ o).count("1") < 10 for o in hashes):
            continue
        hashes.append(hsh)
        p = dest / f"{prefix}_src{len(saved)}.jpg"
        im.save(p, "JPEG", quality=92)
        saved.append(p)
    return saved

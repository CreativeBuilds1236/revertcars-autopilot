"""Things you send to the Telegram bot: Reddit posts, photos, article links → drafts.

  • Photo(s) + optional text            → a SPOTTED / community post, credited to whoever you name
  • Reddit link (+ photos if you like)  → community post credited "u/name via r/sub"
  • Any other article link              → a normal news post from that article (fact-checked as usual)

Credit: write "credit: @someone" or "u/someone" in the message to set the photo credit.
"""
from __future__ import annotations

import re
from datetime import datetime

from . import article
from .util import domain_of, http, log, now_utc

URL_RE = re.compile(r"https?://\S+")


def add_to_inbox(state, msg: dict) -> bool:
    """Returns True if this message is a new submission (first part of it)."""
    key = msg.get("media_group_id") or f"m{msg['message_id']}"
    inbox = state.data.setdefault("inbox", {})
    new = key not in inbox
    e = inbox.setdefault(key, {"photos": [], "text": "", "first": now_utc().isoformat(), "msg_id": msg["message_id"]})
    if msg.get("photo"):
        e["photos"].append(max(msg["photo"], key=lambda p: p.get("width", 0) * p.get("height", 0))["file_id"])
    doc = msg.get("document") or {}
    if str(doc.get("mime_type", "")).startswith("image/"):
        e["photos"].append(doc["file_id"])
    t = (msg.get("caption") or msg.get("text") or "").strip()
    if t:
        e["text"] = (e["text"] + "\n" + t).strip()
    e["last"] = now_utc().isoformat()
    state.dirty = True
    return new


def ready_keys(state, force=False, quiet_seconds=6) -> list[str]:
    out = []
    for k, e in state.data.get("inbox", {}).items():
        if force or (now_utc() - datetime.fromisoformat(e["last"])).total_seconds() > quiet_seconds:
            out.append(k)
    return out


def parse_credit(text: str, sub: str = "", author: str = "") -> str:
    m = re.search(r"(?im)^\s*(?:credit|photo|📸)\s*[:\-]\s*(.+)$", text)
    if m:
        return m.group(1).strip()[:60]
    u = re.search(r"\bu/([A-Za-z0-9_\-]{3,30})", text)
    user = f"u/{u.group(1)}" if u else (f"u/{author}" if author else "")
    if user and sub:
        return f"{user} via r/{sub}"
    if sub:
        return f"via r/{sub}"
    h = re.search(r"(?<![\w/])@([A-Za-z0-9_.]{2,30})", text)
    return f"@{h.group(1)}" if h else user


def try_reddit(url: str) -> dict:
    """Best effort: Reddit blocks most automated reads now, so this often returns {}."""
    try:
        r = http().get(url.split("?")[0].rstrip("/") + ".json", timeout=12,
                       headers={"User-Agent": "RevertMediaBot/1.0"})
        if r.status_code != 200:
            return {}
        post = r.json()[0]["data"]["children"][0]["data"]
        imgs = []
        if post.get("is_gallery") and post.get("media_metadata"):
            for v in post["media_metadata"].values():
                s = (v.get("s") or {}).get("u")
                if s:
                    imgs.append(s.replace("&amp;", "&"))
        elif re.search(r"\.(jpe?g|png|webp)$", post.get("url_overridden_by_dest", "") or "", re.I):
            imgs.append(post["url_overridden_by_dest"])
        return {"title": post.get("title", ""), "author": post.get("author", ""), "sub": post.get("subreddit", ""),
                "selftext": post.get("selftext", "")[:3000], "images": imgs}
    except Exception as ex:
        log.info("Reddit read failed (expected these days): %s", ex)
        return {}


def publisher_name(url: str, cfg) -> str:
    d = domain_of(url)
    for f in cfg.get("feeds", []):
        if domain_of(f["url"]) == d:
            return f["name"]
    return d


def build_item(entry: dict, cfg) -> tuple[dict | None, str]:
    """Turn an inbox entry into a draft item. Returns (item, problem_message)."""
    text = entry.get("text", "")
    urls = [u.rstrip(").,") for u in URL_RE.findall(text)]
    reddit_urls = [u for u in urls if "reddit.com" in u or "redd.it" in u]
    other_urls = [u for u in urls if u not in reddit_urls]
    plain = URL_RE.sub("", text).strip()
    trusted = set(cfg.get("google_news", {}).get("trusted_publishers", []))
    blocked = set(cfg.get("google_news", {}).get("blocked_publishers", []))

    if other_urls and not reddit_urls:      # an article link (with or without your own photos)
        url = other_urls[0]
        d = domain_of(url)
        # The blocked list only keeps sites out of the automatic drafts — a link you send yourself is read anyway
        # (still fact-checked against the article, and marked as a less trusted source).
        page = article.fetch_article(url)
        if len(page["text"]) < cfg["drafting"].get("min_source_chars", 500):
            return None, "I couldn't read enough of that article to fact-check it. Send the photos plus a few lines instead."
        item = {"kind": "news", "title": page["title"] or plain[:100] or url, "url": url,
                "source_name": publisher_name(url, cfg), "text": page["text"][:9000],
                "image_urls": page["images"], "outlets": [publisher_name(url, cfg)],
                "untrusted": any(d == b or d.endswith("." + b) for b in blocked)
                             or not any(d == t or d.endswith("." + t) for t in trusted),
                "angle": plain}
        if entry["photos"]:
            # your photos come first (the first one is the cover); the article's photos fill any gaps
            item["tg_file_ids"] = entry["photos"]
            item["fill_from_article"] = True
            m = re.search(r"(?im)^\s*(?:credit|photo|📸)\s*[:\-]\s*(.+)$", text)
            if m:
                item["credit"] = m.group(1).strip()[:60]
                item["angle"] = URL_RE.sub("", text.replace(m.group(0), "")).strip()
        return item, ""

    rd = try_reddit(reddit_urls[0]) if reddit_urls else {}
    sub = rd.get("sub") or (re.search(r"/r/([A-Za-z0-9_]+)", reddit_urls[0]).group(1)
                            if reddit_urls and re.search(r"/r/([A-Za-z0-9_]+)", reddit_urls[0]) else "")
    if not entry["photos"] and not rd.get("images"):
        return None, ("Reddit blocks bots from opening posts now, so I can't see that one. "
                      "Save the photo(s) and send them to me with the link and I'll draft it.")
    body = "\n".join(x for x in [rd.get("title", ""), rd.get("selftext", ""), plain] if x)
    item = {"kind": "community", "title": (rd.get("title") or plain.split("\n")[0] or "Spotted")[:120],
            "url": reddit_urls[0] if reddit_urls else "", "source_name": f"r/{sub}" if sub else "Community",
            "text": body, "image_urls": rd.get("images", []), "outlets": [],
            "credit": parse_credit(text, sub, rd.get("author", "")), "tg_file_ids": entry["photos"]}
    return item, ""

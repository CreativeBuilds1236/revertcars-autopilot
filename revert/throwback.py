"""Throwback posts: facts from Wikipedia, photos from Wikimedia Commons."""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from .util import BOT_UA, http, log, now_utc

WIKI = "https://en.wikipedia.org"
CAR_WORDS = re.compile(r"\b(automobile|car|cars|motor|racing|grand prix|rally|le mans|ferrari|porsche|ford|"
                       r"toyota|nissan|honda|mercedes|bmw|lamborghini|bugatti|jaguar|chevrolet|mustang|"
                       r"speed record|land speed|formula one|supercar|race car|driver)\b", re.I)


def _get(url, **params):
    r = http().get(url, params=params, headers={"User-Agent": BOT_UA}, timeout=25)
    r.raise_for_status()
    return r.json()


def wiki_text(title: str, max_chars: int = 7000) -> dict:
    data = _get(f"{WIKI}/w/api.php", action="query", prop="extracts|info", explaintext=1,
                titles=title, format="json", redirects=1, inprop="url")
    page = next(iter(data["query"]["pages"].values()))
    if "missing" in page:
        return {}
    text = page.get("extract", "")
    # drop reference-ish tail sections
    text = re.split(r"\n== (See also|References|External links|Notes|Further reading) ==", text)[0]
    return {"title": page["title"], "text": text[:max_chars], "url": page.get("fullurl", "")}


def wiki_images(title: str, max_n: int = 6) -> list[str]:
    try:
        data = _get(f"{WIKI}/api/rest_v1/page/media-list/{quote(title.replace(' ', '_'))}")
    except Exception as ex:
        log.info("media-list failed for %s: %s", title, ex)
        return []
    urls = []
    for item in data.get("items", []):
        if item.get("type") != "image":
            continue
        name = item.get("title", "").lower()
        if any(x in name for x in (".svg", "logo", "map", "diagram", "badge", "emblem", "flag", "icon", "chart")):
            continue
        srcset = item.get("srcset") or []
        if not srcset:
            continue
        src = srcset[-1]["src"]
        src = "https:" + src if src.startswith("//") else src
        # ask for a 1600px-wide thumbnail instead of the (sometimes huge) original
        src = re.sub(r"/(\d+)px-", "/1600px-", src)
        urls.append(src)
        if len(urls) >= max_n:
            break
    return urls


def on_this_day_car_event() -> dict | None:
    """Wikipedia 'On this day' events that are about cars."""
    t = now_utc()
    try:
        data = _get(f"{WIKI}/api/rest_v1/feed/onthisday/events/{t.month:02d}/{t.day:02d}")
        events = data.get("events", [])
    except Exception:
        return None
    for ev in events:
        if CAR_WORDS.search(ev.get("text", "")):
            pages = ev.get("pages") or []
            for p in pages:
                if CAR_WORDS.search(p.get("extract", "") + p.get("title", "")):
                    return {"title": p.get("titles", {}).get("canonical", p.get("title", "")).replace("_", " "),
                            "angle": f"On this day in {ev.get('year')}: {ev.get('text')}",
                            "year": ev.get("year")}
    return None


def pick_topic(cfg, state) -> dict:
    used = state.data["throwback_used"]
    cutoff = now_utc() - timedelta(days=60)
    ev = on_this_day_car_event()
    if ev and ev["title"] not in used:
        return ev
    topics = cfg.get("throwbacks", [])
    fresh = [t for t in topics if t["title"] not in used
             or datetime.fromisoformat(used[t["title"]]) < cutoff]
    pool = fresh or sorted(topics, key=lambda t: used.get(t["title"], ""))[:5]
    return random.choice(pool)


def build_throwback(cfg, state) -> dict | None:
    for _ in range(4):
        topic = pick_topic(cfg, state)
        state.data["throwback_used"][topic["title"]] = now_utc().isoformat()
        state.dirty = True
        try:
            info = wiki_text(topic["title"])
        except Exception as ex:
            log.warning("Wikipedia fetch failed for %s: %s", topic["title"], ex)
            continue
        if not info or len(info["text"]) < 800:
            continue
        return {
            "kind": "throwback",
            "title": info["title"],
            "url": info["url"],
            "source_name": "Wikipedia",
            "text": info["text"],
            "angle": topic.get("angle", ""),
            "image_urls": wiki_images(info["title"]),
            "outlets": ["Wikipedia"],
        }
    return None

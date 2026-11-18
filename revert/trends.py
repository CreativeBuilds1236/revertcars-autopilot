"""What are people in the UAE searching for right now? (Google Trends)

Reddit used to be read here too, but Reddit switched off its RSS feeds on 13 Nov 2026 and is closing its
public API, so Reddit content now comes in through the Telegram bot instead (share a post to the bot).
"""
from __future__ import annotations

import feedparser

from .util import clean_text, http, log


def car_vocab(cfg) -> set[str]:
    words = {b.lower() for b in cfg.get("brands", [])}
    for group in cfg.get("boost_keywords", {}).values():
        words |= {k.strip().lower() for k in group}
    words |= {"car", "cars", "motor", "supercar", "ev", "drift", "f1", "formula 1", "grand prix", "sema",
              "suv", "pickup", "hypercar", "jdm"}
    return {w for w in words if len(w) > 2}


def google_trends(geo: str) -> list[str]:
    try:
        r = http().get(f"https://trends.google.com/trending/rss?geo={geo}", timeout=20)
        r.raise_for_status()
        return [clean_text(e.title) for e in feedparser.parse(r.content).entries]
    except Exception as ex:
        log.info("Google Trends unavailable: %s", ex)
        return []


def trending_terms(cfg) -> tuple[list[str], list[str]]:
    """Returns (trend terms used to boost matching stories, extra Google News queries)."""
    vocab = car_vocab(cfg)
    gt = google_trends(cfg.get("trends", {}).get("google_trends_geo", "AE"))
    car_trends = [x for x in gt if any(v in x.lower() for v in vocab)]
    if car_trends:
        log.info("Car-related UAE trends: %s", car_trends)
    return car_trends, [f'"{x}" when:2d' for x in car_trends[:3]]

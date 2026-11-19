"""Collect stories from RSS feeds + Google News, group duplicates across outlets, and rank them."""
from __future__ import annotations

import random
import re
from calendar import timegm
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser

from .util import clean_text, domain_of, http, jaccard, log, now_utc, tokens


@dataclass
class Story:
    title: str
    url: str
    source_name: str
    published: datetime
    summary: str = ""
    content: str = ""                  # full text if the feed includes it
    image_urls: list = field(default_factory=list)
    origin: str = "feed"               # feed | gnews
    uae: bool = False
    culture: bool = False
    wild: bool = False                 # found by an "Only in the UAE" search
    weight: float = 1.0
    fp: set = field(default_factory=set)

    def __post_init__(self):
        self.fp = tokens(self.title)


@dataclass
class Cluster:
    stories: list
    score: float = 0.0
    trend_hit: str = ""

    @property
    def best(self) -> Story:
        # Prefer direct-feed items (real URL), with images and the most text.
        return sorted(self.stories, key=lambda s: (s.origin == "feed", bool(s.image_urls),
                                                   len(s.content or s.summary)), reverse=True)[0]

    def is_wild(self, cfg) -> bool:
        text = " ".join(s.title.lower() for s in self.stories)
        kw = cfg.get("boost_keywords", {})
        uae = any(s.uae for s in self.stories) or any(k in text for k in kw.get("uae", []))
        return any(s.wild for s in self.stories) or (uae and any(k in text for k in kw.get("wild", [])))

    @property
    def outlets(self) -> list[str]:
        seen = []
        for s in self.stories:
            if s.source_name not in seen:
                seen.append(s.source_name)
        return seen


def _parse_date(entry) -> datetime:
    for k in ("published_parsed", "updated_parsed"):
        t = entry.get(k)
        if t:
            return datetime.fromtimestamp(timegm(t), tz=timezone.utc)
    return now_utc()


def _entry_images(entry) -> list[str]:
    urls = []
    for m in entry.get("media_content", []) or []:
        if m.get("url") and (m.get("medium") in (None, "image") or re.search(r"\.(jpe?g|png|webp)", m["url"], re.I)):
            urls.append(m["url"])
    for m in entry.get("media_thumbnail", []) or []:
        if m.get("url"):
            urls.append(m["url"])
    for enc in entry.get("enclosures", []) or []:
        if str(enc.get("type", "")).startswith("image") and enc.get("href"):
            urls.append(enc["href"])
    html = ""
    if entry.get("content"):
        html = entry["content"][0].get("value", "")
    html += entry.get("summary", "")
    urls += re.findall(r'<img[^>]+src="([^"]+)"', html)
    out = []
    for u in urls:
        if u not in out and not u.startswith("data:"):
            out.append(u)
    return out


def fetch_feed(url: str, timeout: int = 20):
    r = http().get(url, timeout=timeout)
    r.raise_for_status()
    return feedparser.parse(r.content)


def collect_feeds(cfg) -> tuple[list[Story], dict]:
    stories, health = [], {}
    for f in cfg.get("feeds", []):
        try:
            parsed = fetch_feed(f["url"])
            n = 0
            for e in parsed.entries[:40]:
                if not e.get("link") or not e.get("title"):
                    continue
                content = ""
                if e.get("content"):
                    content = clean_text(e["content"][0].get("value", ""))
                stories.append(Story(
                    title=clean_text(e["title"]), url=e["link"], source_name=f["name"],
                    published=_parse_date(e), summary=clean_text(e.get("summary", ""))[:1500],
                    content=content, image_urls=_entry_images(e), origin="feed",
                    uae=bool(f.get("uae")), culture=bool(f.get("culture")), weight=f.get("weight", 1.0)))
                n += 1
            health[f["name"]] = f"ok ({n} items)" if n else "EMPTY"
        except Exception as ex:  # a dead feed must never break the run
            health[f["name"]] = f"FAILED: {type(ex).__name__}: {str(ex)[:80]}"
            log.warning("Feed %s failed: %s", f["name"], ex)
    return stories, health


def google_news_url(query: str, ed: dict) -> str:
    return (f"https://news.google.com/rss/search?q={quote_plus(query)}"
            f"&hl={ed['hl']}&gl={ed['gl']}&ceid={ed['ceid']}")


def collect_google_news(cfg, extra_queries: list[str] | None = None) -> tuple[list[Story], dict]:
    g = cfg.get("google_news", {})
    ed = g.get("edition", {"hl": "en-AE", "gl": "AE", "ceid": "AE:en"})
    trusted = set(g.get("trusted_publishers", []))
    blocked = set(g.get("blocked_publishers", []))
    queries = [(q, False) for q in g.get("queries", [])]
    queries += [(q, True) for q in g.get("uae_wild_queries", [])]
    brands = list(cfg.get("brands", []))
    random.shuffle(brands)
    for b in brands[: g.get("brand_queries_per_run", 4)]:
        queries.append((g.get("brand_query", "{brand} when:2d").format(brand=b), False))
    queries += [(q, False) for q in (extra_queries or [])]

    stories, health, dropped = [], {}, 0
    for q, wild in queries:
        try:
            parsed = fetch_feed(google_news_url(q, ed))
            n = 0
            for e in parsed.entries[:15]:
                src = e.get("source") or {}
                pub_domain = domain_of(src.get("href", ""))
                if pub_domain in blocked or not any(pub_domain == t or pub_domain.endswith("." + t) for t in trusted):
                    dropped += 1
                    continue
                title = clean_text(e.get("title", ""))
                # Google appends " - Publisher" to titles
                pub_name = src.get("title") or pub_domain
                if title.endswith(" - " + pub_name):
                    title = title[: -len(" - " + pub_name)]
                stories.append(Story(
                    title=title, url=e.get("link", ""), source_name=pub_name,
                    published=_parse_date(e), summary="", origin="gnews", wild=wild,
                    uae=wild or any(k in (q + title).lower() for k in ("uae", "dubai", "abu dhabi", "rta"))))
                n += 1
            health[f"Google News: {q[:50]}"] = f"ok ({n} trusted items)"
        except Exception as ex:
            health[f"Google News: {q[:50]}"] = f"FAILED: {ex}"
    log.info("Google News: dropped %d items from untrusted/blocked publishers", dropped)
    return stories, health


def is_excluded(title: str, cfg) -> bool:
    """Whole-word match, so "toy" skips toy stories but never "Toyota"."""
    t = title.lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(k.lower()) + r"(?![a-z0-9])", t)
               for k in cfg.get("exclude_keywords", []))


def cluster_stories(stories: list[Story], threshold: float = 0.42) -> list[Cluster]:
    clusters: list[Cluster] = []
    for s in sorted(stories, key=lambda x: x.published, reverse=True):
        for c in clusters:
            if any(jaccard(s.fp, o.fp) >= threshold for o in c.stories):
                c.stories.append(s)
                break
        else:
            clusters.append(Cluster([s]))
    return clusters


def already_seen(cluster: Cluster, seen: list[dict], threshold: float = 0.42) -> bool:
    urls = {x["url"] for x in seen}
    for s in cluster.stories:
        if s.url in urls:
            return True
        for x in seen:
            if jaccard(s.fp, set(x["fp"])) >= threshold:
                return True
    return False


def score_cluster(c: Cluster, cfg, trend_terms: list[str]) -> float:
    b = c.best
    text = " ".join(s.title.lower() for s in c.stories)
    age_h = (now_utc() - max(s.published for s in c.stories)).total_seconds() / 3600
    kw = cfg.get("boost_keywords", {})
    score = 5.0 * max(s.weight for s in c.stories)
    score += 1.6 * (len(c.outlets) - 1)                   # corroborated by several outlets
    score += 2.5 * any(k in text for k in kw.get("uae", [])) + 1.5 * any(s.uae for s in c.stories)
    score += 2.0 * any(k in text for k in kw.get("events", []))
    score += min(3, sum(0.8 for k in kw.get("brands", []) if k in text))
    score += 0.6 * any(s.culture for s in c.stories)
    score += 1.5 * any(k in text for k in kw.get("wild", []))
    score += 0.8 * bool(b.image_urls)
    for term in trend_terms:
        tt = tokens(term)
        if tt and (len(tt & b.fp) >= min(2, len(tt))):
            score += 3.0
            c.trend_hit = term
            break
    score -= 0.12 * age_h
    return round(score, 2)


def ranked_candidates(cfg, state, trend_terms: list[str], extra_queries=None) -> tuple[list[Cluster], dict]:
    max_age = max(cfg["drafting"].get("max_story_age_hours", 36), 0)
    s1, h1 = collect_feeds(cfg)
    s2, h2 = collect_google_news(cfg, extra_queries)
    # crazy-UAE and culture stories aren't time-critical, so they may be up to a week old
    fresh = [s for s in s1 + s2
             if (now_utc() - s.published).total_seconds() < (168 if (s.wild or s.culture) else max_age) * 3600
             and not is_excluded(s.title, cfg)]
    clusters = [c for c in cluster_stories(fresh) if not already_seen(c, state.seen_items())]
    for c in clusters:
        c.score = score_cluster(c, cfg, trend_terms)
    clusters.sort(key=lambda c: c.score, reverse=True)
    log.info("Collected %d stories -> %d fresh, unseen story groups", len(s1) + len(s2), len(clusters))
    return clusters, {**h1, **h2}

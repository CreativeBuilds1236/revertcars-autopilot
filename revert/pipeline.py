"""The workflow: find stories -> write -> design -> send for approval -> publish on schedule."""
from __future__ import annotations

import html
import random
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import article, render, sources, storage, submissions, throwback, trends, writer
from .submissions import URL_RE
from .instagram import Instagram
from .state import MEDIA_DIR, State
from .telegram_bot import Telegram, wait_seconds
from .util import ROOT, env, log, now_utc, tz

WORK = ROOT / "work"   # downloaded source photos (temporary, never committed)


# ───────────────────────── preparing stories ─────────────────────────

def prepare_news(cluster: sources.Cluster, cfg) -> dict | None:
    min_chars = cfg["drafting"].get("min_source_chars", 500)
    for s in sorted(cluster.stories, key=lambda x: (x.origin == "feed", len(x.content)), reverse=True):
        url = s.url if s.origin == "feed" else article.resolve_google_news(s.url)
        if not url:
            continue
        text, imgs = s.content, list(s.image_urls)
        if len(text) < 1500:
            page = article.fetch_article(url)
            if len(page["text"]) > len(text):
                text = page["text"]
            imgs = page["images"] + [i for i in imgs if i not in page["images"]]
        if len(text) < min_chars:
            log.info("Too little source text (%d chars) for: %s", len(text), s.title)
            continue
        return {"kind": "news", "title": s.title, "url": url, "source_name": s.source_name,
                "text": text[:9000], "image_urls": imgs, "outlets": cluster.outlets,
                "trend_hit": cluster.trend_hit}
    return None


def make_draft(item: dict, cfg, state: State, client=None, note: str = "", photos: list | None = None,
               tg: Telegram | None = None, avoid_style: dict | None = None) -> dict | None:
    did = state.new_id()
    WORK.mkdir(exist_ok=True)
    d = cfg["drafting"]
    max_slides = d.get("max_carousel_slides", 5)
    if photos is None:
        if item.get("tg_file_ids") and tg:      # community submission being rewritten
            photos = [tg.download_file(fid, WORK / f"d{did}_tg{i}.jpg") for i, fid in enumerate(item["tg_file_ids"])]
        else:
            photos = article.download_images(item.get("image_urls", []), WORK, f"d{did}", max_n=max_slides,
                                             min_w=700 if item["kind"] == "throwback" else 800)
    carousel = len(photos) >= 2 and random.random() < d.get("carousel_probability", 0.55)
    if item["kind"] == "throwback" and len(photos) >= 2:
        carousel = carousel or random.random() < 0.5
    n_slides = max(1, min(len(photos) - 1, max_slides - 2 - int(d.get("outro_slide", True)))) if carousel else 0
    if item["kind"] == "community" and carousel:
        n_slides = 0          # community carousels are photo-led: cover + extra photos, no fact slides

    post = writer.write_post(item, cfg, n_slides=n_slides, note=note, client=client, images=photos)
    if post.get("skip"):
        log.info("Writer skipped '%s': %s", item["title"], post.get("skip_reason"))
        return None
    if item["kind"] == "throwback":
        post["category"] = "THROWBACK"
    elif item["kind"] == "community" and post.get("category") not in ("SPOTTED", "CULTURE"):
        post["category"] = "SPOTTED"
    if post.get("is_rumour"):
        post["category"] = "RUMOUR"
    if not post.get("stat") or item["kind"] == "community":
        post["stat"] = {"value": "", "label": ""}

    recent = list(state.data.get("recent_styles", []))[-3:] + ([avoid_style] if avoid_style else [])
    credit = f"Photo: {item['credit']}" if item["kind"] == "community" and item.get("credit") else (
        "Photo: community" if item["kind"] == "community" else "")
    community_carousel = item["kind"] == "community" and carousel
    prefix = f"d{did}_{int(time.time())}"
    out, style = render.render_post(post, photos, item["source_name"], cfg["page"]["handle"], MEDIA_DIR,
                                    prefix, carousel, d.get("outro_slide", True) and not community_carousel,
                                    recent=recent, kind=item["kind"], credit=credit, issue=int(did))
    if community_carousel:      # the other photos as clean filmic slides, then the outro
        out += extra_photo_slides(photos[1:], style, MEDIA_DIR, prefix)
        if d.get("outro_slide", True):
            p = MEDIA_DIR / f"{prefix}_{len(out) + 1}.jpg"
            render.outro_slide(cfg["page"]["handle"], render.THEMES[style["theme"]]).save(p, "JPEG", quality=90)
            out.append(p)
    state.data.setdefault("recent_styles", []).append(style)
    state.data["recent_styles"] = state.data["recent_styles"][-6:]
    caption = writer.final_caption(post, item, cfg)
    now = now_utc().isoformat()
    draft = {
        "id": did, "status": "pending", "created": now, "updated": now, "kind": item["kind"],
        "category": post["category"], "is_rumour": bool(post.get("is_rumour")),
        "headline": post["headline"], "caption": caption, "check": post.get("check"), "style": style,
        "images": [p.name for p in out], "url": item.get("url", ""), "source_name": item["source_name"],
        "outlets": item.get("outlets", []), "trend_hit": item.get("trend_hit", ""),
        "untrusted": item.get("untrusted", False),
        "item": {k: item[k] for k in ("kind", "title", "url", "source_name", "image_urls", "outlets", "angle",
                                      "trend_hit", "uae_wild", "credit", "tg_file_ids", "untrusted") if k in item}
                | {"text": item.get("text", "")[:9000]},
    }
    state.put(draft)
    return draft


def extra_photo_slides(photos, style, out_dir: Path, prefix: str) -> list[Path]:
    th = render.THEMES[style["theme"]]
    out = []
    for i, p in enumerate(photos[:4]):
        from PIL import Image
        im = render.filmify(render.smart_crop(Image.open(p).convert("RGB"), render.W, render.H), th, 1.0, i)
        im = render.paste_badge(im, 86, (48, 48))
        path = out_dir / f"{prefix}_{i + 2}.jpg"
        im.save(path, "JPEG", quality=90)
        out.append(path)
    return out


# ───────────────────────── drafting run ─────────────────────────

def draft_run(cfg, state: State, tg: Telegram | None, n_news: int | None = None,
              n_throwback: int | None = None, client=None) -> list[dict]:
    d = cfg["drafting"]
    n_news = d.get("news_per_run", 2) if n_news is None else n_news
    today = datetime.now(tz(cfg)).date().isoformat()
    if n_throwback is None:
        n_throwback = d.get("throwback_per_day", 1) if state.data.get("last_throwback_day") != today else 0

    made = []
    n_wild = d.get("uae_wild_per_run", 1) if n_news else 0
    if n_news or n_wild:
        terms, extra_q = trends.trending_terms(cfg)
        clusters, _health = sources.ranked_candidates(cfg, state, terms, extra_q)
        used = set()

        def run_lane(pool, want, wild):
            got, attempts = 0, 0
            for c in pool:
                if got >= want or attempts >= want * 4:
                    break
                if id(c) in used:
                    continue
                used.add(id(c))
                attempts += 1
                for s in c.stories:
                    state.mark_seen(s.url, s.fp)
                item = prepare_news(c, cfg)
                if not item:
                    continue
                item["uae_wild"] = wild
                try:
                    dr = make_draft(item, cfg, state, client)
                except Exception as ex:
                    log.exception("Draft failed for %s: %s", item["title"], ex)
                    continue
                if dr:
                    made.append(dr)
                    deliver(dr, tg, state)
                    got += 1

        run_lane([c for c in clusters if c.is_wild(cfg)], n_wild, True)     # "Only in the UAE" slot
        run_lane(clusters, n_news, False)
    for _ in range(n_throwback):
        item = throwback.build_throwback(cfg, state)
        if item:
            dr = make_draft(item, cfg, state, client)
            if dr:
                made.append(dr)
                state.data["last_throwback_day"] = today
                deliver(dr, tg, state)
    if tg and not made:
        tg.send_text("🤷 Drafting run found nothing worth posting this time (no fresh, well-sourced stories).")
    storage.sync(state, f"drafts {today}")
    shutil.rmtree(WORK, ignore_errors=True)
    return made


def deliver(draft: dict, tg: Telegram | None, state: State):
    if tg:
        tg.send_draft(draft, [MEDIA_DIR / n for n in draft["images"]])
        state.put(draft)


# ───────────────────────── scheduling ─────────────────────────

def next_free_slot(cfg, state: State, after: datetime | None = None) -> datetime:
    zone = tz(cfg)
    after = after or now_utc() + timedelta(minutes=2)
    taken = {d.get("scheduled_for") for d in state.by_status("approved", "posted")}
    slots = sorted(cfg["schedule"]["post_slots"])
    start = after.astimezone(zone).date()
    for day in range(30):
        date = start + timedelta(days=day)
        for s in slots:
            hh, mm = map(int, s.split(":"))
            dt = datetime(date.year, date.month, date.day, hh, mm, tzinfo=zone).astimezone(timezone.utc)
            if dt > after and dt.isoformat() not in taken:
                return dt
    return after


def fmt_local(cfg, iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(tz(cfg)).strftime("%a %d %b, %H:%M")


# ───────────────────────── publishing ─────────────────────────

def publish(draft: dict, cfg, state: State, tg: Telegram | None, ig: Instagram | None = None):
    ig = ig or Instagram(api_version=cfg["instagram"].get("api_version", "v26.0"))
    storage.sync(state, f"pre-publish #{draft['id']}")     # make sure the images are online
    urls = [storage.media_url(cfg, n) for n in draft["images"]]
    try:
        res = ig.publish(urls, draft["caption"])
    except Exception as ex:
        draft.update(status="failed", error=str(ex), updated=now_utc().isoformat())
        state.put(draft)
        log.error("Publish failed for #%s: %s", draft["id"], ex)
        if tg:
            tg.update_control(draft, f"❗ <b>Posting failed:</b> {html.escape(str(ex))[:300]}\n"
                                     f"Tap Approve or Post now to retry.", keep_buttons=True)
        return False
    draft.update(status="posted", permalink=res.get("permalink", ""), ig_id=res["id"],
                 posted_at=now_utc().isoformat(), updated=now_utc().isoformat())
    state.put(draft)
    if tg:
        link = f' — <a href="{html.escape(draft["permalink"])}">view post</a>' if draft.get("permalink") else ""
        tg.update_control(draft, f"✅ <b>Posted</b>{link}")
    return True


def publish_due(cfg, state: State, tg: Telegram | None, ig=None):
    now = now_utc()
    for d in sorted(state.by_status("approved"), key=lambda x: x["scheduled_for"]):
        if datetime.fromisoformat(d["scheduled_for"]) <= now:
            publish(d, cfg, state, tg, ig)


def expire_old(cfg, state: State, tg: Telegram | None):
    hours = cfg["schedule"].get("draft_expiry_hours", 48)
    for d in state.by_status("pending"):
        if now_utc() - datetime.fromisoformat(d["created"]) > timedelta(hours=hours):
            d.update(status="expired", updated=now_utc().isoformat())
            state.put(d)
            if tg:
                tg.update_control(d, "⌛ Expired (no answer in time)")


# ───────────────────────── handling your taps ─────────────────────────

HELP = ("<b>Revert Media bot</b>\n"
        "Each draft comes with buttons:\n"
        "✅ Approve — posts at the next free slot\n🚀 Post now — posts immediately\n"
        "🔄 Rewrite — same story, fresh caption &amp; design\n❌ Skip — bin it\n\n"
        "Reply to a draft's text message to replace its caption.\n\n"
        "<b>Send me stuff:</b>\n"
        "📸 Photo(s) + a line of text → a SPOTTED post\n"
        "🔗 Reddit link + the photo(s) → community post credited to the poster\n"
        "📰 Any article link → a news post (fact-checked as usual)\n"
        "Add <code>credit: @name</code> or <code>u/name</code> to set the photo credit.\n\n"
        "/status — what's queued\n/draft — make new drafts now\n/throwback — make a throwback draft now")


def handle_update(u: dict, cfg, state: State, tg: Telegram, client=None, ig=None):
    cq = u.get("callback_query")
    msg = u.get("message")
    chat = str(((cq or {}).get("message") or msg or {}).get("chat", {}).get("id", ""))
    if chat != tg.chat_id:
        log.warning("Ignoring update from unknown chat %s", chat)
        return
    if cq:
        action, _, did = (cq.get("data") or "").partition(":")
        d = state.drafts.get(did)
        if not d:
            tg.answer(cq["id"], "That draft no longer exists.")
            return
        if d["status"] in ("posted", "skipped", "expired", "replaced"):
            tg.answer(cq["id"], f"Already {d['status']}.")
            return
        if action == "a":
            slot = next_free_slot(cfg, state)
            d.update(status="approved", scheduled_for=slot.isoformat(), updated=now_utc().isoformat())
            state.put(d)
            tg.answer(cq["id"], "Approved")
            tg.update_control(d, f"✅ <b>Approved</b> — goes live {fmt_local(cfg, d['scheduled_for'])}"
                                 f" (UAE)\nTap 🚀 to post now instead, or ❌ to cancel.", keep_buttons=True)
        elif action == "n":
            tg.answer(cq["id"], "Posting now…")
            d.update(status="approved", scheduled_for=now_utc().isoformat())
            tg.update_control(d, "⏳ Posting…")
            publish(d, cfg, state, tg, ig)
        elif action == "s":
            d.update(status="skipped", updated=now_utc().isoformat())
            state.put(d)
            tg.answer(cq["id"], "Skipped")
            tg.update_control(d, "❌ Skipped")
        elif action == "r":
            tg.answer(cq["id"], "Rewriting…")
            tg.update_control(d, "🔄 Rewriting — new version coming up…")
            item = d["item"]
            note = ("Write a fresh version: a different opening line, a different joke, different headline. "
                    f"The previous caption was:\n{d['caption']}")
            new = make_draft(item, cfg, state, client, note=note, tg=tg, avoid_style=d.get("style"))
            d.update(status="replaced", updated=now_utc().isoformat())
            state.put(d)
            if new:
                deliver(new, tg, state)
            else:
                tg.send_text("The writer couldn't produce a safe new version of that one, so it's been dropped.")
        return

    if not msg:
        return
    text = (msg.get("text") or "").strip()
    reply_to = (msg.get("reply_to_message") or {}).get("message_id")
    if reply_to and text:
        d = state.find_by_message(reply_to)
        if d and d["status"] in ("pending", "approved", "failed"):
            old = d["caption"]
            # keep the source line + hashtags block if the new text doesn't include them
            tail = old[old.find("\n\n📰"):] if "\n\n📰" in old else old[old.find("\n\n📚"):] if "\n\n📚" in old else ""
            d["caption"] = (text if ("📰" in text or "📚" in text or "#" in text) else text + tail)[:2200]
            d["updated"] = now_utc().isoformat()
            state.put(d)
            status = "✏️ Caption updated"
            if d["status"] == "approved":
                status += f" — still scheduled for {fmt_local(cfg, d['scheduled_for'])}"
            tg.update_control(d, status, keep_buttons=True)
            return
    is_cmd = text.startswith("/")
    if not is_cmd and (msg.get("photo") or msg.get("document") or URL_RE.search(text) or msg.get("media_group_id")):
        if submissions.add_to_inbox(state, msg):
            tg.send_text("📥 Got it — I'll turn that into a draft in a moment.",
                         reply_to_message_id=msg["message_id"])
        return
    if not is_cmd and text:
        tg.send_text("Send me photo(s), a Reddit link or an article link and I'll make a draft. /help for more.")
        return
    cmd = text.split("@")[0].lower()
    if cmd in ("/start", "/help"):
        tg.send_text(HELP)
    elif cmd == "/status":
        q = sorted(state.by_status("approved"), key=lambda x: x["scheduled_for"])
        p = state.by_status("pending")
        lines = [f"<b>Queue</b> ({len(q)} approved, {len(p)} waiting for you)"]
        lines += [f"• {fmt_local(cfg, x['scheduled_for'])} — #{x['id']} {html.escape(x['headline'])}" for x in q]
        tg.send_text("\n".join(lines))
    elif cmd == "/draft":
        tg.send_text("On it — new drafts in a minute or two.")
        draft_run(cfg, state, tg, n_throwback=0, client=client)
    elif cmd == "/throwback":
        tg.send_text("Digging through the archives…")
        draft_run(cfg, state, tg, n_news=0, n_throwback=1, client=client)


def process_inbox(cfg, state: State, tg: Telegram, client=None, force=False):
    """Turn finished submissions (photo albums arrive as several messages) into drafts."""
    for key in submissions.ready_keys(state, force):
        entry = state.data["inbox"].pop(key)
        state.dirty = True
        try:
            item, problem = submissions.build_item(entry, cfg)
            if not item:
                tg.send_text(f"🤔 {html.escape(problem)}", reply_to_message_id=entry["msg_id"])
                continue
            photos = None
            if entry["photos"]:
                WORK.mkdir(exist_ok=True)
                photos = [tg.download_file(fid, WORK / f"sub{key}_{i}.jpg") for i, fid in enumerate(entry["photos"])]
            dr = make_draft(item, cfg, state, client, photos=photos, tg=tg)
            if dr:
                deliver(dr, tg, state)
            else:
                tg.send_text("The writer didn't think that one could be posted accurately, so I skipped it.",
                             reply_to_message_id=entry["msg_id"])
        except Exception as ex:
            log.exception("Submission failed: %s", ex)
            tg.send_text(f"❗ Couldn't draft that one: {html.escape(str(ex))[:200]}")
        state.save()


def poll_run(cfg, state: State, tg: Telegram, listen: int = 240, client=None, ig=None):
    """Listen for taps for `listen` seconds, then publish anything that's due."""
    import json
    before = json.dumps(state.data, sort_keys=True)
    expire_old(cfg, state, tg)
    publish_due(cfg, state, tg, ig)
    deadline = time.time() + listen
    while True:
        ups = tg.updates(state.data["tg_offset"], wait=wait_seconds(deadline))
        for u in ups:
            state.data["tg_offset"] = u["update_id"] + 1
            state.dirty = True
            try:
                handle_update(u, cfg, state, tg, client, ig)
            except Exception as ex:
                log.exception("Handling update failed: %s", ex)
                tg.send_text(f"❗ Something went wrong: {html.escape(str(ex))[:300]}")
            state.save()
        process_inbox(cfg, state, tg, client)
        publish_due(cfg, state, tg, ig)
        if time.time() >= deadline:
            break
    process_inbox(cfg, state, tg, client, force=True)
    state.prune()
    if json.dumps(state.data, sort_keys=True) != before:
        storage.sync(state, "poll")

"""The workflow: find stories -> write -> design -> send for approval -> publish on schedule."""
from __future__ import annotations

import html
import random
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import article, llm, render, sources, storage, submissions, throwback, trends, writer
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
               tg: Telegram | None = None, avoid_style: dict | None = None, rewrite: bool = False) -> dict | None:
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
    if item.get("fill_from_article") and len(photos) < max_slides:
        photos = list(photos) + article.download_images(item.get("image_urls", []), WORK, f"d{did}a",
                                                        max_n=max_slides - len(photos), min_w=800)
    carousel = len(photos) >= 2 and random.random() < d.get("carousel_probability", 0.55)
    if not photos:
        log.info("No usable photos for '%s' — skipped (posts always need a real photo)", item["title"])
        return None
    if item["kind"] == "throwback" and len(photos) >= 2:
        carousel = carousel or random.random() < 0.5
    # daily carousel quota: the first drafts of the day are carousels until the minimum is reached
    today = datetime.now(tz(cfg)).date().isoformat()
    cc = state.data.get("carousel_count") or {}
    if cc.get("day") != today:
        cc = {"day": today, "n": 0}
    if not carousel and item["kind"] != "community" and photos and cc["n"] < d.get("min_carousels_per_day", 0):
        carousel = True
    outro = int(d.get("outro_slide", True))
    min_slides = d.get("min_carousel_slides", 4)
    room = max_slides - 1 - outro                  # slots between the cover and the follow card
    # enough fact slides to reach the minimum, more when there are photos for them (one slot left for a stat)
    n_slides = min(room, max(min_slides - 1 - outro, min(len(photos) - 1, room - 1))) if carousel else 0
    if item["kind"] == "community" and carousel:
        n_slides = 0          # community carousels are photo-led: cover + extra photos, no fact slides

    post = writer.write_post(item, cfg, n_slides=n_slides, note=note, client=client, images=photos, rewrite=rewrite)
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
    credit = f"Photo: {item['credit']}" if item.get("credit") else (
        "Photo: community" if item["kind"] == "community" else "")
    community_carousel = item["kind"] == "community" and carousel
    prefix = f"d{did}_{int(time.time())}"
    out, style = render.render_post(post, photos, item["source_name"], cfg["page"]["handle"], MEDIA_DIR,
                                    prefix, carousel, d.get("outro_slide", True) and not community_carousel,
                                    recent=recent, kind=item["kind"], credit=credit, issue=int(did),
                                    min_total=0 if community_carousel else min_slides)
    if carousel and not community_carousel and len(out) < min_slides:
        # the writer found fewer facts than slots: top up with clean photo slides (before the follow card)
        pad = extra_photo_slides((photos[1:] + photos)[: min_slides - len(out)], style, MEDIA_DIR, prefix + "p")
        out = out[:-1] + pad + out[-1:] if outro else out + pad
    if community_carousel:      # the other photos as clean filmic slides, then the outro
        out += extra_photo_slides(photos[1:], style, MEDIA_DIR, prefix)
        if d.get("outro_slide", True):
            p = MEDIA_DIR / f"{prefix}_{len(out) + 1}.jpg"
            render.outro_slide(cfg["page"]["handle"], render.THEMES[style["theme"]]).save(p, "JPEG", quality=90)
            out.append(p)
    if carousel:
        cc["n"] += 1
        state.data["carousel_count"] = cc
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
              n_throwback: int | None = None, client=None, n_wild: int = 0, n_culture: int = 0) -> list[dict]:
    """Scheduled run (no counts given): the daily plan from config.yaml —
    `news_per_day` news drafts + one "rotation" draft (crazy UAE → throwback → car culture → ...).
    If the rotation lane has nothing good today, it falls back to one more news story.
    Manual runs / bot commands pass explicit counts instead."""
    d = cfg["drafting"]
    today = datetime.now(tz(cfg)).date().isoformat()
    fallback_news = False
    if n_news is None and n_throwback is None:
        if state.data.get("last_plan_day") == today:
            log.info("Today's drafts were already made — skipping (this run was a duplicate trigger).")
            return []
        state.data["last_plan_day"] = today
        n_news = d.get("news_per_day", 1)
        n_throwback = 0
        rotation = d.get("rotation", ["uae_wild", "throwback", "culture"])
        if rotation:
            idx = state.data.get("rotation_index", 0)
            lane = rotation[idx % len(rotation)]
            state.data["rotation_index"] = idx + 1
            log.info("Today's rotation slot: %s", lane)
            n_wild, n_throwback, n_culture = int(lane == "uae_wild"), int(lane == "throwback"), int(lane == "culture")
            fallback_news = True
    n_news = n_news or 0
    n_throwback = n_throwback or 0

    made = []
    if n_news or n_wild or n_culture:
        terms, extra_q = trends.trending_terms(cfg)
        clusters, _health = sources.ranked_candidates(cfg, state, terms, extra_q)
        used = set()

        def run_lane(pool, want, wild):
            got, attempts = 0, 0
            if want <= 0:
                return 0
            for c in pool:
                if got >= want or attempts >= max(want * 4, 8):
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
                except llm.QuotaExceeded:
                    quota_hit(tg, state)
                    return want                     # stop: no point trying more today
                except Exception as ex:
                    log.exception("Draft failed for %s: %s", item["title"], ex)
                    continue
                if dr:
                    made.append(dr)
                    deliver(dr, tg, state)
                    got += 1
            return got

        short = 0
        short += n_wild - run_lane([c for c in clusters if c.is_wild(cfg)], n_wild, True)     # "Only in the UAE"
        short += n_culture - run_lane([c for c in clusters if any(s.culture for s in c.stories)], n_culture, False)
        run_lane(clusters, n_news + (short if fallback_news else 0), False)
    tb_made = 0
    for _ in range(n_throwback):
        item = throwback.build_throwback(cfg, state)
        if item:
            try:
                dr = make_draft(item, cfg, state, client)
            except llm.QuotaExceeded:
                quota_hit(tg, state)
                break
            if dr:
                made.append(dr)
                tb_made += 1
                state.data["last_throwback_day"] = today
                deliver(dr, tg, state)
    if fallback_news and tb_made < n_throwback and not n_wild and not n_culture:
        terms, extra_q = trends.trending_terms(cfg)
        clusters, _ = sources.ranked_candidates(cfg, state, terms, extra_q)
        for c in clusters[:4]:
            for s in c.stories:
                state.mark_seen(s.url, s.fp)
            item = prepare_news(c, cfg)
            try:
                dr = make_draft(item, cfg, state, client) if item else None
            except llm.QuotaExceeded:
                quota_hit(tg, state)
                break
            if dr:
                made.append(dr)
                deliver(dr, tg, state)
                break
    if tg and not made and state.data.get("quota_notice") != now_utc().date().isoformat():
        tg.send_text("🤷 Drafting run found nothing worth posting this time (no fresh, well-sourced stories).")
    storage.sync(state, f"drafts {today}")
    shutil.rmtree(WORK, ignore_errors=True)
    return made


def quota_hit(tg: Telegram | None, state: State):
    """Tell the owner once per day that the free AI allowance has run out."""
    day = now_utc().date().isoformat()
    if state.data.get("quota_notice") == day:
        return
    state.data["quota_notice"] = day
    log.warning("Free AI daily limit reached")
    if tg:
        tg.send_text("⏸️ The free AI limit for today has run out, so no more drafts until it resets "
                     "(around 11am UAE). Nothing is broken — it'll carry on by itself.")


def draft_from_url(cfg, state: State, tg: Telegram | None, url: str, client=None) -> list[dict]:
    """Draft one specific article (used by 'Make drafts' with a link)."""
    item, problem = submissions.build_item({"text": url, "photos": [], "msg_id": None}, cfg)
    if not item:
        if tg:
            tg.send_text(f"🤔 {html.escape(problem)}")
        log.warning("Can't draft %s: %s", url, problem)
        return []
    from .util import tokens
    state.mark_seen(item["url"], tokens(item["title"]))
    try:
        dr = make_draft(item, cfg, state, client)
    except llm.QuotaExceeded:
        quota_hit(tg, state)
        dr = None
    if dr:
        deliver(dr, tg, state)
    elif tg and state.data.get("quota_notice") != now_utc().date().isoformat():
        tg.send_text("The writer didn't think that article could be posted accurately, so I skipped it.")
    storage.sync(state, "draft from link")
    shutil.rmtree(WORK, ignore_errors=True)
    return [dr] if dr else []


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

def manual_mode(cfg) -> bool:
    return cfg.get("instagram", {}).get("mode", "manual") != "auto"


def hand_over(draft: dict, cfg, state: State, tg: Telegram | None):
    """Manual posting: send the finished slides + a copy-ready caption, wait for "I posted it"."""
    draft.update(status="ready", handed_at=now_utc().isoformat(), updated=now_utc().isoformat())
    state.put(draft)
    if not tg:
        return True
    n = len(draft["images"])
    photos = f"the {n} photos below (in order)" if n > 1 else "the photo below"
    tg.send_text(f"🔔 <b>Time to post #{draft['id']}</b> — {html.escape(draft['headline'])}\n"
                 f"1. Save {photos}\n"
                 f"2. Long-press the caption message → Copy\n"
                 f"3. Post on Instagram {'as a carousel ' if n > 1 else ''}and paste the caption\n"
                 f"4. Tap <b>✅ I posted it</b>")
    tg.send_album([MEDIA_DIR / name for name in draft["images"]])
    tg.send_text(html.escape(draft["caption"]))         # plain message: long-press → Copy
    msg = tg.send_text(f"#{draft['id']} ready to post", reply_markup={"inline_keyboard": [
        [{"text": "✅ I posted it", "callback_data": f"p:{draft['id']}"},
         {"text": "❌ Skip", "callback_data": f"s:{draft['id']}"}],
        [{"text": "📱 Open Instagram", "url": "https://www.instagram.com/"}]]})
    draft["tg_ready_id"] = msg["message_id"]
    tg.update_control(draft, "📲 <b>Sent to you to post</b> — see the messages below.")
    return True


def publish(draft: dict, cfg, state: State, tg: Telegram | None, ig: Instagram | None = None):
    if manual_mode(cfg):
        return hand_over(draft, cfg, state, tg)
    ig = ig or Instagram.from_cfg(cfg)
    storage.sync(state, f"pre-publish #{draft['id']}")     # make sure the images are online
    urls = [storage.media_url(cfg, n) for n in draft["images"]]
    try:
        res = ig.publish(urls, draft["caption"])
    except Exception as ex:
        draft.update(status="failed", error=str(ex), updated=now_utc().isoformat())
        state.put(draft)
        log.error("Publish failed for #%s: %s", draft["id"], ex)
        if tg:
            # Don't lose the slot: hand the finished post over to be uploaded by hand instead.
            tg.send_text(f"❗ <b>Auto-posting #{draft['id']} failed:</b> {html.escape(str(ex))[:300]}\n"
                         "Sending it to you to post by hand instead.")
            try:
                hand_over(draft, cfg, state, tg)
            except Exception as ex2:
                log.error("Hand-over after failed publish also failed: %s", ex2)
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
        "/status — what's queued\n/draft — 1 news + 1 crazy-UAE draft now\n/throwback — a throwback draft now")


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
            when = fmt_local(cfg, d["scheduled_for"])
            what = (f"I'll send it to you ready to post at {when}" if manual_mode(cfg)
                    else f"goes live {when}")
            tg.update_control(d, f"✅ <b>Approved</b> — {what} (UAE)\nTap 🚀 to do it now instead, "
                                 f"or ❌ to cancel.", keep_buttons=True)
        elif action == "p":
            d.update(status="posted", posted_at=now_utc().isoformat(), updated=now_utc().isoformat())
            state.put(d)
            tg.answer(cq["id"], "Nice one!")
            tg.update_control(d, "✅ <b>Posted</b> (by you)")
            if d.get("tg_ready_id"):
                try:
                    tg.call("editMessageText", chat_id=tg.chat_id, message_id=d["tg_ready_id"],
                            text=f"#{d['id']} ✅ posted", reply_markup={"inline_keyboard": []})
                except Exception:
                    pass
        elif action == "n":
            tg.answer(cq["id"], "On it…")
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
            new = make_draft(item, cfg, state, client, note=note, tg=tg, avoid_style=d.get("style"),
                             rewrite=True)
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
            tg.send_text("📰 Reading that article — the draft will be here in a minute or two."
                         if URL_RE.search(text) and not (msg.get("photo") or msg.get("document"))
                         else "📥 Got it — I'll turn that into a draft in a moment.",
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
        r = state.by_status("ready")
        lines = [f"<b>Queue</b> ({len(q)} approved, {len(p)} drafts to review"
                 + (f", {len(r)} ready for you to post" if r else "") + ")"]
        lines += [f"• 📲 #{x['id']} {html.escape(x['headline'])} — waiting for you to post" for x in r]
        lines += [f"• {fmt_local(cfg, x['scheduled_for'])} — #{x['id']} {html.escape(x['headline'])}" for x in q]
        tg.send_text("\n".join(lines))
    elif cmd == "/draft":
        tg.send_text("On it — new drafts in a minute or two.")
        draft_run(cfg, state, tg, n_news=1, n_throwback=0, client=client, n_wild=1)
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
        try:
            ups = tg.updates(state.data["tg_offset"], wait=wait_seconds(deadline))
        except Exception as ex:          # Telegram hiccup (e.g. "Bad Gateway"): wait a moment and carry on
            log.warning("Telegram unavailable (%s) — retrying shortly", ex)
            time.sleep(min(15, max(0, deadline - time.time())))
            ups = []
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

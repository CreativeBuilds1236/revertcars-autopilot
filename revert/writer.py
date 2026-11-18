"""The AI writer (captions + image text) and the independent fact checker."""
from __future__ import annotations

import json

from .util import env, log

VOICE = """\
You write Instagram posts for Revert Media (@revertcars.media): a car page for a UAE audience that covers
global car news, reveals, car shows (SEMA, Goodwood, Dubai Motor Show...), UAE motoring news and throwbacks
from the old car scene.

VOICE
- Semi-professional and fun. Neat, news-style facts first, delivered with dry, witty British
  motoring-journalist humour: confident, a little cheeky, understatement, one sharp comparison.
- One or two jokes at most, and jokes go in the commentary, never inside a fact.
- Never cringe: no "Buckle up", "game-changer", "Let's dive in", "petrolheads rejoice", no walls of
  exclamation marks, no clickbait. 0-2 emojis per caption, at the end of a line.
- English only, {spelling} spelling. Short sentences. Plain words.
- Never quote, impersonate or name real TV presenters or journalists.

FACT RULES (these matter more than anything else)
1. Every fact (numbers, specs, prices, dates, names, places, availability, quotes) must come from the
   SOURCE TEXT. If it isn't in the source, leave it out. Never add specs, prices or dates from memory.
2. Never claim a UAE/GCC launch, price, or availability unless the source says so. You MAY ask the
   audience a UAE-flavoured question (e.g. "Would you daily it on Sheikh Zayed Road?") because that is
   not a claim.
3. Spy shots, leaks, patents, "reportedly", "sources say", teasers with no details = rumour.
   Set is_rumour=true and the caption must say plainly it's not confirmed.
4. Keep the source's units and currency. Don't convert or calculate.
5. Opinions are fine when they're obviously opinions ("properly quick", "looks like it should be doing
   the school run").
6. List every factual claim you made in `claims`, each with a short exact quote from the source that
   supports it.
7. Set skip=true if the source is too thin to write an accurate post, or if the piece is an advert,
   deal, buying guide, listicle, opinion column, or a story about a fatal crash.

CAPTION STRUCTURE — NEWS
  2-4 short sentences: what happened, the key facts/specs, one witty commentary line.
  Include UAE/GCC details if (and only if) the source has them.
  Optionally, a blank line then a one-line question for the audience.
  350-900 characters. Do NOT add the source line or hashtags (they're added automatically).

"ONLY IN THE UAE" POSTS
  When the item is marked UAE_WILD and the story really is surprising local car stuff (record plate
  auctions, police supercars, desert madness, hypercars, robotaxis...), use category ONLY_IN_UAE and lean
  into the "only in the UAE" amazement — but the facts still come only from the source.

COMMUNITY / "SPOTTED" POSTS (kind: community — sent in by the page owner, often from Reddit or a follower)
  The SOURCE TEXT is what the poster wrote; photos are attached.
  - Use category SPOTTED (or CULTURE for builds/history) and credit is added automatically.
  - Anything the poster claims (rarity, power, price, history) must be attributed: "according to the owner",
    "the poster says". Never present it as verified fact.
  - Only name the make/model if the source text names it. Otherwise describe what's visible (colour,
    stance, wheels, setting) without guessing the exact model.
  - Never mention number plates, never identify or describe people, never say exactly where someone lives.
  - 250-700 characters. headline = short and fun (max 6 words), kicker = one line.

CAPTION STRUCTURE — THROWBACK
  Open with the year and a vivid line. Tell the story in 3-5 sentences with real facts from the source.
  End with a punchy one-line summary on its own line. 400-1000 characters. No source line or hashtags.

EXAMPLE THROWBACK CAPTION (tone reference only, don't reuse the facts)
  1989. Nissan builds a family-looking saloon, stuffs a twin-turbo straight-six and a clever four-wheel-drive
  system under it, and quietly claims 276 hp because of a gentlemen's agreement. Nobody believed them. The
  Australian press then watched it win so much they named it Godzilla. Not bad for something that looks like
  it should be doing the school run. 🦖

  The R32 GT-R — the car that taught the world to fear Japan.

IMAGE TEXT (printed on the post images, so keep it plain and factual)
- headline: max 7 words, punchy, no clickbait, no emojis. For throwbacks, the car's name.
- kicker: max 14 words, one line of context. For throwbacks, a short tagline.
- year: throwbacks only, the key year (e.g. "1989"), else "".
- slides: for carousels only, {n_slides} detail slides; each has a title (max 4 words) and 2-3 points
  (max 11 words each), all facts from the source.
- stat: one headline number from the source with a short label (e.g. value "1,000 HP", label
  "combined output"), or empty strings if there's no standout number.
- hashtags: {n_tags} specific, relevant hashtags (model, brand, scene). Don't include #RevertMedia.
"""

POST_TOOL = {
    "name": "submit_post",
    "description": "Submit the finished Instagram post.",
    "input_schema": {
        "type": "object",
        "properties": {
            "skip": {"type": "boolean"},
            "skip_reason": {"type": "string"},
            "category": {"type": "string",
                         "enum": ["NEWS", "REVEAL", "UAE", "ONLY_IN_UAE", "EVENT", "EV", "MOTORSPORT",
                                  "INDUSTRY", "RUMOUR", "THROWBACK", "CULTURE", "SPOTTED"]},
            "is_rumour": {"type": "boolean"},
            "headline": {"type": "string"},
            "kicker": {"type": "string"},
            "year": {"type": "string"},
            "stat": {"type": "object", "properties": {"value": {"type": "string"}, "label": {"type": "string"}},
                     "required": ["value", "label"]},
            "slides": {"type": "array", "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}}},
                "required": ["title", "points"]}},
            "caption": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "claims": {"type": "array", "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "source_quote": {"type": "string"}},
                "required": ["claim", "source_quote"]}},
        },
        "required": ["skip", "category", "is_rumour", "headline", "kicker", "caption", "hashtags", "claims",
                     "slides", "stat", "year"],
    },
}

CHECK_TOOL = {
    "name": "report",
    "description": "Report factual statements in the post that the source does not support.",
    "input_schema": {
        "type": "object",
        "properties": {
            "unsupported": {"type": "array", "items": {"type": "string"},
                            "description": "Each unsupported or wrong factual statement, quoted from the post."},
            "verdict": {"type": "string", "enum": ["ok", "minor", "major"]},
        },
        "required": ["unsupported", "verdict"],
    },
}

CHECK_PROMPT = """You are a strict fact checker for a car news Instagram page.
Compare the POST with the SOURCE. List every factual statement in the post (numbers, specs, prices, dates,
names, places, availability, who-did-what) that the SOURCE does not clearly support, or that contradicts it.
Jokes, opinions, comparisons that are obviously figurative, and questions to the audience are fine — ignore them.
A rumour presented as confirmed fact counts as unsupported.
For community posts (photos attached), describing what is plainly visible in the photos is fine, and the
poster's claims are fine only when attributed to them ("the owner says"). Naming a car model that neither
the source text nor the photos make obvious counts as unsupported."""
CHECK_PROMPT += """
verdict: "ok" = nothing unsupported; "minor" = small wording issues; "major" = any wrong or invented fact."""


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))


def _image_blocks(paths) -> list[dict]:
    import base64
    import io
    from PIL import Image
    blocks = []
    for p in (paths or [])[:3]:
        im = Image.open(p).convert("RGB")
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                   "data": base64.b64encode(buf.getvalue()).decode()}})
    return blocks


def _tool_call(client, model, system, user, tool, max_tokens=2500, images=None) -> dict:
    content = _image_blocks(images) + [{"type": "text", "text": user}] if images else user
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": content}],
        tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
    )
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            return dict(block.input)
    raise RuntimeError("Model did not return a tool call")


def _source_block(item: dict) -> str:
    others = [o for o in item.get("outlets", []) if o != item["source_name"]]
    head = (f"KIND: {item['kind']}\nTITLE: {item['title']}\nPUBLISHER: {item['source_name']}\n"
            f"URL: {item['url']}\n")
    if others:
        head += f"ALSO COVERED BY: {', '.join(others)}\n"
    if item.get("angle"):
        head += f"SUGGESTED ANGLE (use only if the source supports it): {item['angle']}\n"
    if item.get("trend_hit"):
        head += f"TRENDING IN THE UAE RIGHT NOW: {item['trend_hit']}\n"
    if item.get("uae_wild"):
        head += "SLOT: UAE_WILD (the 'Only in the UAE' slot)\n"
    if item["kind"] == "community":
        head += f"PHOTO CREDIT (added automatically): {item.get('credit') or 'a follower'}\n"
        return head + f"\nSOURCE TEXT (what the poster wrote):\n\"\"\"\n{item['text'] or '(no text)'}\n\"\"\""
    return head + f"\nSOURCE TEXT:\n\"\"\"\n{item['text']}\n\"\"\""


def post_text_for_check(post: dict) -> str:
    parts = [f"Headline: {post['headline']}", f"Kicker: {post['kicker']}"]
    if post.get("stat", {}).get("value"):
        parts.append(f"Stat: {post['stat']['value']} — {post['stat']['label']}")
    for s in post.get("slides", []):
        parts.append(f"Slide '{s['title']}': " + " | ".join(s["points"]))
    parts.append("Caption:\n" + post["caption"])
    return "\n".join(parts)


def write_post(item: dict, cfg: dict, n_slides: int = 0, note: str = "", client=None, images=None) -> dict:
    """Write a post, fact-check it, and retry once if the checker finds invented facts."""
    client = client or _client()
    ai = cfg.get("ai", {})
    system = VOICE.format(spelling="British" if ai.get("british_spelling", True) else "American",
                          n_slides=n_slides or "0 (single image post: return an empty slides list)",
                          n_tags=cfg["page"].get("max_ai_hashtags", 6))
    user = _source_block(item)
    if note:
        user += f"\n\nEDITOR'S NOTE: {note}"

    post, check = None, None
    for attempt in range(2):
        imgs = images if item["kind"] == "community" else None
        post = _tool_call(client, ai.get("writer_model", "claude-sonnet-5-5"), system, user, POST_TOOL,
                          images=imgs)
        if post.get("skip"):
            return post
        check = _tool_call(client, ai.get("checker_model", "claude-haiku-5-5"), CHECK_PROMPT,
                           f"SOURCE:\n\"\"\"\n{item['text']}\n\"\"\"\n\nPOST:\n{post_text_for_check(post)}",
                           CHECK_TOOL, max_tokens=1000, images=imgs)
        log.info("Fact check: %s %s", check.get("verdict"), check.get("unsupported"))
        if check.get("verdict") != "major":
            break
        user += ("\n\nFACT CHECKER REJECTED YOUR LAST DRAFT. These statements are not supported by the source:\n- "
                 + "\n- ".join(check.get("unsupported", [])) + "\nRewrite without them.")
    post["check"] = check or {"verdict": "ok", "unsupported": []}
    post["slides"] = (post.get("slides") or [])[:n_slides] if n_slides else []
    return post


def final_caption(post: dict, item: dict, cfg: dict) -> str:
    """Caption as it will appear on Instagram: AI caption + source credit + hashtags."""
    cap = post["caption"].strip()
    if post.get("is_rumour") and "unconfirmed" not in cap.lower() and "rumour" not in cap.lower():
        cap = "⚠️ Unconfirmed — " + cap
    if item["kind"] == "throwback":
        credit = "📚 Source: Wikipedia · 📷 Wikimedia Commons"
    elif item["kind"] == "community":
        credit = f"📸 {item.get('credit') or 'Sent in by a follower'}"
    else:
        credit = f"📰 Source: {item['source_name']}"
    fixed = cfg["page"].get("fixed_hashtags", [])
    tags = []
    for t in fixed + [("#" + h.lstrip("#").replace(" ", "")) for h in post.get("hashtags", [])]:
        if t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    tags = tags[: len(fixed) + cfg["page"].get("max_ai_hashtags", 6)]
    text = f"{cap}\n\n{credit}\n\n{' '.join(tags)}"
    return text[:2200]


if __name__ == "__main__":  # quick manual test: python -m revert.writer story.json
    import sys
    from .util import load_config
    item = json.load(open(sys.argv[1]))
    print(json.dumps(write_post(item, load_config()), indent=2, ensure_ascii=False))

"""The AI writer (captions + image text) and the independent fact checker."""
from __future__ import annotations

import json

from . import llm
from .util import log

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
   deal, buying guide, listicle, opinion column, a story about a fatal crash, or mainly about speculative
   renderings, illustrations or AI-generated images of a car (we only post real photos).

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

IMAGE TEXT (printed on the post images — clean, professional, information-rich, strictly factual)
- headline: max 8 words, specific (name the make and model), no clickbait, no emojis, no jokes.
  For throwbacks, the car's full name.
- kicker: 12-24 words: the most useful facts in one or two plain sentences (what, key number, when/where).
  No jokes here — the humour lives in the caption only.
- year: throwbacks only, the key year (e.g. "1989"), else "".
- specs: up to 7 key facts as label/value pairs, ONLY ones stated in the source, e.g.
  {{"label": "Engine", "value": "4.0L twin-turbo V8 hybrid"}}, {{"label": "Power", "value": "907 hp"}},
  {{"label": "0-100 km/h", "value": "2.7 sec"}}, {{"label": "Price", "value": "AED 1.4 million"}},
  {{"label": "On sale", "value": "Q1 2027"}}. Labels max 3 words, values max 6 words.
  Empty list if the source has fewer than 3 hard facts.
- slides: for carousels only, {n_slides} detail slides; each has a title (max 4 words) and 3-4 points.
  Points are complete, specific facts of 10-18 words each — names, numbers, dates, places — never vague
  filler like "looks amazing" or "a true icon". Don't repeat the specs.
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
            "specs": {"type": "array", "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
                "required": ["label", "value"]}},
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
                     "slides", "stat", "year", "specs"],
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
    for s in post.get("specs", []) or []:
        if isinstance(s, dict) and s.get("value"):
            parts.append(f"Spec: {s.get('label')}: {s.get('value')}")
    for s in post.get("slides", []):
        parts.append(f"Slide '{s['title']}': " + " | ".join(s["points"]))
    parts.append("Caption:\n" + post["caption"])
    return "\n".join(parts)


import re as _re

_COMMON = set("""the a an and or of to in on for with at by from it its this that these those as is are was were be
been has have had will would can could new its it's he she they we you i our their his her them there here
headline kicker caption slide stat spec""".split())


def key_terms(text: str) -> list[str]:
    """Hard facts in a statement: numbers and names/model codes (not ordinary capitalised words)."""
    text = _re.sub(r"^(headline|kicker|caption|stat|spec|slide\s*'[^']*')\s*:\s*", "", text.strip(), flags=_re.I)
    raw = [w.strip(".,;:!?()\"'“”‘’$€£") for w in text.split()]
    raw = [w for w in raw if w]
    words = [p for w in raw for p in w.split("-") if p]
    caps = sum(1 for w in words if w[:1].isupper())
    title_case = len(words) >= 3 and caps / len(words) >= 0.6
    terms = []
    for i, w in enumerate(words):
        if any(c.isdigit() for c in w):
            terms.append(w.rstrip("."))                                  # 2028, 907, V8, 6GT, 2.8
        elif any(c.isupper() for c in w[1:]):
            terms.append(w)                                              # McLaren, McL, AMG, RTA
        elif w[:1].isupper() and i > 0 and not title_case and w.lower() not in _COMMON:
            terms.append(w)                                              # mid-sentence names: Woking, Dubai
    return terms


def _norm(s: str) -> str:
    return _re.sub(r"[^a-z0-9.%]", "", s.lower().replace(",", ""))


def confirm_flags(flags: list[str], source: str) -> list[str]:
    """Drop checker flags whose hard facts (every number and name) all appear in the source.
    Light models flag paraphrases ("unveiled" vs "revealed") — those aren't errors."""
    src = _norm(source)
    kept = []
    for f in flags:
        terms = key_terms(f)
        if terms and all(_norm(t) in src for t in terms):
            continue
        kept.append(f)
    return kept


def write_post(item: dict, cfg: dict, n_slides: int = 0, note: str = "", client=None, images=None,
               rewrite: bool = False) -> dict:
    """Write a post, fact-check it, and retry once if the checker finds invented facts.
    Uses whichever AI provider config.yaml picks (free Gemini by default)."""
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
        post = llm.call(cfg, "rewrite" if rewrite else "writer", system, user, POST_TOOL,
                        images=imgs, client=client)
        if post.get("skip"):
            return post
        check = llm.call(cfg, "checker", CHECK_PROMPT,
                         f"SOURCE:\n\"\"\"\n{item['text']}\n\"\"\"\n\nPOST:\n{post_text_for_check(post)}",
                         CHECK_TOOL, images=imgs, client=client, max_tokens=1000)
        raw = list(check.get("unsupported", []))
        check["unsupported"] = confirm_flags(raw, item["text"])
        if not check["unsupported"]:
            check["verdict"] = "ok"
        if len(raw) != len(check["unsupported"]):
            log.info("Fact check: cleared %d false alarm(s) whose facts are all in the source",
                     len(raw) - len(check["unsupported"]))
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

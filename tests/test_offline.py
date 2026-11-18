"""Offline end-to-end rehearsal: fake feeds, fake AI, fake Telegram, fake Instagram.

Run:  python -m tests.test_offline
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

TMP = Path(tempfile.mkdtemp(prefix="revert_test_"))
os.environ["REVERT_DATA_DIR"] = str(TMP / "data")
os.environ.pop("GITHUB_ACTIONS", None)

from PIL import Image  # noqa: E402

from revert import pipeline, util  # noqa: E402
from revert.state import State  # noqa: E402
from revert.telegram_bot import Telegram  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
NOW = util.now_utc()


def rss(items):
    out = ['<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>']
    for t, link, img, hours in items:
        out.append(f"<item><title>{t}</title><link>{link}</link>"
                   f"<pubDate>{format_datetime(NOW - timedelta(hours=hours))}</pubDate>"
                   f"<description>Short teaser.</description>"
                   f'<media:content url="{img}" medium="image"/></item>')
    out.append("</channel></rss>")
    return "".join(out).encode()


ARTICLE = """<html><head><meta property="og:image" content="https://img.test/patrol1.jpg"></head><body><article>
<p>Nissan has revealed the new Patrol Nismo, the most powerful Patrol ever made, at an event in Abu Dhabi.</p>
<p>The Patrol Nismo uses a 3.5-litre twin-turbo V6 producing 495 hp and 700 Nm of torque, up from the standard
car's 425 hp. Nissan says it will go on sale in the GCC first, with UAE deliveries starting later this year.</p>
<p>Nismo has fitted a sports exhaust, retuned suspension with Bilstein dampers and 22-inch forged wheels.</p>
<p>The cabin gets red stitching, Nismo-branded seats and a 14.3-inch display. Pricing will be announced closer
to launch, Nissan said in a statement released on Monday.</p>
<img src="https://img.test/patrol2.jpg"><img src="https://img.test/patrol3.jpg"><img src="https://img.test/logo.png">
</article></body></html>"""


PLATE_ARTICLE = """<html><head><meta property="og:image" content="https://img.test/patrol3.jpg"></head><body><article>
<p>The number plate AA 7 has been sold for AED 15 million at an auction held by Dubai's Roads and Transport
Authority on Saturday evening, according to the RTA.</p><p>The auction featured 90 premium plates. Bidding for
AA 7 lasted around 20 minutes. Proceeds from the auction will go to a charity initiative, the RTA said.</p>
<p>Single and double-digit plates are among the most sought-after in the emirate and regularly sell for millions
of dirhams at public auctions held by the authority.</p><p>The RTA said the evening's auction raised a combined
total across all 90 plates, with several other two-digit combinations also attracting bids in the millions. Registration
for the next public auction will open on the RTA website in the coming weeks, the authority added.</p></article></body></html>"""


class FakeResp:
    def __init__(self, content=b"", status=200, js=None):
        self.content, self.status_code, self._js = content, status, js
        self.text = content.decode("utf-8", "ignore") if isinstance(content, bytes) else content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._js


def jpeg(crop):
    src = Image.open(FIX / "car.jpg")
    im = src.crop(crop).resize((1600, 1000))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


IMAGES = {
    "https://img.test/patrol1.jpg": jpeg((0, 0, 1270, 660)),
    "https://img.test/patrol2.jpg": jpeg((300, 100, 1270, 660)),
    "https://img.test/patrol3.jpg": jpeg((0, 150, 900, 660)),
}
WIKI_TEXT = ("The Nissan Skyline GT-R R32 was launched in 1989. It used the RB26DETT, a 2.6-litre twin-turbocharged "
             "straight-six engine, and the ATTESA E-TS all-wheel-drive system. Its output was officially quoted at "
             "276 hp (280 PS) due to a gentlemen's agreement among Japanese manufacturers. In Group A racing in "
             "Japan it won all 29 races it entered. The Australian motoring magazine Wheels nicknamed it Godzilla "
             "after its dominance in Australian touring car racing. " * 3)


class FakeSession:
    def get(self, url, params=None, headers=None, timeout=None):
        if "wikipedia.org" in url:
            return self.wiki(url)
        if (url.startswith("https://www.motor1.com/news/") or url.startswith("https://www.carscoops.com/")) \
                and "/feed" not in url:
            return FakeResp(ARTICLE.encode())
        if "motor1" in url:
            return FakeResp(rss([("Nissan Patrol Nismo revealed with 495 hp twin-turbo V6",
                                  "https://www.motor1.com/news/patrol-nismo", "https://img.test/patrol1.jpg", 3),
                                 ("Best tires for your SUV: our picks", "https://www.motor1.com/deals/x", "", 2)]))
        if "carscoops" in url:
            return FakeResp(rss([("Nissan Patrol Nismo revealed: 495 hp V6 for the desert king",
                                  "https://www.carscoops.com/patrol-nismo", "https://img.test/patrol2.jpg", 4),
                                 ("Toyota GR GT3 road car spotted testing at the Nurburgring",
                                  "https://www.carscoops.com/gr-gt3-spy", "https://img.test/patrol3.jpg", 6)]))
        if "news.google.com" in url and "plate" in url.lower():
            body = rss([("Dubai plate AA 7 sells for AED 15 million at RTA auction - The National",
                         "https://news.google.com/rss/articles/PLATE", "", 30)])
            body = body.replace(b"</link>", b'</link><source url="https://www.thenationalnews.com">The National</source>')
            return FakeResp(body)
        if url.startswith("https://www.thenationalnews.com/"):
            return FakeResp(PLATE_ARTICLE.encode())
        if "reddit.com" in url:
            return FakeResp(b"blocked", 403)
        if "rss" in url or "feed" in url:
            return FakeResp(rss([]))
        if url.startswith("https://www.motor1.com/news/") or url.startswith("https://www.carscoops.com/"):
            return FakeResp(ARTICLE.encode())
        if url in IMAGES:
            return FakeResp(IMAGES[url])
        return FakeResp(b"", 404)

    def wiki(self, url):
        if "onthisday" in url:
            return FakeResp(js={"events": []})
        if "w/api.php" in url:
            return FakeResp(js={"query": {"pages": {"1": {"title": "Nissan Skyline GT-R", "extract": WIKI_TEXT,
                                                         "fullurl": "https://en.wikipedia.org/wiki/Nissan_Skyline_GT-R"}}}})
        if "media-list" in url:
            return FakeResp(js={"items": [{"type": "image", "title": "File:R32.jpg",
                                           "srcset": [{"src": "https://img.test/patrol1.jpg"}]},
                                          {"type": "image", "title": "File:R32b.jpg",
                                           "srcset": [{"src": "https://img.test/patrol3.jpg"}]}]})
        return FakeResp(b"", 404)

    post = get
    request = lambda self, m, url, **kw: self.get(url)


util._session = FakeSession()


# ── fake Claude ──
NEWS_POST = {
    "skip": False, "category": "UAE", "is_rumour": False,
    "headline": "Nissan Patrol Nismo gets 495 hp", "kicker": "The desert king just got louder, lower and angrier.",
    "year": "", "stat": {"value": "495 HP", "label": "3.5-litre twin-turbo V6"},
    "slides": [{"title": "What's new", "points": ["Sports exhaust and Bilstein dampers", "22-inch forged wheels",
                                                  "Red stitching and Nismo seats"]},
               {"title": "UAE details", "points": ["On sale in the GCC first", "UAE deliveries later this year"]}],
    "caption": ("Nissan has turned the Patrol up to eleven. The new Patrol Nismo gets a 3.5-litre twin-turbo V6 "
                "with 495 hp and 700 Nm, plus a sports exhaust, Bilstein dampers and 22-inch forged wheels. "
                "It goes on sale in the GCC first, with UAE deliveries later this year. Which means the fast lane "
                "on the E11 is about to get a lot more crowded. 🏜️\n\nPatrol Nismo or Land Cruiser GR Sport?"),
    "hashtags": ["#NissanPatrol", "#PatrolNismo", "#Nismo", "#DubaiCars", "#4x4"],
    "claims": [{"claim": "495 hp", "source_quote": "producing 495 hp"}],
}
TB_POST = {
    "skip": False, "category": "THROWBACK", "is_rumour": False, "headline": "Skyline GT-R R32",
    "kicker": "The car that taught the world to fear Japan", "year": "1989",
    "stat": {"value": "29 / 29", "label": "Group A races won in Japan"},
    "slides": [{"title": "Under the bonnet", "points": ["2.6-litre twin-turbo RB26DETT straight-six",
                                                        "ATTESA E-TS all-wheel drive",
                                                        "Officially 276 hp, thanks to a gentlemen's agreement"]}],
    "caption": ("1989. Nissan builds a family-looking saloon, stuffs a twin-turbo straight-six and a clever "
                "four-wheel-drive system under it, and quietly claims 276 hp because of a gentlemen's agreement. "
                "It then won all 29 Group A races it entered in Japan, and Australia's Wheels magazine named it "
                "Godzilla. Not bad for something that looks like it should be doing the school run. 🦖\n\n"
                "The R32 GT-R — the car that taught the world to fear Japan."),
    "hashtags": ["#ThrowbackThursday", "#R32", "#GTR", "#JDM", "#Skyline"],
    "claims": [],
}
RUMOUR_SKIP = {**NEWS_POST, "skip": True, "skip_reason": "test skip"}


class FakeClaude:
    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, model, max_tokens, system, messages, tools, tool_choice):
        user = messages[0]["content"]
        n_images = 0
        if isinstance(user, list):
            n_images = sum(1 for b in user if b["type"] == "image")
            user = " ".join(b.get("text", "") for b in user)
        self.calls.append((model, tool_choice["name"], n_images))
        if tool_choice["name"] == "report":
            out = {"unsupported": [], "verdict": "ok"}
        elif "KIND: community" in user:
            out = {**NEWS_POST, "category": "SPOTTED", "headline": "Spotted at JBR",
                   "kicker": "Matte olive, widebody, zero chill.", "slides": [],
                   "caption": "Someone in JBR has decided subtle is overrated. Matte olive paint, a widebody kit "
                              "and wheels you could lose a cat in. The owner says it's the only one in the "
                              "country. 👀", "hashtags": ["#SpottedInDubai", "#Widebody"]}
        elif "SLOT: UAE_WILD" in user:
            out = {**NEWS_POST, "category": "ONLY_IN_UAE", "headline": "Plate AA 7 sells for AED 15 million",
                   "kicker": "Supercar money. For two characters.", "slides": [],
                   "stat": {"value": "AED 15M", "label": "winning bid"},
                   "caption": "Only in the UAE. Plate AA 7 has sold for AED 15 million at an RTA auction.",
                   "hashtags": ["#OnlyInDubai", "#NumberPlate"]}
        elif "KIND: throwback" in user:
            out = dict(TB_POST)
        elif "GR GT3" in user:
            out = {**NEWS_POST, "is_rumour": True, "headline": "Toyota GR GT3 road car spotted testing",
                   "kicker": "Camouflaged prototype caught at the Nurburgring.", "category": "RUMOUR"}
        else:
            out = json.loads(json.dumps(NEWS_POST))
            if "EDITOR'S NOTE" in user:
                out["headline"] = "Patrol Nismo: 495 hp desert weapon"
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=out)])


# ── fake Telegram ──
class FakeTG(Telegram):
    def __init__(self):
        super().__init__(token="TEST", chat_id="42")
        self.sent, self.queue, self.mid = [], [], 100

    def call(self, method, files=None, timeout=60, **params):
        self.sent.append((method, params))
        self.mid += 1
        if method == "sendMediaGroup":
            return [{"message_id": self.mid + i} for i in range(len(params["media"]))]
        return {"message_id": self.mid}

    def download_file(self, file_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.open(io.BytesIO(IMAGES[file_id])).save(dest, "JPEG")
        return dest

    def texts(self):
        return [p.get("text", "") for m, p in self.sent if m == "sendMessage"]

    def updates(self, offset, wait=0):
        q, self.queue = self.queue, []
        return q


class FakeIG:
    def __init__(self):
        self.published = []

    def publish(self, urls, caption):
        self.published.append((urls, caption))
        return {"id": f"ig{len(self.published)}", "permalink": f"https://instagram.com/p/x{len(self.published)}"}


def tap(tg, data, did, uid):
    tg.queue.append({"update_id": uid, "callback_query": {"id": f"cb{uid}", "data": f"{data}:{did}",
                                                           "message": {"chat": {"id": 42}}}})


def main():
    from revert import article
    article.resolve_google_news = lambda u: "https://www.thenationalnews.com/uae/plate-aa7" if "PLATE" in u else None
    cfg = util.load_config()
    cfg["drafting"]["carousel_probability"] = 1.0
    cfg["google_news"]["queries"] = []
    cfg["google_news"]["uae_wild_queries"] = ['Dubai number plate auction record when:7d']
    cfg["google_news"]["brand_queries_per_run"] = 0
    state, tg, ai, ig = State(), FakeTG(), FakeClaude(), FakeIG()

    made = pipeline.draft_run(cfg, state, tg, n_news=2, n_throwback=1, client=ai, n_wild=1)
    kinds = [(d["id"], d["kind"], d["category"], len(d["images"]), d["style"]["template"]) for d in made]
    print("Drafts:", kinds)
    assert len(made) == 4, kinds
    wild = made[0]
    assert wild["category"] == "ONLY_IN_UAE" and wild["source_name"] == "The National", wild   # UAE lane first
    made = made[1:]
    assert made[0]["outlets"] == ["Motor1", "Carscoops"], made[0]["outlets"]       # duplicate story grouped
    assert all("Best tires" not in d["headline"] for d in made)                     # deals filtered out
    assert made[1]["category"] == "RUMOUR"
    assert made[2]["kind"] == "throwback" and "📚 Source: Wikipedia" in made[2]["caption"]
    assert "📰 Source: Motor1" in made[0]["caption"] and "#RevertMedia" in made[0]["caption"]
    assert any(m == "sendMediaGroup" for m, _ in tg.sent)
    assert sum(1 for c in ai.calls if c[1] == "report") == 4                        # every draft fact-checked
    styles = [(d["style"]["template"], d["style"]["theme"]) for d in [wild] + made]
    assert all(styles[i] != styles[i + 1] for i in range(len(styles) - 1)), styles  # no repeats in a row

    # Running again must not re-draft the same stories
    again = pipeline.draft_run(cfg, state, tg, n_news=2, n_throwback=0, client=ai)
    assert again == [], again

    d1, d2, d3 = (d["id"] for d in made)
    tap(tg, "a", d1, 1)                       # approve -> next slot
    tap(tg, "n", d3, 2)                       # post now
    tap(tg, "r", d2, 3)                       # rewrite
    tg.queue.append({"update_id": 4, "message": {"chat": {"id": 999}, "text": "/status"}})   # stranger: ignored
    pipeline.poll_run(cfg, state, tg, listen=0, client=ai, ig=ig)

    s = state.drafts
    assert s[d1]["status"] == "approved", s[d1]["status"]
    print("Draft", d1, "scheduled for", pipeline.fmt_local(cfg, s[d1]["scheduled_for"]), "UAE")
    assert s[d3]["status"] == "posted" and len(ig.published) == 1
    assert len(ig.published[0][0]) == len(s[d3]["images"]) > 1                      # carousel published
    assert s[d2]["status"] == "replaced"
    new_id = str(max(int(k) for k in s))
    assert s[new_id]["headline"].startswith("Patrol Nismo:") or s[new_id]["status"] == "pending"
    assert state.data["tg_offset"] == 5

    # reply to the control message to replace a caption
    tg.queue.append({"update_id": 5, "message": {"chat": {"id": 42}, "text": "My own caption here.",
                                                 "reply_to_message": {"message_id": s[d1]["tg_control_id"]}}})
    pipeline.poll_run(cfg, state, tg, listen=0, client=ai, ig=ig)
    assert s[d1]["caption"].startswith("My own caption here.") and "📰 Source" in s[d1]["caption"]

    # time passes -> the approved post goes out
    s[d1]["scheduled_for"] = (util.now_utc() - timedelta(minutes=1)).isoformat()
    pipeline.publish_due(cfg, state, tg, ig)
    assert s[d1]["status"] == "posted" and len(ig.published) == 2

    # ── send-to-bot: album of 2 photos + Reddit link (Reddit itself blocks us -> uses the photos) ──
    n_before = len(state.drafts)
    link = "https://www.reddit.com/r/dubai/comments/abc123/liberty_walk_gtr_jbr/"
    tg.queue += [
        {"update_id": 10, "message": {"message_id": 501, "chat": {"id": 42}, "media_group_id": "G1",
                                      "photo": [{"file_id": "https://img.test/patrol1.jpg", "width": 1280, "height": 800}],
                                      "caption": f"Spotted this at JBR u/dxbspotter {link}"}},
        {"update_id": 11, "message": {"message_id": 502, "chat": {"id": 42}, "media_group_id": "G1",
                                      "photo": [{"file_id": "https://img.test/patrol2.jpg", "width": 1280, "height": 800}]}},
        # Reddit link with no photos -> polite explanation
        {"update_id": 12, "message": {"message_id": 503, "chat": {"id": 42}, "text": link}},
        # an article link -> normal news draft
        {"update_id": 13, "message": {"message_id": 504, "chat": {"id": 42},
                                      "text": "this is mad https://www.thenationalnews.com/uae/plate-aa7"}},
    ]
    pipeline.poll_run(cfg, state, tg, listen=0, client=ai, ig=ig)
    new = [d for k, d in state.drafts.items() if int(k) > n_before and k != "x"]
    comm = [d for d in new if d["kind"] == "community"]
    art = [d for d in new if d["kind"] == "news"]
    assert len(comm) == 1 and len(art) == 1, [(d["kind"], d["headline"]) for d in new]
    c = comm[0]
    assert c["category"] == "SPOTTED" and "📸 u/dxbspotter via r/dubai" in c["caption"], c["caption"]
    assert len(c["images"]) == 3, c["images"]                    # cover + 2nd photo + outro
    assert any(cl[2] > 0 for cl in ai.calls), "writer should see community photos"
    assert any("Reddit blocks bots" in t for t in tg.texts())
    assert any("📥 Got it" in t for t in tg.texts())
    assert not state.data.get("inbox")
    print("Community draft:", c["headline"], "|", c["style"], "| images:", len(c["images"]))

    # ── the daily scheduled plan: exactly 2 drafts, rotation lane falls back to news when empty ──
    s2, tg2 = State(Path(TMP / "plan.json")), FakeTG()
    s2.data["rotation_index"] = 2                      # today = "culture", and the fixtures have no culture stories
    plan = pipeline.draft_run(cfg, s2, tg2, client=ai)
    assert len(plan) == 2 and all(p["kind"] == "news" for p in plan), [(p["kind"], p["category"]) for p in plan]
    s3 = State(Path(TMP / "plan3.json"))
    s3.data["rotation_index"] = 1                      # today = "throwback"
    plan3 = pipeline.draft_run(cfg, s3, FakeTG(), client=ai)
    assert sorted(p["kind"] for p in plan3) == ["news", "throwback"], [p["kind"] for p in plan3]
    assert s3.data["rotation_index"] == 2
    print("Daily plan OK:", [(p["kind"], p["category"]) for p in plan], [(p["kind"], p["category"]) for p in plan3])

    # slots never double-book
    a = pipeline.next_free_slot(cfg, state)
    state.drafts["x"] = {"id": "x", "status": "approved", "scheduled_for": a.isoformat()}
    b = pipeline.next_free_slot(cfg, state)
    assert b > a
    print("Next free slots:", pipeline.fmt_local(cfg, a.isoformat()), "->", pipeline.fmt_local(cfg, b.isoformat()))

    out = Path(os.environ.get("REVERT_TEST_OUT", TMP / "out"))
    out.mkdir(parents=True, exist_ok=True)
    for d in made:
        for n in d["images"]:
            shutil.copy(TMP / "data" / "media" / n, out / n)
        (out / f"caption_{d['id']}.txt").write_text(d["caption"], encoding="utf-8")
    ctrl = [p for m, p in tg.sent if m == "sendMessage" and "Draft #1" in p.get("text", "")]
    (out / "telegram_message.txt").write_text(ctrl[0]["text"], encoding="utf-8")
    print("ALL CHECKS PASSED. Samples in", out)


if __name__ == "__main__":
    main()

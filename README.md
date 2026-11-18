# Revert Media — Instagram autopilot

Finds the latest car news, writes the caption, designs the post in the Revert Media style, and sends it
to you on **Telegram**. You tap ✅, and it goes live on **@revertcars.media** at the next posting slot.
It all runs for free on GitHub, so nothing needs to stay switched on at home.

```
 News feeds + Google News + Trends ──► pick the best fresh stories (no repeats, no deals/ads)
 "Only in the UAE" searches ───────► crazy local car stuff (every 3rd day)
 Wikipedia archives ───────────────► old-scene throwbacks (every 3rd day)
 Stuff YOU send the bot ───────────► Reddit posts, photos, article links → drafts
          │
          ▼
 Claude writes it (facts only from the source) ──► second AI fact-checks it
          │
          ▼
 Designer makes a single post or carousel (1080×1350, retro film look + your logo)
          │
          ▼
 Telegram: ✅ Approve  🚀 Post now  🔄 Rewrite  ❌ Skip   (or reply to change the caption)
          │
          ▼
 Instagram: posted at the next slot — 18:00 · 21:00 UAE
```

---

## One-time setup (about 30 minutes)

### 1. Telegram bot ✅ (done if you followed the chat)
`@BotFather` → `/newbot` → copy the **token**. Open your bot and press **Start**, then send it "hi".

### 2. Put the code on GitHub
1. Go to github.com → **New repository** → name it `revertcars-autopilot` → set it to **Public** → Create.
   *Public is needed so Instagram can download the images. Your keys stay hidden in "Secrets" and are never
   visible to anyone, even on a public repo.*
2. Upload all the files in this folder, including the hidden `.github` folder. Or just tell Claude the repo
   is created, and Claude can push the code for you.

### 3. Add your secret keys
Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add these one by one:

| Name | What it is |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from BotFather |
| `ANTHROPIC_API_KEY` | from console.anthropic.com → API keys (add ~$5 credit) |
| `IG_ACCESS_TOKEN` | from step 4 |
| `TELEGRAM_CHAT_ID` | from step 5 |
| `GH_PAT` | from step 6 (lets the Instagram token renew itself) |

### 4. Connect Instagram (the fiddly bit; Meta's screens may be labelled slightly differently)
1. Go to **developers.facebook.com** → log in with Facebook → **My Apps → Create App**.
2. Choose the use case **"Manage messaging & content on Instagram"** (or "Other" → app type **Business**).
3. In the app dashboard, open **Instagram → API setup with Instagram business login**.
4. Under **Generate access tokens**, click **Add account** and log in as **revertcars.media**.
   - If it asks you to add a tester: go to **App roles → Roles → Add people → Instagram Tester**,
     enter `revertcars.media`, then on Instagram open *Settings → Website permissions → Apps and websites →
     Tester invites* and accept.
5. Make sure the permissions include `instagram_business_basic` and `instagram_business_content_publish`.
6. Click **Generate token**, copy it, and save it as the `IG_ACCESS_TOKEN` secret.
   You don't need to submit the app for review, because you're only posting to your own account.

### 5. Run the setup check
Repo → **Actions** tab → enable workflows if asked → **Setup check → Run workflow**.
Open the run when it finishes. It tests every connection, and **it prints your Telegram chat ID**.
Save that number as the `TELEGRAM_CHAT_ID` secret and run the check again. The result also arrives in Telegram.

### 6. Let the Instagram token renew itself
Instagram tokens expire after 60 days. To have them renewed automatically:
github.com → your photo → **Settings → Developer settings → Personal access tokens → Fine-grained tokens →
Generate new token**. Under *Repository access*, choose **Only select repositories → revertcars-autopilot**.
Under *Permissions*, set **Secrets → Read and write**. Copy the token and save it as the `GH_PAT` secret.

### 7. Go
**Actions → Make drafts → Run workflow** (put 1 in *throwback* to also get a throwback).
Drafts land in Telegram within a few minutes. From then on, everything runs by itself.

---

## Day to day

- **Every day at about 10:15 UAE** you get **2 drafts**: the best news story, plus one from the rotation:
  crazy UAE stuff → throwback → car culture → (repeat). If the rotation lane has nothing good that day,
  you get a second news story instead. Change this in `config.yaml` (`news_per_day`, `rotation`).
- Tap **✅ Approve** to post at the next free slot (18:00 / 21:00), or **🚀 Post now** to post immediately.
- **🔄 Rewrite** gives a new caption and a new design for the same story. **❌ Skip** bins it.
- **Reply** to the draft's text message with your own words to replace the caption. The source line and
  hashtags are kept automatically.
- Drafts you ignore expire after 48 hours.
- Bot commands: `/status` (what's queued), `/draft` (1 news + 1 crazy-UAE draft now), `/throwback`, `/help`.

### Send stuff to the bot (Reddit, your own spots, links)
Reddit stopped allowing automatic reading: it switched off its RSS feeds on 13 Nov 2026 and is closing
its public API. So Reddit content comes in through you instead, which takes about two taps:

| You send | You get |
|---|---|
| Photo(s) + a line of text | a **SPOTTED** post |
| A Reddit link **plus the photo(s)** (save them from the Reddit app first) | a community post credited "u/name via r/sub" |
| Any article link | a normal news post, fact-checked like everything else (flagged if the site isn't on your trusted list) |

Write `credit: @someone` or `u/someone` in the message to set the photo credit.
Claims from posters ("only one in the UAE", "800 hp") are always attributed ("the owner says"), never stated as fact.

## "Only in the UAE" lane
Every third day the second draft is reserved for crazy local car stories: record plate auctions, Dubai Police
supercars, Liwa/Moreeb dune climbs, drag and drift events, hypercars, robotaxis, Top Gear Middle East.
These come only from trusted sources (The National, WAM, RTA, Dubai/Abu Dhabi Police, Emirates Auction,
Top Gear ME, DriveArabia, YallaMotor...) and get the **ONLY IN THE UAE** tag. Searches are in `config.yaml`
under `uae_wild_queries`.

## Looks
There are 8 cover layouts (fade, colour-strip, split poster, retro magazine, logo-style sticker burst,
TV lower-third, VHS tape, polaroid) and 7 colour themes, plus several carousel slide styles. Each post's look
is picked so it doesn't repeat the last few. The Telegram draft shows which look was used, and **🔄 Rewrite**
always gives a different one.

Taps are picked up every 15 minutes, because GitHub checks on a timer. During busy periods GitHub
sometimes runs a little late, so a post can go out 5–20 minutes after its slot.

## How it avoids misinformation
- **Sources:** direct feeds from established outlets. Google News results are only accepted from a
  trusted-publisher list, and Gulf News / wheels.ae are blocked. Stories covered by several outlets rank higher.
- **The writer** may only use facts that are in the source article, and must list a supporting quote for each one.
- **A second AI checks** every draft against the source. If it finds invented facts, the draft is rewritten.
  Anything still doubtful is shown to you as **🔎 Double-check** in Telegram.
- **Rumours and spy shots** get an **UNCONFIRMED** tag on the image and in the caption.
- Thin stories (not enough text to check) and deals, ads, buying guides and fatal-crash stories are skipped.
- Community posts never mention number plates or describe people. Do check sent-in photos yourself for
  visible plates and faces before approving, because UAE privacy rules on posting photos of people are strict.
- Nothing posts without your tap.

## Changing things
Edit `config.yaml` on GitHub (pencil icon) to change:
posting times, drafts per run, how often carousels appear, hashtags, feeds, Google News searches, trusted
publishers, boosted keywords and brands. Throwback topics are in `throwbacks.yaml`.

## Costs
GitHub: free (public repo). Telegram: free. Instagram API: free.
Claude: about **10–20 cents a month** at 2 drafts a day. Haiku writes and checks everyday drafts (~0.2 cents each),
and the stronger Sonnet model (~2 cents) is only used when you tap 🔄 Rewrite. This is billed separately from any
Claude subscription. Set a monthly spend limit in the Claude Console so it can never surprise you.
For Sonnet on every draft, set `writer_model: "claude-sonnet-5-5"` in `config.yaml` (about $1.50–3 a month).

## Where things live
- `revert/`: the code (sources, writer, designer, Telegram, Instagram, scheduler)
- `data` branch: drafts, images and state, managed automatically. It's squashed to one commit each
  time so the repo never grows. Don't edit it.
- `tests/test_offline.py`: a full offline rehearsal with fake feeds, AI, Telegram and Instagram
  (`python -m tests.test_offline`).

## Troubleshooting
- **No drafts arriving?** Run *Setup check*. It shows which feeds and keys work.
- **"Posting failed" in Telegram?** Usually the Instagram token. Re-do step 4 and update `IG_ACCESS_TOKEN`.
  Tap Approve on the draft again to retry.
- **GitHub email saying scheduled workflows were disabled** (happens after 60 days with no activity):
  Actions tab → click *Enable*.

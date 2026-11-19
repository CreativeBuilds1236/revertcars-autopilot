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
 AI writes it (free Gemini; facts only from the source) ──► second AI fact-checks it
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
| `GEMINI_API_KEY` | **free**: aistudio.google.com → sign in with Google → **Get API key** → Create API key (no card needed) |
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

### 7. Make it run on time (cron-job.org, free)
GitHub's own timer is unreliable. On a new repo it can run hours late, which would leave your ✅ taps waiting.
So a free timer service, cron-job.org, nudges GitHub at the right moments instead.

**a) A token that can only start this repo's jobs.** github.com → your photo → Settings → Developer settings →
Personal access tokens → Fine-grained tokens → Generate new token. Name: `cron-job`. Repository access:
**Only select repositories → revertcars-autopilot**. Permissions → **Actions: Read and write** (nothing else).
Copy it.

**b) cron-job.org.** Sign up free → Settings → set the time zone to **Asia/Dubai**. Then **Create cronjob** twice:

| | Job 1: "Revert – taps & posting" | Job 2: "Revert – daily drafts" |
|---|---|---|
| URL | `https://api.github.com/repos/CreativeBuilds1236/revertcars-autopilot/actions/workflows/poll.yml/dispatches` | `https://api.github.com/repos/CreativeBuilds1236/revertcars-autopilot/actions/workflows/draft.yml/dispatches` |
| Schedule | Every **10 minutes** (custom: hours 8–1 if you'd rather it sleeps at night) | Every day at **10:15** |

For **both** jobs, open the **Advanced** tab:
- Request method: **POST**
- Headers (add three):
  `Authorization` = `Bearer YOUR_CRON_JOB_TOKEN`
  `Accept` = `application/vnd.github+json`
  `X-GitHub-Api-Version` = `2022-11-28`
- Request body: `{"ref":"main"}`

Save, then use **Test run** on Job 1. A response of **204** means it worked, and you'll see a new run appear in
your repo's Actions tab. GitHub's own timer stays switched on as a backup, and the daily drafts can never run twice
in one day.

### 8. Go
**Actions → Make drafts → Run workflow**, leaving the boxes blank, to get today's 2 drafts now.
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

Taps are picked up within about 10 minutes (cron-job.org triggers a check every 10 minutes). During busy periods GitHub
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
AI: **free**. Captions are written and fact-checked by Google Gemini on its free tier, which is well above the
2 drafts a day this needs. On the free tier Google may use what's sent to improve its products (it's public
car news, so that's usually fine). If the free daily limit ever runs out, the bot tells you in Telegram and
carries on the next day. If Google renames a model, the system switches to the newest one by itself.

**Optional upgrade:** Claude writes sharper, wittier captions for about 10–20 cents a month. Add an
`ANTHROPIC_API_KEY` secret (console.anthropic.com, billed separately from any Claude subscription) and set
`provider: "anthropic"` under `ai:` in `config.yaml`.

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

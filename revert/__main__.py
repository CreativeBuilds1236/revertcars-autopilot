"""Command line entry point:  python -m revert <command>

  draft          find stories, write + design drafts, send them to Telegram
  poll           listen for your Telegram taps for a few minutes, publish anything due
  setup-check    test every connection and print what's missing
  refresh-token  renew the Instagram token (runs monthly)
"""
from __future__ import annotations

import argparse
import html
import os
import subprocess
import sys

from . import pipeline, sources, throwback
from .instagram import Instagram
from .state import State
from .telegram_bot import Telegram, discover_chat_id
from .util import env, http, load_config, log


def configured() -> bool:
    """Scheduled runs wait quietly (instead of failing) until setup is finished."""
    from . import llm
    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", llm.key_name(load_config())) if not env(k)]
    if missing:
        log.info("Not set up yet (missing secrets: %s) — skipping. Run 'Setup check' for help.", ", ".join(missing))
        return False
    return True


def cmd_draft(a, cfg):
    if configured():
        pipeline.draft_run(cfg, State(), Telegram(), n_news=a.news, n_throwback=a.throwback)


def cmd_poll(a, cfg):
    if configured():
        pipeline.poll_run(cfg, State(), Telegram(), listen=a.listen)


def cmd_refresh(a, cfg):
    if cfg.get("instagram", {}).get("mode", "manual") != "auto" or not env("IG_ACCESS_TOKEN"):
        log.info("Manual posting mode / no Instagram token — nothing to renew.")
        return
    tg = Telegram() if env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID") else None
    try:
        res = Instagram(api_version=cfg["instagram"]["api_version"]).refresh_token()
    except Exception as ex:
        if tg:
            tg.send_text(f"❗ <b>Instagram token refresh failed</b>\n{html.escape(str(ex))[:400]}\n\n"
                         "Generate a new token (README step 4) and update the IG_ACCESS_TOKEN secret.")
        raise
    days = int(res.get("expires_in", 0)) // 86400
    if env("GH_PAT"):
        subprocess.run(["gh", "secret", "set", "IG_ACCESS_TOKEN", "--repo", os.environ["GITHUB_REPOSITORY"]],
                       input=res["access_token"].encode(), check=True,
                       env={**os.environ, "GH_TOKEN": env("GH_PAT")})
        msg = f"🔑 Instagram token renewed — valid for another {days} days."
    else:
        msg = ("🔑 Instagram token refreshed, but GH_PAT isn't set so the new token couldn't be saved. "
               "Add GH_PAT (README step 6) so this happens automatically.")
    log.info(msg)
    if tg:
        tg.send_text(msg)


def cmd_setup_check(a, cfg):
    report, ok = [], True

    def line(good, text):
        nonlocal ok
        ok &= bool(good)
        report.append(("✅ " if good else "❌ ") + text)

    # Telegram
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not token:
        line(False, "TELEGRAM_BOT_TOKEN secret is missing")
    else:
        try:
            me = Telegram(token, "0").call("getMe")
            line(True, f"Telegram bot works: @{me['username']}")
            if not chat:
                found = discover_chat_id(token)
                if found:
                    line(False, "TELEGRAM_CHAT_ID missing. Add a secret TELEGRAM_CHAT_ID with this value: "
                                + ", ".join(f"{cid} (from {name})" for cid, name in found))
                else:
                    line(False, f"TELEGRAM_CHAT_ID missing. Open @{me['username']} in Telegram, press Start, "
                                "send 'hi', then run this check again.")
        except Exception as ex:
            line(False, f"Telegram token rejected: {ex}")

    # AI writer (free Gemini by default, or Claude)
    from . import llm
    kname = llm.key_name(cfg)
    if not env(kname):
        line(False, f"{kname} secret is missing" + (" (free key from aistudio.google.com)"
                                                    if kname == "GEMINI_API_KEY" else ""))
    else:
        probe = {"name": "report", "input_schema": {"type": "object", "properties": {
            "ok": {"type": "boolean"}}, "required": ["ok"]}}
        for role in ("writer", "checker"):
            try:
                llm.call(cfg, role, "You are a health check.", 'Reply {"ok": true}', probe, max_tokens=50)
                line(True, f"AI {role} works ({llm.provider(cfg)}: {llm.model_for(cfg, role)})")
            except llm.ModelNotFound:
                alt = llm.pick_available_gemini(role)
                line(False, f"Model {llm.model_for(cfg, role)} doesn't exist any more. In config.yaml set "
                            f"{role}_model to \"{alt}\" (it's being used automatically until then)")
            except Exception as ex:
                line(False, f"AI {role} problem: {str(ex)[:200]}")

    # Instagram
    manual = cfg.get("instagram", {}).get("mode", "manual") != "auto"
    if manual:
        report.append("📲 Manual posting mode: the bot sends you finished posts to upload yourself "
                      "(no Instagram connection needed). Switch to auto in config.yaml later.")
    elif not env("IG_ACCESS_TOKEN"):
        line(False, "IG_ACCESS_TOKEN secret is missing")
    else:
        try:
            ig = Instagram(api_version=cfg["instagram"]["api_version"])
            me = ig.me()
            line(True, f"Instagram connected: @{me.get('username')} ({me.get('account_type')}), user id {ig.uid}")
        except Exception as ex:
            line(False, f"Instagram token problem: {ex}")

    if not manual and not env("GH_PAT"):
        report.append("⚠️ GH_PAT not set — the Instagram token won't renew itself (README step 6)")

    # Image hosting (Instagram must be able to download the images)
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and not manual and not cfg["instagram"].get("media_base_url"):
        try:
            r = http().get(f"https://api.github.com/repos/{repo}",
                           headers={"Authorization": f"Bearer {env('GITHUB_TOKEN')}"}, timeout=20).json()
            line(not r.get("private", True), "Repository is public (needed so Instagram can fetch the images)"
                 if not r.get("private", True) else "Repository is PRIVATE — make it public (README step 2)")
        except Exception:
            pass

    # Sources
    _, health = sources.collect_feeds(cfg)
    report.append("\n<b>News feeds</b>")
    report += [("✅ " if v.startswith("ok") else "⚠️ ") + f"{k}: {v}" for k, v in health.items()]
    try:
        info = throwback.wiki_text("Nissan Skyline GT-R")
        report.append(("✅ " if info else "⚠️ ") + "Wikipedia (throwbacks)")
    except Exception as ex:
        report.append(f"⚠️ Wikipedia: {ex}")

    text = "\n".join(report)
    print(text.replace("<b>", "").replace("</b>", ""))
    if token and chat:
        try:
            Telegram(token, chat).send_text("<b>Setup check</b>\n" + html.escape(text).replace("&lt;b&gt;", "<b>")
                                            .replace("&lt;/b&gt;", "</b>"))
        except Exception:
            pass
    if not ok:
        sys.exit(1)


def main():
    p = argparse.ArgumentParser(prog="revert")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--news", type=int, default=None)
    d.add_argument("--throwback", type=int, default=None)
    pl = sub.add_parser("poll")
    pl.add_argument("--listen", type=int, default=240)
    sub.add_parser("setup-check")
    sub.add_parser("refresh-token")
    a = p.parse_args()
    cfg = load_config()
    {"draft": cmd_draft, "poll": cmd_poll, "setup-check": cmd_setup_check,
     "refresh-token": cmd_refresh}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()

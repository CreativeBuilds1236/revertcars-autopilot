"""Telegram approval bot: sends drafts with buttons and reads your taps/replies."""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

from .util import env, http, log

API = "https://api.telegram.org/bot{token}/{method}"

BUTTONS = lambda did: {"inline_keyboard": [
    [{"text": "✅ Approve", "callback_data": f"a:{did}"}, {"text": "🚀 Post now", "callback_data": f"n:{did}"}],
    [{"text": "🔄 Rewrite", "callback_data": f"r:{did}"}, {"text": "❌ Skip", "callback_data": f"s:{did}"}],
]}


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or env("TELEGRAM_BOT_TOKEN", required=True)
        self.chat_id = str(chat_id or env("TELEGRAM_CHAT_ID"))

    def call(self, method: str, files=None, timeout=60, **params):
        data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items() if v is not None}
        r = http().post(API.format(token=self.token, method=method), data=data, files=files, timeout=timeout)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
        return body["result"]

    # ── outgoing ──
    def send_text(self, text: str, **kw):
        return self.call("sendMessage", chat_id=self.chat_id, text=text[:4096], parse_mode="HTML",
                         disable_web_page_preview=True, **kw)

    def send_album(self, paths: list[Path]) -> list[int]:
        if len(paths) == 1:
            with open(paths[0], "rb") as f:
                m = self.call("sendPhoto", files={"photo": f}, chat_id=self.chat_id)
            return [m["message_id"]]
        files, media = {}, []
        for i, p in enumerate(paths[:10]):
            files[f"p{i}"] = open(p, "rb")
            media.append({"type": "photo", "media": f"attach://p{i}"})
        try:
            msgs = self.call("sendMediaGroup", files=files, chat_id=self.chat_id, media=media, timeout=120)
        finally:
            for f in files.values():
                f.close()
        return [m["message_id"] for m in msgs]

    def send_draft(self, draft: dict, image_paths: list[Path]):
        draft["tg_album_ids"] = self.send_album(image_paths)
        msg = self.send_text(control_text(draft), reply_markup=BUTTONS(draft["id"]))
        draft["tg_control_id"] = msg["message_id"]

    def update_control(self, draft: dict, status_line: str, keep_buttons: bool = False):
        try:
            self.call("editMessageText", chat_id=self.chat_id, message_id=draft["tg_control_id"],
                      text=(status_line + "\n\n" + control_text(draft))[:4096], parse_mode="HTML",
                      disable_web_page_preview=True,
                      reply_markup=BUTTONS(draft["id"]) if keep_buttons else {"inline_keyboard": []})
        except Exception as ex:
            log.info("Could not edit control message: %s", ex)

    def download_file(self, file_id: str, dest: Path) -> Path:
        info = self.call("getFile", file_id=file_id)
        r = http().get(f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}", timeout=60)
        r.raise_for_status()
        from io import BytesIO
        from PIL import Image
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.open(BytesIO(r.content)).convert("RGB").save(dest, "JPEG", quality=93)
        return dest

    def answer(self, callback_id: str, text: str):
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except Exception:
            pass  # callbacks older than ~15 min can't be answered; the message edit covers it

    # ── incoming ──
    def updates(self, offset: int, wait: int = 0) -> list[dict]:
        """Long-poll for new taps/messages (waits up to `wait` seconds)."""
        data = {"offset": offset, "timeout": wait,
                "allowed_updates": json.dumps(["message", "callback_query"])}
        r = http().post(API.format(token=self.token, method="getUpdates"), data=data, timeout=wait + 20)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {body.get('description')}")
        return body["result"]


def control_text(d: dict) -> str:
    fmt = f"carousel · {len(d['images'])} slides" if len(d["images"]) > 1 else "single post"
    lines = [f"<b>Draft #{d['id']} · {html.escape(d['category'])} · {fmt}</b>"]
    src = (f'<a href="{html.escape(d["url"])}">{html.escape(d["source_name"])}</a>' if d.get("url")
           else html.escape(d["source_name"]))
    others = [o for o in d.get("outlets", []) if o != d["source_name"]]
    lines.append(f"Source: {src}" + (f" (also: {html.escape(', '.join(others[:4]))})" if others else ""))
    if d.get("trend_hit"):
        lines.append(f"📈 Trending: {html.escape(d['trend_hit'])}")
    if d.get("is_rumour"):
        lines.append("⚠️ Marked as RUMOUR / unconfirmed")
    if d.get("untrusted"):
        lines.append("⚠️ This publisher isn't on your trusted list — double-check before posting")
    if d.get("kind") == "community":
        lines.append("📸 Community post — owner's claims are attributed, not verified")
    if d.get("style"):
        lines.append(f"🎨 Look: {d['style']['template']} · {d['style']['theme']}")
    chk = d.get("check") or {}
    if chk.get("unsupported"):
        lines.append("🔎 <b>Double-check:</b>\n• " + "\n• ".join(html.escape(x) for x in chk["unsupported"][:5]))
    else:
        lines.append("🔎 Fact check: all claims found in the source")
    lines.append("──────────")
    lines.append(html.escape(d["caption"]))
    lines.append("──────────")
    lines.append("<i>Reply to this message with new text to replace the caption.</i>")
    return "\n".join(lines)


def discover_chat_id(token: str) -> list[tuple[str, str]]:
    """Used by the setup check: who has messaged the bot?"""
    tg = Telegram(token=token, chat_id="0")
    found = []
    for u in tg.call("getUpdates", timeout=0):
        m = u.get("message") or (u.get("callback_query") or {}).get("message")
        if m:
            c = m["chat"]
            entry = (str(c["id"]), c.get("username") or c.get("first_name") or "")
            if entry not in found:
                found.append(entry)
    return found


def wait_seconds(deadline: float) -> int:
    return max(0, min(50, int(deadline - time.time())))

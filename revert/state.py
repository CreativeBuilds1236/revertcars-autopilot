"""Persistent state (drafts, approvals, what's been seen) stored as JSON in the data branch."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .util import DATA, now_utc

STATE_FILE = DATA / "state.json"
MEDIA_DIR = DATA / "media"

DEFAULT = {
    "next_id": 1,
    "tg_offset": 0,
    "drafts": {},           # id -> draft dict
    "seen": [],             # [{"t": iso, "url": str, "fp": [tokens]}]
    "throwback_used": {},   # wikipedia title -> iso date
    "token_checked": None,
    "last_throwback_day": None,
}


class State:
    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        self.data = json.loads(json.dumps(DEFAULT))
        if path.exists():
            self.data.update(json.loads(path.read_text(encoding="utf-8")))
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.dirty = False

    # ── drafts ──
    def new_id(self) -> str:
        i = self.data["next_id"]
        self.data["next_id"] = i + 1
        self.dirty = True
        return str(i)

    @property
    def drafts(self) -> dict:
        return self.data["drafts"]

    def put(self, draft: dict):
        self.drafts[draft["id"]] = draft
        self.dirty = True

    def by_status(self, *statuses) -> list[dict]:
        return [d for d in self.drafts.values() if d.get("status") in statuses]

    def find_by_message(self, message_id: int):
        for d in self.drafts.values():
            if d.get("tg_control_id") == message_id:
                return d
        return None

    # ── seen stories ──
    def mark_seen(self, url: str, fp: set):
        self.data["seen"].append({"t": now_utc().isoformat(), "url": url, "fp": sorted(fp)})
        self.dirty = True

    def seen_items(self):
        return self.data["seen"]

    def prune(self, days_seen: int = 21, days_drafts: int = 10):
        cutoff = now_utc() - timedelta(days=days_seen)
        before = len(self.data["seen"])
        self.data["seen"] = [s for s in self.data["seen"] if datetime.fromisoformat(s["t"]) > cutoff]
        dcut = now_utc() - timedelta(days=days_drafts)
        removed_media = []
        for did, d in list(self.drafts.items()):
            if d["status"] in ("posted", "skipped", "expired", "replaced", "failed"):
                if datetime.fromisoformat(d.get("updated", d["created"])) < dcut:
                    removed_media += d.get("images", [])
                    del self.drafts[did]
        for name in removed_media:
            p = MEDIA_DIR / name
            if p.exists():
                p.unlink()
        if removed_media or before != len(self.data["seen"]):
            self.dirty = True

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
        self.dirty = False

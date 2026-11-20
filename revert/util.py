"""Shared helpers: config loading, HTTP session, logging, text utilities."""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
DATA = Path(os.environ.get("REVERT_DATA_DIR", ROOT / "data"))

log = logging.getLogger("revert")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
# Wikimedia blocks look-alike browser user agents from servers; it wants an honest bot name with a contact link
BOT_UA = ("RevertMediaBot/1.1 (Instagram car news page; https://github.com/"
          + (os.environ.get("GITHUB_REPOSITORY") or "CreativeBuilds1236/revertcars-autopilot") + ")")


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    with open(ROOT / "throwbacks.yaml", encoding="utf-8") as f:
        cfg["throwbacks"] = yaml.safe_load(f).get("topics", [])
    return cfg


def env(name: str, required: bool = False) -> str:
    v = os.environ.get(name, "").strip()
    if required and not v:
        raise SystemExit(f"Missing secret/environment variable: {name}")
    return v


_session = None


def http() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"})
        _session = s
    return _session


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def tz(cfg) -> ZoneInfo:
    return ZoneInfo(cfg["page"].get("timezone", "Asia/Dubai"))


STOP = set("""a an the and or of to in on for with at by from new is are be its it this that as into over after
first more most than vs how why what who will can could just now gets get has have his her their our your up out
car cars auto news report reveals revealed unveiled debut debuts says said here""".split())


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9\-]+", (text or "").lower())
    return {w for w in words if w not in STOP and len(w) > 2}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def short_hash(s: str, n: int = 10) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


def clean_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"&nbsp;|&#160;", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    d = (m.group(1) if m else "").lower()
    return d[4:] if d.startswith("www.") else d

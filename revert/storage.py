"""Saves state + images to the repo's `data` branch so the next run (and Instagram) can see them."""
from __future__ import annotations

import os
import subprocess

from .util import DATA, ROOT, log


def media_url(cfg, filename: str) -> str:
    base = (cfg.get("instagram", {}).get("media_base_url") or "").rstrip("/")
    if base:
        return f"{base}/{filename}"
    repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO")
    return f"https://raw.githubusercontent.com/{repo}/data/media/{filename}"


def sync(state=None, message: str = "update"):
    """Save state.json and push the data branch (only inside GitHub Actions)."""
    if state is not None:
        state.save()
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    try:
        subprocess.run(["bash", str(ROOT / "scripts" / "data_branch.sh"), "push", message],
                       check=True, cwd=ROOT)
    except subprocess.CalledProcessError as ex:
        log.error("Pushing data branch failed: %s", ex)
        raise

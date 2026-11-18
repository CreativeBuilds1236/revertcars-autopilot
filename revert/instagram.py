"""Publish to Instagram via the official Instagram API (Instagram Login, works with Creator accounts)."""
from __future__ import annotations

import time

from .util import env, http, log

BASE = "https://graph.instagram.com"


class InstagramError(RuntimeError):
    pass


class Instagram:
    def __init__(self, token: str | None = None, api_version: str = "v26.0"):
        self.token = token or env("IG_ACCESS_TOKEN", required=True)
        self.v = api_version
        self._uid = env("IG_USER_ID") or None

    def _req(self, method, path, **params):
        url = f"{BASE}/{self.v}/{path}" if path else BASE
        params["access_token"] = self.token
        r = http().request(method, url, params=params if method == "GET" else None,
                           data=params if method == "POST" else None, timeout=60)
        body = r.json()
        if "error" in body:
            e = body["error"]
            raise InstagramError(f"{e.get('message')} (code {e.get('code')}/{e.get('error_subcode')})")
        return body

    def me(self) -> dict:
        b = self._req("GET", "me", fields="user_id,username,account_type")
        self._uid = self._uid or str(b.get("user_id") or b.get("id"))
        return b

    @property
    def uid(self) -> str:
        if not self._uid:
            self.me()
        return self._uid

    def _container(self, retries=4, **params) -> str:
        last = None
        for i in range(retries):
            try:
                return self._req("POST", f"{self.uid}/media", **params)["id"]
            except InstagramError as ex:
                last = ex
                # the image host can take a few seconds to serve a just-pushed file
                log.info("Container attempt %d failed: %s", i + 1, ex)
                time.sleep(20)
        raise last

    def _wait(self, cid: str, max_wait: int = 180):
        t0 = time.time()
        while time.time() - t0 < max_wait:
            st = self._req("GET", cid, fields="status_code,status").get("status_code")
            if st == "FINISHED":
                return
            if st in ("ERROR", "EXPIRED"):
                raise InstagramError(f"Container {cid} status {st}")
            time.sleep(4)
        raise InstagramError("Timed out waiting for Instagram to process the image")

    def publish(self, image_urls: list[str], caption: str) -> dict:
        if len(image_urls) == 1:
            cid = self._container(image_url=image_urls[0], caption=caption)
        else:
            children = []
            for u in image_urls[:10]:
                c = self._container(image_url=u, is_carousel_item="true")
                children.append(c)
            for c in children:
                self._wait(c)
            cid = self._container(media_type="CAROUSEL", children=",".join(children), caption=caption)
        self._wait(cid)
        media = self._req("POST", f"{self.uid}/media_publish", creation_id=cid)
        try:
            link = self._req("GET", media["id"], fields="permalink").get("permalink", "")
        except Exception:
            link = ""
        return {"id": media["id"], "permalink": link}

    def quota(self) -> dict:
        return self._req("GET", f"{self.uid}/content_publishing_limit", fields="quota_usage,config")

    def refresh_token(self) -> dict:
        r = http().get(f"{BASE}/refresh_access_token",
                       params={"grant_type": "ig_refresh_token", "access_token": self.token}, timeout=30)
        body = r.json()
        if "access_token" not in body:
            raise InstagramError(f"Token refresh failed: {body}")
        return body  # {"access_token", "token_type", "expires_in"}

"""Publish to Instagram via Meta's official Instagram API.

Two kinds of access token work:
  • "Unified login" (newer Meta apps): a never-expiring system-user token, used on graph.facebook.com.
    Needs the IG_USER_ID secret (the Instagram account's ID) — the token can't look it up by itself.
  • "Instagram login" (older apps): a 60-day Instagram user token, used on graph.instagram.com.
"""
from __future__ import annotations

import time

from .util import env, http, log

FACEBOOK_HOST = "graph.facebook.com"
INSTAGRAM_HOST = "graph.instagram.com"


class InstagramError(RuntimeError):
    pass


class Instagram:
    def __init__(self, token: str | None = None, api_version: str = "v26.0", host: str = FACEBOOK_HOST):
        self.token = token or env("IG_ACCESS_TOKEN", required=True)
        self.v = api_version
        self.host = host
        self.base = f"https://{host}"
        self._uid = env("IG_USER_ID") or None

    @classmethod
    def from_cfg(cls, cfg) -> "Instagram":
        ig = cfg.get("instagram", {})
        token = env("IG_ACCESS_TOKEN", required=True)
        host = ig.get("api_host", FACEBOOK_HOST)
        # The token's prefix says where it belongs: "IG..." = Instagram-login token, "EAA..." = Facebook/system user
        if token.startswith("IG"):
            host = INSTAGRAM_HOST
        elif token.startswith("EAA"):
            host = FACEBOOK_HOST
        return cls(token=token, api_version=ig.get("api_version", "v26.0"), host=host)

    @property
    def never_expires(self) -> bool:
        return self.host == FACEBOOK_HOST

    def _req(self, method, path, **params):
        url = f"{self.base}/{self.v}/{path}" if path else self.base
        params["access_token"] = self.token
        r = http().request(method, url, params=params if method == "GET" else None,
                           data=params if method == "POST" else None, timeout=60)
        body = r.json()
        if "error" in body:
            e = body["error"]
            raise InstagramError(f"{e.get('message')} (code {e.get('code')}/{e.get('error_subcode')})")
        return body

    def me(self) -> dict:
        if self.host == INSTAGRAM_HOST:
            b = self._req("GET", "me", fields="user_id,username,account_type")
            self._uid = self._uid or str(b.get("user_id") or b.get("id"))
            return b
        if not self._uid:
            # User tokens can find the account through a linked Page; system-user tokens can't.
            try:
                pages = self._req("GET", "me/accounts", fields="instagram_business_account{id,username}")
                for p in pages.get("data", []):
                    acct = p.get("instagram_business_account")
                    if acct:
                        self._uid = str(acct["id"])
                        break
            except InstagramError:
                pass
        if not self._uid:
            raise InstagramError("Add the IG_USER_ID secret (your Instagram account's ID — shown in Meta Business "
                                 "Settings → Accounts → Instagram accounts, or next to the account in the app's "
                                 "API setup page)")
        b = self._req("GET", self._uid, fields="id,username,name")
        b.setdefault("account_type", "professional")
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
        if self.never_expires:
            return {"never_expires": True}
        r = http().get(f"{self.base}/refresh_access_token",
                       params={"grant_type": "ig_refresh_token", "access_token": self.token}, timeout=30)
        body = r.json()
        if "access_token" not in body:
            raise InstagramError(f"Token refresh failed: {body}")
        return body  # {"access_token", "token_type", "expires_in"}

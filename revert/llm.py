"""One way to call the AI, whichever provider config.yaml picks.

  provider: "gemini"     → Google Gemini free tier (no cost; needs GEMINI_API_KEY from aistudio.google.com)
  provider: "anthropic"  → Claude (paid, sharper writing; needs ANTHROPIC_API_KEY)

Every call asks for a JSON object matching a schema and returns it as a dict.
"""
from __future__ import annotations

import base64
import io
import json
import re
import time

from .util import env, http, log

GEMINI = "https://generativelanguage.googleapis.com/v1beta"
ROLES = ("writer", "checker", "rewrite")
DEFAULTS = {
    "gemini": {"writer_model": "gemini-3.5-flash", "checker_model": "gemini-3.1-flash-lite",
               "rewrite_model": "gemini-3.5-flash"},
    "anthropic": {"writer_model": "claude-haiku-5-5", "checker_model": "claude-haiku-5-5",
                  "rewrite_model": "claude-sonnet-5-5"},
}


class QuotaExceeded(RuntimeError):
    """The free daily limit has run out (resets at midnight US Pacific, ~11am UAE)."""


class ModelNotFound(RuntimeError):
    pass


class ModelTooSlow(RuntimeError):
    pass


def provider(cfg) -> str:
    return cfg.get("ai", {}).get("provider", "gemini")


def model_for(cfg, role: str) -> str:
    p = provider(cfg)
    section = cfg.get("ai", {}).get(p, {}) or {}
    return section.get(f"{role}_model") or DEFAULTS[p][f"{role}_model"]


def key_name(cfg) -> str:
    return "GEMINI_API_KEY" if provider(cfg) == "gemini" else "ANTHROPIC_API_KEY"


def _jpegs(paths) -> list[str]:
    from PIL import Image
    out = []
    for p in (paths or [])[:3]:
        im = Image.open(p).convert("RGB")
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        out.append(base64.b64encode(buf.getvalue()).decode())
    return out


def call(cfg, role: str, system: str, user: str, tool: dict, images=None, client=None,
         max_tokens: int = 2500) -> dict:
    """Ask the configured AI for a JSON object shaped like tool['input_schema']."""
    model = model_for(cfg, role)
    if provider(cfg) == "anthropic":
        out = _anthropic(client, model, system, user, tool, images, max_tokens)
    else:
        # Try the chosen model, then the backups (free models are sometimes busy or out of quota).
        chain = [model] + [m for m in gemini_backups(cfg, role) if m != model]
        last_err = None
        out = None
        for m in chain:
            try:
                out = _gemini(m, system, user, tool, images, max_tokens)
                break
            except ModelNotFound:
                try:
                    alt = pick_available_gemini(role)
                except Exception as ex:
                    last_err = ex
                    continue
                if alt in chain:
                    continue
                log.warning("Gemini model %s not found — trying %s (update config.yaml)", m, alt)
                try:
                    out = _gemini(alt, system, user, tool, images, max_tokens)
                    break
                except (QuotaExceeded, ModelTooSlow, ModelNotFound) as ex:
                    last_err = ex
            except (QuotaExceeded, ModelTooSlow) as ex:
                log.warning("%s — trying the next model", ex)
                last_err = ex
        if out is None:
            raise last_err or RuntimeError("No Gemini model available")
    return normalise(out, tool)


def gemini_backups(cfg, role: str) -> list[str]:
    g = cfg.get("ai", {}).get("gemini", {}) or {}
    backups = g.get("backup_models") or ["auto", model_for(cfg, "checker"), "auto-lite"]
    out = []
    for b in backups:
        if b in ("auto", "auto-lite"):         # newest Flash / Flash-Lite this key can use, looked up live
            try:
                b = pick_available_gemini("checker" if b == "auto-lite" or role == "checker" else "writer")
            except Exception as ex:
                log.info("Couldn't list Gemini models: %s", ex)
                continue
        if b not in out:
            out.append(b)
    if role == "checker":      # the checker is already the light model; its backups are the other light ones
        out = [b for b in out if "lite" in b] + [b for b in out if "lite" not in b]
    return out


# ───────────────────────── Anthropic (Claude) ─────────────────────────

def _anthropic(client, model, system, user, tool, images, max_tokens) -> dict:
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    if images:
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}
                   for b in _jpegs(images)] + [{"type": "text", "text": user}]
    else:
        content = user
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": content}],
        tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
    )
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            return dict(block.input)
    raise RuntimeError("Claude did not return a structured answer")


# ───────────────────────── Google Gemini (free tier) ─────────────────────────

def _gemini(model, system, user, tool, images, max_tokens) -> dict:
    key = env("GEMINI_API_KEY", required=True)
    schema = tool["input_schema"]
    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": b}} for b in _jpegs(images)]
    parts.append({"text": user})
    body = {
        "system_instruction": {"parts": [{"text": system + "\n\nAnswer with ONLY a JSON object that matches "
                                                           "this JSON schema:\n" + json.dumps(schema)}]},
        "contents": [{"role": "user", "parts": parts}],
        # thinking models count their thinking against the output budget, so leave plenty of room
        "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema,
                             "maxOutputTokens": max(max_tokens, 8192), "temperature": 0.8,
                             "thinkingConfig": {"thinkingLevel": "low"}},   # faster; captions don't need deep thought
    }
    last = ""
    timeouts = busy = 0
    for attempt in range(6):
        try:
            r = http().post(f"{GEMINI}/models/{model}:generateContent", json=body,
                            headers={"x-goog-api-key": key}, timeout=75)
        except Exception as ex:          # read timeout / connection drop on a busy free model
            timeouts += 1
            last = f"{type(ex).__name__}"
            if timeouts >= 2:
                raise ModelTooSlow(f"{model} is too slow right now ({last})")
            continue
        last = f"{r.status_code}: {r.text[:300]}"
        if r.status_code == 200:
            data = r.json()
            cands = data.get("candidates") or []
            if not cands:
                raise RuntimeError(f"Gemini returned no answer ({data.get('promptFeedback', {})})")
            text = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", [])
                           if not p.get("thought"))
            if not text.strip():
                if attempt < 2:
                    continue
                raise RuntimeError(f"Gemini gave an empty answer (finish: {cands[0].get('finishReason')})")
            try:
                return parse_json(text)
            except ValueError:
                if attempt < 2:
                    continue
                raise
        if r.status_code == 400 and "thinkingConfig" in body["generationConfig"] and "thinking" in r.text.lower():
            body["generationConfig"].pop("thinkingConfig")      # model doesn't support the setting
            continue
        if r.status_code == 400 and "responseJsonSchema" in body["generationConfig"]:
            # older/other models may not accept a full JSON schema — fall back to plain JSON mode
            body["generationConfig"].pop("responseJsonSchema")
            continue
        if r.status_code == 404:
            raise ModelNotFound(model)
        if r.status_code == 429:
            txt = r.text
            if re.search(r"PerDay|per day|daily", txt, re.I):
                raise QuotaExceeded(f"Free daily AI limit reached for {model}")
            m = re.search(r'"retryDelay":\s*"(\d+)', txt)
            time.sleep(min(int(m.group(1)) + 2 if m else 30, 65))
            continue
        if r.status_code >= 500:            # "model is experiencing high demand" etc.
            busy += 1
            if busy >= 3:
                raise ModelTooSlow(f"{model} is overloaded right now ({r.status_code})")
            time.sleep(8 * busy)
            continue
        break
    raise RuntimeError(f"Gemini request failed ({last})")


_picked: dict[str, str] = {}


def pick_available_gemini(role: str) -> str:
    """If Google renames/retires a model, pick the newest available Flash (or Flash-Lite for checks)."""
    if role in _picked:
        return _picked[role]
    r = http().get(f"{GEMINI}/models", params={"pageSize": 200},
                   headers={"x-goog-api-key": env("GEMINI_API_KEY", required=True)}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    want_lite = role == "checker"
    good = [n for n in names if re.fullmatch(r"gemini-[\d.]+-flash" + ("-lite" if want_lite else ""), n)]
    if not good:
        good = [n for n in names if "flash" in n and not re.search(r"tts|audio|live|image|embed", n)]
    if not good:
        raise RuntimeError("No usable Gemini Flash model found for this key")

    def ver(n):
        m = re.search(r"gemini-([\d.]+)", n)
        return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)
    _picked[role] = max(good, key=ver)
    return _picked[role]


# ───────────────────────── helpers ─────────────────────────

def parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        out = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise ValueError("AI answer was not JSON")
        out = json.loads(m.group(0))
    if isinstance(out, list) and out and isinstance(out[0], dict):
        out = out[0]
    if not isinstance(out, dict):
        raise ValueError("AI answer was not a JSON object")
    return out


def normalise(out: dict, tool: dict) -> dict:
    """Fill in anything a less strict model left out, so the rest of the system can rely on the shape."""
    props = tool["input_schema"]["properties"]
    for k, spec in props.items():
        t = spec.get("type")
        if k not in out or out[k] is None:
            out[k] = {"array": [], "boolean": False, "string": "",
                      "object": {p: "" for p in spec.get("properties", {})}}.get(t, "")
        if "enum" in spec and out[k] not in spec["enum"]:
            out[k] = {"category": "NEWS", "verdict": "minor"}.get(k, spec["enum"][0])
        if t == "array" and not isinstance(out[k], list):
            out[k] = [out[k]] if out[k] else []
        if t == "string" and not isinstance(out[k], str):
            out[k] = str(out[k])
        if t == "boolean" and not isinstance(out[k], bool):
            out[k] = str(out[k]).lower() in ("true", "1", "yes")
    if "slides" in out:
        out["slides"] = [s for s in out["slides"] if isinstance(s, dict) and s.get("title")
                         and isinstance(s.get("points"), list)]
    if "specs" in out:
        out["specs"] = [{"label": str(s.get("label", "")).strip(), "value": str(s.get("value", "")).strip()}
                        for s in out["specs"] if isinstance(s, dict) and s.get("label") and s.get("value")]
    if "hashtags" in out:
        out["hashtags"] = [h for h in out["hashtags"] if isinstance(h, str) and h.strip()]
    return out

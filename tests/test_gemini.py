"""Offline test of the free Gemini path with a simulated Google API.

Run:  python -m tests.test_gemini
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ["REVERT_DATA_DIR"] = tempfile.mkdtemp(prefix="revert_gem_")
os.environ["GEMINI_API_KEY"] = "test-key"

from revert import llm, util, writer  # noqa: E402
from tests.test_offline import NEWS_POST  # noqa: E402

llm.time.sleep = lambda s: None          # don't actually wait on simulated rate limits


class R:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return self._body if not isinstance(self._body, str) else json.loads(self._body)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def answer(obj, fenced=False):
    text = json.dumps(obj)
    if fenced:
        text = "```json\n" + text + "\n```"
    return R(200, {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True},
                                                         {"text": text}]}}]})


class FakeGoogle:
    def __init__(self, script):
        self.script = script            # list of functions(model, body) -> R, consumed in order
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        model = url.split("/models/")[1].split(":")[0]
        self.calls.append((model, "responseJsonSchema" in json["generationConfig"],
                           "fact checker" in json["system_instruction"]["parts"][0]["text"]))
        assert headers["x-goog-api-key"] == "test-key"
        return self.script.pop(0)(model, json)

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert url.endswith("/models")
        names = ["gemini-2.5-flash", "gemini-3.6-flash", "gemini-3.6-flash-lite", "gemini-3.6-flash-tts",
                 "gemini-embedding-2"]
        return R(200, {"models": [{"name": f"models/{n}", "supportedGenerationMethods":
                                   ["embedContent"] if "embed" in n else ["generateContent"]} for n in names]})


def main():
    cfg = util.load_config()
    assert llm.provider(cfg) == "gemini" and llm.key_name(cfg) == "GEMINI_API_KEY"
    item = {"kind": "news", "title": "Patrol Nismo", "url": "https://x", "source_name": "Motor1",
            "text": "Nissan revealed the Patrol Nismo with 495 hp. " * 20, "outlets": ["Motor1"]}
    ok = {"unsupported": [], "verdict": "ok"}
    partial = {k: v for k, v in NEWS_POST.items() if k not in ("slides", "stat", "year", "claims")}
    partial["category"] = "SOMETHING_ODD"

    # 1. normal: writer answer is fenced + missing fields + bad category, checker fine
    g = FakeGoogle([lambda m, b: answer(partial, fenced=True), lambda m, b: answer(ok)])
    util._session = g
    post = writer.write_post(item, cfg)
    assert post["headline"] == NEWS_POST["headline"] and post["category"] == "NEWS"
    assert post["slides"] == [] and post["stat"] == {"value": "", "label": ""} and post["check"]["verdict"] == "ok"
    assert [c[0] for c in g.calls] == ["gemini-3.5-flash", "gemini-3.1-flash-lite"], g.calls
    assert g.calls[1][2], "second call should be the fact checker"

    # 2. per-minute rate limit -> waits and retries
    g = FakeGoogle([lambda m, b: R(429, '{"error":{"details":[{"retryDelay":"7s"}]}}'),
                    lambda m, b: answer(NEWS_POST), lambda m, b: answer(ok)])
    util._session = g
    assert writer.write_post(item, cfg)["headline"] == NEWS_POST["headline"]

    # 3. model renamed/retired -> picks newest available Flash automatically (not TTS / embedding)
    llm._picked.clear()
    g = FakeGoogle([lambda m, b: R(404, "not found"), lambda m, b: answer(NEWS_POST), lambda m, b: answer(ok)])
    util._session = g
    writer.write_post(item, cfg)
    assert g.calls[1][0] == "gemini-3.6-flash", g.calls

    # 4. older model rejects the JSON schema field -> retries in plain JSON mode
    g = FakeGoogle([lambda m, b: R(400, "Invalid JSON payload: responseJsonSchema"),
                    lambda m, b: answer(NEWS_POST), lambda m, b: answer(ok)])
    util._session = g
    writer.write_post(item, cfg)
    assert g.calls[0][1] is True and g.calls[1][1] is False, g.calls

    # 5. writer's daily free limit used up -> falls back to Flash-Lite for writing
    g = FakeGoogle([lambda m, b: R(429, "Quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
                    lambda m, b: answer(NEWS_POST), lambda m, b: answer(ok)])
    util._session = g
    writer.write_post(item, cfg)
    assert g.calls[1][0] == "gemini-3.1-flash-lite", g.calls

    # 5b. writer model too slow (timeouts) -> falls back to Flash-Lite
    def slow(m, b):
        raise TimeoutError("read timed out")
    g = FakeGoogle([slow, slow, lambda m, b: answer(NEWS_POST), lambda m, b: answer(ok)])
    util._session = g
    writer.write_post(item, cfg)
    assert [c[0] for c in g.calls][2] == "gemini-3.1-flash-lite", g.calls

    # 5c. model doesn't know the thinking setting -> retries without it
    seen_thinking = []

    def no_thinking(m, b):
        seen_thinking.append("thinkingConfig" in b["generationConfig"])
        return R(400, "Unknown name thinkingConfig: thinking_level not supported") if seen_thinking[-1] else answer(NEWS_POST)
    util._session = FakeGoogle([no_thinking, no_thinking, lambda m, b: answer(ok)])
    writer.write_post(item, cfg)
    assert seen_thinking == [True, False], seen_thinking

    # 6. everything used up -> QuotaExceeded, and the pipeline sends ONE friendly Telegram notice
    from revert import pipeline
    from revert.state import State
    from tests.test_offline import FakeTG
    daily = lambda m, b: R(429, "RESOURCE_EXHAUSTED requests per day")
    util._session = FakeGoogle([daily] * 10)
    try:
        writer.write_post(item, cfg)
        raise AssertionError("should have raised QuotaExceeded")
    except llm.QuotaExceeded:
        pass
    tmp = Path(tempfile.mkdtemp(prefix="revert_gem_t_"))
    tg, st = FakeTG(), State(tmp / "s.json")
    pipeline.quota_hit(tg, st)
    pipeline.quota_hit(tg, st)
    assert sum("free AI limit" in t for t in tg.texts()) == 1

    # 7. community photos are sent to Gemini as images
    from PIL import Image
    p = tmp / "c.jpg"
    Image.new("RGB", (800, 600), (90, 100, 80)).save(p)
    seen = []

    def grab(m, b):
        seen.append(sum(1 for part in b["contents"][0]["parts"] if "inline_data" in part))
        return answer(NEWS_POST)
    util._session = FakeGoogle([grab, lambda m, b: answer(ok)])
    writer.write_post({**item, "kind": "community", "credit": "u/x via r/dubai"}, cfg, images=[p])
    assert seen == [1], seen

    print("GEMINI CHECKS PASSED")


if __name__ == "__main__":
    main()

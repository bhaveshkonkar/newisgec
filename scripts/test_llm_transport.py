"""LLM transport behaviour: retry, ASCII folding, honest failure reporting.

The assistant degrading to "computed result only" is a safety feature, but it
is useless if you cannot tell why. These tests pin the three things that went
wrong in production:

  * a single 429 was taken at face value, so a burst of selections fell
    straight through to the offline fallback;
  * the model emits non-ASCII (U+2011, U+202f, curly quotes) despite being
    told not to, and one such character can blow up a legacy-code-page log;
  * every failure was reported as "no LLM configured", including the case
    where a key was present and the provider was simply rate limiting.

No network: the HTTP client is faked.

Run: .\\.venv\\Scripts\\python.exe scripts\\test_llm_transport.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import reasoning  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append((name, detail))
        print(f"  FAIL  {name}" + (f"\n          {detail}" if detail else ""))


def section(t: str) -> None:
    print(f"\n{t}\n" + "-" * len(t))


class FakeResponse:
    def __init__(self, status, text="", payload=None, headers=None):
        self.status_code = status
        self.text = text
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def ok(content: str) -> FakeResponse:
    return FakeResponse(200, payload={"choices": [{"message": {"content": content}}]})


class FakeClient:
    """Replays a scripted sequence of responses and records headers."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.headers_seen = []

    def post(self, url, headers=None, json=None):
        self.calls += 1
        if headers:
            self.headers_seen.append(headers)
        idx = min(self.calls - 1, len(self.script) - 1)
        nxt = self.script[idx]
        return nxt() if callable(nxt) else nxt


def run_with(script):
    """Call the synchronous helper against a fake client.

    Returns ((answer, reason), waits, client) with time.sleep captured so the
    backoff can be asserted without actually waiting.
    """
    slept: list[float] = []
    real_sleep = time.sleep
    time.sleep = slept.append
    try:
        client = FakeClient(script)
        result = reasoning._post_completion(client, "k", {"model": "m"})
    finally:
        time.sleep = real_sleep
    return result, slept, client


class FakeAsyncClient(FakeClient):
    """Async twin. A sync helper here returns a coroutine, not a response."""

    async def post(self, url, headers=None, json=None):
        return FakeClient.post(self, url, headers=headers, json=json)


async def run_with_async(script):
    import asyncio

    waited: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        waited.append(seconds)

    asyncio.sleep = fake_sleep
    try:
        client = FakeAsyncClient(script)
        result = await reasoning._post_completion_async(client, "k", {"model": "m"})
    finally:
        asyncio.sleep = real_sleep
    return result, waited, client


def main() -> int:
    section("a clean call is passed through")
    (ans, reason), _, _ = run_with([ok("S3-40 is the smallest size rated at or above PN.")])
    check("answer returned", ans is not None and "S3-40" in ans, str(ans))
    check("reason empty on success", reason == "", reason)

    section("429 is retried, not surfaced as offline")
    (ans, reason), slept, _ = run_with([
        FakeResponse(429, "rate limited", headers={"retry-after": "2"}),
        FakeResponse(429, "rate limited"),
        ok("Recovered answer."),
    ])
    check("answer recovered after two 429s", ans == "Recovered answer.", str(ans))
    check("no failure reason", reason == "", reason)
    check("it actually waited between attempts", len(slept) == 2, str(slept))
    check("honoured Retry-After on the first wait", slept and slept[0] == 2.0, str(slept))
    check("backed off on the second", len(slept) > 1 and slept[1] > slept[0], str(slept))

    section("a persistent 429 degrades, and says so")
    (ans, reason), slept, _ = run_with([FakeResponse(429, "rate limited")])
    check("answer is None", ans is None, str(ans))
    check("reason is rate_limited, not a missing key", reason == "rate_limited", reason)
    check("it used all three attempts", len(slept) == 2, str(slept))

    section("5xx is retried; 4xx is not")
    (ans, reason), _, _ = run_with([FakeResponse(503, "upstream"), ok("Back up.")])
    check("5xx recovers", ans == "Back up.", str(ans))
    (ans, reason), _, client = run_with([FakeResponse(401, "bad key")])
    check("401 gives up immediately", reason == "upstream", reason)
    check("401 did not retry", client.calls == 1, f"calls={client.calls}")

    section("non-ASCII from the model is folded to ASCII")
    dirty = (
        "Choose the S3\u201140 \u2014 rated 3.0\u202fkW at "
        "17:1\u2019s ratio \u201cthe published figure\u201d, "
        "not an estimate \u2022 see \u3010note\u3011 "
        "3\u00d74 face 10\u2070C and 50\u00b0C \u2265 5 \u00b1 0.5 "
        "\u2264 8 area 12 m\u00b2 \u2192 14 W\u00b7m \u2026"
    )
    folded = reasoning.to_ascii(dirty)
    check("output is pure ASCII", folded.isascii(), repr(folded[:90]))
    check("non-breaking hyphen becomes a plain hyphen", "S3-40" in folded, folded[:60])
    check("narrow no-break space becomes a normal space", "3.0 kW" in folded, folded[:60])
    check("curly quotes become straight", '"the published figure"' in folded, folded)
    check("apostrophe normalised", "17:1's ratio" in folded, folded)
    check(
        "punctuation, maths and units all folded",
        all(t in folded for t in ("-", "[note]", "3x4", "100C", "50 degC",
                                  ">= 5", "+/- 0.5", "<= 8", "m2", "->",
                                  "W*m", "...")),
        folded,
    )
    check("superscript digits are not left behind", "\u2070" not in folded, folded)
    check("superscript two is not left behind", "\u00b2" not in folded, folded)
    check("ellipsis expanded", "..." in folded and "\u2026" not in folded, folded[-30:])
    check("numbers survive intact", "3.0" in folded and "17" in folded, folded)

    section("ASCII folding is safe on ordinary text")
    for s in ("", "plain ascii answer", "PN = 60 kW at 1500 rpm", "a\tb\nc", "a-b"):
        check(f"unchanged: {s[:24]!r}", reasoning.to_ascii(s) == s, repr(reasoning.to_ascii(s)))
    check("an unmapped character degrades to '?', not an exception",
          reasoning.to_ascii("\u4e2d\u6587") == "??",
          repr(reasoning.to_ascii("\u4e2d\u6587")))
    check("astral-plane characters do not crash the fold",
          reasoning.to_ascii("ok \U0001F9EA done").isascii(),
          repr(reasoning.to_ascii("ok \U0001F9EA done")))

    section("a User-Agent is always sent")
    _, _, client = run_with([ok("hi")])
    sent = client.headers_seen[0] if client.headers_seen else {}
    ua = sent.get("User-Agent")
    check("User-Agent header present", bool(ua), str(sent))
    check(
        "it is not the agent Cloudflare blocks",
        "python-httpx" not in (ua or "") and "urllib" not in (ua or ""),
        ua,
    )
    check("the bearer token is still sent", sent.get("Authorization") == "Bearer k", str(sent))

    section("an empty completion is distinguishable from a transport failure")
    (ans, reason), _, _ = run_with([ok("")])
    check("empty content reported as empty", reason == "empty", reason)
    (ans, reason), _, _ = run_with([FakeResponse(200, text="not json", payload=None)])
    check("unparseable body reported as error", reason == "error", reason)

    section("the async path is a real async path")
    # Regression: a single synchronous helper was handed an AsyncClient, so
    # client.post() returned a coroutine and every catalog question answered
    # "Sorry, I couldn't retrieve that from the catalog." The failure looked
    # like missing data rather than a type error.
    import asyncio

    (ans, reason), waited, client = asyncio.run(
        run_with_async([ok("Async answer.")])
    )
    check("async helper returns the answer", ans == "Async answer.", str(ans))
    check("async helper reports success", reason == "", reason)
    check("no spurious backoff on the first success", waited == [], str(waited))

    (ans, reason), waited, _ = asyncio.run(
        run_with_async([FakeResponse(429, "slow down"), ok("Recovered async.")])
    )
    check("async helper retries a 429", ans == "Recovered async.", str(ans))
    check("async helper awaited between attempts", len(waited) == 1, str(waited))

    (ans, reason), _, _ = asyncio.run(
        run_with_async([FakeResponse(429, "slow down")])
    )
    check("async helper reports rate_limited", reason == "rate_limited", reason)

    (ans, reason), _, _ = asyncio.run(run_with_async([ok("")]))
    check("async helper reports empty", reason == "empty", reason)

    section("both helpers exist and call sites are paired correctly")
    src = (ROOT / "app" / "reasoning.py").read_text(encoding="utf-8")
    needle = "choices'][0]['message']['content']"
    check("sync helper exists", "def _post_completion(" in src)
    check("async helper exists", "async def _post_completion_async(" in src)
    check("only the shared _interpret reads the completion", src.count(needle) == 1,
          f"count={src.count(needle)}")
    # Anchor on `async with`/`with`, not the bare class name: a docstring
    # mentioning httpx.AsyncClient is documentation, not a call site.
    lines = src.splitlines()
    code = [
        (i + 1, ln) for i, ln in enumerate(lines)
        if not ln.strip().startswith(("#", '"', "'"))
        and "AsyncClient" not in ln.split('"""')[0][:0]
    ]
    bad = []
    for i, line in code:
        if "async with httpx.AsyncClient" in line:
            window = "\n".join(lines[i:i + 4])
            if "_post_completion_async" not in window or "await" not in window:
                bad.append(i)
    check("no AsyncClient is paired with the sync helper", not bad, f"lines {bad}")
    bad = []
    for i, line in code:
        if "with httpx.Client(" in line:
            window = "\n".join(lines[i:i + 4])
            if "_post_completion_async" in window:
                bad.append(i)
    check("no sync Client is paired with the async helper", not bad, f"lines {bad}")
    api = (ROOT / "app" / "internal_api.py").read_text(encoding="utf-8")
    check("endpoint no longer blames a missing key for every failure",
          "LLM did not return an answer" in api)
    check("diagnostics go to stderr so they survive buffering",
          "file=sys.stderr" in src)

    print("\n" + "=" * 60)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    for name, detail in FAILED:
        print(f"  - {name}" + (f"\n      {detail}" if detail else ""))
    print("=" * 60)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
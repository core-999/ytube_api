"""Regression tests for the stream-path performance work.

Deliberately minimal: this covers only the invariants that are *fragile* — the ones
where a plausible-looking edit silently reintroduces a bug that is expensive to
diagnose in production (a 4 s stall, a corrupted stream, a dead URL served forever).
Each test names the regression it guards in its docstring.

Verified the way a regression test should be: by reverting each fix and confirming the
matching test fails. Nothing here touches the network or a real Redis.
"""
import asyncio
import gzip
import json

import httpx
import pytest
from starlette.requests import Request

import main
from utils import stream_proxy

VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


# ─────────────────────────── helpers ───────────────────────────


class FakeRedis:
    """Just enough Redis for the job helpers: GET/SET (NX/XX)/DELETE, with call counts."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.gets = 0
        self.sets = 0
        self.deleted: list[str] = []
        # Lets a test hold a write open to prove what happens *before* it lands.
        self.set_gate: asyncio.Event | None = None

    async def get(self, name):
        self.gets += 1
        return self.store.get(name)

    async def set(self, name, value, ex=None, nx=False, xx=False):
        if self.set_gate is not None:
            await self.set_gate.wait()
        self.sets += 1
        if nx and name in self.store:
            return None
        if xx and name not in self.store:
            return None
        self.store[name] = value
        return True

    async def delete(self, *names):
        self.deleted.extend(names)
        for n in names:
            self.store.pop(n, None)
        return len(names)


@pytest.fixture
def redis(monkeypatch):
    """Fake Redis + a clean process-local memo/event/lock state for every test."""
    fake = FakeRedis()

    async def _get_async_redis():
        return fake

    monkeypatch.setattr(main, "get_async_redis", _get_async_redis)
    main._JOB_MEMO._data.clear()
    main._JOB_EVENTS._data.clear()
    main._REFRESH_LOCKS._data.clear()
    return fake


def make_request(path="/stream", headers=None, query_string=b"") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "query_string": query_string,
        }
    )


def seed_job(redis, stream_id, **over):
    job = {"url": VIDEO_URL, "mode": "video", "extracted_url": None, "extracted_time": None}
    job.update(over)
    redis.store[f"stream_job:{stream_id}"] = json.dumps(job)
    return job


# ───────────────────── C2/C3: byte-exact proxying ─────────────────────


@pytest.mark.asyncio
async def test_proxy_forwards_body_verbatim_and_asks_for_identity():
    """Guards the corrupted-stream regression.

    The proxy forwards `content-length`/`content-encoding` from upstream unchanged, so it
    must also forward the *bytes* unchanged. An earlier copy used `aiter_bytes()`, which
    transparently decompresses — the client then got a decompressed body described by a
    compressed length and saw a truncated or hanging stream. Two halves of one contract:
    ask upstream for `identity` so httpx never negotiates an encoding it would decode,
    and read with `aiter_raw()`.
    """
    payload = gzip.compress(b"media-bytes" * 500)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["accept-encoding"] = request.headers.get("accept-encoding")
        seen["range"] = request.headers.get("range")
        seen["user-agent"] = request.headers.get("user-agent")

        async def body():
            yield payload[:64]
            yield payload[64:]

        return httpx.Response(
            200,
            headers={
                "content-type": "video/mp4",
                "content-encoding": "gzip",
                "content-length": str(len(payload)),
                "connection": "keep-alive",  # hop-by-hop: must not be copied downstream
            },
            content=body(),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resp = await stream_proxy.proxy_stream(
            "https://rr1---sn-x.googlevideo.com/videoplayback",
            range_header="bytes=0-",
            user_agent="TestPlayer/1.0",
            client=client,
        )
        out = b"".join([chunk async for chunk in resp.body_iterator])

    assert seen["accept-encoding"] == "identity"
    assert seen["range"] == "bytes=0-"  # Range forwarded so players can seek
    assert seen["user-agent"] == "TestPlayer/1.0"

    assert out == payload, "body must be forwarded raw, not decompressed"
    assert resp.headers["content-length"] == str(len(payload))
    assert resp.headers["content-encoding"] == "gzip"
    assert resp.headers["accept-ranges"] == "bytes"
    assert "connection" not in resp.headers


@pytest.mark.asyncio
async def test_proxy_releases_connection_when_body_is_never_iterated():
    """Guards the pool-exhaustion regression.

    If the client hangs up between headers and the first chunk the body generator never
    runs, so its `finally` never fires. Without the response's `BackgroundTask` fallback
    that upstream connection sits in the pool until GC finalizes the generator — with
    `max_connections=200` and long-lived media transfers, that leaks the pool.
    `release_once` is idempotent so the two paths can't double-close.
    """
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        async def body():
            yield b"never-read"

        resp = httpx.Response(200, headers={"content-type": "video/mp4"}, content=body())
        captured.append(resp)
        return resp

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resp = await stream_proxy.proxy_stream("https://rr1---sn-x.googlevideo.com/v", client=client)

        upstream = captured[0]
        assert not upstream.is_closed, "still open while the response is pending"

        assert resp.background is not None, "no background task = leaked connection"
        await resp.background()
        assert upstream.is_closed

        await resp.background()  # idempotent: a second release must not raise


@pytest.mark.asyncio
async def test_proxy_mirrors_upstream_error_status():
    """The 403 recovery in `stream_resolver` keys off this status, so it must not be
    flattened into a generic 502. Connect *failures* are a different case and do map
    to 502."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b"denied")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resp = await stream_proxy.proxy_stream("https://rr1---sn-x.googlevideo.com/v", client=client)
    assert resp.status_code == 403

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns is down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
        resp = await stream_proxy.proxy_stream("https://rr1---sn-x.googlevideo.com/v", client=client)
    assert resp.status_code == 502


# ───────────────────── B1/B2: memo + local-first publish ─────────────────────


@pytest.mark.asyncio
async def test_job_memo_caches_completed_jobs_only(redis):
    """Guards the stale-wait regression.

    Redis is remote (~250 ms/GET), so completed jobs are memoised — their extracted URL is
    immutable until revoked. A *pending* job is precisely what `_await_extracted` is
    watching for a change, so memoising it would make the wait loop spin on stale data
    until the TTL lapsed. This asymmetry is why no "bypass the cache" flag is needed.
    """
    seed_job(redis, "pending-id")
    await main._job_get("pending-id")
    await main._job_get("pending-id")
    assert redis.gets == 2, "pending job must not be memoised"

    seed_job(redis, "done-id", extracted_url="https://cdn/x", extracted_time=1.0)
    redis.gets = 0
    first = await main._job_get("done-id")
    second = await main._job_get("done-id")
    assert redis.gets == 1, "completed job must be served from the memo"
    assert second["extracted_url"] == "https://cdn/x"

    first["extracted_url"] = "mutated"
    assert (await main._job_get("done-id"))["extracted_url"] == "https://cdn/x", (
        "_job_get must hand out copies; callers mutate jobs before writing them back"
    )


@pytest.mark.asyncio
async def test_waiter_wakes_before_the_redis_write_lands(redis, monkeypatch):
    """Guards the ~265 ms-per-stream regression.

    Extraction publishes to the local memo/event *before* persisting to Redis. The URL is
    already valid at that point; Redis only exists to share it with other replicas. If the
    order is flipped, every local waiter pays a round trip to another continent before it
    can send byte one. Pinned by holding the Redis write open and requiring the waiter to
    return anyway.
    """
    stream_id = main._encode_stream_id(VIDEO_URL, "video")
    seed_job(redis, stream_id)

    import utils.cache_manager as cm

    async def fake_get_video_stream(url):
        return "https://cdn/extracted"

    monkeypatch.setattr(cm, "get_video_stream", fake_get_video_stream, raising=False)

    redis.set_gate = asyncio.Event()  # the write will block until we open this
    main._start_background_extraction(stream_id, VIDEO_URL, "video")

    job = await asyncio.wait_for(main._await_extracted(stream_id, timeout=5.0), timeout=2.0)
    assert job["extracted_url"] == "https://cdn/extracted"
    assert redis.sets == 0, "waiter must not have waited on the Redis round trip"

    redis.set_gate.set()
    await asyncio.sleep(0)  # let the pending write drain
    for _ in range(50):
        if redis.sets:
            break
        await asyncio.sleep(0.01)
    assert redis.sets == 1, "the job must still be persisted for other replicas"


# ───────────────────── C1: revoked-URL recovery ─────────────────────


@pytest.mark.asyncio
async def test_refresh_invalidates_cache_and_clears_url_before_reextracting(redis, monkeypatch):
    """Guards the never-heals regression.

    Recovering from a 403 needs all three steps, and the fix is inert without any one:
    invalidate the cache_manager entry (it expires off the `expire` stamped in the URL,
    which googlevideo revokes long before, so re-extraction is otherwise handed the same
    dead URL), clear `extracted_url` *before* re-extracting (or `_await_extracted` returns
    the dead URL instantly), and only then extract.
    """
    stream_id = main._encode_stream_id(VIDEO_URL, "video")
    dead = "https://cdn/dead"
    job = seed_job(redis, stream_id, extracted_url=dead, extracted_time=1.0)

    import utils.cache_manager as cm

    invalidated = []
    state_when_extraction_started = {}

    async def fake_invalidate(url, prefix=""):
        invalidated.append((url, prefix))

    async def fake_get_video_stream(url):
        memo = main._JOB_MEMO.get(stream_id)
        state_when_extraction_started["memo"] = memo
        state_when_extraction_started["invalidated_first"] = bool(invalidated)
        return "https://cdn/fresh"

    monkeypatch.setattr(cm, "invalidate", fake_invalidate, raising=False)
    monkeypatch.setattr(cm, "get_video_stream", fake_get_video_stream, raising=False)

    refreshed = await main._refresh_stream_url(stream_id, job)

    assert refreshed["extracted_url"] == "https://cdn/fresh"
    assert invalidated == [(VIDEO_URL, "video:")], "both cache layers keyed by mode prefix"
    assert state_when_extraction_started["invalidated_first"] is True
    assert state_when_extraction_started["memo"] is None, (
        "the dead URL must be cleared before re-extraction, or waiters get it back"
    )


@pytest.mark.asyncio
async def test_concurrent_refreshes_extract_once(redis, monkeypatch):
    """Guards the 403-storm regression.

    N players hitting one revoked URL all 403 at the same instant. Uncoalesced, each
    invalidates the cache and launches its own extraction — and those rapid repeat
    requests are themselves what trips googlevideo's per-IP 403s, so the recovery
    sustains the outage it is trying to fix.
    """
    stream_id = main._encode_stream_id(VIDEO_URL, "video")
    dead = "https://cdn/dead"
    job = seed_job(redis, stream_id, extracted_url=dead, extracted_time=1.0)

    import utils.cache_manager as cm

    extractions = 0
    invalidations = 0

    async def fake_invalidate(url, prefix=""):
        nonlocal invalidations
        invalidations += 1

    async def fake_get_video_stream(url):
        nonlocal extractions
        extractions += 1
        await asyncio.sleep(0.05)  # hold the lock so the others must queue
        return "https://cdn/fresh"

    monkeypatch.setattr(cm, "invalidate", fake_invalidate, raising=False)
    monkeypatch.setattr(cm, "get_video_stream", fake_get_video_stream, raising=False)

    results = await asyncio.gather(*[main._refresh_stream_url(stream_id, dict(job)) for _ in range(5)])

    assert extractions == 1, f"expected one extraction, got {extractions}"
    assert invalidations == 1
    assert {r["extracted_url"] for r in results} == {"https://cdn/fresh"}


@pytest.mark.asyncio
async def test_resolver_retries_403_and_410_but_not_404(redis, monkeypatch):
    """Guards both halves of the retry policy.

    403/410 mean the URL was revoked and re-extraction fixes it. 404 means the *video* is
    gone — retrying just fails again more slowly, after a full extraction. The retry is
    also capped at one attempt so a permanently dead URL can't loop.
    """
    stream_id = "sid"

    async def fake_await_extracted(sid, timeout=45.0):
        return {"url": VIDEO_URL, "mode": "video", "extracted_url": "https://cdn/dead"}

    monkeypatch.setattr(main, "_await_extracted", fake_await_extracted)

    for status, should_refresh in ((403, True), (410, True), (404, False)):
        refreshes = 0
        proxied = []

        async def fake_proxy(target_url, request, started=None, _status=status, _proxied=proxied):
            _proxied.append(target_url)
            return main.JSONResponse(status_code=_status, content={"error": "x"})

        async def fake_refresh(sid, job):
            nonlocal refreshes
            refreshes += 1
            return {**job, "extracted_url": "https://cdn/fresh"}

        monkeypatch.setattr(main, "_proxy_stream_response", fake_proxy)
        monkeypatch.setattr(main, "_refresh_stream_url", fake_refresh)

        resp = await main.stream_resolver(make_request(), stream_id)

        assert refreshes == (1 if should_refresh else 0), f"status {status}"
        assert proxied[0] == "https://cdn/dead"
        if should_refresh:
            assert proxied[1] == "https://cdn/fresh", f"status {status} must retry the new URL"
            assert len(proxied) == 2, "retry must be capped at one attempt"
        else:
            assert len(proxied) == 1
        assert resp.status_code == status


# ───────────────────── B4: de-duplicated auth ─────────────────────


@pytest.mark.asyncio
async def test_require_token_reuses_the_middleware_lookup(monkeypatch):
    """Guards the double-lookup regression.

    Every token resolution is a ~290 ms round trip to a remote Redis, and the middleware
    has already done it for this exact request. The `_UNRESOLVED` sentinel is load-bearing:
    a plain `None` default cannot distinguish "middleware ran and found no user" (401, no
    second lookup) from "middleware never ran" — the free `/stream/resolver/` and
    `/stream/proxy/` prefixes it skips, which still need a real lookup.
    """
    lookups = 0

    async def fake_get_user_by_token(token):
        nonlocal lookups
        lookups += 1
        return 4242 if token == "good" else None

    monkeypatch.setattr(main, "get_user_by_token", fake_get_user_by_token)

    # Middleware ran and resolved a user: reuse it, don't pay again.
    req = make_request(headers={"authorization": "Bearer good"})
    req.state.auth_user_id = 4242
    assert await main.require_token(req) == 4242
    assert lookups == 0, "token resolved twice, expected once"

    # Middleware ran and found nobody: 401 without a redundant lookup.
    req = make_request(headers={"authorization": "Bearer bad"})
    req.state.auth_user_id = None
    with pytest.raises(main.HTTPException) as exc:
        await main.require_token(req)
    assert exc.value.status_code == 401
    assert lookups == 0

    # Middleware skipped this path (free prefix): fall back to a real lookup.
    req = make_request(path="/stream/resolver/abc", headers={"authorization": "Bearer good"})
    assert await main.require_token(req) == 4242
    assert lookups == 1

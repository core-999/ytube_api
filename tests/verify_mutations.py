"""Mutation harness: revert each fix, confirm the matching test fails, restore.

A regression test that passes on broken code is worthless. This applies each fix in
reverse (as a targeted source edit), runs only the test that should catch it, and asserts
that test FAILS. Restores from git after every mutation.

Run:  TESTING=1 python3 tests/verify_mutations.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (label, file, old, new, test that must fail)
MUTATIONS = [
    (
        "C2: aiter_raw -> aiter_bytes (decompresses while forwarding compressed length)",
        "utils/stream_proxy.py",
        "async for chunk in upstream.aiter_raw(_CHUNK):",
        "async for chunk in upstream.aiter_bytes(_CHUNK):",
        "test_proxy_forwards_body_verbatim_and_asks_for_identity",
    ),
    (
        "C2: drop accept-encoding: identity",
        "utils/stream_proxy.py",
        '        "accept-encoding": "identity",\n',
        "",
        "test_proxy_forwards_body_verbatim_and_asks_for_identity",
    ),
    (
        "C3: drop the BackgroundTask connection release",
        "utils/stream_proxy.py",
        "        background=BackgroundTask(release_once),\n",
        "",
        "test_proxy_releases_connection_when_body_is_never_iterated",
    ),
    (
        "C2: flatten upstream error status into 502",
        "utils/stream_proxy.py",
        "            status_code=status,\n            content={\"error\": f\"Upstream returned HTTP {status}\"},",
        "            status_code=502,\n            content={\"error\": f\"Upstream returned HTTP {status}\"},",
        "test_proxy_mirrors_upstream_error_status",
    ),
    (
        "B1: memoise pending jobs too",
        "main.py",
        '    if job.get("extracted_url"):\n        _JOB_MEMO[stream_id] = dict(job)\n    return job',
        "    _JOB_MEMO[stream_id] = dict(job)\n    return job",
        "test_job_memo_caches_completed_jobs_only",
    ),
    (
        "B2: publish locally AFTER the Redis write instead of before",
        "main.py",
        "                _job_publish_local(stream_id, job)\n                # SET XX",
        "                # SET XX",
        "test_waiter_wakes_before_the_redis_write_lands",
    ),
    (
        "C1: skip cache invalidation on refresh",
        "main.py",
        "            from utils.cache_manager import invalidate\n            await invalidate(url, \"video:\" if mode == \"video\" else \"audio:\")",
        "            pass",
        "test_refresh_invalidates_cache_and_clears_url_before_reextracting",
    ),
    (
        "C1: don't clear extracted_url before re-extracting",
        "main.py",
        '        pending = dict(job)\n        pending["extracted_url"] = None\n        pending["extracted_time"] = None\n        await _job_set(stream_id, pending)\n',
        "",
        "test_refresh_invalidates_cache_and_clears_url_before_reextracting",
    ),
    (
        "C1: drop the refresh lock (concurrent 403s all re-extract)",
        "main.py",
        "    async with _refresh_lock(stream_id):",
        "    if True:",
        "test_concurrent_refreshes_extract_once",
    ),
    (
        "C1: retry 404 as well as 403/410",
        "main.py",
        "    if resp.status_code in (403, 410):",
        "    if resp.status_code in (403, 410, 404):",
        "test_resolver_retries_403_and_410_but_not_404",
    ),
    (
        "B4: replace the _UNRESOLVED sentinel with a None default",
        "main.py",
        '    user_id = getattr(request.state, "auth_user_id", _UNRESOLVED)\n    if user_id is _UNRESOLVED:',
        '    user_id = getattr(request.state, "auth_user_id", None)\n    if user_id is None:',
        "test_require_token_reuses_the_middleware_lookup",
    ),
]


def restore():
    subprocess.run(["git", "checkout", "--", "main.py", "utils/stream_proxy.py"], cwd=ROOT, check=True)


def main() -> int:
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "main.py", "utils/stream_proxy.py"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    if dirty:
        print("refusing to run: main.py / utils/stream_proxy.py have uncommitted changes")
        print(dirty)
        return 2

    failures = []
    try:
        for label, relpath, old, new, test in MUTATIONS:
            path = ROOT / relpath
            src = path.read_text()
            if old not in src:
                failures.append(f"{label}: mutation target not found (code moved?)")
                print(f"SKIP  {label}\n      target text not found in {relpath}")
                continue
            path.write_text(src.replace(old, new, 1))

            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/test_stream_path.py", "-k", test, "-q", "--no-header"],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            restore()

            caught = proc.returncode != 0
            print(f"{'OK   ' if caught else 'MISS '} {label}\n      -> {test} {'failed as expected' if caught else 'STILL PASSED'}")
            if not caught:
                failures.append(f"{label}: {test} did not catch it")
    finally:
        restore()

    print()
    if failures:
        print(f"{len(failures)} mutation(s) uncaught:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"all {len(MUTATIONS)} mutations caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())

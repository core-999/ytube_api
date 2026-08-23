"""Zero-dependency Prometheus metrics.

In-process counters, rendered in Prometheus text exposition format. Per-process
state is correct for Prometheus — it scrapes each replica as its own target, so
no cross-replica sharing (unlike job state, which lives in Redis).

ponytail: summary-style latency (_sum/_count → average) instead of full
histograms. Add buckets only when you actually need p95/p99 on the scrape side.
"""
from collections import defaultdict

_req_total: dict = defaultdict(int)      # (method, path, status) -> count
_latency_sum: dict = defaultdict(float)  # (method, path) -> seconds
_latency_count: dict = defaultdict(int)  # (method, path) -> count

# ── Streaming ─────────────────────────────────────────────────
# http_request_duration_seconds is ~TTFB for a StreamingResponse (the middleware
# returns once headers are sent, before a single body byte), so the transfer itself
# is invisible without these.
_stream_ttfb_sum: float = 0.0
_stream_ttfb_count: int = 0
_upstream_connect_sum: float = 0.0
_upstream_connect_count: int = 0
_upstream_connect_slow: int = 0  # connects > _SLOW_CONNECT_S (see D2 below)
_stream_bytes: int = 0
_stream_active: int = 0
_stream_errors: dict = defaultdict(int)   # code -> count

# A googlevideo connect is normally 30-300 ms. Anything past a second means DNS or
# the CDN is degrading — the exact signature of the 4-5 s resolver stalls that were
# traced to dropped UDP DNS queries. Alert on a rising rate here.
_SLOW_CONNECT_S = 1.0


def record(method: str, path: str, status: int, duration: float) -> None:
    _req_total[(method, path, str(status))] += 1
    _latency_sum[(method, path)] += duration
    _latency_count[(method, path)] += 1


def record_upstream_connect(duration: float) -> None:
    """Time to get response headers back from googlevideo (DNS + TCP + TLS + TTFB)."""
    global _upstream_connect_sum, _upstream_connect_count, _upstream_connect_slow
    _upstream_connect_sum += duration
    _upstream_connect_count += 1
    if duration > _SLOW_CONNECT_S:
        _upstream_connect_slow += 1


def record_stream_ttfb(duration: float) -> None:
    """End-to-end time from request arrival to first byte handed to the client."""
    global _stream_ttfb_sum, _stream_ttfb_count
    _stream_ttfb_sum += duration
    _stream_ttfb_count += 1


def record_stream_bytes(n: int) -> None:
    global _stream_bytes
    _stream_bytes += n


def record_stream_error(code) -> None:
    _stream_errors[str(code)] += 1


def stream_started() -> None:
    global _stream_active
    _stream_active += 1


def stream_finished() -> None:
    global _stream_active
    _stream_active -= 1


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"')


def render() -> str:
    lines = [
        "# HELP http_requests_total Total HTTP requests by method, path and status.",
        "# TYPE http_requests_total counter",
    ]
    for (method, path, status), n in sorted(_req_total.items()):
        lines.append(
            f'http_requests_total{{method="{_esc(method)}",path="{_esc(path)}",status="{status}"}} {n}'
        )
    lines += [
        "# HELP http_request_duration_seconds Request latency by method and path.",
        "# TYPE http_request_duration_seconds summary",
    ]
    for (method, path), total in sorted(_latency_sum.items()):
        labels = f'method="{_esc(method)}",path="{_esc(path)}"'
        lines.append(f"http_request_duration_seconds_sum{{{labels}}} {total}")
        lines.append(f"http_request_duration_seconds_count{{{labels}}} {_latency_count[(method, path)]}")

    lines += [
        "# HELP stream_ttfb_seconds Time from proxy request to first byte sent to client.",
        "# TYPE stream_ttfb_seconds summary",
        f"stream_ttfb_seconds_sum {_stream_ttfb_sum}",
        f"stream_ttfb_seconds_count {_stream_ttfb_count}",
        "# HELP stream_upstream_connect_seconds Time to receive upstream response headers.",
        "# TYPE stream_upstream_connect_seconds summary",
        f"stream_upstream_connect_seconds_sum {_upstream_connect_sum}",
        f"stream_upstream_connect_seconds_count {_upstream_connect_count}",
        "# HELP stream_upstream_connect_slow_total Upstream connects slower than "
        f"{_SLOW_CONNECT_S}s (DNS/CDN degradation signal).",
        "# TYPE stream_upstream_connect_slow_total counter",
        f"stream_upstream_connect_slow_total {_upstream_connect_slow}",
        "# HELP stream_bytes_total Bytes proxied to clients.",
        "# TYPE stream_bytes_total counter",
        f"stream_bytes_total {_stream_bytes}",
        "# HELP stream_active Streams currently being proxied.",
        "# TYPE stream_active gauge",
        f"stream_active {_stream_active}",
        "# HELP stream_errors_total Stream failures by upstream status or error class.",
        "# TYPE stream_errors_total counter",
    ]
    for code, n in sorted(_stream_errors.items()):
        lines.append(f'stream_errors_total{{code="{_esc(code)}"}} {n}')
    return "\n".join(lines) + "\n"

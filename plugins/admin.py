import html
import time
import datetime
import statistics
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, InputRichMessage
from pyrogram.enums import ButtonStyle

from tools import (
    redis_client, scan_keys, is_admin, get_user_token, revoke_user_token,
    get_user_request_count, set_user_request_count,
    get_failed_request_count, get_recent_errors
)

ADMIN_BOT_START_TIME = time.time()


def _get_readable_uptime(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d > 0:
        parts.append(f"{d}d")
    if h > 0:
        parts.append(f"{h}h")
    if m > 0:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


async def _resolve_username(client: Client, uid: str) -> str:
    """Try to resolve a Telegram user ID to a display name."""
    try:
        user = await client.get_users(int(uid))
        name = user.first_name or ""
        if user.last_name:
            name += f" {user.last_name}"
        return name.strip() or f"User {uid}"
    except Exception:
        return f"User {uid}"


async def _build_stats(client: Client, progress_callback=None):
    """Collect all stats data and return (message1_html, message2_html) tuple."""
    now = datetime.datetime.now(datetime.timezone.utc)

    if progress_callback:
        await progress_callback("Connecting to Redis cache database...")

    # ── User data ──────────────────────────────────────────
    user_keys = scan_keys("user_token:*")
    total_users = len(user_keys)

    if progress_callback:
        await progress_callback(f"Registered users loaded ({total_users:,} found). Scanning active sessions...")

    request_keys = scan_keys("user_requests:*")
    active_users = len(request_keys)

    total_requests_today = 0
    user_request_data = []
    request_counts = []

    for key in request_keys:
        try:
            count = int(redis_client.get(key) or 0)
            total_requests_today += count
            user_id_from_key = key.split(":")[1]
            user_request_data.append((user_id_from_key, count))
            request_counts.append(count)
        except Exception:
            continue

    user_request_data.sort(key=lambda x: x[1], reverse=True)

    # ── Admin / regular breakdown ──────────────────────────
    admin_count = 0
    admin_requests = 0
    regular_requests = 0
    admin_active = 0
    regular_active = 0

    for user_id_str, count in user_request_data:
        if is_admin(int(user_id_str)):
            admin_count += 1
            admin_requests += count
            admin_active += 1
        else:
            regular_requests += count
            regular_active += 1

    total_admin_count = sum(1 for k in user_keys if is_admin(int(k.split(":")[1])))
    regular_total = total_users - total_admin_count

    # ── Request analytics ──────────────────────────────────
    avg_requests = round(total_requests_today / max(active_users, 1), 2)
    median_requests = int(statistics.median(request_counts)) if request_counts else 0
    peak_requests = max(request_counts) if request_counts else 0
    min_requests = min(request_counts) if request_counts else 0

    # ── User activity tiers ────────────────────────────────
    heavy_users = sum(1 for c in request_counts if c >= 500)
    moderate_users = sum(1 for c in request_counts if 100 <= c < 500)
    light_users = sum(1 for c in request_counts if 10 <= c < 100)
    idle_users = sum(1 for c in request_counts if c < 10)
    inactive_users = total_users - active_users

    # ── New vs returning ───────────────────────────────────
    new_today = 0
    for key in user_keys:
        uid = key.split(":")[1]
        req_count = redis_client.get(f"user_requests:{uid}")
        if req_count is None:
            new_today += 1

    # ── Uptime ─────────────────────────────────────────────
    bot_uptime = _get_readable_uptime(int(time.time() - ADMIN_BOT_START_TIME))

    # ── Redis info ─────────────────────────────────────────
    redis_info = redis_client.info()
    redis_memory = redis_info.get('used_memory_human', 'N/A')
    redis_peak_memory = redis_info.get('used_memory_peak_human', 'N/A')
    redis_uptime = redis_info.get('uptime_in_seconds', 0)
    redis_uptime_str = _get_readable_uptime(redis_uptime)
    connected_clients = redis_info.get('connected_clients', 'N/A')
    ops_per_sec = redis_info.get('instantaneous_ops_per_sec', 'N/A')
    total_commands = redis_info.get('total_commands_processed', 'N/A')

    hits = redis_info.get('keyspace_hits', 0)
    misses = redis_info.get('keyspace_misses', 0)
    total_lookups = hits + misses
    hit_rate = round((hits / max(total_lookups, 1)) * 100, 1)

    total_keys = len(scan_keys('*'))

    user_utilization = round((active_users / max(total_users, 1)) * 100, 1)

    theoretical_max = (regular_active * 1000) + (admin_active * 10000) if active_users > 0 else 1
    capacity_usage = round((total_requests_today / theoretical_max) * 100, 1)

    if total_requests_today < 10000:
        load_indicator = "🟢 Low"
    elif total_requests_today < 50000:
        load_indicator = "🟡 Moderate"
    elif total_requests_today < 100000:
        load_indicator = "🟠 High"
    else:
        load_indicator = "🔴 Critical"

    # ── Failure analytics ──────────────────────────────────
    global_failed = int(redis_client.get("global_failed_total") or 0)

    status_keys = scan_keys("failed_by_status:*")
    status_breakdown = []
    for sk in status_keys:
        code = sk.split(":")[1]
        cnt = int(redis_client.get(sk) or 0)
        status_breakdown.append((code, cnt))
    status_breakdown.sort(key=lambda x: x[1], reverse=True)

    path_keys = scan_keys("failed_by_path:*")
    path_breakdown = []
    for pk in path_keys:
        path = pk.split(":", 1)[1]
        cnt = int(redis_client.get(pk) or 0)
        path_breakdown.append((path, cnt))
    path_breakdown.sort(key=lambda x: x[1], reverse=True)
    top_fail_paths = path_breakdown[:5]

    fail_user_keys = scan_keys("user_failed:*")
    user_fail_data = []
    for fk in fail_user_keys:
        uid = fk.split(":")[1]
        cnt = int(redis_client.get(fk) or 0)
        user_fail_data.append((uid, cnt))
    user_fail_data.sort(key=lambda x: x[1], reverse=True)
    top_fail_users = user_fail_data[:5]

    total_all = total_requests_today + global_failed
    success_rate = round(((total_all - global_failed) / max(total_all, 1)) * 100, 1)

    status_table_rows = "".join(f"<tr><td><code>{html.escape(code)}</code></td><td><b>{cnt:,}</b></td></tr>" for code, cnt in status_breakdown[:6]) or "<tr><td colspan='2'>None today ✨</td></tr>"
    path_table_rows = "".join(f"<tr><td><code>{html.escape(path)}</code></td><td><b>{cnt:,}</b></td></tr>" for path, cnt in top_fail_paths) or "<tr><td colspan='2'>None today ✨</td></tr>"

    fail_user_rows = []
    for idx, (uid, cnt) in enumerate(top_fail_users, 1):
        if progress_callback:
            await progress_callback(f"Resolving failed user identity {idx}/{len(top_fail_users)}...")
        name = await _resolve_username(client, uid)
        fail_user_rows.append(f"<tr><td><b>{html.escape(name)}</b> (<code>{uid}</code>)</td><td><b>{cnt:,}</b></td></tr>")
    fail_user_table_rows = "".join(fail_user_rows) or "<tr><td colspan='2'>None today ✨</td></tr>"

    # ── Top 10 users with names ────────────────────────────
    top_users = user_request_data[:10]
    top_users_rows = []
    for i, (uid, count) in enumerate(top_users, 1):
        admin_badge = "👑 Admin" if is_admin(int(uid)) else "👤 User"
        if progress_callback:
            await progress_callback(f"Resolving identity for active user {i}/{len(top_users)}...")
        name = await _resolve_username(client, uid)
        limit = 10000 if is_admin(int(uid)) else 1000
        pct = round((count / limit) * 100, 1)
        top_users_rows.append(
            f"<tr><td>{i}</td><td>{admin_badge} <b>{html.escape(name)}</b><br/><code>{uid}</code></td><td><b>{count:,}</b> / {limit:,}</td><td><b>{pct}%</b></td></tr>"
        )

    top_users_table = "".join(top_users_rows) or "<tr><td colspan='4'>No active users today</td></tr>"

    # ── Build Message 1: Overview ──────────────────────────
    msg1 = f"""<h1>Bot Statistics Dashboard</h1>
<blockquote>Generated: <b>{now.strftime('%Y-%m-%d %H:%M:%S')} UTC</b> | Bot Uptime: <code>{bot_uptime}</code></blockquote>

<h2>User Metrics</h2>
<table border="1">
  <tr><th>Metric</th><th>Count</th></tr>
  <tr><td><b>Total Registered</b></td><td>{total_users:,}</td></tr>
  <tr><td><b>Active Today</b></td><td>{active_users:,} ({user_utilization}%)</td></tr>
  <tr><td><b>Inactive Today</b></td><td>{inactive_users:,}</td></tr>
  <tr><td><b>New (0 Requests)</b></td><td>{new_today:,}</td></tr>
  <tr><td><b>Admin Users</b></td><td>{total_admin_count} ({admin_active} active)</td></tr>
  <tr><td><b>Regular Users</b></td><td>{regular_total:,} ({regular_active} active)</td></tr>
</table>

<h2>Request Analytics</h2>
<table border="1">
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td><b>Total Today</b></td><td><b>{total_requests_today:,}</b></td></tr>
  <tr><td><b>Admin Requests</b></td><td>{admin_requests:,}</td></tr>
  <tr><td><b>Regular Requests</b></td><td>{regular_requests:,}</td></tr>
  <tr><td><b>Avg / Active User</b></td><td>{avg_requests}</td></tr>
  <tr><td><b>Median / User</b></td><td>{median_requests}</td></tr>
  <tr><td><b>Peak Single User</b></td><td>{peak_requests:,}</td></tr>
  <tr><td><b>Capacity Used</b></td><td>{capacity_usage}%</td></tr>
</table>

<h2>Activity Tiers</h2>
<table border="1">
  <tr><th>Tier</th><th>Range</th><th>Users</th></tr>
  <tr><td>🔴 <b>Heavy</b></td><td>500+ req</td><td>{heavy_users}</td></tr>
  <tr><td>🟠 <b>Moderate</b></td><td>100–499 req</td><td>{moderate_users}</td></tr>
  <tr><td>🟢 <b>Light</b></td><td>10–99 req</td><td>{light_users}</td></tr>
  <tr><td>⚪ <b>Idle</b></td><td>&lt;10 req</td><td>{idle_users}</td></tr>
</table>

<h2>Failure Analytics</h2>
<table border="1">
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td><b>Total Failed</b></td><td><b>{global_failed:,}</b></td></tr>
  <tr><td><b>Success Rate</b></td><td><b>{success_rate}%</b></td></tr>
</table>

<details>
  <summary>Error Details &amp; Failing Endpoints</summary>
  <h3>By Status Code</h3>
  <table border="1">
    <tr><th>Status</th><th>Count</th></tr>
    {status_table_rows}
  </table>
  <h3>Top Failing Paths</h3>
  <table border="1">
    <tr><th>Path</th><th>Failures</th></tr>
    {path_table_rows}
  </table>
  <h3>Top Failing Users</h3>
  <table border="1">
    <tr><th>User</th><th>Failures</th></tr>
    {fail_user_table_rows}
  </table>
</details>"""

    # ── Build Message 2: Top Users + System ────────────────
    cmd_count_str = f"{total_commands:,}" if isinstance(total_commands, int) else str(total_commands)

    msg2 = f"""<h1>Top 10 Users Today</h1>
<table border="1">
  <tr><th>#</th><th>User</th><th>Requests</th><th>Quota</th></tr>
  {top_users_table}
</table>

<h2>Redis Infrastructure</h2>
<table border="1">
  <tr><th>Property</th><th>Status</th></tr>
  <tr><td><b>Used Memory</b></td><td>{redis_memory} (Peak: {redis_peak_memory})</td></tr>
  <tr><td><b>Redis Uptime</b></td><td>{redis_uptime_str}</td></tr>
  <tr><td><b>Clients</b></td><td>{connected_clients}</td></tr>
  <tr><td><b>Ops / Sec</b></td><td>{ops_per_sec}</td></tr>
  <tr><td><b>Commands</b></td><td>{cmd_count_str}</td></tr>
  <tr><td><b>Hit Rate</b></td><td>{hit_rate}% ({hits:,} hits / {misses:,} misses)</td></tr>
  <tr><td><b>Total Keys</b></td><td>{total_keys:,}</td></tr>
</table>

<h2>System Health &amp; Rate Limits</h2>
<table border="1">
  <tr><th>Configuration</th><th>Value</th></tr>
  <tr><td><b>Regular Limit</b></td><td>1,000 req/day</td></tr>
  <tr><td><b>Admin Limit</b></td><td>10,000 req/day</td></tr>
  <tr><td><b>Search API</b></td><td>Unlimited</td></tr>
  <tr><td><b>System Load</b></td><td>{load_indicator}</td></tr>
  <tr><td><b>Active Ratio</b></td><td>{user_utilization}%</td></tr>
  <tr><td><b>Cache Status</b></td><td><b>Operational</b></td></tr>
</table>"""

    return msg1, msg2


@Client.on_message(filters.command("stats") & filters.private)
async def bot_stats(client: Client, message: Message):
    user_id = message.from_user.id

    if not is_admin(user_id):
        await client.send_rich_message(
            chat_id=message.chat.id,
            receiver_user_id=user_id,
            rich_message=InputRichMessage(html="<blockquote>❌ <b>Access Denied:</b> You don't have admin privileges.</blockquote>")
        )
        return

    chat_id = message.chat.id
    draft_id = client.rnd_id()

    try:
        async def progress(text):
            await client.send_rich_message_draft(
                chat_id=chat_id,
                draft_id=draft_id,
                rich_message=InputRichMessage(html=f"<blockquote>⚡ <b>Compiling Statistics...</b><br/>{html.escape(text)}</blockquote>")
            )

        # Initial draft
        await progress("Scanning Redis database structure...")

        msg1_html, msg2_html = await _build_stats(client, progress_callback=progress)

        # Send dashboard parts
        await client.send_rich_message(
            chat_id=chat_id,
            rich_message=InputRichMessage(html=msg1_html)
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin_refresh_stats", style=ButtonStyle.PRIMARY)],
        ])
        await client.send_rich_message(
            chat_id=chat_id,
            rich_message=InputRichMessage(html=msg2_html),
            reply_markup=keyboard
        )

    except Exception as e:
        await client.send_rich_message(
            chat_id=chat_id,
            rich_message=InputRichMessage(html=f"<blockquote>❌ <b>Error retrieving stats:</b> {html.escape(str(e))}</blockquote>")
        )


@Client.on_message(filters.regex(r"^/user \d+") & filters.private)
async def user_info(client: Client, message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await client.send_rich_message(
            chat_id=message.chat.id,
            receiver_user_id=user_id,
            rich_message=InputRichMessage(html="<blockquote>❌ <b>Access Denied:</b> Admin privileges required.</blockquote>")
        )
        return
    
    try:
        target_user_id = message.text.split()[1]
        token = await get_user_token(target_user_id)
        request_count = await get_user_request_count(target_user_id)
        failed_count = await get_failed_request_count(target_user_id)
        
        if token:
            total = request_count + failed_count
            success_rate = round((request_count / max(total, 1)) * 100, 1)
            limit = 10000 if is_admin(int(target_user_id)) else 1000
            remaining = max(0, limit - request_count)
            is_adm = "Yes (10,000 req/day)" if is_admin(int(target_user_id)) else "No (1,000 req/day)"

            content_html = f"""<h1>User Information</h1>
<blockquote>Account profile and activity metrics for user <code>{target_user_id}</code>.</blockquote>

<table border="1">
  <tr><th>Field</th><th>Value</th></tr>
  <tr><td><b>User ID</b></td><td><code>{target_user_id}</code></td></tr>
  <tr><td><b>Token</b></td><td><code>{token}</code></td></tr>
  <tr><td><b>Admin Status</b></td><td>{is_adm}</td></tr>
</table>

<h2>Usage Summary</h2>
<table border="1">
  <tr><th>Metric</th><th>Count</th></tr>
  <tr><td><b>Successful Requests</b></td><td><b>{request_count:,}</b> / {limit:,}</td></tr>
  <tr><td><b>Failed Requests</b></td><td><b>{failed_count:,}</b></td></tr>
  <tr><td><b>Total Requests</b></td><td><b>{total:,}</b></td></tr>
  <tr><td><b>Success Rate</b></td><td><b>{success_rate}%</b></td></tr>
  <tr><td><b>Remaining Quota</b></td><td><b>{remaining:,}</b></td></tr>
</table>"""

            await client.send_rich_message(
                chat_id=message.chat.id,
                rich_message=InputRichMessage(html=content_html)
            )
        else:
            await client.send_rich_message(
                chat_id=message.chat.id,
                rich_message=InputRichMessage(html=f"<blockquote>❌ <b>Not Found:</b> User <code>{target_user_id}</code> has no registered token.</blockquote>")
            )
    except Exception as e:
        await client.send_rich_message(
            chat_id=message.chat.id,
            rich_message=InputRichMessage(html=f"<blockquote>❌ <b>Error:</b> {html.escape(str(e))}</blockquote>")
        )


@Client.on_message(filters.regex(r"^/grant \d+ \d+") & filters.private)
async def grant_requests(client: Client, message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await client.send_rich_message(
            chat_id=message.chat.id,
            receiver_user_id=user_id,
            rich_message=InputRichMessage(html="<blockquote>❌ <b>Access Denied:</b> Admin privileges required.</blockquote>")
        )
        return
    
    try:
        _, target_user_id, amount = message.text.split()
        target_user_id = int(target_user_id)
        amount = int(amount)
        
        current_count = await get_user_request_count(target_user_id)
        new_count = max(0, current_count - amount)  # Reduce count to grant more requests
        await set_user_request_count(target_user_id, new_count)
        
        content_html = f"""<h1>Request Quota Granted</h1>
<blockquote>Successfully credited extra API requests to user <code>{target_user_id}</code>.</blockquote>

<table border="1">
  <tr><th>Parameter</th><th>Detail</th></tr>
  <tr><td><b>User ID</b></td><td><code>{target_user_id}</code></td></tr>
  <tr><td><b>Granted Bonus</b></td><td><b>+{amount:,}</b> requests</td></tr>
  <tr><td><b>Previous Used Count</b></td><td>{current_count:,}</td></tr>
  <tr><td><b>Adjusted Used Count</b></td><td><b>{new_count:,}</b></td></tr>
</table>"""

        await client.send_rich_message(
            chat_id=message.chat.id,
            rich_message=InputRichMessage(html=content_html)
        )
    except Exception as e:
        await client.send_rich_message(
            chat_id=message.chat.id,
            rich_message=InputRichMessage(html=f"<blockquote>❌ <b>Error:</b> {html.escape(str(e))}</blockquote>")
        )


@Client.on_message(filters.regex(r"^/revoke \d+") & filters.private)
async def revoke_token(client: Client, message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await client.send_rich_message(
            chat_id=message.chat.id,
            receiver_user_id=user_id,
            rich_message=InputRichMessage(html="<blockquote>❌ <b>Access Denied:</b> Admin privileges required.</blockquote>")
        )
        return
    
    try:
        target_user_id = int(message.text.split()[1])
        await revoke_user_token(target_user_id)
        content_html = f"""<h1>Token Revoked</h1>
<blockquote>✅ API token for user <code>{target_user_id}</code> has been revoked and deleted from the database.</blockquote>"""

        await client.send_rich_message(
            chat_id=message.chat.id,
            rich_message=InputRichMessage(html=content_html)
        )
    except Exception as e:
        await client.send_rich_message(
            chat_id=message.chat.id,
            rich_message=InputRichMessage(html=f"<blockquote>❌ <b>Error:</b> {html.escape(str(e))}</blockquote>")
        )


@Client.on_message(filters.command("listusers") & filters.private)
async def list_users(client: Client, message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await client.send_rich_message(
            chat_id=message.chat.id,
            receiver_user_id=user_id,
            rich_message=InputRichMessage(html="<blockquote>❌ <b>Access Denied:</b> Admin privileges required.</blockquote>")
        )
        return
    
    user_keys = scan_keys("user_token:*")
    rows = []
    
    for key in user_keys[:20]:  # Show last 20 users
        user_id_key = key.split(":")[1]
        request_count = redis_client.get(f"user_requests:{user_id_key}") or "0"
        rows.append(f"<tr><td><code>{user_id_key}</code></td><td><b>{int(request_count):,}</b></td></tr>")
    
    table_rows = "".join(rows) or "<tr><td colspan='2'>No users found</td></tr>"
    
    content_html = f"""<h1>Recent Registered Users</h1>
<blockquote>Displaying up to 20 registered users and their daily request counts.</blockquote>

<table border="1">
  <tr><th>User ID</th><th>Requests Today</th></tr>
  {table_rows}
</table>"""

    await client.send_rich_message(
        chat_id=message.chat.id,
        rich_message=InputRichMessage(html=content_html)
    )


@Client.on_message(filters.command("adminhelp") & filters.private)
async def admin_help(client: Client, message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await client.send_rich_message(
            chat_id=message.chat.id,
            receiver_user_id=user_id,
            rich_message=InputRichMessage(html="<blockquote>❌ <b>Access Denied:</b> Admin privileges required.</blockquote>")
        )
        return
    
    content_html = """<h1>Admin Control Panel</h1>
<blockquote>Administrative commands for maintenance, telemetry, and quota control.</blockquote>

<h2>Command Reference</h2>
<table border="1">
  <tr><th>Command</th><th>Purpose</th></tr>
  <tr><td><code>/stats</code></td><td>View interactive bot and server statistics</td></tr>
  <tr><td><code>/errors [n]</code></td><td>View recent API error logs (default 15)</td></tr>
  <tr><td><code>/user &lt;id&gt;</code></td><td>Query user quota, token, and error counts</td></tr>
  <tr><td><code>/grant &lt;id&gt; &lt;qty&gt;</code></td><td>Credit extra requests to a user</td></tr>
  <tr><td><code>/revoke &lt;id&gt;</code></td><td>Forcefully revoke a user's API token</td></tr>
  <tr><td><code>/listusers</code></td><td>List recent registered users</td></tr>
  <tr><td><code>/broadcast</code></td><td>Broadcast a replied message to all users</td></tr>
</table>

<details>
  <summary>Command Examples</summary>
  <pre><code>/user 123456789
/grant 123456789 500
/revoke 123456789
/errors 30</code></pre>
</details>"""

    await client.send_rich_message(
        chat_id=message.chat.id,
        rich_message=InputRichMessage(html=content_html)
    )


@Client.on_message(filters.command("errors") & filters.private)
async def errors_command(client: Client, message: Message):
    """Show recent API error log with full error messages."""
    user_id = message.from_user.id

    if not is_admin(user_id):
        await client.send_rich_message(
            chat_id=message.chat.id,
            receiver_user_id=user_id,
            rich_message=InputRichMessage(html="<blockquote>❌ <b>Access Denied:</b> Admin privileges required.</blockquote>")
        )
        return

    parts = message.text.split()
    try:
        count = min(int(parts[1]), 50) if len(parts) > 1 else 15
    except ValueError:
        count = 15

    try:
        errors = await get_recent_errors(count)

        if not errors:
            await client.send_rich_message(
                chat_id=message.chat.id,
                rich_message=InputRichMessage(html="<h1>Recent Error Log</h1><blockquote>✅ <b>No errors logged yet!</b> Everything is running clean.</blockquote>")
            )
            return

        header = f"<h1>Recent API Error Log ({len(errors)})</h1><blockquote>Displaying latest error entries recorded by the API.</blockquote>"
        
        cards = []
        for i, entry in enumerate(errors, 1):
            ts = html.escape(str(entry.get("ts", "?")))
            uid = html.escape(str(entry.get("user", "?")))
            status = html.escape(str(entry.get("status", "?")))
            path = html.escape(str(entry.get("path", "?")))
            error = html.escape(str(entry.get("error", "No message")))

            if len(error) > 150:
                error = error[:147] + "..."

            card = f"""<table border="1">
  <tr><th>#</th><th>Timestamp</th><th>User</th><th>Status</th><th>Path</th></tr>
  <tr><td>{i}</td><td>{ts}</td><td><code>{uid}</code></td><td><code>{status}</code></td><td><code>{path}</code></td></tr>
</table>
<blockquote>💬 {error}</blockquote>"""
            cards.append(card)

        # Telegram length limit safety
        messages = []
        current = header
        for card in cards:
            if len(current) + len(card) > 3600:
                messages.append(current)
                current = ""
            current += "\n" + card
        if current:
            messages.append(current)

        for msg_html in messages:
            await client.send_rich_message(
                chat_id=message.chat.id,
                rich_message=InputRichMessage(html=msg_html)
            )

    except Exception as e:
        await client.send_rich_message(
            chat_id=message.chat.id,
            rich_message=InputRichMessage(html=f"<blockquote>❌ <b>Error fetching logs:</b> {html.escape(str(e))}</blockquote>")
        )

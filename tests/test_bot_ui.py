import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pyrogram.types import InputRichMessage, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, User, Chat
from pyrogram.enums import ButtonStyle, ChatType
from pyrogram.errors import BadRequest

import plugins.commands as commands_plugin
import plugins.status as status_plugin
import plugins.admin as admin_plugin
import plugins.broadcast as broadcast_plugin


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.rnd_id.return_value = 12345
    client.send_rich_message = AsyncMock(return_value=MagicMock(spec=Message))
    client.send_rich_message_draft = AsyncMock(return_value=True)
    client.send_message = AsyncMock(return_value=MagicMock(spec=Message))
    client.send_message_draft = AsyncMock(return_value=True)
    client.get_users = AsyncMock(return_value=MagicMock(first_name="TestUser", last_name=None))
    return client


@pytest.fixture
def mock_message():
    msg = MagicMock(spec=Message)
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = 1001
    msg.chat.type = ChatType.PRIVATE
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = 123456
    msg.from_user.username = "testuser"
    msg.from_user.first_name = "Test"
    msg.text = ""
    msg.reply_text = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_start_command_existing_token(mock_client, mock_message):
    with patch("plugins.commands.get_user_token", new_callable=AsyncMock) as mock_get_token:
        mock_get_token.return_value = "abc123token"
        await commands_plugin.start_command(mock_client, mock_message)

        assert mock_client.send_rich_message.called
        call_kwargs = mock_client.send_rich_message.call_args[1]
        assert call_kwargs["chat_id"] == 1001
        assert call_kwargs.get("receiver_user_id") is None
        rich_msg = call_kwargs["rich_message"]
        assert isinstance(rich_msg, InputRichMessage)
        assert "<h1>Welcome back" in rich_msg.html
        assert "abc123token" in rich_msg.html
        assert "<table border=\"1\">" in rich_msg.html
        assert isinstance(call_kwargs["reply_markup"], InlineKeyboardMarkup)


@pytest.mark.asyncio
async def test_start_command_group_ephemeral(mock_client, mock_message):
    mock_message.chat.type = ChatType.SUPERGROUP
    with patch("plugins.commands.get_user_token", new_callable=AsyncMock) as mock_get_token:
        mock_get_token.return_value = "secretgroupkey123"
        await commands_plugin.start_command(mock_client, mock_message)

        assert mock_client.send_rich_message.called
        call_kwargs = mock_client.send_rich_message.call_args[1]
        assert call_kwargs["receiver_user_id"] == mock_message.from_user.id
        rich_msg = call_kwargs["rich_message"]
        assert "secretgroupkey123" in rich_msg.html
        assert "Ephemeral Message" in rich_msg.html


@pytest.mark.asyncio
async def test_start_command_group_bot_not_admin_fallback(mock_client, mock_message):
    mock_message.chat.type = ChatType.SUPERGROUP
    # Simulate Telegram raising BadRequest BOT_NOT_ADMIN on first ephemeral call
    mock_client.send_rich_message.side_effect = [
        BadRequest("[400 Bad Request] - [400 BOT_NOT_ADMIN] (caused by ephemeral.SendMessage)"),
        MagicMock(spec=Message)
    ]
    with patch("plugins.commands.get_user_token", new_callable=AsyncMock) as mock_get_token:
        mock_get_token.return_value = "secretgroupkey123"
        await commands_plugin.start_command(mock_client, mock_message)

        assert mock_client.send_rich_message.call_count == 2
        # The second call is the fallback without receiver_user_id and with masked token
        fallback_call_kwargs = mock_client.send_rich_message.call_args_list[1][1]
        assert fallback_call_kwargs.get("receiver_user_id") is None
        rich_msg = fallback_call_kwargs["rich_message"]
        assert "secr*************" in rich_msg.html or "secr" in rich_msg.html
        assert "Token is masked" in rich_msg.html


@pytest.mark.asyncio
async def test_start_command_new_token(mock_client, mock_message):
    with patch("plugins.commands.get_user_token", new_callable=AsyncMock) as mock_get_token, \
         patch("plugins.commands.set_user_token", new_callable=AsyncMock) as mock_set_token:
        mock_get_token.return_value = None
        await commands_plugin.start_command(mock_client, mock_message)

        assert mock_set_token.called
        assert mock_client.send_rich_message.called
        rich_msg = mock_client.send_rich_message.call_args[1]["rich_message"]
        assert "<h1>Welcome to YT-DLP API" in rich_msg.html
        assert "<table border=\"1\">" in rich_msg.html


@pytest.mark.asyncio
async def test_menu_command(mock_client, mock_message):
    await commands_plugin.menu_command(mock_client, mock_message)
    assert mock_client.send_rich_message.called
    rich_msg = mock_client.send_rich_message.call_args[1]["rich_message"]
    assert "<h1>YT-DLP API Bot Menu</h1>" in rich_msg.html
    assert "<table border=\"1\">" in rich_msg.html


@pytest.mark.asyncio
async def test_ping_command(mock_client, mock_message):
    await commands_plugin.ping_command(mock_client, mock_message)
    assert mock_client.send_rich_message_draft.called
    assert mock_client.send_rich_message.called
    rich_msg = mock_client.send_rich_message.call_args[1]["rich_message"]
    assert "<h1>🏓 Pong!</h1>" in rich_msg.html
    assert "<table border=\"1\">" in rich_msg.html


@pytest.mark.asyncio
async def test_callbacks_api_implementation(mock_client):
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(id=123456)
    cb.data = "api_implementation"
    cb.chat = MagicMock(type=ChatType.PRIVATE)
    cb.message = MagicMock(chat=cb.chat)
    cb.answer = AsyncMock()
    cb.edit_message_text = AsyncMock()

    with patch("plugins.commands.get_user_token", new_callable=AsyncMock) as mock_get_token:
        mock_get_token.return_value = "mytoken123"
        await commands_plugin.handle_callbacks(mock_client, cb)

        assert cb.answer.called
        assert cb.edit_message_text.called
        rich_msg = cb.edit_message_text.call_args[1]["rich_message"]
        assert "<h1>API Implementation Guide</h1>" in rich_msg.html
        assert "mytoken123" in rich_msg.html


@pytest.mark.asyncio
async def test_callbacks_usage_status(mock_client):
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(id=123456)
    cb.data = "usage_status"
    cb.chat = MagicMock(type=ChatType.PRIVATE)
    cb.message = MagicMock(chat=cb.chat)
    cb.answer = AsyncMock()
    cb.edit_message_text = AsyncMock()

    with patch("plugins.commands.get_user_token", new_callable=AsyncMock) as mock_get_token, \
         patch("plugins.commands.get_user_request_count", new_callable=AsyncMock) as mock_req_count:
        mock_get_token.return_value = "mytoken123"
        mock_req_count.return_value = 42
        await commands_plugin.handle_callbacks(mock_client, cb)

        assert cb.answer.called
        assert cb.edit_message_text.called
        rich_msg = cb.edit_message_text.call_args[1]["rich_message"]
        assert "<h1>Usage Statistics</h1>" in rich_msg.html
        assert "<table border=\"1\">" in rich_msg.html


@pytest.mark.asyncio
async def test_callbacks_view_token_group_ephemeral(mock_client):
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(id=123456)
    cb.data = "view_token"
    cb.chat = MagicMock(type=ChatType.SUPERGROUP)
    cb.message = MagicMock(chat=cb.chat)
    cb.message.chat.id = -100998877
    cb.answer = AsyncMock()

    with patch("plugins.commands.get_user_token", new_callable=AsyncMock) as mock_get_token:
        mock_get_token.return_value = "my_ephemeral_token_xyz"
        await commands_plugin.handle_callbacks(mock_client, cb)

        assert mock_client.send_rich_message.called
        call_kwargs = mock_client.send_rich_message.call_args[1]
        assert call_kwargs["receiver_user_id"] == 123456
        assert "my_ephemeral_token_xyz" in call_kwargs["rich_message"].html


@pytest.mark.asyncio
async def test_callbacks_view_token_group_bot_not_admin_fallback(mock_client):
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(id=123456)
    cb.data = "view_token"
    cb.chat = MagicMock(type=ChatType.SUPERGROUP)
    cb.message = MagicMock(chat=cb.chat)
    cb.message.chat.id = -100998877
    cb.answer = AsyncMock()
    mock_client.send_rich_message.side_effect = BadRequest("[400 BOT_NOT_ADMIN]")

    with patch("plugins.commands.get_user_token", new_callable=AsyncMock) as mock_get_token:
        mock_get_token.return_value = "my_ephemeral_token_xyz"
        await commands_plugin.handle_callbacks(mock_client, cb)

        assert cb.answer.called
        assert "my_ephemeral_token_xyz" in cb.answer.call_args[0][0]
        assert cb.answer.call_args[1]["show_alert"] is True


@pytest.mark.asyncio
async def test_callbacks_revoke_and_confirm(mock_client):
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(id=123456)
    cb.chat = MagicMock(type=ChatType.PRIVATE)
    cb.message = MagicMock(chat=cb.chat)
    cb.answer = AsyncMock()
    cb.edit_message_text = AsyncMock()

    # Step 1: Revoke request dialog
    cb.data = "revoke_token"
    await commands_plugin.handle_callbacks(mock_client, cb)
    assert "<h1>Revoke API Token</h1>" in cb.edit_message_text.call_args[1]["rich_message"].html

    # Step 2: Confirm revoke
    cb.data = "confirm_revoke"
    with patch("plugins.commands.revoke_user_token", new_callable=AsyncMock) as mock_revoke, \
         patch("plugins.commands.set_user_token", new_callable=AsyncMock) as mock_set:
        await commands_plugin.handle_callbacks(mock_client, cb)
        assert mock_revoke.called
        assert mock_set.called
        assert "<h1>Token Revoked Successfully</h1>" in cb.edit_message_text.call_args[1]["rich_message"].html


@pytest.mark.asyncio
async def test_callbacks_docs_and_endpoints(mock_client):
    cb = MagicMock(spec=CallbackQuery)
    cb.from_user = MagicMock(id=123456)
    cb.chat = MagicMock(type=ChatType.PRIVATE)
    cb.message = MagicMock(chat=cb.chat)
    cb.answer = AsyncMock()
    cb.edit_message_text = AsyncMock()

    doc_routes = [
        ("help", "<h1>Help &amp; Documentation</h1>"),
        ("api_docs", "<h1>API Documentation</h1>"),
        ("api_info", "<h1>Video Info Endpoint</h1>"),
        ("api_info_get", "<h1>Video Info — GET Examples</h1>"),
        ("api_info_python", "<h1>Video Info — Python Code</h1>"),
        ("api_search", "<h1>Search Endpoint (Free)</h1>"),
        ("api_search_get", "<h1>Search — GET Examples</h1>"),
        ("api_search_python", "<h1>Search — Python Implementation</h1>"),
        ("api_ratelimit", "<h1>Rate Limit Status Endpoint</h1>"),
        ("api_ratelimit_get", "<h1>Rate Limit — GET Examples</h1>"),
        ("api_ratelimit_python", "<h1>Rate Limit — Python Example</h1>"),
        ("api_health", "<h1>Health Check Endpoint</h1>"),
        ("api_health_get", "<h1>Health Probe — GET Examples</h1>"),
        ("api_health_python", "<h1>Health Check — Python Example</h1>"),
        ("impl_get_all", "<h1>GET Endpoint Examples</h1>"),
        ("impl_python_all", "<h1>Python Implementation (Part 1)</h1>"),
        ("impl_python_part2", "<h1>Python Implementation (Part 2)</h1>"),
        ("impl_python_examples", "<h1>Python Usage Examples</h1>"),
        ("impl_python_advanced", "<h1>Advanced Batching &amp; Fallbacks</h1>"),
        ("impl_python_errors", "<h1>Error Handling &amp; Best Practices</h1>"),
        ("impl_quick_ref", "<h1>Quick Reference Guide</h1>"),
        ("back_menu", "<h1>YT-DLP API Bot Menu</h1>"),
    ]

    with patch("plugins.commands.get_user_token", new_callable=AsyncMock) as mock_tok:
        mock_tok.return_value = "disp_tok_123"
        for route, expected_title in doc_routes:
            cb.data = route
            await commands_plugin.handle_callbacks(mock_client, cb)
            html_content = cb.edit_message_text.call_args[1]["rich_message"].html
            assert expected_title in html_content, f"Failed for route {route}"


@pytest.mark.asyncio
async def test_status_command_group_ephemeral(mock_client, mock_message):
    mock_message.chat.type = ChatType.SUPERGROUP
    with patch("plugins.status.get_user_token", new_callable=AsyncMock) as mock_get_token, \
         patch("plugins.status.get_user_request_count", new_callable=AsyncMock) as mock_req_count:
        mock_get_token.return_value = "mytoken123"
        mock_req_count.return_value = 10
        await status_plugin.status_command(mock_client, mock_message)

        assert mock_client.send_rich_message.called
        call_kwargs = mock_client.send_rich_message.call_args[1]
        assert call_kwargs["receiver_user_id"] == mock_message.from_user.id
        rich_msg = call_kwargs["rich_message"]
        assert "<h1>Usage Status</h1>" in rich_msg.html
        assert "mytoken123" in rich_msg.html
        assert "Ephemeral Message" in rich_msg.html


@pytest.mark.asyncio
async def test_token_command_group_ephemeral(mock_client, mock_message):
    mock_message.chat.type = ChatType.GROUP
    with patch("plugins.status.get_user_token", new_callable=AsyncMock) as mock_get_token:
        mock_get_token.return_value = "group_token_123"
        await status_plugin.token_command(mock_client, mock_message)

        assert mock_client.send_rich_message.called
        call_kwargs = mock_client.send_rich_message.call_args[1]
        assert call_kwargs["receiver_user_id"] == mock_message.from_user.id
        rich_msg = call_kwargs["rich_message"]
        assert "<h1>Your API Token</h1>" in rich_msg.html
        assert "group_token_123" in rich_msg.html
        assert "Ephemeral Message" in rich_msg.html


@pytest.mark.asyncio
async def test_admin_stats_authorized(mock_client, mock_message):
    with patch("plugins.admin.is_admin", return_value=True), \
         patch("plugins.admin._build_stats", new_callable=AsyncMock) as mock_build:
        mock_build.return_value = ("<h1>Dashboard 1</h1>", "<h1>Dashboard 2</h1>")
        await admin_plugin.bot_stats(mock_client, mock_message)

        assert mock_client.send_rich_message_draft.called
        assert mock_client.send_rich_message.call_count >= 2
        calls = mock_client.send_rich_message.call_args_list
        assert "<h1>Dashboard 1</h1>" in calls[0][1]["rich_message"].html
        assert "<h1>Dashboard 2</h1>" in calls[1][1]["rich_message"].html


@pytest.mark.asyncio
async def test_admin_user_info(mock_client, mock_message):
    mock_message.text = "/user 999888"
    with patch("plugins.admin.is_admin", return_value=True), \
         patch("plugins.admin.get_user_token", new_callable=AsyncMock) as mock_tok, \
         patch("plugins.admin.get_user_request_count", new_callable=AsyncMock) as mock_req, \
         patch("plugins.admin.get_failed_request_count", new_callable=AsyncMock) as mock_fail:
        mock_tok.return_value = "user_tok_xyz"
        mock_req.return_value = 100
        mock_fail.return_value = 2

        await admin_plugin.user_info(mock_client, mock_message)
        assert mock_client.send_rich_message.called
        rich_msg = mock_client.send_rich_message.call_args[1]["rich_message"]
        assert "<h1>User Information</h1>" in rich_msg.html
        assert "999888" in rich_msg.html
        assert "user_tok_xyz" in rich_msg.html


@pytest.mark.asyncio
async def test_admin_grant_and_revoke(mock_client, mock_message):
    # Grant
    mock_message.text = "/grant 999888 500"
    with patch("plugins.admin.is_admin", return_value=True), \
         patch("plugins.admin.get_user_request_count", new_callable=AsyncMock) as mock_req, \
         patch("plugins.admin.set_user_request_count", new_callable=AsyncMock) as mock_set:
        mock_req.return_value = 600
        await admin_plugin.grant_requests(mock_client, mock_message)
        assert mock_client.send_rich_message.called
        rich_msg = mock_client.send_rich_message.call_args[1]["rich_message"]
        assert "<h1>Request Quota Granted</h1>" in rich_msg.html
        assert mock_set.called

    # Revoke
    mock_message.text = "/revoke 999888"
    with patch("plugins.admin.is_admin", return_value=True), \
         patch("plugins.admin.revoke_user_token", new_callable=AsyncMock) as mock_rev:
        await admin_plugin.revoke_token(mock_client, mock_message)
        assert mock_client.send_rich_message.called
        rich_msg = mock_client.send_rich_message.call_args[1]["rich_message"]
        assert "<h1>Token Revoked</h1>" in rich_msg.html
        assert mock_rev.called


@pytest.mark.asyncio
async def test_admin_listusers_and_help(mock_client, mock_message):
    with patch("plugins.admin.is_admin", return_value=True), \
         patch("plugins.admin.scan_keys", return_value=["user_token:123", "user_token:456"]), \
         patch("plugins.admin.redis_client.get", return_value="25"):
        await admin_plugin.list_users(mock_client, mock_message)
        assert mock_client.send_rich_message.called
        rich_msg = mock_client.send_rich_message.call_args[1]["rich_message"]
        assert "<h1>Recent Registered Users</h1>" in rich_msg.html
        assert "123" in rich_msg.html

    with patch("plugins.admin.is_admin", return_value=True):
        await admin_plugin.admin_help(mock_client, mock_message)
        assert mock_client.send_rich_message.called
        rich_msg = mock_client.send_rich_message.call_args[1]["rich_message"]
        assert "<h1>Admin Control Panel</h1>" in rich_msg.html


@pytest.mark.asyncio
async def test_admin_errors_command(mock_client, mock_message):
    mock_message.text = "/errors 10"
    sample_errors = [
        {"ts": "2026-08-22 12:00:00", "user": "123", "status": 404, "path": "/info", "error": "Video not found"}
    ]
    with patch("plugins.admin.is_admin", return_value=True), \
         patch("plugins.admin.get_recent_errors", new_callable=AsyncMock) as mock_errs:
        mock_errs.return_value = sample_errors
        await admin_plugin.errors_command(mock_client, mock_message)
        assert mock_client.send_rich_message.called
        rich_msg = mock_client.send_rich_message.call_args[1]["rich_message"]
        assert "<h1>Recent API Error Log" in rich_msg.html
        assert "Video not found" in rich_msg.html


@pytest.mark.asyncio
async def test_broadcast_flow(mock_client, mock_message):
    mock_message.reply_to_message = MagicMock(text="Hello everyone!", photo=None, video=None, document=None)
    mock_message.text = "/broadcast"
    with patch("plugins.broadcast.is_admin", return_value=True), \
         patch("plugins.broadcast.scan_keys", return_value=["user_token:111", "user_token:222"]), \
         patch.object(mock_client, "forward_messages", new_callable=AsyncMock) as mock_fwd:
        await broadcast_plugin.broadcast_command(mock_client, mock_message)
        assert mock_client.send_rich_message_draft.called
        assert mock_fwd.call_count == 2
        assert mock_client.send_rich_message.called
        rich_msg = mock_client.send_rich_message.call_args[1]["rich_message"]
        assert "<h1>📢 Broadcast Completed</h1>" in rich_msg.html

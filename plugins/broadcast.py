import html
from pyrogram import Client, filters
from pyrogram.types import Message, InputRichMessage

from tools import redis_client, scan_keys, is_admin

@Client.on_message(filters.command("broadcast") & filters.private)
async def broadcast_command(client: Client, message: Message):
    user_id = message.from_user.id
    
    # Check if user is admin
    if not is_admin(user_id):
        await client.send_rich_message(
            chat_id=message.chat.id,
            receiver_user_id=user_id,
            rich_message=InputRichMessage(html="<blockquote>❌ <b>Access Denied:</b> Admin privileges required.</blockquote>")
        )
        return
    
    # Check if this is a reply to a message
    if not message.reply_to_message:
        content_html = """<h1>📢 Broadcast Command</h1>
<blockquote>Please reply to the message you want to broadcast to all registered bot users.</blockquote>

<table border="1">
  <tr><th>Option</th><th>Effect</th></tr>
  <tr><td><code>/broadcast</code></td><td>Forward with original author header</td></tr>
  <tr><td><code>/broadcast -f</code></td><td>Copy message content without author header</td></tr>
</table>

<details>
  <summary>Broadcast Instructions</summary>
  <p>1. Send or forward any text, photo, video, or document to this chat.<br/>
  2. Reply to that message with <code>/broadcast</code> or <code>/broadcast -f</code>.<br/>
  3. Real-time progress will stream via draft updates until delivery completes.</p>
</details>"""
        await client.send_rich_message(
            chat_id=message.chat.id,
            rich_message=InputRichMessage(html=content_html)
        )
        return
    
    try:
        # Check for -f flag to drop author
        command_parts = message.text.split()
        drop_author = "-f" in command_parts
        
        # Get all user IDs from Redis
        user_keys = scan_keys("user_token:*")
        stored_user_ids = [int(key.split(":")[1]) for key in user_keys]
        total_users = len(stored_user_ids)
        
        if total_users == 0:
            await client.send_rich_message(
                chat_id=message.chat.id,
                rich_message=InputRichMessage(html="<h1>Broadcast</h1><blockquote>❌ No registered users found in the database.</blockquote>")
            )
            return
        
        # Send initial status message using streaming rich draft
        draft_id = client.rnd_id()
        drop_label = "Yes (-f)" if drop_author else "No (Forward)"
        await client.send_rich_message_draft(
            chat_id=message.chat.id,
            draft_id=draft_id,
            rich_message=InputRichMessage(html=f"""<blockquote>📢 <b>Broadcast Initialized</b><br/>
👥 Targets: <b>{total_users:,}</b> registered users<br/>
📝 Drop Author: <b>{drop_label}</b></blockquote>""")
        )
        
        reply_message = message.reply_to_message
        sent_count = 0
        failed_count = 0
        removed_users = 0
        
        for user_id_target in stored_user_ids:
            try:
                if drop_author:
                    # Send as copy without forwarding (drops author info)
                    if reply_message.text:
                        await client.send_message(user_id_target, reply_message.text)
                    elif reply_message.photo:
                        await client.send_photo(
                            user_id_target, 
                            reply_message.photo.file_id,
                            caption=reply_message.caption or ""
                        )
                    elif reply_message.video:
                        await client.send_video(
                            user_id_target,
                            reply_message.video.file_id,
                            caption=reply_message.caption or ""
                        )
                    elif reply_message.document:
                        await client.send_document(
                            user_id_target,
                            reply_message.document.file_id,
                            caption=reply_message.caption or ""
                        )
                    else:
                        # For other message types, forward normally
                        await client.forward_messages(user_id_target, message.chat.id, reply_message.id)
                else:
                    # Forward with author info
                    await client.forward_messages(user_id_target, message.chat.id, reply_message.id)
                
                sent_count += 1
                
                # Update status progress using native send_rich_message_draft
                if sent_count % 10 == 0 or sent_count == total_users:
                    await client.send_rich_message_draft(
                        chat_id=message.chat.id,
                        draft_id=draft_id,
                        rich_message=InputRichMessage(html=f"""<blockquote>📢 <b>Broadcast Progress</b><br/>
✅ Delivered: <b>{sent_count:,}</b> / {total_users:,}<br/>
❌ Failed: <b>{failed_count:,}</b><br/>
🗑 Removed Inactive: <b>{removed_users:,}</b><br/>
⏳ Transmission in progress...</blockquote>""")
                    )
                
            except Exception as e:
                error_str = str(e).lower()
                
                # Check if user is unreachable/blocked the bot
                if any(keyword in error_str for keyword in ["user not found", "blocked", "forbidden", "chat not found"]):
                    # Remove user from Redis if they're unreachable
                    try:
                        redis_client.delete(f"user_token:{user_id_target}")
                        redis_client.delete(f"user_requests:{user_id_target}")
                        removed_users += 1
                    except Exception:
                        pass
                
                failed_count += 1
        
        # Send final status using rich message
        success_pct = round((sent_count / total_users) * 100, 1) if total_users else 0.0
        final_html = f"""<h1>📢 Broadcast Completed</h1>
<blockquote>Transmission finished across all registered users.</blockquote>

<table border="1">
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td><b>Successfully Sent</b></td><td><b>{sent_count:,}</b></td></tr>
  <tr><td><b>Failed Attempts</b></td><td><b>{failed_count:,}</b></td></tr>
  <tr><td><b>Invalid Users Purged</b></td><td><b>{removed_users:,}</b></td></tr>
  <tr><td><b>Total Recipients</b></td><td>{total_users:,}</td></tr>
  <tr><td><b>Success Rate</b></td><td><b>{success_pct}%</b></td></tr>
  <tr><td><b>Delivery Mode</b></td><td>{drop_label}</td></tr>
</table>"""
        
        await client.send_rich_message(
            chat_id=message.chat.id,
            rich_message=InputRichMessage(html=final_html)
        )
        
    except Exception as e:
        await client.send_rich_message(
            chat_id=message.chat.id,
            rich_message=InputRichMessage(html=f"<blockquote>❌ <b>Broadcast failed:</b> {html.escape(str(e))}</blockquote>")
        )

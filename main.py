import os
import re
import asyncio
from datetime import timedelta
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Application, ChatMemberHandler, CallbackQueryHandler, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

OWNER_ID = 7807347685

BOT_VERSION = "v1.8.0（2026-01-05 更新）"

pending_verifications = {}
known_groups = {}
recent_members = {}

def has_spam_bio(bio: str) -> bool:
    if not bio:
        return False
    return bool(re.search(r"@|\bhttps?://", bio, re.IGNORECASE))

async def track_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        return

    chat_id = chat.id
    title = chat.title or "未知群組"
    known_groups[chat_id] = title

    if update.effective_user and update.message and update.message.text:
        user = update.effective_user
        user_id = user.id
        full_name = user.full_name
        username = user.username or "無"
        if chat_id not in recent_members:
            recent_members[chat_id] = {}
        recent_members[chat_id][user_id] = (full_name, username)

async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_members = []
    chat_id = None

    if update.chat_member:
        cm = update.chat_member
        if cm.new_chat_member.status == "member" and cm.old_chat_member.status != "member":
            new_members.append(cm.new_chat_member.user)
        chat_id = cm.chat.id
    elif update.message and update.message.new_chat_members:
        new_members = update.message.new_chat_members
        chat_id = update.message.chat.id
    else:
        return

    if not chat_id or not new_members:
        return

    try:
        chat = await context.bot.get_chat(chat_id)
        known_groups[chat_id] = chat.title or "未知群組"
    except:
        pass

    for user in new_members:
        try:
            member = await context.bot.get_chat_member(chat_id, user.id)
            bio = getattr(member.user, "bio", "") or ""
        except:
            bio = ""

        need_captcha = has_spam_bio(bio)
        welcome_text = f"歡迎 {user.mention_html()} 加入群組！"

        if need_captcha:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user.id,
                permissions=ChatPermissions(can_send_messages=False)
            )

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("👤 我是真人，驗證通過", callback_data=f"verify_{user.id}_{chat_id}")
            ]])

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{user.mention_html()} 你的簡介含 @ 或連結，請5分鐘內點擊下方按鈕驗證你是真人。",
                reply_markup=keyboard,
                parse_mode="HTML"
            )

            # 5分鐘後強制踢出
            asyncio.create_task(delayed_kick(context.bot, user.id, chat_id))

            pending_verifications[user.id] = chat_id
        else:
            await context.bot.send_message(chat_id=chat_id, text=welcome_text, parse_mode="HTML")

async def delayed_kick(bot, user_id, chat_id):
    await asyncio.sleep(300)  # 5分鐘
    try:
        await bot.kick_chat_member(chat_id=chat_id, user_id=user_id)
        await bot.send_message(chat_id=chat_id, text="未在5分鐘內驗證，已自動踢出群組。")
    except:
        pass

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("verify_"):
        return

    _, user_id_str, chat_id_str = query.data.split("_")
    user_id = int(user_id_str)
    chat_id = int(chat_id_str)

    if query.from_user.id != user_id:
        await query.edit_message_text("這不是你的驗證按鈕！")
        return

    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
    )

    await query.edit_message_text(f"{query.from_user.mention_html()} 驗證通過！")
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"歡迎 {query.from_user.mention_html()} 加入群組！",
        parse_mode="HTML"
    )
    pending_verifications.pop(user_id, None)

# 強制定時解除禁言（最穩方式）
async def delayed_unmute(bot, user_id, chat_id, name, minutes):
    await asyncio.sleep(minutes * 60)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        await bot.send_message(chat_id=chat_id, text=f"🔊 {name} 的禁言時間已到，自動解除～", parse_mode="HTML")
    except:
        pass

# /banme
async def ban_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("這個指令只能在群組使用喔～")
        return

    user = update.effective_user
    chat_id = update.effective_chat.id
    minutes = 2

    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user.id,
        permissions=ChatPermissions(can_send_messages=False)
    )

    # 強制定時解除
    asyncio.create_task(delayed_unmute(context.bot, user.id, chat_id, user.mention_html(), minutes))

    await update.message.reply_text(
        f"{user.mention_html()} 你自己要求的喔～\n被禁言 {minutes} 分鐘，冷靜一下 😂\n時間到一定會自動解除",
        parse_mode="HTML"
    )

# /ban
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("用法：/ban <編號> <user_id> [分鐘]\n用 /members 取得ID")
        return
    try:
        idx = int(args[0]) - 1
        user_id = int(args[1])
        minutes = int(args[2]) if len(args) >= 3 else 60
        if minutes <= 0:
            minutes = 60

        chat_ids = sorted(known_groups.keys())
        chat_id = chat_ids[idx]

        bot_info = await context.bot.get_me()
        if user_id == bot_info.id:
            await update.message.reply_text("❌ 不能禁言 Bot 自己！")
            return

        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False)
        )

        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            user_mention = member.user.mention_html()
        except:
            user_mention = f"user_id {user_id}"

        # 強制定時解除
        asyncio.create_task(delayed_unmute(context.bot, user_id, chat_id, user_mention, minutes))

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔇 {user_mention} 被管理員禁言 {minutes} 分鐘（只能看不能說）\n時間到一定會自動解除",
            parse_mode="HTML"
        )

        await update.message.reply_text(f"✅ 已禁言 {minutes} 分鐘，時間到一定自動解除")
    except Exception as e:
        await update.message.reply_text(f"❌ 操作失敗：{str(e)}")

# 其他指令保持不變
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID or update.effective_chat.type != "private":
        return
    await update.message.reply_text(
        f"🔧 帝ACG 群組管理 Bot 【{BOT_VERSION}】\n\n"
        "/help - 顯示說明\n"
        "/list - 顯示所有群組\n"
        "/members <編號> - 顯示最近活躍成員\n"
        "/users <編號> - 顯示管理員\n"
        "/ban <編號> <user_id> [分鐘] - 禁言並群組宣布\n"
        "/endorsement <編號> <內容> - Bot代發言\n\n"
        "群組公開指令：/banme - 自己禁言2分鐘"
    )

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not known_groups:
        await update.message.reply_text("尚未記錄群組（請在群組發訊息）")
        return
    text = f"📋 群組列表 【{BOT_VERSION}】：\n\n"
    for i, (chat_id, title) in enumerate(sorted(known_groups.items(), key=lambda x: x[0]), 1):
        text += f"{i}. {title} (ID: {chat_id})\n"
    await update.message.reply_text(text)

async def list_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("用法：/members <群組編號>")
        return
    try:
        idx = int(args[0]) - 1
        chat_ids = sorted(known_groups.keys())
        chat_id = chat_ids[idx]
        members = recent_members.get(chat_id, {})
        if not members:
            await update.message.reply_text("該群組暫無發言記錄，讓大家聊幾句就有了～")
            return
        text = f"👥 群組「{known_groups[chat_id]}」最近活躍成員：\n\n"
        for i, (user_id, (name, username)) in enumerate(list(members.items())[-50:], 1):
            username_str = f"@{username}" if username != "無" else ""
            text += f"{i}. {name} {username_str} (ID: {user_id})\n"
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"錯誤：{str(e)}")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("用法：/users <群組編號>")
        return
    try:
        idx = int(args[0]) - 1
        chat_ids = sorted(known_groups.keys())
        chat_id = chat_ids[idx]
        admins = await context.bot.get_chat_administrators(chat_id)
        text = f"👑 群組「{known_groups[chat_id]}」管理員：\n\n"
        for admin in admins:
            user = admin.user
            text += f"• {user.mention_html()} (ID: {user.id})\n"
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"錯誤：{str(e)}")

async def endorsement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("用法：/endorsement <編號> <內容>")
        return
    try:
        idx = int(args[0]) - 1
        content = " ".join(args[1:])
        chat_ids = sorted(known_groups.keys())
        chat_id = chat_ids[idx]
        await context.bot.send_message(chat_id=chat_id, text=content)
        await update.message.reply_text("✅ 已代發言")
    except Exception as e:
        await update.message.reply_text(f"❌ 失敗：{str(e)}")

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("請設定 BOT_TOKEN")
        return

    app = Application.builder().token(token).build()

    app.add_handler(MessageHandler(filters.ChatType.GROUPS, track_group_message))
    app.add_handler(ChatMemberHandler(handle_new_member, chat_member_types=ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_member))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.add_handler(CommandHandler("banme", ban_me, filters=filters.ChatType.GROUPS))

    app.add_handler(CommandHandler("help", help_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("list", list_groups))
    app.add_handler(CommandHandler("members", list_members))
    app.add_handler(CommandHandler("users", list_users))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("endorsement", endorsement))

    logger.info(f"🤖 帝ACG 群組管理 Bot {BOT_VERSION} 已啟動！（強制定時解除版）")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
import os
import re
from datetime import timedelta
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Application, ChatMemberHandler, CallbackQueryHandler, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 你的 Telegram User ID（後台指令僅你可使用）
OWNER_ID = 7807347685

# 全域儲存
pending_verifications = {}  # {user_id: chat_id} 待驗證用戶
known_groups = {}            # {chat_id: title} 已知群組（自動記錄）

# 檢查簡介是否有 @ 或連結（防廣告）
def has_spam_bio(bio: str) -> bool:
    if not bio:
        return False
    return bool(re.search(r"@|\bhttps?://", bio, re.IGNORECASE))

# === 關鍵：只要群組有任何訊息，就自動記錄該群組（最可靠方式）===
async def track_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type in ["group", "supergroup"]:
        chat_id = chat.id
        title = chat.title or "未知群組"
        if chat_id not in known_groups:
            known_groups[chat_id] = title
            logger.info(f"自動發現並記錄新群組：{title} (ID: {chat_id})")
        else:
            # 如果群組改名，自動更新
            known_groups[chat_id] = title

# 處理新成員加入
async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    if not chat_member or chat_member.new_chat_member.status != "member":
        return

    user = chat_member.new_chat_member.user
    chat_id = chat_member.chat.id
    chat = chat_member.chat

    # 自動記錄群組（保險）
    known_groups[chat_id] = chat.title or "未知群組"

    # 取得 bio
    member = await context.bot.get_chat_member(chat_id, user.id)
    bio = getattr(member.user, "bio", "") or ""

    need_captcha = has_spam_bio(bio)
    welcome_text = f"歡迎 {user.mention_html()} 加入群組！"

    if need_captcha:
        # 暫時禁言
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False)
        )

        # 發驗證按鈕
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👤 我是真人，驗證通過", callback_data=f"verify_{user.id}_{chat_id}")
        ]])

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{user.mention_html()} 你的簡介含有 @ 或連結，請在5分鐘內點擊下方按鈕驗證你是真人。",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        # 5分鐘後自動踢出
        context.job_queue.run_once(
            kick_unverified,
            timedelta(minutes=5),
            data={"user_id": user.id, "chat_id": chat_id}
        )
        pending_verifications[user.id] = chat_id
    else:
        await context.bot.send_message(chat_id=chat_id, text=welcome_text, parse_mode="HTML")

# 驗證按鈕點擊
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

    # 解除禁言
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

# 未驗證自動踢出
async def kick_unverified(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data["user_id"]
    chat_id = job.data["chat_id"]

    await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
    await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
    await context.bot.send_message(chat_id=chat_id, text="未在5分鐘內完成驗證，已自動移除。")
    pending_verifications.pop(user_id, None)

# ===== 後台管理指令（僅限主人私訊）=====
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID or update.effective_chat.type != "private":
        return
    await update.message.reply_text(
        "🔧 後台管理指令（僅限主人私訊使用）\n\n"
        "/help - 顯示此說明\n"
        "/list - 顯示 Bot 所在的所有群組（帶編號）\n"
        "/list user <編號> - 顯示該群組的管理員名單\n"
        "/ban <編號> <user_id> - 禁言該用戶24小時\n"
        "/endorsement <編號> <內容> - 以 Bot 名義發言"
    )

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not known_groups:
        await update.message.reply_text("目前尚未記錄到任何群組（請在群組發一條訊息讓我發現）")
        return

    text = "📋 Bot 所在群組列表：\n\n"
    for i, (chat_id, title) in enumerate(sorted(known_groups.items(), key=lambda x: x[0]), 1):
        text += f"{i}. {title} (ID: {chat_id})\n"
    await update.message.reply_text(text)

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("用法：/list user <群組編號>")
        return
    try:
        idx = int(args[0]) - 1
        chat_ids = sorted(known_groups.keys())
        chat_id = chat_ids[idx]
        chat = await context.bot.get_chat(chat_id)

        admins = await context.bot.get_chat_administrators(chat_id)
        text = f"👥 群組「{chat.title}」管理員名單：\n\n"
        for admin in admins:
            user = admin.user
            text += f"• {user.mention_html()} (ID: {user.id})\n"
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ 無法取得：{str(e)}")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("用法：/ban <群組編號> <user_id>")
        return
    try:
        idx = int(args[0]) - 1
        user_id = int(args[1])
        chat_ids = sorted(known_groups.keys())
        chat_id = chat_ids[idx]

        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id, until_date=timedelta(hours=24))
        await update.message.reply_text(f"✅ 已將 user_id {user_id} 禁言24小時")
    except Exception as e:
        await update.message.reply_text(f"❌ 禁言失敗：{str(e)}")

async def endorsement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("用法：/endorsement <群組編號> <內容>")
        return
    try:
        idx = int(args[0]) - 1
        content = " ".join(args[1:])
        chat_ids = sorted(known_groups.keys())
        chat_id = chat_ids[idx]

        await context.bot.send_message(chat_id=chat_id, text=content)
        await update.message.reply_text("✅ 已成功代發言")
    except Exception as e:
        await update.message.reply_text(f"❌ 發言失敗：{str(e)}")

# 主函數
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("請設定 BOT_TOKEN 環境變數")
        return

    app = Application.builder().token(token).build()

    # 關鍵：收到任何群組訊息就記錄群組
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, track_group_message))

    # 新成員加入處理
    app.add_handler(ChatMemberHandler(handle_new_member, chat_member_types=ChatMemberHandler.CHAT_MEMBER))

    # 驗證按鈕
    app.add_handler(CallbackQueryHandler(button_callback))

    # 後台指令（私訊限定 help）
    app.add_handler(CommandHandler("help", help_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("list", list_groups))
    app.add_handler(CommandHandler("list", list_users, filters=filters.Regex(r"^user\b")))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("endorsement", endorsement))

    logger.info("🤖 群組管理 Bot 已啟動，所有功能就緒！")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
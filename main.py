import os
import re
from datetime import timedelta
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Application, ChatMemberHandler, CallbackQueryHandler, CommandHandler, ContextTypes, filters

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# 你的 Telegram ID（後台命令僅你可用）
OWNER_ID = 7807347685

# 儲存狀態
pending_verifications = {}  # {user_id: chat_id}
known_groups = {}            # {chat_id: title}

def has_spam_bio(bio: str) -> bool:
    if not bio:
        return False
    return bool(re.search(r"@|\bhttps?://", bio, re.IGNORECASE))

# 新成員加入處理
async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    if not chat_member or chat_member.new_chat_member.status != "member":
        return

    user = chat_member.new_chat_member.user
    chat_id = chat_member.chat.id
    chat = chat_member.chat
    known_groups[chat_id] = chat.title or "未知群組"

    # 取得 bio
    member = await context.bot.get_chat_member(chat_id, user.id)
    bio = getattr(member.user, "bio", "") or ""

    need_captcha = has_spam_bio(bio)
    welcome_text = f"歡迎 {user.mention_html()} 加入群組！"

    if need_captcha:
        # 禁言
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
            text=f"{user.mention_html()} 你的簡介含可疑 @ 或連結，請在5分鐘內點擊下方按鈕驗證你是真人。",
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

# ===== 後台完整命令 =====
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID or update.effective_chat.type != "private":
        return
    await update.message.reply_text(
        "🔧 後台管理指令（僅限主人私訊使用）\n\n"
        "/help - 顯示此說明\n"
        "/list - 顯示所有群組（帶編號）\n"
        "/list user <編號> - 顯示該群組的管理員名單\n"
        "/ban <編號> <@username 或 user_id> - 禁言該用戶24小時\n"
        "/endorsement <編號> <內容> - 以Bot名義發言"
    )

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not known_groups:
        await update.message.reply_text("目前 Bot 尚未加入任何群組")
        return

    text = "📋 群組列表：\n\n"
    for i, (chat_id, title) in enumerate(sorted(known_groups.items(), key=lambda x: x[0]), 1):
        text += f"{i}. {title} (ID: {chat_id})\n"
    await update.message.reply_text(text)

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("用法：/list user <編號>")
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
            text += f"• {user.mention_html()} ({user.id})\n"
        await update.message.reply_text(text, parse_mode="HTML")
    except:
        await update.message.reply_text("❌ 編號錯誤或無法取得資料")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("用法：/ban <編號> <@username 或 user_id>")
        return
    try:
        idx = int(args[0]) - 1
        target = args[1].lstrip("@")
        chat_ids = sorted(known_groups.keys())
        chat_id = chat_ids[idx]

        # 嘗試用 username 或直接當 user_id
        if target.isdigit():
            user_id = int(target)
        else:
            # 簡易方式：用 username 找（實際可擴充）
            await update.message.reply_text("⚠️ 目前支援直接輸入 user_id 禁言（從 /list user 取得）")
            return

        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id, until_date=timedelta(hours=24))
        await update.message.reply_text(f"已禁言 user_id {user_id} 24小時")
    except Exception as e:
        await update.message.reply_text(f"禁言失敗：{str(e)}")

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
        await update.message.reply_text("✅ 已成功代發言")
    except:
        await update.message.reply_text("❌ 失敗，請檢查編號（用 /list 查看）")

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("錯誤：請設定 BOT_TOKEN 環境變數")
        return

    app = Application.builder().token(token).build()

    # 事件處理
    app.add_handler(ChatMemberHandler(handle_new_member, chat_member_types=ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(button_callback))

    # 後台命令（僅限主人私訊）
    app.add_handler(CommandHandler("help", help_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("list", list_groups))
    app.add_handler(CommandHandler("list", list_users, filters=filters.Regex(r"^user\b")))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("endorsement", endorsement))

    print("🤖 群組管理 Bot 已成功啟動！所有功能就緒")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
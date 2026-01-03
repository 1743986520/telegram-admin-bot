import os
import re
from datetime import timedelta, datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Application, ChatMemberHandler, CallbackQueryHandler, CommandHandler, ContextTypes, filters

# 主人 ID
OWNER_ID = 7807347685

# 待驗證字典
pending_verifications = {}

def has_spam_bio(bio: str) -> bool:
    if not bio:
        return False
    return bool(re.search(r"@|\bhttps?://", bio, re.IGNORECASE))

async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    if not chat_member or chat_member.new_chat_member.status != "member":
        return

    user = chat_member.new_chat_member.user
    chat_id = chat_member.chat.id

    # 取得 bio
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        bio = member.user.bio or ""
    except:
        bio = ""

    need_captcha = has_spam_bio(bio)

    if need_captcha:
        await context.bot.restrict_chat_member(chat_id, user.id, permissions=ChatPermissions(can_send_messages=False))

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👤 我是真人，驗證通過", callback_data=f"verify_{user.id}_{chat_id}")
        ]])

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{user.mention_html()} 你的簡介含可疑連結，請5分鐘內點擊下方按鈕驗證。",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

        context.job_queue.run_once(
            kick_if_not_verified,
            datetime.utcnow() + timedelta(minutes=5),
            data={"user_id": user.id, "chat_id": chat_id}
        )
        pending_verifications[user.id] = chat_id
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"歡迎 {user.mention_html()} 加入群組！",
            parse_mode="HTML"
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("verify_"):
        return

    _, uid, cid = query.data.split("_")
    user_id, chat_id = int(uid), int(cid)

    if query.from_user.id != user_id:
        await query.edit_message_text("這不是你的按鈕！")
        return

    await context.bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(can_send_messages=True))

    await query.edit_message_text(f"{query.from_user.mention_html()} 驗證通過！")

    await context.bot.send_message(chat_id, f"歡迎 {query.from_user.mention_html()} 加入群組！", parse_mode="HTML")

    pending_verifications.pop(user_id, None)

async def kick_if_not_verified(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data["user_id"]
    chat_id = job.data["chat_id"]

    await context.bot.ban_chat_member(chat_id, user_id)
    await context.bot.unban_chat_member(chat_id, user_id)
    await context.bot.send_message(chat_id, "未完成驗證，已自動移除。")
    pending_verifications.pop(user_id, None)

# ===== 後台命令 =====
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID or not update.effective_chat.type == "private":
        return
    await update.message.reply_text(
        "/help - 顯示幫助\n"
        "/list - 列出所有群組（帶編號）\n"
        "/list user <編號> - 顯示該群組管理員\n"
        "/ban <編號> <@username 或 ID> - 禁言\n"
        "/endorsement <編號> <內容> - Bot代發言"
    )

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    chats = context.application.chat_data.keys()
    if not chats:
        await update.message.reply_text("目前沒有群組記錄")
        return

    text = "群組列表：\n"
    for i, chat_id in enumerate(sorted([c for c in chats if isinstance(c, int)]), 1):
        try:
            chat = await context.bot.get_chat(chat_id)
            title = chat.title or "未知"
        except:
            title = "無法取得"
        text += f"{i}. {title} (ID: {chat_id})\n"
    await update.message.reply_text(text)

async def endorsement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID or len(context.args) < 2:
        return
    try:
        idx = int(context.args[0]) - 1
        content = " ".join(context.args[1:])
        chat_ids = sorted([c for c in context.application.chat_data.keys() if isinstance(c, int)])
        chat_id = chat_ids[idx]
        await context.bot.send_message(chat_id, content)
        await update.message.reply_text("已代發言")
    except:
        await update.message.reply_text("失敗，檢查編號或內容")

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("請設定 BOT_TOKEN 環境變數")
        return

    app = Application.builder().token(token).build()

    app.add_handler(ChatMemberHandler(handle_new_member, chat_member_types=ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("list", list_groups))
    app.add_handler(CommandHandler("endorsement", endorsement))

    print("Bot 已啟動！")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

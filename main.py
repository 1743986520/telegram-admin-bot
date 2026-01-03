import os
import re
import logging
from datetime import timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, ParseMode
from telegram.ext import Updater, CallbackContext, ChatMemberHandler, CallbackQueryHandler, CommandHandler, Filters

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 你的 ID（後台命令只限你）
OWNER_ID = 7807347685

# 儲存待驗證用戶 {user_id: chat_id}
pending_verifications = {}

# 儲存已知群組 {chat_id: title}
known_groups = {}

# 檢查 bio 是否可疑（v13.7 無法取 bio，先留著，未來升級再用）
def has_spam_bio(bio):
    if not bio:
        return False
    return bool(re.search(r"@|\bhttps?://", bio, re.IGNORECASE))

# 處理成員狀態變化（包括新加入）
def handle_chat_member(update: Update, context: CallbackContext):
    chat_member_update = update.chat_member or update.my_chat_member
    if not chat_member_update:
        return

    old_status = chat_member_update.old_chat_member.status
    new_status = chat_member_update.new_chat_member.status
    user = chat_member_update.new_chat_member.user
    chat_id = chat_member_update.chat.id
    chat_title = chat_member_update.chat.title or "未知群組"

    # 記錄群組
    known_groups[chat_id] = chat_title

    # 只處理加入（從非 member 變成 member）
    if old_status in ["left", "kicked", "banned"] and new_status == "member":
        # v13.7 無法取 bio，直接假設不需要驗證（或強制驗證可改這裡）
        need_captcha = False  # 無法取 bio，暫時關閉檢查

        welcome_text = f"歡迎 <a href='tg://user?id={user.id}'>{user.full_name}</a> 加入群組！"

        if need_captcha:
            # 禁言
            context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user.id,
                permissions=ChatPermissions(can_send_messages=False)
            )

            # 發驗證按鈕
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("👤 我是真人，驗證通過", callback_data=f"verify_{user.id}_{chat_id}")
            ]])
            context.bot.send_message(
                chat_id=chat_id,
                text=f"<a href='tg://user?id={user.id}'>{user.full_name}</a> 請在5分鐘內點擊下方按鈕驗證你是真人。",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

            # 5分鐘後踢出
            context.job_queue.run_once(
                kick_unverified,
                when=timedelta(minutes=5),
                context={"user_id": user.id, "chat_id": chat_id}
            )
            pending_verifications[user.id] = chat_id
        else:
            context.bot.send_message(chat_id=chat_id, text=welcome_text, parse_mode=ParseMode.HTML)

# 按鈕點擊處理
def button_click(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if not query.data.startswith("verify_"):
        return

    _, user_id_str, chat_id_str = query.data.split("_")
    user_id = int(user_id_str)
    chat_id = int(chat_id_str)

    if query.from_user.id != user_id:
        query.edit_message_text(text="這不是你的驗證按鈕！")
        return

    # 解除禁言
    context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                                    can_send_polls=True, can_send_other_messages=True,
                                    can_add_web_page_previews=True)
    )

    query.edit_message_text(text=f"<a href='tg://user?id={user_id}'>{query.from_user.full_name}</a> 驗證通過！")

    # 發歡迎
    context.bot.send_message(
        chat_id=chat_id,
        text=f"歡迎 <a href='tg://user?id={user_id}'>{query.from_user.full_name}</a> 加入群組！",
        parse_mode=ParseMode.HTML
    )

    pending_verifications.pop(user_id, None)

# 未驗證自動踢出
def kick_unverified(context: CallbackContext):
    data = context.job.context
    user_id = data["user_id"]
    chat_id = data["chat_id"]

    context.bot.kick_chat_member(chat_id=chat_id, user_id=user_id)
    context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)  # 只 kick 不永久 ban
    context.bot.send_message(chat_id=chat_id, text="未完成驗證，已自動移除。")
    pending_verifications.pop(user_id, None)

# ===== 後台命令（只限主人私訊） =====
def help_cmd(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID or update.effective_chat.type != "private":
        return
    update.message.reply_text(
        "/help - 顯示幫助\n"
        "/list - 顯示所有群組（帶編號）\n"
        "/endorsement <編號> <內容> - 以 Bot 名義發言\n"
        "（/ban 和 /list user 因 v13.7 限制暫未實作，可未來升級）"
    )

def list_groups(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID:
        return
    if not known_groups:
        update.message.reply_text("目前沒有記錄到群組")
        return

    text = "群組列表：\n"
    sorted_groups = sorted(known_groups.items(), key=lambda x: x[0])
    for i, (chat_id, title) in enumerate(sorted_groups, 1):
        text += f"{i}. {title} (ID: {chat_id})\n"
    update.message.reply_text(text)

def endorsement(update: Update, context: CallbackContext):
    if update.effective_user.id != OWNER_ID or len(context.args) < 2:
        return
    try:
        idx = int(context.args[0]) - 1
        content = " ".join(context.args[1:])
        chat_ids = sorted(known_groups.keys())
        chat_id = chat_ids[idx]
        context.bot.send_message(chat_id=chat_id, text=content)
        update.message.reply_text("已代發言")
    except:
        update.message.reply_text("失敗，檢查編號")

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("請設定 BOT_TOKEN 環境變數")
        return

    updater = Updater(token=token, use_context=True)

    dp = updater.dispatcher

    # 捕捉成員變化
    dp.add_handler(ChatMemberHandler(handle_chat_member, chat_member_types=ChatMemberHandler.ANY_CHAT_MEMBER))
    dp.add_handler(ChatMemberHandler(handle_chat_member, chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER))

    # 按鈕
    dp.add_handler(CallbackQueryHandler(button_click))

    # 後台命令（限私訊主人）
    dp.add_handler(CommandHandler("help", help_cmd, filters=Filters.user(user_id=OWNER_ID) & Filters.chat_type.private))
    dp.add_handler(CommandHandler("list", list_groups, filters=Filters.user(user_id=OWNER_ID)))
    dp.add_handler(CommandHandler("endorsement", endorsement, filters=Filters.user(user_id=OWNER_ID)))

    logger.info("Bot 啟動中...")
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == '__main__':
    main()

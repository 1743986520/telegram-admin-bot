import os
import re
import asyncio
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== 基本設定 ==================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

OWNER_ID = 7807347685
BOT_VERSION = "v2.0.0-stable"

known_groups: dict[int, str] = {}
pending_verifications: dict[int, int] = {}  # user_id -> chat_id


# ================== 權限 ==================

def mute_permissions() -> ChatPermissions:
    return ChatPermissions(can_send_messages=False)


# ⚠️ Telegram 目前「解除禁言」唯一穩定方式
def unmute_permissions() -> ChatPermissions:
    return ChatPermissions()  # 必須是空的


# ================== 工具 ==================

async def delayed_unmute(bot, chat_id: int, user_id: int, minutes: int):
    await asyncio.sleep(minutes * 60)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=unmute_permissions(),
            until_date=0,
        )
        await bot.send_message(chat_id, "🔊 禁言已解除")
    except Exception as e:
        logger.error(f"解除禁言失敗: {e}")


# ================== 進群處理 ==================

async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return

    if result.old_chat_member.status in ("left", "kicked") \
       and result.new_chat_member.status == "member":

        user = result.new_chat_member.user
        chat = result.chat

        known_groups[chat.id] = chat.title

        try:
            bio = (await context.bot.get_chat(user.id)).bio or ""
        except Exception:
            bio = ""

        suspicious = bool(re.search(r"@|https?://", bio, re.I))

        if suspicious:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions=mute_permissions(),
                until_date=0,
            )

            pending_verifications[user.id] = chat.id

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 我是真人（點擊驗證）", callback_data=f"verify_{user.id}")]
            ])

            await context.bot.send_message(
                chat.id,
                f"⚠️ {user.mention_html()} 請完成驗證",
                reply_markup=kb,
                parse_mode="HTML",
            )
        else:
            await context.bot.send_message(
                chat.id,
                f"🎉 歡迎 {user.mention_html()}",
                parse_mode="HTML",
            )


# ================== 驗證按鈕 ==================

async def on_verify_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data.startswith("verify_"):
        return

    user_id = int(query.data.split("_")[1])

    if query.from_user.id != user_id:
        await query.answer("這不是你的驗證", show_alert=True)
        return

    chat_id = query.message.chat_id

    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=unmute_permissions(),  # ⭐ 關鍵
        until_date=0,
    )

    pending_verifications.pop(user_id, None)

    await query.edit_message_text(
        f"✅ {query.from_user.mention_html()} 驗證成功，已解除限制",
        parse_mode="HTML",
    )


# ================== 指令 ==================

async def banme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("❌ 這個指令只能在群組使用")
        return

    await context.bot.restrict_chat_member(
        chat.id,
        user.id,
        permissions=mute_permissions(),
        until_date=0,
    )

    await update.message.reply_text(
        f"🤐 {user.mention_html()} 已禁言 2 分鐘",
        parse_mode="HTML",
    )

    asyncio.create_task(delayed_unmute(context.bot, chat.id, user.id, 2))


async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if user.id != OWNER_ID:
        await update.message.reply_text("❌ 無權限")
        return

    if not known_groups:
        await update.message.reply_text("尚未記錄任何群組")
        return

    text = "📋 群組清單：\n" + "\n".join(
        f"- {name} ({gid})" for gid, name in known_groups.items()
    )

    await update.message.reply_text(text)


# ================== 私聊可用測試指令 ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 Bot 正常運作\n版本：{BOT_VERSION}"
    )


# ================== 主程式 ==================

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN 未設定")

    app = Application.builder().token(token).build()

    # 進群
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))

    # 驗證按鈕
    app.add_handler(CallbackQueryHandler(on_verify_click))

    # 指令（私聊 + 群組）
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("banme", banme))
    app.add_handler(CommandHandler("list", list_groups))

    logger.info("Bot 啟動完成")

    # ❗ 不限制 allowed_updates
    app.run_polling()


if __name__ == "__main__":
    main()
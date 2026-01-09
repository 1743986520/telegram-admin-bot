import os
import re
import asyncio
import logging
from datetime import timedelta

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

# ------------------ 基本設定 ------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

OWNER_ID = 7807347685
BOT_VERSION = "v1.9.3-fixed (PTB 22)"

known_groups: dict[int, str] = {}
pending_verifications: dict[int, int] = {}  # user_id -> chat_id


# ------------------ 權限工具 ------------------

def get_full_permissions() -> ChatPermissions:
    """完整權限（PTB 22 必須全部寫）"""
    return ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
    )


# ------------------ 定時解除禁言 ------------------

async def delayed_unmute(bot, chat_id: int, user_id: int, name: str, minutes: int):
    logger.info(f"等待 {minutes} 分鐘後解除禁言: {user_id}")
    await asyncio.sleep(minutes * 60)

    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=get_full_permissions(),
            until_date=0,  # ⭐ 關鍵
        )
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔊 {name} 禁言結束，已恢復發言。",
        )
    except Exception as e:
        logger.error(f"解除禁言失敗: {e}")


# ------------------ 進群驗證 ------------------

async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return

    if (
        result.old_chat_member.status in ("left", "kicked")
        and result.new_chat_member.status == "member"
    ):
        user = result.new_chat_member.user
        chat = result.chat
        known_groups[chat.id] = chat.title

        # 讀取 Bio（Bot 必須是管理員）
        try:
            member_info = await context.bot.get_chat(user.id)
            bio = member_info.bio or ""
        except Exception:
            bio = ""

        # 簡單廣告判斷
        is_suspicious = bool(re.search(r"@|\bhttps?://", bio, re.IGNORECASE))

        if is_suspicious:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=0,
            )

            pending_verifications[user.id] = chat.id

            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("👤 我是真人，點我驗證", callback_data=f"v_{user.id}")]]
            )

            await context.bot.send_message(
                chat_id=chat.id,
                text=f"⚠️ {user.mention_html()}，你的簡介可疑，請點擊下方按鈕驗證。",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await context.bot.send_message(
                chat_id=chat.id,
                text=f"🎉 歡迎 {user.mention_html()} 加入！",
                parse_mode="HTML",
            )


# ------------------ 驗證按鈕 ------------------

async def on_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data.startswith("v_"):
        return

    target_user_id = int(query.data.split("_", 1)[1])

    if query.from_user.id != target_user_id:
        await query.answer("❌ 這不是你的驗證按鈕", show_alert=True)
        return

    await context.bot.restrict_chat_member(
        chat_id=query.message.chat_id,
        user_id=target_user_id,
        permissions=get_full_permissions(),
        until_date=0,  # ⭐ 必須
    )

    pending_verifications.pop(target_user_id, None)

    await query.edit_message_text(
        f"✅ {query.from_user.mention_html()} 驗證成功，已解除限制。",
        parse_mode="HTML",
    )


# ------------------ 指令 ------------------

async def ban_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        return

    await context.bot.restrict_chat_member(
        chat_id=chat.id,
        user_id=user.id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=0,
    )

    await update.message.reply_text(
        f"🤐 {user.mention_html()} 已禁言 2 分鐘。",
        parse_mode="HTML",
    )

    asyncio.create_task(
        delayed_unmute(context.bot, chat.id, user.id, user.mention_html(), 2)
    )


async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    if not known_groups:
        await update.message.reply_text("尚未記錄任何群組。")
        return

    text = "📋 已知群組：\n" + "\n".join(
        f"- {title} ({gid})" for gid, title in known_groups.items()
    )

    await update.message.reply_text(text)


# ------------------ 群組追蹤（不要用 lambda） ------------------

async def track_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    known_groups[update.effective_chat.id] = update.effective_chat.title


# ------------------ 主程式 ------------------

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN 未設定")

    app = Application.builder().token(token).build()

    # 進群
    app.add_handler(
        ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER)
    )

    # 驗證按鈕
    app.add_handler(CallbackQueryHandler(on_button_click))

    # 指令
    app.add_handler(CommandHandler("banme", ban_me))
    app.add_handler(CommandHandler("list", list_groups))

    # 群組記錄（最後執行）
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, track_groups),
        group=99,
    )

    logger.info(f"Bot 啟動完成 {BOT_VERSION}")

    app.run_polling(
        allowed_updates=["message", "chat_member", "callback_query"]
    )


if __name__ == "__main__":
    main()
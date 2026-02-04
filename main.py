import os
import re
import asyncio
from collections import defaultdict
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
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],  # 日志同時輸出到文件和終端
)
logger = logging.getLogger(__name__)
OWNER_ID = 7807347685  # 替換為你的 Telegram ID（必填！）
BOT_VERSION = "v2.1.0-fix"
known_groups: dict[int, str] = defaultdict(str)
pending_verifications: dict[int, int] = {}

# ================== 權限設定 ==================
def mute_permissions() -> ChatPermissions:
    return ChatPermissions(can_send_messages=False)

def unmute_permissions() -> ChatPermissions:
    return ChatPermissions()

# ================== 工具函數 ==================
async def delayed_unmute(bot, chat_id: int, user_id: int, minutes: int):
    await asyncio.sleep(minutes * 60)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=unmute_permissions(),
            until_date=0,
        )
        await bot.send_message(chat_id, "🔊 禁言已解除，請遵守群規～")
    except Exception as e:
        logger.error(f"解除禁言失敗：chat_id={chat_id}, user_id={user_id}, 錯誤：{e}")
        await bot.send_message(chat_id, "❌ 解除禁言失敗，請管理員手動操作")

# ================== 進群處理 ==================
async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return

    if result.old_chat_member.status in ("left", "kicked") and result.new_chat_member.status == "member":
        user = result.new_chat_member.user
        chat = result.chat
        known_groups[chat.id] = chat.title

        try:
            user_chat = await asyncio.wait_for(context.bot.get_chat(user.id), timeout=5)
            bio = user_chat.bio or ""
        except (Exception, asyncio.TimeoutError):
            bio = ""
            logger.warning(f"獲取用戶 {user.id} 簡介失敗")

        suspicious_pattern = re.compile(r"@|https?://", re.IGNORECASE)
        suspicious = bool(suspicious_pattern.search(bio))

        if suspicious:
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions=mute_permissions(),
                    until_date=0,
                )
                pending_verifications[user.id] = chat.id
                verify_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("👤 我是真人（點擊驗證）", callback_data=f"verify_{user.id}")]
                ])
                await context.bot.send_message(
                    chat.id,
                    f"⚠️ 檢測到可疑賬號：{user.mention_html()}\n請點擊按鈕完成驗證",
                    reply_markup=verify_keyboard,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"可疑用戶處理失敗：{e}")
                await context.bot.send_message(chat.id, "❌ 驗證功能啟動失敗，請管理員手動審核")
        else:
            await context.bot.send_message(
                chat.id,
                f"🎉 歡迎 {user.mention_html()} 加入群組！",
                parse_mode="HTML",
            )

# ================== 驗證按鈕 ==================
async def on_verify_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()  # 必須回應按鈕請求，否則 Telegram 會重試

    if not query.data.startswith("verify_"):
        await query.edit_message_text("❌ 無效的驗證請求")
        return

    try:
        user_id = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.edit_message_text("❌ 驗證參數錯誤")
        return

    if query.from_user.id != user_id:
        await query.answer("這不是你的驗證按鈕", show_alert=True)
        return

    chat_id = query.message.chat_id
    if pending_verifications.get(user_id) != chat_id:
        await query.edit_message_text("❌ 驗證已過期或無效")
        return

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=unmute_permissions(),
            until_date=0,
        )
        pending_verifications.pop(user_id, None)
        await query.edit_message_text(
            f"✅ {query.from_user.mention_html()} 驗證成功！",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"驗證解除禁言失敗：{e}")
        await query.edit_message_text("❌ 驗證成功但解除禁言失敗，請聯繫管理員")

# ================== 指令修復 ==================
async def banme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("❌ 此指令僅支持群組使用！\n請在群聊中發送 /banme 自願禁言")
        return

    try:
        await context.bot.restrict_chat_member(
            chat.id,
            user.id,
            permissions=mute_permissions(),
            until_date=0,
        )
        await update.message.reply_text(
            f"🤐 {user.mention_html()} 已自願禁言 2 分鐘",
            parse_mode="HTML",
        )
        asyncio.create_task(delayed_unmute(context.bot, chat.id, user.id, 2))
    except Exception as e:
        logger.error(f"/banme 指令執行失敗：{e}")
        await update.message.reply_text("❌ 禁言失敗！請確認機器人已獲得「限制成員」管理員權限")

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if chat.type != "private":
        await update.message.reply_text("❌ 此指令僅支持私聊使用！\n請直接向機器人發送 /list 查詢群組")
        return

    if user.id != OWNER_ID:
        await update.message.reply_text("❌ 無權限執行此指令！\n僅管理員（OWNER_ID 對應賬號）可使用")
        return

    if not known_groups:
        await update.message.reply_text("📭 尚未記錄任何群組\n原因：\n1. 機器人未加入群組\n2. 群組中暫無新成員進群（僅新成員進群才會記錄）")
        return

    group_list = "📋 管理的群組清單：\n"
    for gid, name in known_groups.items():
        group_list += f"- {name}（ID：{gid}）\n"
    await update.message.reply_text(group_list)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 機器人正常運作（版本：{BOT_VERSION}）\n"
        f"📌 可用指令：\n"
        f"/start - 查看狀態和指令\n"
        f"/banme - 群組內自願禁言 2 分鐘\n"
        f"/list - 私聊查詢管理群組（僅管理員）\n"
        f"⚠️  若指令失效，請確認：\n"
        f"1. 機器人已獲得群組管理員權限\n"
        f"2. 指令在正確場景使用（/list 私聊、/banme 群組）"
    )

# ================== 錯誤處理器（新增） ==================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """捕獲所有指令執行錯誤並提示"""
    logger.error(f"指令執行錯誤：{context.error}")
    if update and update.message:
        await update.message.reply_text("❌ 指令執行失敗！\n請檢查：\n1. 機器人管理員權限\n2. 指令使用場景\n3. 查看 bot.log 日誌獲取詳情")

# ================== 主程式 ==================
def main():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("❌ 未設置 BOT_TOKEN 環境變量！\n請執行：export BOT_TOKEN='你的Token'")

    # 強制指定 Python 版本兼容
    import sys
    if sys.version_info < (3, 12):
        raise RuntimeError("❌ Python 版本低於 3.12！請升級後重試")

    application = Application.builder().token(bot_token).build()

    # 註冊處理器
    application.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(CallbackQueryHandler(on_verify_click))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("banme", banme))
    application.add_handler(CommandHandler("list", list_groups))
    application.add_error_handler(error_handler)  # 註冊錯誤處理器

    logger.info(f"✅ 機器人啟動完成（Python 版本：{sys.version.split()[0]}）")
    application.run_polling()

if __name__ == "__main__":
    main()

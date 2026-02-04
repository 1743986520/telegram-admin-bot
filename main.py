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
)
logger = logging.getLogger(__name__)
OWNER_ID = 7807347685  # 替換為你的 Telegram ID
BOT_VERSION = "v2.0.0-stable"
known_groups: dict[int, str] = defaultdict(str)  # 避免重複鍵值衝突
pending_verifications: dict[int, int] = {}  # user_id -> chat_id

# ================== 權限設定 ==================
def mute_permissions() -> ChatPermissions:
    """返回禁言權限配置"""
    return ChatPermissions(can_send_messages=False)

def unmute_permissions() -> ChatPermissions:
    """返回解除禁言權限配置（Telegram 穩定方式）"""
    return ChatPermissions()  # 必須為空字典

# ================== 工具函數 ==================
async def delayed_unmute(bot, chat_id: int, user_id: int, minutes: int):
    """延時解除禁言（預設 2 分鐘）"""
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

# ================== 進群成員處理 ==================
async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理成員進群事件（驗證可疑賬號）"""
    result = update.chat_member
    if not result:
        return

    # 僅處理「從離開/被踢出」到「成為成員」的事件
    if result.old_chat_member.status in ("left", "kicked") and result.new_chat_member.status == "member":
        user = result.new_chat_member.user
        chat = result.chat
        known_groups[chat.id] = chat.title  # 記錄群組信息

        # 獲取用戶簡介並檢測可疑內容（@ 標籤、網址）
        try:
            # 增加 5 秒超時控制，避免請求卡頓
            user_chat = await asyncio.wait_for(context.bot.get_chat(user.id), timeout=5)
            bio = user_chat.bio or ""
        except (Exception, asyncio.TimeoutError):
            bio = ""
            logger.warning(f"獲取用戶 {user.id} 簡介失敗（超時/無權限）")

        # 檢測可疑簡介（不區分大小寫）
        suspicious_pattern = re.compile(r"@|https?://", re.IGNORECASE)
        suspicious = bool(suspicious_pattern.search(bio))

        if suspicious:
            # 可疑用戶自動禁言，觸發驗證
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions=mute_permissions(),
                until_date=0,
            )
            pending_verifications[user.id] = chat.id  # 記錄待驗證用戶

            # 創建驗證按鈕
            verify_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 我是真人（點擊驗證）", callback_data=f"verify_{user.id}")]
            ])

            # 發送驗證通知
            await context.bot.send_message(
                chat.id,
                f"⚠️ 檢測到可疑賬號：{user.mention_html()}\n"
                f"簡介包含敏感內容（@ 標籤/網址），請點擊按鈕完成真人驗證",
                reply_markup=verify_keyboard,
                parse_mode="HTML",
            )
        else:
            # 正常用戶發送歡迎消息
            await context.bot.send_message(
                chat.id,
                f"🎉 歡迎 {user.mention_html()} 加入群組！\n請遵守群規，文明交流～",
                parse_mode="HTML",
            )

# ================== 驗證按鈕回調 ==================
async def on_verify_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理驗證按鈕點擊事件"""
    query = update.callback_query
    if not query or not query.data.startswith("verify_"):
        return

    # 解析用戶 ID
    try:
        user_id = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer("驗證參數錯誤", show_alert=True)
        return

    # 校驗點 1：點擊者必須是待驗證用戶
    if query.from_user.id != user_id:
        await query.answer("這不是你的驗證按鈕哦～", show_alert=True)
        return

    # 校驗點 2：驗證請求必須來自對應群組
    chat_id = query.message.chat_id
    if pending_verifications.get(user_id) != chat_id:
        await query.answer("驗證已過期或無效", show_alert=True)
        return

    # 驗證成功：解除禁言
    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=unmute_permissions(),
        until_date=0,
    )
    pending_verifications.pop(user_id, None)  # 移除待驗證記錄

    # 更新消息提示
    await query.edit_message_text(
        f"✅ {query.from_user.mention_html()} 驗證成功！\n已解除禁言，請遵守群規～",
        parse_mode="HTML",
    )

# ================== 機器人指令 ==================
async def banme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """自動禁言指令（用戶自願禁言 2 分鐘）"""
    chat = update.effective_chat
    user = update.effective_user

    # 僅群組可用
    if chat.type == "private":
        await update.message.reply_text("❌ 這個指令只能在群組中使用哦～")
        return

    # 執行禁言
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
    # 啟動延時解除禁言任務
    asyncio.create_task(delayed_unmute(context.bot, chat.id, user.id, 2))

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查詢機器人管理的群組（僅管理員可用）"""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("❌ 無權限執行此指令（僅管理員可用）")
        return

    if not known_groups:
        await update.message.reply_text("📭 尚未記錄任何群組（機器人未加入群組或未檢測到成員進群）")
        return

    # 生成群組清單
    group_list = "📋 機器人管理的群組清單：\n"
    for gid, name in known_groups.items():
        group_list += f"- 群組名稱：{name}\n  群組 ID：{gid}\n"
    await update.message.reply_text(group_list)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """啟動指令（私聊測試機器人狀態）"""
    await update.message.reply_text(
        f"🤖 Telegram 管理機器人已啟動！\n"
        f"版本：{BOT_VERSION}\n"
        f"可用指令：\n"
        f"/start - 查看機器人狀態\n"
        f"/banme - 自願禁言 2 分鐘（群組可用）\n"
        f"/list - 查詢管理群組（僅管理員可用）"
    )

# ================== 主程式入口 ==================
def main():
    """啟動機器人"""
    # 從環境變量獲取 Bot Token
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("❌ 未設置 BOT_TOKEN 環境變量，請先配置 Token")

    # 創建機器人應用
    application = Application.builder().token(bot_token).build()

    # 註冊處理器
    application.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))  # 進群處理
    application.add_handler(CallbackQueryHandler(on_verify_click))  # 驗證按鈕
    application.add_handler(CommandHandler("start", start))  # 啟動指令
    application.add_handler(CommandHandler("banme", banme))  # 自動禁言指令
    application.add_handler(CommandHandler("list", list_groups))  # 群組查詢指令

    logger.info(f"✅ Bot 啟動完成（版本：{BOT_VERSION}）")
    # 運行機器人（不限制更新類型）
    application.run_polling()

if __name__ == "__main__":
    main()

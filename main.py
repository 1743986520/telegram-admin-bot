import os
import re
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application, 
    ChatMemberHandler, 
    CallbackQueryHandler, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes, 
    filters
)

# 日誌配置
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 配置 
OWNER_ID = 7807347685
BOT_VERSION = "v1.9.3 (2026-01-05 終極修復版)"

known_groups = {}
pending_verifications = {}

# --- 工具函數 ---

def get_full_permissions():
    """返回所有開啟的權限，用於解除禁言"""
    return ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
        can_pin_messages=False, # 通常普通成員不給盯選
        can_change_info=False
    )

async def delayed_unmute(bot, user_id, chat_id, name, minutes):
    """定時解除禁言，確保 Task 不被中斷"""
    logger.info(f"等待 {minutes} 分鐘後解除 {user_id}")
    await asyncio.sleep(minutes * 60)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id, 
            user_id=user_id, 
            permissions=get_full_permissions()
        )
        await bot.send_message(chat_id=chat_id, text=f"🔊 {name} 禁言結束，已恢復發言。")
    except Exception as e:
        logger.error(f"解除禁言出錯: {e}")

# --- 事件處理 ---

async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """專門處理進群邏輯 (ChatMemberHandler)"""
    result = update.chat_member
    if not result:
        return

    # 只處理從「非成員」變成「成員」的情況
    if result.old_chat_member.status in ["left", "kicked"] and result.new_chat_member.status == "member":
        user = result.new_chat_member.user
        chat_id = result.chat.id
        known_groups[chat_id] = result.chat.title

        # 嘗試獲取 Bio (Bot 必須是管理員)
        try:
            member_info = await context.bot.get_chat(user.id)
            bio = member_info.bio or ""
        except:
            bio = ""

        # 檢查廣告
        if bool(re.search(r"@|\bhttps?://", bio, re.IGNORECASE)):
            await context.bot.restrict_chat_member(chat_id, user.id, ChatPermissions(can_send_messages=False))
            pending_verifications[user.id] = chat_id
            
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("👤 我是真人，點我驗證", callback_data=f"v_{user.id}")]])
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ {user.mention_html()}，您的簡介可疑，請在 5 分鐘內驗證。",
                reply_markup=kb,
                parse_mode="HTML"
            )
            # 5 分鐘後踢出邏輯...
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"歡迎 {user.mention_html()} 加入！", parse_mode="HTML")

async def on_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query.data.startswith("v_"): return
    
    target_user_id = int(query.data.split("_")[1])
    if query.from_user.id != target_user_id:
        await query.answer("這不是你的按鈕！", show_alert=True)
        return

    await query.answer("驗證成功")
    await context.bot.restrict_chat_member(query.message.chat_id, target_user_id, get_full_permissions())
    await query.edit_message_text(f"✅ {query.from_user.mention_html()} 驗證成功！", parse_mode="HTML")
    pending_verifications.pop(target_user_id, None)

# --- 指令 ---

async def ban_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if chat.type == "private": return

    try:
        # 立即禁言
        await context.bot.restrict_chat_member(chat.id, user.id, ChatPermissions(can_send_messages=False))
        await update.message.reply_text(f"🤐 {user.mention_html()} 已禁言 2 分鐘。", parse_mode="HTML")
        # 啟動非同步任務解除
        asyncio.create_task(delayed_unmute(context.bot, user.id, chat.id, user.mention_html(), 2))
    except Exception as e:
        logger.error(f"Banme 失敗: {e}")

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if not known_groups:
        await update.message.reply_text("無紀錄，請讓我在群組說句話。")
        return
    text = "📋 群組清單：\n" + "\n".join([f"- {v} ({k})" for k, v in known_groups.items()])
    await update.message.reply_text(text)

# --- 主程式 ---

def main():
    token = os.getenv("BOT_TOKEN") # 
    if not token: return

    # 必須在這裡明確聲明要接收的更新類型
    # chat_member 負責進群，message 負責文字，callback_query 負責按鈕
    app = Application.builder().token(token).build()

    # 1. 處理新成員進群 (最優先)
    app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    
    # 2. 處理驗證按鈕
    app.add_handler(CallbackQueryHandler(on_button_click))

    # 3. 處理指令
    app.add_handler(CommandHandler("banme", ban_me))
    app.add_handler(CommandHandler("list", list_groups))

    # 4. 追蹤群組 (用於更新 known_groups)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, 
        lambda u, c: known_groups.update({u.effective_chat.id: u.effective_chat.title})))

    logger.info("Bot 已啟動...")
    # 關鍵：必須包含 chat_member 更新類型
    app.run_polling(allowed_updates=["message", "chat_member", "callback_query"])

if __name__ == "__main__":
    main()

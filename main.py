import os
import re
import asyncio
import logging
from datetime import datetime

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

# 日誌設定
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 配置資訊 [cite: 1]
OWNER_ID = 7807347685
BOT_VERSION = "v1.9.2 (2026-01-05 修復版)"

# 全域變數
pending_verifications = {}
known_groups = {}
recent_members = {}

# --- 工具函數 ---

def has_spam_bio(bio: str) -> bool:
    """檢查簡介是否含有廣告連結"""
    if not bio:
        return False
    return bool(re.search(r"@|\bhttps?://", bio, re.IGNORECASE))

async def delayed_unmute(bot, user_id, chat_id, name, minutes):
    """定時解除禁言協程"""
    logger.info(f"啟動計時器：{minutes} 分鐘後解除 {name} ({user_id}) 的禁言")
    await asyncio.sleep(minutes * 60)
    try:
        # 恢復所有權限
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_invite_users=True
        )
        await bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=permissions)
        await bot.send_message(
            chat_id=chat_id, 
            text=f"🔊 {name} 的禁言時間已到，已恢復發言權限！", 
            parse_mode="HTML"
        )
        logger.info(f"成功解除禁言: {user_id}")
    except Exception as e:
        logger.error(f"自動解除禁言失敗: {e}")

async def delayed_kick(bot, user_id, chat_id):
    """驗證超時踢出協程"""
    await asyncio.sleep(300)
    if user_id in pending_verifications:
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await bot.unban_chat_member(chat_id=chat_id, user_id=user_id) # 踢出而非永久封鎖
            await bot.send_message(chat_id=chat_id, text="驗證超時，已自動踢出該成員。")
            pending_verifications.pop(user_id, None)
        except Exception as e:
            logger.error(f"踢出失敗: {e}")

# --- 事件處理 ---

async def track_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """記錄群組與成員資訊"""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or chat.type not in ["group", "supergroup"]:
        return

    known_groups[chat.id] = chat.title or "未知群組"
    
    if update.message and update.message.text:
        if chat.id not in recent_members:
            recent_members[chat.id] = {}
        recent_members[chat.id][user.id] = (user.full_name, user.username or "無")

async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理新成員加入（包含驗證邏輯）"""
    # 支援兩種更新類型
    if update.chat_member:
        new_status = update.chat_member.new_chat_member
        if update.chat_member.old_chat_member.status == "member" or new_status.status != "member":
            return
        user = new_status.user
        chat_id = update.chat_member.chat.id
    elif update.message and update.message.new_chat_members:
        user = update.message.new_chat_members[0]
        chat_id = update.message.chat.id
    else:
        return

    try:
        # 更新群組清單
        chat_info = await context.bot.get_chat(chat_id)
        known_groups[chat_id] = chat_info.title
        
        # 獲取 Bio (需要 Bot 有管理權限)
        member = await context.bot.get_chat_member(chat_id, user.id)
        bio = getattr(member.user, "bio", "") or ""
        
        if has_spam_bio(bio):
            await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user.id, permissions=ChatPermissions(can_send_messages=False))
            pending_verifications[user.id] = chat_id
            
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("👤 我是真人，點我驗證", callback_data=f"verify_{user.id}_{chat_id}")
            ]])
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ {user.mention_html()}，偵測到您的簡介含敏感連結。\n請在 5 分鐘內點擊按鈕完成驗證，否則將被踢出。",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            asyncio.create_task(delayed_kick(context.bot, user.id, chat_id))
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"歡迎 {user.mention_html()} 加入本群！", parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"處理新成員時發生錯誤: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理驗證按鈕"""
    query = update.callback_query
    if not query.data.startswith("verify_"):
        return

    _, user_id_str, chat_id_str = query.data.split("_")
    user_id, chat_id = int(user_id_str), int(chat_id_str)

    if query.from_user.id != user_id:
        await query.answer("這不是你的驗證按鈕！", show_alert=True)
        return

    await query.answer("驗證成功！")
    try:
        permissions = ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
        await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=permissions)
        await query.edit_message_text(f"✅ {query.from_user.mention_html()} 驗證通過，歡迎加入！", parse_mode="HTML")
        pending_verifications.pop(user_id, None)
    except Exception as e:
        logger.error(f"驗證通過但恢復權限失敗: {e}")

# --- 指令處理 ---

async def ban_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/banme 指令：禁言自己 2 分鐘"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        await update.message.reply_text("請在群組內使用此指令。")
        return

    try:
        await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user.id, permissions=ChatPermissions(can_send_messages=False))
        await update.message.reply_text(f"🤐 好的，{user.mention_html()} 已被禁言 2 分鐘。請冷靜一下。", parse_mode="HTML")
        asyncio.create_task(delayed_unmute(context.bot, user.id, chat_id, user.mention_html(), 2))
    except Exception as e:
        await update.message.reply_text(f"禁言失敗：{e}")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ban <編號> <ID> <時間> (Owner Only)"""
    if update.effective_user.id != OWNER_ID: return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("用法: /ban <群組編號> <User_ID> [分鐘]")
        return
    
    try:
        idx = int(args[0]) - 1
        target_user_id = int(args[1])
        minutes = int(args[2]) if len(args) >= 3 else 60
        chat_id = sorted(known_groups.keys())[idx]

        await context.bot.restrict_chat_member(chat_id=chat_id, user_id=target_user_id, permissions=ChatPermissions(can_send_messages=False))
        
        try:
            member = await context.bot.get_chat_member(chat_id, target_user_id)
            name = member.user.mention_html()
        except:
            name = f"用戶 {target_user_id}"

        asyncio.create_task(delayed_unmute(context.bot, target_user_id, chat_id, name, minutes))
        await update.message.reply_text(f"✅ 已在群組「{known_groups[chat_id]}」禁言該用戶 {minutes} 分鐘")
    except Exception as e:
        await update.message.reply_text(f"❌ 操作失敗: {e}")

# --- 其他管理指令 (Owner Only) ---

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text(f"🔧 管理員指令 ({BOT_VERSION}):\n/list - 群組列表\n/members <編號>\n/ban <編號> <ID> <分>\n/endorsement <編號> <內容>")

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if not known_groups:
        await update.message.reply_text("暫無紀錄。")
        return
    msg = "📋 群組列表：\n"
    for i, (cid, title) in enumerate(sorted(known_groups.items()), 1):
        msg += f"{i}. {title} ({cid})\n"
    await update.message.reply_text(msg)

async def list_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        idx = int(context.args[0]) - 1
        chat_id = sorted(known_groups.keys())[idx]
        members = recent_members.get(chat_id, {})
        msg = f"👥 「{known_groups[chat_id]}」最近活躍：\n"
        for uid, (name, uname) in list(members.items())[-20:]:
            msg += f"- {name} (@{uname}): {uid}\n"
        await update.message.reply_text(msg)
    except:
        await update.message.reply_text("請輸入正確的編號")

# --- 主程式 ---

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("未找到 BOT_TOKEN！")
        return

    # 初始化 Application
    app = Application.builder().token(token).build()

    # 註冊處理程序
    # 重要：ChatMemberHandler 必須放在 MessageHandler 之前
    app.add_handler(ChatMemberHandler(handle_new_member, chat_member_types=ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_member))
    
    app.add_handler(CommandHandler("banme", ban_me))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("list", list_groups))
    app.add_handler(CommandHandler("members", list_members))
    app.add_handler(CommandHandler("ban", ban_user))
    
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # 群組訊息追蹤 (排除指令以免衝突)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, track_group_message))

    logger.info(f"Bot {BOT_VERSION} 啟動中...")
    
    # 啟動並設定 allowed_updates 以確保接收所有必要更新 
    app.run_polling(allowed_updates=["message", "chat_member", "callback_query"])

if __name__ == "__main__":
    main()

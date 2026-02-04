import os
import re
import asyncio
import time
from collections import defaultdict
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
    ChatMemberAdministrator,
)
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ================== 基本設定 ==================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)
OWNER_ID = 7807347685  # 替換為你的 Telegram ID（@userinfobot 查詢）
BOT_VERSION = "v2.3.0-fixed-all"
known_groups: dict[int, str] = defaultdict(str)  # 存儲已加入群組
pending_verifications: dict[int, int] = {}  # user_id -> chat_id

# ================== 權限設定（完整修復） ==================
def mute_permissions() -> ChatPermissions:
    """禁言權限（完全限制）"""
    return ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )

def unmute_permissions() -> ChatPermissions:
    """解除禁言（正常用戶權限）"""
    return ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
        can_manage_topics=False,
    )

# ================== 工具函數 ==================
async def delayed_unmute(bot, chat_id: int, user_id: int, minutes: int):
    """延遲解除禁言"""
    await asyncio.sleep(minutes * 60)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=unmute_permissions(),
        )
        await bot.send_message(chat_id, f"🔊 禁言已解除（{minutes}分鐘到期），請遵守群規～")
    except Exception as e:
        logger.error(f"解除禁言失敗：chat_id={chat_id}, user_id={user_id}, 錯誤：{e}")
        await bot.send_message(chat_id, "❌ 解除禁言失敗，請管理員手動操作")

async def check_bot_permissions(bot, chat_id: int) -> tuple[bool, str]:
    """檢查機器人權限"""
    try:
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        if not isinstance(bot_member, ChatMemberAdministrator):
            return False, "機器人不是管理員"
        
        if not bot_member.can_restrict_members:
            return False, "缺少「限制成員」權限"
        
        if bot_member.is_anonymous:
            return False, "請關閉「匿名管理員」模式"
        
        return True, "權限正常"
    except Exception as e:
        return False, f"檢查權限失敗：{e}"

# ================== 進群處理（自動驗證可疑用戶） ==================
async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理新成員加入"""
    try:
        result = update.chat_member
        if not result:
            return

        old_status = result.old_chat_member.status
        new_status = result.new_chat_member.status
        user = result.new_chat_member.user
        chat = result.chat
        
        # 記錄群組
        known_groups[chat.id] = chat.title
        logger.info(f"📝 記錄群組：{chat.title} (ID: {chat.id})")
        
        # 處理新成員加入
        if old_status in ("left", "kicked", "restricted") and new_status == "member":
            logger.info(f"👤 新成員加入：{user.full_name} (@{user.username}) 在 {chat.title}")
            
            # 發送歡迎消息（非可疑用戶）
            try:
                await context.bot.send_message(
                    chat.id,
                    f"🎉 歡迎 {user.mention_html()} 加入 {chat.title}！",
                    parse_mode="HTML",
                )
            except:
                pass  # 忽略歡迎消息錯誤
            
            # 檢查用戶簡介
            try:
                user_chat = await asyncio.wait_for(context.bot.get_chat(user.id), timeout=5)
                bio = user_chat.bio or ""
                logger.info(f"用戶簡介：{bio[:50]}...")
            except Exception:
                bio = ""
                logger.warning(f"無法獲取用戶 {user.id} 的簡介")
            
            # 檢測可疑內容
            suspicious = False
            suspicious_reasons = []
            
            if re.search(r"@\w+", bio, re.IGNORECASE):
                suspicious = True
                suspicious_reasons.append("包含@標籤")
            
            if re.search(r"https?://", bio, re.IGNORECASE):
                suspicious = True
                suspicious_reasons.append("包含網址")
            
            if suspicious:
                logger.info(f"⚠️ 檢測到可疑用戶：{user.id}，原因：{', '.join(suspicious_reasons)}")
                
                # 檢查機器人權限
                has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
                if not has_perms:
                    await context.bot.send_message(
                        chat.id,
                        f"⚠️ 檢測到可疑用戶 {user.mention_html()}，但機器人權限不足：{perm_msg}",
                        parse_mode="HTML"
                    )
                    return
                
                # 禁言可疑用戶
                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=user.id,
                        permissions=mute_permissions(),
                    )
                    
                    pending_verifications[user.id] = chat.id
                    
                    # 創建驗證按鈕
                    keyboard = [[
                        InlineKeyboardButton(
                            "👤 我是真人（點擊驗證）",
                            callback_data=f"verify_{user.id}"
                        )
                    ]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        chat.id,
                        f"⚠️ {user.mention_html()} 請完成真人驗證（簡介包含可疑內容：{', '.join(suspicious_reasons)}）",
                        reply_markup=reply_markup,
                        parse_mode="HTML",
                    )
                    
                    logger.info(f"✅ 已禁言可疑用戶 {user.id}，等待驗證")
                    
                except Exception as e:
                    logger.error(f"禁言可疑用戶失敗：{e}")
                    await context.bot.send_message(
                        chat.id,
                        f"❌ 無法禁言可疑用戶 {user.mention_html()}，請管理員手動處理",
                        parse_mode="HTML"
                    )
                    
    except Exception as e:
        logger.error(f"處理成員事件失敗：{e}", exc_info=True)

# ================== 驗證按鈕處理 ==================
async def on_verify_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理驗證按鈕點擊"""
    query = update.callback_query
    if not query:
        return
    
    # 立即回應按鈕點擊
    await query.answer()
    
    try:
        if not query.data.startswith("verify_"):
            await query.edit_message_text("❌ 無效的驗證請求")
            return
        
        user_id = int(query.data.split("_")[1])
        chat_id = query.message.chat_id
        
        # 驗證用戶身份
        if query.from_user.id != user_id:
            await query.answer("⚠️ 這不是你的驗證按鈕", show_alert=True)
            return
        
        # 檢查驗證是否有效
        if pending_verifications.get(user_id) != chat_id:
            await query.edit_message_text("❌ 驗證已過期或無效")
            return
        
        # 解除禁言
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=unmute_permissions(),
            )
            
            # 從待驗證列表中移除
            pending_verifications.pop(user_id, None)
            
            await query.edit_message_text(
                f"✅ {query.from_user.mention_html()} 驗證成功！歡迎加入群組～",
                parse_mode="HTML",
            )
            
            logger.info(f"✅ 用戶 {user_id} 驗證成功，已解除禁言")
            
        except Exception as e:
            logger.error(f"解除禁言失敗：{e}")
            await query.edit_message_text("❌ 驗證成功但解除禁言失敗，請聯繫管理員")
            
    except Exception as e:
        logger.error(f"處理驗證按鈕失敗：{e}")
        await query.edit_message_text("❌ 驗證處理失敗")

# ================== 指令處理 ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /start 指令"""
    user = update.effective_user
    chat = update.effective_chat
    
    logger.info(f"📱 /start 來自用戶 {user.id}，場景：{chat.type}")
    
    if chat.type == "private":
        welcome_text = f"""
🤖 Telegram 管理機器人 {BOT_VERSION}

👤 你的 ID: `{user.id}`
🔧 機器人狀態: 正常運行

📌 可用指令:
/start - 查看狀態和指令列表
/banme - 群組內自願禁言 2 分鐘（僅群組可用）
/list - 私聊查詢管理群組（僅管理員）

⚠️  重要配置:
1. 向 @BotFather 設置指令列表 (/setcommands)
2. 將機器人設為群組管理員
3. 開啟「限制成員」權限
4. 關閉「匿名管理員」

📊 當前狀態:
- 管理群組數: {len(known_groups)}
- 待驗證用戶: {len(pending_verifications)}
"""
        await update.message.reply_text(welcome_text, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"🤖 機器人正常運作\n試試 /banme 自願禁言2分鐘",
            parse_mode="HTML"
        )

async def banme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /banme 指令（自願禁言）"""
    chat = update.effective_chat
    user = update.effective_user
    
    logger.info(f"🔇 /banme 來自用戶 {user.id}，群組 {chat.id}")
    
    # 僅群組可用
    if chat.type == "private":
        await update.message.reply_text(
            "❌ 此指令僅在群組中可用！\n"
            "請在群聊中發送 /banme 自願禁言。"
        )
        return
    
    # 檢查機器人權限
    has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
    if not has_perms:
        await update.message.reply_text(
            f"❌ 機器人權限不足：{perm_msg}\n\n"
            "請確認：\n"
            "1. 機器人已設為管理員\n"
            "2. 開啟「限制成員」權限\n"
            "3. 關閉「匿名管理員」"
        )
        return
    
    try:
        # 檢查用戶是否已經是管理員
        user_member = await chat.get_member(user.id)
        if user_member.status in ["administrator", "creator"]:
            await update.message.reply_text("❌ 管理員不能使用此指令！")
            return
        
        # 執行禁言
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=mute_permissions(),
        )
        
        await update.message.reply_text(
            f"🤐 {user.mention_html()} 已自願禁言 2 分鐘\n"
            f"時間到後會自動解除～",
            parse_mode="HTML"
        )
        
        logger.info(f"✅ 已禁言用戶 {user.id} 2 分鐘")
        
        # 2分鐘後自動解除
        asyncio.create_task(delayed_unmute(context.bot, chat.id, user.id, 2))
        
    except Exception as e:
        logger.error(f"/banme 失敗：{e}", exc_info=True)
        error_msg = str(e).lower()
        
        if "not enough rights" in error_msg or "can't restrict" in error_msg:
            await update.message.reply_text(
                "❌ 禁言失敗！權限不足。\n"
                "請確認機器人有「限制成員」權限。"
            )
        elif "user is an administrator" in error_msg:
            await update.message.reply_text("❌ 無法禁言管理員！")
        else:
            await update.message.reply_text(f"❌ 禁言失敗：{e}")

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /list 指令（查看管理群組）"""
    user = update.effective_user
    chat = update.effective_chat
    
    logger.info(f"📋 /list 來自用戶 {user.id}")
    
    # 僅私聊可用
    if chat.type != "private":
        await update.message.reply_text(
            "❌ 此指令僅支持私聊使用！\n"
            "請直接私聊機器人發送 /list"
        )
        return
    
    # 僅管理員可用
    if user.id != OWNER_ID:
        await update.message.reply_text(
            "❌ 無權限執行此指令！\n"
            f"僅管理員 (ID: {OWNER_ID}) 可使用。"
        )
        return
    
    # 生成群組列表
    if not known_groups:
        await update.message.reply_text(
            "📭 尚未記錄任何群組\n\n"
            "可能原因：\n"
            "1. 機器人未加入任何群組\n"
            "2. 群組中暫無新成員加入\n"
            "3. 等待新成員觸發記錄"
        )
        return
    
    group_list = "📋 管理的群組清單：\n\n"
    for idx, (gid, name) in enumerate(known_groups.items(), 1):
        group_list += f"{idx}. {name}\n   ID: `{gid}`\n\n"
    
    group_list += f"總計: {len(known_groups)} 個群組"
    
    await update.message.reply_text(group_list, parse_mode="Markdown")

# ================== 錯誤處理 ==================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """全局錯誤處理"""
    logger.error(f"發生錯誤：{context.error}", exc_info=True)
    
    if update and update.effective_message:
        try:
            error_msg = str(context.error).lower()
            
            if "invalid token" in error_msg:
                await update.effective_message.reply_text(
                    "❌ Token 無效！\n"
                    "請檢查 BOT_TOKEN 環境變量是否正確。"
                )
            elif "not enough rights" in error_msg or "can't restrict" in error_msg:
                await update.effective_message.reply_text(
                    "❌ 權限不足！\n"
                    "請確認機器人有管理員權限和「限制成員」權限。"
                )
            else:
                await update.effective_message.reply_text(
                    f"❌ 發生錯誤：{context.error}\n"
                    "請查看 bot.log 獲取詳細信息。"
                )
        except:
            pass  # 忽略回復錯誤

# ================== 主程式 ==================
def main():
    """主程序入口"""
    # 檢查 Token
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("❌ 未設置 BOT_TOKEN 環境變量！")
        print("❌ 錯誤：未設置 BOT_TOKEN")
        print("請執行：export BOT_TOKEN='你的Token'")
        print("或編輯 ~/.bashrc 添加 export BOT_TOKEN='你的Token'")
        return
    
    # 檢查 Python 版本
    import sys
    if sys.version_info < (3, 12):
        logger.error("❌ Python 版本低於 3.12")
        print("❌ 請升級 Python 到 3.12+ 版本")
        return
    
    # 創建應用
    try:
        application = Application.builder().token(bot_token).build()
        logger.info(f"✅ 應用創建成功，Python {sys.version.split()[0]}")
    except Exception as e:
        logger.error(f"創建應用失敗：{e}")
        print(f"❌ 創建應用失敗：{e}")
        return
    
    # 註冊錯誤處理器
    application.add_error_handler(error_handler)
    
    # 註冊處理器（重要：順序正確）
    # 1. 先註冊指令處理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("banme", banme))
    application.add_handler(CommandHandler("list", list_groups))
    
    # 2. 註冊按鈕回調
    application.add_handler(CallbackQueryHandler(on_verify_click))
    
    # 3. 註冊成員變化處理器（最後）
    application.add_handler(
        ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER)
    )
    
    # 啟動信息
    print(f"\n{'='*50}")
    print(f"🤖 Telegram Admin Bot {BOT_VERSION}")
    print(f"🐍 Python {sys.version.split()[0]}")
    print(f"🔑 Token: {bot_token[:10]}...{bot_token[-10:]}")
    print(f"👤 Owner ID: {OWNER_ID}")
    print(f"{'='*50}")
    print("✅ 機器人正在啟動...")
    print("📝 查看日誌：tail -f bot.log")
    print("\n⚠️  重要檢查：")
    print("1. 已在 @BotFather 設置 /setcommands")
    print("2. 機器人在群組中是管理員")
    print("3. 開啟了「限制成員」權限")
    print("4. 關閉了「匿名管理員」")
    print(f"{'='*50}\n")
    
    # 啟動機器人
    try:
        application.run_polling(
            allowed_updates=[
                Update.MESSAGE,
                Update.CALLBACK_QUERY,
                Update.CHAT_MEMBER,
                Update.MY_CHAT_MEMBER,
            ],
            drop_pending_updates=True,  # 清理舊更新
            close_loop=False,
        )
    except KeyboardInterrupt:
        logger.info("機器人手動停止")
        print("\n👋 機器人已停止")
    except Exception as e:
        logger.error(f"運行失敗：{e}")
        print(f"❌ 運行失敗：{e}")

if __name__ == "__main__":
    main()
import os
import re
import asyncio
import time
from typing import Optional, Dict
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
    ChatMember,
    Chat,
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
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ],
)
logger = logging.getLogger(__name__)

# === 從環境變量讀取 OWNER_ID ===
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
BOT_VERSION = "v4.0.0-stealth-mode"

# 數據存儲
known_groups: Dict[int, Dict] = {}
pending_verifications: Dict[int, int] = {}

# ================== 權限設定 ==================
def create_mute_permissions():
    """創建禁言權限"""
    try:
        return ChatPermissions(can_send_messages=False)
    except:
        return ChatPermissions(can_send_messages=False)

def create_unmute_permissions():
    """創建解除禁言權限"""
    try:
        return ChatPermissions(can_send_messages=True)
    except:
        return ChatPermissions(can_send_messages=True)

# ================== 工具函數 ==================
def save_known_groups():
    """保存群組數據到文件"""
    try:
        with open("known_groups.json", "w", encoding='utf-8') as f:
            import json
            json.dump(known_groups, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存群組數據失敗: {e}")

def load_known_groups():
    """從文件加載群組數據"""
    global known_groups
    try:
        with open("known_groups.json", "r", encoding='utf-8') as f:
            import json
            known_groups = json.load(f)
            known_groups = {int(k): v for k, v in known_groups.items()}
    except FileNotFoundError:
        known_groups = {}
    except Exception as e:
        logger.error(f"加載群組數據失敗: {e}")
        known_groups = {}

async def delayed_unmute(bot, chat_id: int, user_id: int, minutes: int):
    """延遲解除禁言"""
    await asyncio.sleep(minutes * 60)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=create_unmute_permissions(),
        )
        logger.info(f"✅ 自動解除禁言: 用戶 {user_id} 在群組 {chat_id}")
    except Exception as e:
        logger.error(f"解除禁言失敗: {e}")

async def check_bot_permissions(bot, chat_id: int) -> tuple[bool, str]:
    """檢查機器人權限"""
    try:
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        
        if bot_member.status != "administrator" and bot_member.status != "creator":
            return False, "❌ 機器人不是管理員"
        
        if bot_member.status == "administrator":
            if not hasattr(bot_member, 'can_restrict_members') or not bot_member.can_restrict_members:
                return False, "❌ 缺少「限制成員」權限"
        
        return True, "✅ 權限正常"
    except Exception as e:
        return False, f"❌ 檢查權限失敗: {e}"

# ================== 處理機器人加入群組（取消自我介紹） ==================
async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理機器人自己被加入/移除群組（靜默模式）"""
    try:
        chat_member = update.my_chat_member
        if not chat_member:
            return
        
        chat = chat_member.chat
        old_status = chat_member.old_chat_member.status
        new_status = chat_member.new_chat_member.status
        
        logger.info(f"🤖 機器人狀態變化: {chat.title} | {old_status} -> {new_status}")
        
        if old_status in ["left", "kicked"] and new_status in ["member", "administrator"]:
            known_groups[chat.id] = {
                "title": chat.title,
                "added_at": time.time(),
                "type": chat.type,
                "status": new_status
            }
            save_known_groups()
            logger.info(f"✅ 靜默加入群組: {chat.title} (ID: {chat.id})")
            # 不再發送歡迎消息
        
        elif new_status in ["left", "kicked"]:
            if chat.id in known_groups:
                del known_groups[chat.id]
                save_known_groups()
                logger.info(f"🗑️ 移除群組記錄: {chat.title}")
                
    except Exception as e:
        logger.error(f"處理機器人狀態失敗: {e}")

# ================== 處理新成員加入（自動驗證） ==================
async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理普通成員加入"""
    try:
        chat_member = update.chat_member
        if not chat_member:
            return
        
        user = chat_member.new_chat_member.user
        chat = chat_member.chat
        old_status = chat_member.old_chat_member.status
        new_status = chat_member.new_chat_member.status
        
        if chat.id not in known_groups:
            known_groups[chat.id] = {
                "title": chat.title,
                "added_at": time.time(),
                "type": chat.type,
                "status": "unknown"
            }
            save_known_groups()
        
        if old_status in ["left", "kicked"] and new_status == "member":
            logger.info(f"👤 新成員: {user.full_name} 加入 {chat.title}")
            
            bio = ""
            try:
                user_chat = await context.bot.get_chat(user.id)
                bio = user_chat.bio or ""
            except:
                pass
            
            is_suspicious = False
            reasons = []
            
            if re.search(r"@\w+", bio, re.IGNORECASE):
                is_suspicious = True
                reasons.append("@標籤")
            
            if re.search(r"https?://|t\.me/", bio, re.IGNORECASE):
                is_suspicious = True
                reasons.append("網址/連結")
            
            if is_suspicious:
                logger.info(f"⚠️ 可疑用戶: {user.id}, 原因: {reasons}")
                
                has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
                if not has_perms:
                    # 靜默模式，不再發送公開消息
                    return
                
                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=user.id,
                        permissions=create_mute_permissions(),
                    )
                    
                    pending_verifications[user.id] = chat.id
                    
                    keyboard = [[
                        InlineKeyboardButton(
                            "✅ 我是真人，點擊驗證",
                            callback_data=f"verify_{user.id}"
                        )
                    ]]
                    
                    await context.bot.send_message(
                        chat.id,
                        f"⚠️ {user.mention_html()} 需要完成安全驗證",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="HTML"
                    )
                    
                except Exception as e:
                    logger.error(f"禁言失敗: {e}")
            
            # 取消正常用戶的歡迎消息
                    
    except Exception as e:
        logger.error(f"處理成員失敗: {e}")

# ================== 驗證按鈕處理 ==================
async def on_verify_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理驗證按鈕"""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    try:
        if not query.data.startswith("verify_"):
            return
        
        user_id = int(query.data.split("_")[1])
        chat_id = query.message.chat_id
        
        if query.from_user.id != user_id:
            await query.answer("這不是你的驗證按鈕！", show_alert=True)
            return
        
        if pending_verifications.get(user_id) != chat_id:
            await query.edit_message_text("❌ 驗證已過期")
            return
        
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=create_unmute_permissions(),
            )
            
            pending_verifications.pop(user_id, None)
            
            await query.edit_message_text(
                f"✅ {query.from_user.mention_html()} 驗證成功",
                parse_mode="HTML"
            )
            
        except Exception as e:
            await query.edit_message_text("❌ 解除禁言失敗")
            
    except Exception as e:
        logger.error(f"驗證處理失敗: {e}")

# ================== 私聊過濾器 ==================
async def private_chat_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """檢查是否允許私聊"""
    if update.effective_chat.type != "private":
        return True
    
    user_id = update.effective_user.id
    
    # 只允許管理員私聊
    if user_id == OWNER_ID:
        return True
    
    # 其他用戶拒絕私聊
    if update.message:
        await update.message.reply_text(
            "🚫 此機器人不接受私聊\n"
            "如需使用功能，請在群組中使用",
            parse_mode="HTML"
        )
    
    return False

# ================== 指令處理 ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /start 指令（僅管理員可用）"""
    if not await private_chat_filter(update, context):
        return
    
    user = update.effective_user
    
    response = f"""
🕶️ 隱形管理機器人 {BOT_VERSION}

👤 管理員 ID: `{OWNER_ID}`
📊 當前狀態:
- 管理群組數: {len(known_groups)}
- 待驗證用戶: {len(pending_verifications)}

🔧 運行模式: 隱形模式
✅ 所有功能正常
"""
    
    await update.message.reply_text(response, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /help 指令（僅管理員可用）"""
    if not await private_chat_filter(update, context):
        return
    
    await update.message.reply_text(
        "📖 隱形管理機器人幫助\n\n"
        "🤖 機器人特性:\n"
        "- 靜默加入群組，不發送歡迎消息\n"
        "- 自動檢測可疑新成員\n"
        "- 不接受非管理員私聊\n"
        "- 隱形管理模式\n\n"
        "📋 管理員指令:\n"
        "/start - 查看狀態\n"
        "/list - 查看管理群組\n\n"
        "🎯 群組功能:\n"
        "/banme - 發現驚喜（群組成員專用）",
        parse_mode="HTML"
    )

async def banme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /banme 指令（驚喜模式）"""
    chat = update.effective_chat
    user = update.effective_user
    
    logger.info(f"🎁 /banme 驚喜: 用戶 {user.id} 在群組 {chat.id}")
    
    if chat.type == "private":
        await update.message.reply_text(
            "🎯 這個驚喜只能在群組中發現哦！\n"
            "快回群組試試吧～",
            parse_mode="HTML"
        )
        return
    
    # 檢查用戶是否管理員
    try:
        user_member = await chat.get_member(user.id)
        if user_member.status in ["administrator", "creator"]:
            await update.message.reply_text(
                "👑 管理員大人，這個驚喜是給普通成員準備的啦！\n"
                "您就別湊熱鬧了～",
                parse_mode="HTML"
            )
            return
    except:
        pass
    
    # 檢查機器人權限
    has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
    if not has_perms:
        # 隱形模式，不公開提示權限問題
        return
    
    try:
        # 執行禁言（驚喜！）
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=create_mute_permissions(),
        )
        
        # 有趣的回應
        responses = [
            f"🎉 {user.mention_html()} 發現了隱藏驚喜！獲得2分鐘安靜時間～",
            f"🤫 {user.mention_html()} 觸發了神秘機關！請享受2分鐘靜音體驗",
            f"🔇 {user.mention_html()} 成功解鎖「禁言成就」！冷卻時間：2分鐘",
            f"⏳ {user.mention_html()} 的發言技能正在冷卻中...（2分鐘）",
            f"🎁 {user.mention_html()} 打開了潘多拉魔盒！獲得2分鐘沉默 buff"
        ]
        
        import random
        response = random.choice(responses)
        
        await update.message.reply_text(
            response + "\n\n⏰ 時間到自動恢復，請耐心等待～",
            parse_mode="HTML"
        )
        
        # 2分鐘後解除
        asyncio.create_task(delayed_unmute(context.bot, chat.id, user.id, 2))
        
    except Exception as e:
        logger.error(f"/banme 失敗: {e}")
        # 隱形模式，失敗也不提示

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /list 指令（僅管理員可用）"""
    if not await private_chat_filter(update, context):
        return
    
    user = update.effective_user
    
    if not known_groups:
        await update.message.reply_text("📭 還沒有管理任何群組")
        return
    
    groups_text = "🕶️ 隱形管理的群組:\n\n"
    for idx, (chat_id, info) in enumerate(known_groups.items(), 1):
        title = info.get('title', '未知群組')
        status = info.get('status', 'unknown')
        groups_text += f"{idx}. {title}\n   ID: `{chat_id}`\n\n"
    
    groups_text += f"總計: {len(known_groups)} 個群組"
    
    await update.message.reply_text(groups_text, parse_mode="Markdown")

# ================== 錯誤處理 ==================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """全局錯誤處理"""
    logger.error(f"錯誤: {context.error}", exc_info=True)

# ================== 主程式 ==================
def main():
    """主程序"""
    # 檢查環境變量
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        print("❌ 錯誤: 未設置 BOT_TOKEN")
        print("請執行: export BOT_TOKEN='你的Token'")
        return
    
    owner_id = os.getenv("OWNER_ID")
    if not owner_id:
        print("❌ 錯誤: 未設置 OWNER_ID")
        print("請執行: export OWNER_ID='你的TelegramID'")
        return
    
    global OWNER_ID
    try:
        OWNER_ID = int(owner_id)
    except ValueError:
        print("❌ 錯誤: OWNER_ID 必須是數字")
        return
    
    # 加載群組數據
    load_known_groups()
    
    # 創建應用
    application = Application.builder().token(bot_token).build()
    
    # 註冊處理器（添加過濾器）
    application.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("help", help_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("banme", banme, filters=filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP))
    application.add_handler(CommandHandler("list", list_groups, filters=filters.ChatType.PRIVATE))
    
    application.add_handler(CallbackQueryHandler(on_verify_click))
    
    application.add_handler(ChatMemberHandler(
        handle_my_chat_member, 
        ChatMemberHandler.MY_CHAT_MEMBER
    ))
    
    application.add_handler(ChatMemberHandler(
        handle_chat_member,
        ChatMemberHandler.CHAT_MEMBER
    ))
    
    application.add_error_handler(error_handler)
    
    # 啟動信息
    print(f"\n{'='*60}")
    print(f"🕶️ 隱形管理機器人 {BOT_VERSION}")
    print(f"👤 管理員 ID: {OWNER_ID}")
    print(f"📊 已記錄群組: {len(known_groups)} 個")
    print(f"🔧 運行模式: 隱形模式")
    print(f"📝 日誌文件: bot.log")
    print(f"{'='*60}")
    print("\n✅ 機器人正在靜默運行中...")
    print("💡 特點:")
    print("- 靜默加入群組，不發歡迎消息")
    print("- 不接受非管理員私聊")
    print("- /banme 變成驚喜功能")
    print("- 只記錄日誌，減少公開提示")
    
    # 啟動
    try:
        application.run_polling(
            allowed_updates=[
                Update.MESSAGE,
                Update.CALLBACK_QUERY,
                Update.CHAT_MEMBER,
                Update.MY_CHAT_MEMBER,
            ],
            drop_pending_updates=False,
        )
    except KeyboardInterrupt:
        print("\n👋 機器人已停止")
    except Exception as e:
        print(f"❌ 啟動失敗: {e}")

if __name__ == "__main__":
    main()
import os
import re
import asyncio
import time
from typing import Dict
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
    ChatMember,
)
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
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
OWNER_ID = int(os.getenv("OWNER_ID", "0"))  # 默認為0，需要從安裝腳本設置
BOT_VERSION = "v4.0.0-silent"

# 數據存儲
known_groups: Dict[int, Dict] = {}
pending_verifications: Dict[int, int] = {}

# ================== 權限設定 ==================
def create_mute_permissions():
    """創建禁言權限"""
    try:
        return ChatPermissions(can_send_messages=False)
    except:
        return ChatPermissions(**{'can_send_messages': False})

def create_unmute_permissions():
    """創建解除禁言權限"""
    try:
        return ChatPermissions(can_send_messages=True)
    except:
        return ChatPermissions(**{'can_send_messages': True})

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
        logger.info(f"✅ 自動解除禁言: 用戶 {user_id}")
    except Exception as e:
        logger.error(f"解除禁言失敗: {e}")

async def check_bot_permissions(bot, chat_id: int) -> tuple[bool, str]:
    """檢查機器人權限"""
    try:
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        
        if bot_member.status not in ["administrator", "creator"]:
            return False, "❌ 機器人不是管理員"
        
        if bot_member.status == "administrator":
            if not hasattr(bot_member, 'can_restrict_members') or not bot_member.can_restrict_members:
                return False, "❌ 缺少「限制成員」權限"
        
        return True, "✅ 權限正常"
    except Exception as e:
        return False, f"❌ 檢查權限失敗: {e}"

# ================== 處理機器人加入群組（無自我介紹） ==================
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
            # 不再發送自我介紹消息
        
        elif new_status in ["left", "kicked"]:
            if chat.id in known_groups:
                del known_groups[chat.id]
                save_known_groups()
                logger.info(f"🗑️ 移除群組記錄: {chat.title}")
                
    except Exception as e:
        logger.error(f"處理機器人狀態失敗: {e}")

# ================== 處理新成員加入 ==================
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
                    return  # 靜默模式，不發送消息
                
                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=user.id,
                        permissions=create_mute_permissions(),
                    )
                    
                    pending_verifications[user.id] = chat.id
                    
                    keyboard = [[
                        InlineKeyboardButton(
                            "✅ 點擊驗證身份",
                            callback_data=f"verify_{user.id}"
                        )
                    ]]
                    
                    await context.bot.send_message(
                        chat.id,
                        f"🛡️ {user.mention_html()} 需要驗證身份\n原因: {', '.join(reasons)}",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="HTML"
                    )
                    
                except Exception as e:
                    logger.error(f"禁言失敗: {e}")
            
            # 正常用戶不發送歡迎消息（靜默模式）
                    
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
                f"✅ {query.from_user.mention_html()} 驗證通過",
                parse_mode="HTML"
            )
            
        except Exception as e:
            await query.edit_message_text("❌ 解除禁言失敗")
            
    except Exception as e:
        logger.error(f"驗證處理失敗: {e}")

# ================== 私聊過濾器 ==================
async def private_chat_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """過濾非管理員的私聊"""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == "private" and user.id != OWNER_ID:
        logger.info(f"🚫 拒絕非管理員私聊: 用戶 {user.id}")
        await update.message.reply_text(
            "🔒 此機器人不接受私聊\n"
            "請在群組中使用相關功能",
            parse_mode="HTML"
        )
        return False  # 阻止後續處理
    
    return True  # 允許處理

# ================== 指令處理 ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /start 指令（僅管理員可用）"""
    user = update.effective_user
    chat = update.effective_chat
    
    # 檢查是否管理員
    if chat.type == "private" and user.id != OWNER_ID:
        await update.message.reply_text("🔒 此機器人不接受私聊")
        return
    
    response = f"""
🤖 管理機器人 {BOT_VERSION}

👤 管理員 ID: `{OWNER_ID}`
💬 當前場景: {'私聊' if chat.type == 'private' else '群組'}

📋 可用指令:
/start - 查看狀態 (僅管理員)
/banme - 群組小驚喜 🎁
/list - 查看群組列表 (僅管理員)

📊 狀態:
管理群組: {len(known_groups)} 個
待驗證用戶: {len(pending_verifications)} 人
"""
    
    await update.message.reply_text(response, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /help 指令"""
    user = update.effective_user
    
    if user.id != OWNER_ID:
        return  # 靜默忽略
    
    await update.message.reply_text(
        "🛡️ 管理機器人幫助\n\n"
        "自動功能:\n"
        "• 檢測可疑新成員（含@或網址）\n"
        "• 自動禁言並要求驗證\n"
        "• 驗證成功自動解除\n\n"
        "管理員指令:\n"
        "/list - 查看所有管理群組\n"
        "/start - 查看機器人狀態\n\n"
        "群組指令:\n"
        "/banme - 體驗小驚喜 🎁",
        parse_mode="HTML"
    )

async def banme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /banme 指令（小驚喜版本）"""
    chat = update.effective_chat
    user = update.effective_user
    
    logger.info(f"🎁 /banme: 用戶 {user.id} 在群組 {chat.id}")
    
    if chat.type == "private":
        await update.message.reply_text("🎁 這個驚喜只能在群組裡體驗哦！")
        return
    
    # 檢查用戶是否管理員
    try:
        user_member = await chat.get_member(user.id)
        if user_member.status in ["administrator", "creator"]:
            await update.message.reply_text("👑 管理員大人不能體驗這個驚喜哦～")
            return
    except:
        pass
    
    # 檢查機器人權限
    has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
    if not has_perms:
        await update.message.reply_text(
            f"🎁 驚喜準備中...\n"
            f"（需要設置機器人權限才能體驗）",
            parse_mode="HTML"
        )
        return
    
    try:
        # 執行禁言（小驚喜）
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=create_mute_permissions(),
        )
        
        # 有趣的回复
        surprise_messages = [
            "🤫 噓... 你獲得了一個安靜的2分鐘",
            "🎭 角色扮演：靜音模式啟動",
            "⏳ 時間魔法：靜止2分鐘",
            "🔇 收到！已切換到勿擾模式",
            "🎁 驚喜就是... 讓世界安靜一下"
        ]
        
        import random
        message = random.choice(surprise_messages)
        
        await update.message.reply_text(
            f"{message}\n"
            f"👤 {user.mention_html()}\n"
            f"⏰ 2分鐘後自動恢復",
            parse_mode="HTML"
        )
        
        # 2分鐘後解除
        asyncio.create_task(delayed_unmute(context.bot, chat.id, user.id, 2))
        
    except Exception as e:
        logger.error(f"/banme 失敗: {e}")
        error_msg = str(e).lower()
        
        if "not enough rights" in error_msg:
            await update.message.reply_text(
                "🎁 驚喜發送失敗...\n"
                "需要給機器人「限制成員」權限哦！",
                parse_mode="HTML"
            )
        elif "user is an administrator" in error_msg:
            await update.message.reply_text("👑 管理員大人免疫此驚喜～")
        else:
            await update.message.reply_text(f"🎁 驚喜派送失敗: {e}")

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /list 指令（僅管理員）"""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != "private":
        await update.message.reply_text("🔒 此指令僅在管理員私聊中可用")
        return
    
    if user.id != OWNER_ID:
        logger.warning(f"🚫 非管理員嘗試使用 /list: 用戶 {user.id}")
        return  # 靜默忽略
    
    if not known_groups:
        await update.message.reply_text(
            "📭 尚未管理任何群組\n"
            "將機器人加入群組後會自動記錄",
            parse_mode="HTML"
        )
        return
    
    groups_text = "📋 管理群組列表:\n\n"
    for idx, (chat_id, info) in enumerate(known_groups.items(), 1):
        title = info.get('title', '未知群組')
        status = info.get('status', 'unknown')
        added_time = time.strftime('%Y-%m-%d %H:%M', 
                                 time.localtime(info.get('added_at', 0)))
        
        groups_text += f"{idx}. {title}\n"
        groups_text += f"   🆔: `{chat_id}`\n"
        groups_text += f"   📊: {status}\n"
        groups_text += f"   📅: {added_time}\n\n"
    
    groups_text += f"📈 總計: {len(known_groups)} 個群組"
    
    await update.message.reply_text(groups_text, parse_mode="Markdown")

# ================== 私聊消息過濾 ==================
async def filter_private_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """過濾所有非管理員私聊消息"""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private" and user.id != OWNER_ID:
        logger.info(f"🚫 過濾非管理員私聊: 用戶 {user.id}")
        return  # 阻止處理
    
    # 檢查是否是命令，如果不是且是私聊，也阻止
    if chat.type == "private" and update.message and not update.message.text.startswith('/'):
        if user.id != OWNER_ID:
            return

# ================== 錯誤處理 ==================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """全局錯誤處理"""
    logger.error(f"錯誤: {context.error}", exc_info=True)

# ================== 主程式 ==================
def main():
    """主程序"""
    # 檢查必要設置
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        print("❌ 錯誤: 未設置 BOT_TOKEN")
        print("請運行安裝腳本或執行: export BOT_TOKEN='你的Token'")
        return
    
    owner_id = os.getenv("OWNER_ID")
    if not owner_id or owner_id == "0":
        print("❌ 錯誤: 未設置 OWNER_ID")
        print("請運行安裝腳本設置管理員ID")
        return
    
    OWNER_ID = int(owner_id)
    print(f"✅ 管理員 ID: {OWNER_ID}")
    
    # 加載群組數據
    load_known_groups()
    
    # 創建應用
    application = Application.builder().token(bot_token).build()
    
    # 註冊消息過濾器（最先註冊）
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            filter_private_messages
        ),
        group=-1  # 最高優先級
    )
    
    # 註冊指令處理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("banme", banme))
    application.add_handler(CommandHandler("list", list_groups))
    
    # 註冊按鈕回調
    application.add_handler(CallbackQueryHandler(on_verify_click))
    
    # 註冊成員變化處理
    application.add_handler(ChatMemberHandler(
        handle_my_chat_member, 
        ChatMemberHandler.MY_CHAT_MEMBER
    ))
    
    application.add_handler(ChatMemberHandler(
        handle_chat_member,
        ChatMemberHandler.CHAT_MEMBER
    ))
    
    # 錯誤處理
    application.add_error_handler(error_handler)
    
    # 啟動信息
    print(f"\n{'='*60}")
    print(f"🤖 靜默管理機器人 {BOT_VERSION}")
    print(f"👑 管理員 ID: {OWNER_ID}")
    print(f"📊 管理群組: {len(known_groups)} 個")
    print(f"🔒 私聊模式: 僅管理員")
    print(f"🎁 Banme: 小驚喜模式")
    print(f"{'='*60}")
    print("✅ 機器人啟動成功（靜默模式）")
    print("📝 查看日誌: tail -f bot.log")
    print(f"{'='*60}\n")
    
    # 啟動
    try:
        application.run_polling(
            allowed_updates=[
                Update.MESSAGE,
                Update.CALLBACK_QUERY,
                Update.CHAT_MEMBER,
                Update.MY_CHAT_MEMBER,
            ],
            drop_pending_updates=True,
        )
    except KeyboardInterrupt:
        print("\n🛑 機器人已停止")
    except Exception as e:
        print(f"❌ 啟動失敗: {e}")

if __name__ == "__main__":
    main()
import os
import re
import asyncio
import time
from typing import Optional, Dict, Tuple
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

# === 重要：必須修改這兩個值 ===
OWNER_ID = 7807347685  # 改成你的 Telegram ID
BOT_VERSION = "v3.2.4-fixed-all-permissions"

# 數據存儲
known_groups: Dict[int, Dict] = {}
pending_verifications: Dict[int, Dict] = {}
user_welcomed: Dict[Tuple[int, int], bool] = {}

# ================== 權限設定 ==================
def create_mute_permissions():
    """創建禁言權限 - 關閉特定權限，其他全部設為False"""
    try:
        return ChatPermissions(
            # 關閉這些權限
            can_send_messages=False,          # 發言
            can_send_media_messages=False,    # 傳送媒體
            can_send_polls=False,             # 傳送投票活動
            can_send_other_messages=False,    # 傳送貼圖和GIF
            can_add_web_page_previews=False,  # 連結預覽
            can_invite_users=False,           # 新增用戶
            
            # 其他權限也設為False
            can_change_info=False,            # 變更資訊
            can_pin_messages=False,           # 置頂訊息
            can_manage_topics=False,          # 管理話題
            
            # 新版本的權限
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_manage_chat=False,
        )
    except Exception as e1:
        logger.warning(f"完整禁言參數失敗: {e1}")
        try:
            return ChatPermissions(**{
                # 關閉的權限
                'can_send_messages': False,
                'can_send_media_messages': False,
                'can_send_polls': False,
                'can_send_other_messages': False,
                'can_add_web_page_previews': False,
                'can_invite_users': False,
                # 其他權限也設為False
                'can_change_info': False,
                'can_pin_messages': False,
                'can_manage_topics': False,
            })
        except Exception as e2:
            logger.error(f"禁言權限創建失敗: {e2}")
            # 最簡單的版本
            try:
                return ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_invite_users=False,
                )
            except:
                return ChatPermissions(can_send_messages=False)

def create_unmute_permissions():
    """創建解禁權限 - 開啟特定權限，其他保持False"""
    try:
        return ChatPermissions(
            # 開啟這些權限
            can_send_messages=True,          # 發言
            can_send_media_messages=True,    # 傳送媒體
            can_send_polls=True,             # 傳送投票活動
            can_send_other_messages=True,    # 傳送貼圖和GIF
            can_add_web_page_previews=True,  # 連結預覽
            can_invite_users=True,           # 新增用戶
            
            # 其他權限保持False（群組默認）
            can_change_info=False,           # 變更資訊
            can_pin_messages=False,          # 置頂訊息
            can_manage_topics=False,         # 管理話題
            
            # 新版本的權限
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_manage_chat=False,
        )
    except Exception as e:
        logger.warning(f"完整解禁參數失敗: {e}")
        try:
            return ChatPermissions(**{
                # 開啟的權限
                'can_send_messages': True,
                'can_send_media_messages': True,
                'can_send_polls': True,
                'can_send_other_messages': True,
                'can_add_web_page_previews': True,
                'can_invite_users': True,
                # 其他權限保持False
                'can_change_info': False,
                'can_pin_messages': False,
                'can_manage_topics': False,
            })
        except Exception as e2:
            logger.error(f"解禁權限最終失敗: {e2}")
            try:
                return ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_invite_users=True,
                )
            except:
                return ChatPermissions(can_send_messages=True)

def create_full_permissions():
    """創建完整權限（所有權限都開啟）用於測試"""
    try:
        return ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_manage_topics=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_manage_chat=True,
        )
    except Exception as e:
        logger.warning(f"完整權限創建失敗: {e}")
        return create_unmute_permissions()

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
        # 使用解禁權限
        permissions = create_unmute_permissions()
        logger.info(f"📋 使用解禁權限: 用戶 {user_id} 在群組 {chat_id}")
        
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
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

async def send_welcome_message(bot, chat_id: int, user_id: int, user_name: str, force_send: bool = False):
    """發送歡迎消息"""
    key = (chat_id, user_id)
    
    # 如果已經歡迎過且不是強制發送，則跳過
    if not force_send and key in user_welcomed and user_welcomed[key]:
        logger.info(f"⏭️ 用戶 {user_id} 已歡迎過，跳過")
        return
    
    try:
        await bot.send_message(
            chat_id,
            f"👋 歡迎 {user_name} 加入群組！",
            parse_mode="HTML"
        )
        user_welcomed[key] = True
        logger.info(f"✅ 已發送歡迎消息給 {user_name} (ID: {user_id})")
    except Exception as e:
        logger.error(f"發送歡迎消息失敗: {e}")

# ================== 處理機器人加入群組 ==================
async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理機器人自己被加入/移除群組"""
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
            logger.info(f"✅ 記錄新群組: {chat.title} (ID: {chat.id})")
        
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
            logger.info(f"👤 新成員: {user.full_name} (ID: {user.id}) 加入 {chat.title}")
            
            # 檢查用戶簡介
            bio = ""
            try:
                user_chat = await context.bot.get_chat(user.id)
                bio = user_chat.bio or ""
                logger.info(f"📝 用戶 {user.id} 簡介: {bio[:50]}{'...' if len(bio) > 50 else ''}")
            except Exception as e:
                logger.warning(f"無法獲取用戶 {user.id} 簡介: {e}")
            
            is_suspicious = False
            reasons = []
            
            # 檢查 @ 標籤
            if re.search(r"@\w+", bio, re.IGNORECASE):
                is_suspicious = True
                reasons.append("@標籤")
            
            # 檢查連結
            if re.search(r"https?://|t\.me/", bio, re.IGNORECASE):
                is_suspicious = True
                reasons.append("網址/連結")
            
            if is_suspicious:
                logger.info(f"⚠️ 可疑用戶: {user.id}, 原因: {reasons}")
                
                has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
                if not has_perms:
                    await context.bot.send_message(
                        chat.id,
                        f"⚠️ 檢測到可疑用戶但權限不足\n{perm_msg}",
                        parse_mode="HTML"
                    )
                    return
                
                try:
                    # 禁言用戶（關閉特定權限）
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=user.id,
                        permissions=create_mute_permissions(),
                    )
                    
                    # 記錄待驗證信息
                    pending_verifications[user.id] = {
                        "chat_id": chat.id,
                        "user_name": user.mention_html(),
                        "reasons": reasons,
                        "timestamp": time.time(),
                        "needs_welcome": True  # 標記需要歡迎
                    }
                    
                    # 發送驗證按鈕
                    keyboard = [[
                        InlineKeyboardButton(
                            "✅ 我是真人，點擊驗證",
                            callback_data=f"verify_{user.id}"
                        )
                    ]]
                    
                    await context.bot.send_message(
                        chat.id,
                        f"⚠️ {user.mention_html()} 需要人機驗證（{', '.join(reasons)}）",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="HTML"
                    )
                    
                except Exception as e:
                    logger.error(f"禁言失敗: {e}")
            
            else:
                # 不可疑的用戶，立即發送歡迎消息
                await send_welcome_message(
                    context.bot, 
                    chat.id, 
                    user.id, 
                    user.mention_html(),
                    force_send=True
                )
                    
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
        
        # 獲取驗證信息
        if user_id not in pending_verifications:
            await query.answer("驗證已過期或無效", show_alert=True)
            return
        
        verify_info = pending_verifications[user_id]
        chat_id = verify_info["chat_id"]
        
        if query.from_user.id != user_id:
            await query.answer("這不是你的驗證按鈕！", show_alert=True)
            return
        
        # 檢查是否超時（30分鐘）
        if time.time() - verify_info["timestamp"] > 1800:
            await query.edit_message_text("❌ 驗證已過期（超過30分鐘）")
            del pending_verifications[user_id]
            return
        
        try:
            # 使用解禁權限（明確設置所有權限）
            permissions = create_unmute_permissions()
            logger.info(f"📋 使用解禁權限恢復用戶 {user_id}")
            
            # 測試：先嘗試完整權限
            try:
                full_perms = create_full_permissions()
                await context.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=full_perms,
                )
                logger.info(f"✅ 使用完整權限成功")
            except Exception as full_error:
                logger.warning(f"完整權限失敗，嘗試解禁權限: {full_error}")
                # 使用解禁權限
                await context.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=permissions,
                )
            
            # 移除待驗證記錄
            del pending_verifications[user_id]
            
            # 如果驗證信息中標記需要歡迎，則發送歡迎消息
            if verify_info.get("needs_welcome", False):
                await send_welcome_message(
                    context.bot, 
                    chat_id, 
                    user_id, 
                    query.from_user.mention_html(),
                    force_send=True
                )
            
            await query.edit_message_text(
                f"✅ {query.from_user.mention_html()} 驗證成功！已恢復所有權限。",
                parse_mode="HTML"
            )
            
            # 發送權限測試消息
            try:
                await context.bot.send_message(
                    chat_id,
                    f"🔧 已為 {query.from_user.mention_html()} 恢復以下權限:\n"
                    f"• 發言 ✓\n"
                    f"• 傳送媒體 ✓\n"
                    f"• 傳送投票 ✓\n"
                    f"• 傳送貼圖/GIF ✓\n"
                    f"• 連結預覽 ✓\n"
                    f"• 新增用戶 ✓",
                    parse_mode="HTML"
                )
            except:
                pass
            
        except Exception as e:
            logger.error(f"解除禁言失敗: {e}")
            await query.edit_message_text(f"❌ 解除禁言失敗: {str(e)[:100]}")
            
    except Exception as e:
        logger.error(f"驗證處理失敗: {e}")

# ================== 指令處理 ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /start 指令"""
    user = update.effective_user
    chat = update.effective_chat
    
    response = f"""
🤖 Telegram 管理機器人 {BOT_VERSION}

👤 你的 ID: `{user.id}`
💬 場景: {'私聊' if chat.type == 'private' else '群組'}

📋 可用指令:
/start - 查看幫助
/help - 詳細幫助
/banme - 自願禁言2分鐘
/list - 查看管理群組
/testperms - 測試權限設置

📊 狀態:
群組數: {len(known_groups)}
待驗證: {len(pending_verifications)}
"""
    
    await update.message.reply_text(response, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /help 指令"""
    await update.message.reply_text(
        "📖 幫助信息\n\n"
        "1. /start - 查看狀態\n"
        "2. /help - 查看詳細幫助\n"
        "3. /banme - 群組內自願禁言2分鐘\n"
        "4. /list - 管理員查看群組列表\n"
        "5. /testperms - 測試權限設置\n\n"
        "⚠️ 注意:\n"
        "- 機器人需要管理員權限\n"
        "- 開啟「限制成員」權限\n"
        "- 關閉「匿名管理員」",
        parse_mode="HTML"
    )

async def banme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /banme 指令"""
    chat = update.effective_chat
    user = update.effective_user
    
    logger.info(f"🔇 /banme: 用戶 {user.id} 在群組 {chat.id}")
    
    if chat.type == "private":
        await update.message.reply_text("❌ 此指令僅在群組中可用！")
        return
    
    # 檢查用戶是否管理員
    try:
        user_member = await chat.get_member(user.id)
        if user_member.status in ["administrator", "creator"]:
            await update.message.reply_text("❌ 管理員不能使用此指令！")
            return
    except:
        pass  # 如果檢查失敗，繼續執行
    
    # 檢查機器人權限
    has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
    if not has_perms:
        await update.message.reply_text(
            f"❌ 權限檢查失敗！\n{perm_msg}\n\n"
            "請確認機器人有「限制成員」權限。",
            parse_mode="HTML"
        )
        return
    
    try:
        # 禁言用戶（關閉特定權限）
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=create_mute_permissions(),
        )
        
        await update.message.reply_text(
            f"🤐 {user.mention_html()} 已自願禁言 2 分鐘\n"
            f"已關閉: 發言、媒體、投票、貼圖、連結、新增用戶",
            parse_mode="HTML"
        )
        
        # 2分鐘後解除
        asyncio.create_task(delayed_unmute(context.bot, chat.id, user.id, 2))
        
    except Exception as e:
        logger.error(f"/banme 失敗: {e}")
        error_msg = str(e).lower()
        
        if "not enough rights" in error_msg:
            await update.message.reply_text("❌ 權限不足！請檢查機器人權限。")
        elif "user is an administrator" in error_msg:
            await update.message.reply_text("❌ 無法禁言管理員！")
        else:
            await update.message.reply_text(f"❌ 錯誤: {e}")

async def test_perms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """測試權限設置"""
    if update.effective_user.id != OWNER_ID:
        return
    
    mute_perms = create_mute_permissions()
    unmute_perms = create_unmute_permissions()
    
    response = f"""
🔧 權限測試 - {BOT_VERSION}

禁言權限:
• 發言: {getattr(mute_perms, 'can_send_messages', 'N/A')}
• 媒體: {getattr(mute_perms, 'can_send_media_messages', 'N/A')}
• 投票: {getattr(mute_perms, 'can_send_polls', 'N/A')}
• 貼圖/GIF: {getattr(mute_perms, 'can_send_other_messages', 'N/A')}
• 連結預覽: {getattr(mute_perms, 'can_add_web_page_previews', 'N/A')}
• 新增用戶: {getattr(mute_perms, 'can_invite_users', 'N/A')}

解禁權限:
• 發言: {getattr(unmute_perms, 'can_send_messages', 'N/A')}
• 媒體: {getattr(unmute_perms, 'can_send_media_messages', 'N/A')}
• 投票: {getattr(unmute_perms, 'can_send_polls', 'N/A')}
• 貼圖/GIF: {getattr(unmute_perms, 'can_send_other_messages', 'N/A')}
• 連結預覽: {getattr(unmute_perms, 'can_add_web_page_previews', 'N/A')}
• 新增用戶: {getattr(unmute_perms, 'can_invite_users', 'N/A')}
"""
    
    await update.message.reply_text(response, parse_mode="HTML")

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /list 指令"""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != "private":
        await update.message.reply_text("❌ 此指令僅在私聊中可用！")
        return
    
    if user.id != OWNER_ID:
        await update.message.reply_text(f"❌ 僅管理員可用 (ID: {OWNER_ID})")
        return
    
    if not known_groups:
        await update.message.reply_text("📭 沒有群組記錄")
        return
    
    groups_text = "📋 管理的群組:\n\n"
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
    # 檢查 Token
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        print("❌ 錯誤: 未設置 BOT_TOKEN")
        print("請執行: export BOT_TOKEN='你的Token'")
        return
    
    # 加載群組數據
    load_known_groups()
    
    # 創建應用
    application = Application.builder().token(bot_token).build()
    
    # 註冊處理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("banme", banme))
    application.add_handler(CommandHandler("testperms", test_perms))
    application.add_handler(CommandHandler("list", list_groups))
    
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
    print(f"🤖 Telegram Admin Bot {BOT_VERSION}")
    print(f"👤 Owner ID: {OWNER_ID}")
    print(f"📊 已記錄群組: {len(known_groups)} 個")
    print(f"{'='*60}")
    print("\n✅ 機器人正在啟動...")
    print("⚠️  注意: 確保只運行一個機器人實例")
    print("\n權限設置:")
    print("禁言時關閉: 發言、媒體、投票、貼圖/GIF、連結預覽、新增用戶")
    print("解禁時開啟: 發言、媒體、投票、貼圖/GIF、連結預覽、新增用戶")
    
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
        print("\n👋 機器人已停止")
        save_known_groups()
    except Exception as e:
        print(f"❌ 啟動失敗: {e}")

if __name__ == "__main__":
    main()
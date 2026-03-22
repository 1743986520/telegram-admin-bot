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
BOT_VERSION = "v3.3.0-full-permissions"

# 數據存儲
known_groups: Dict[int, Dict] = {}
pending_verifications: Dict[int, Dict] = {}
user_welcomed: Dict[Tuple[int, int], bool] = {}
active_referendums: Dict[int, Dict] = {}  # chat_id -> referendum state

# ================== 權限設定 ==================
def create_simple_mute_permissions():
    """完全禁言：禁止所有消息類型和功能"""
    try:
        return ChatPermissions(
            # 基本消息權限
            can_send_messages=False,
            
            # 媒體消息權限
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            
            # 其他功能權限
            can_send_polls=False,
            can_send_other_messages=False,  # 包含貼圖、GIF等
            can_add_web_page_previews=False,  # 連結預覽
            
            # 群組管理權限
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False
        )
    except Exception as e:
        logger.error(f"完全禁言權限創建失敗: {e}")
        # 降級方案：只禁止基本發言
        return ChatPermissions(can_send_messages=False)

def create_simple_unmute_permissions():
    """完全解禁：恢復所有權限"""
    try:
        return ChatPermissions(
            # 基本消息權限
            can_send_messages=True,
            
            # 媒體消息權限
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            
            # 其他功能權限
            can_send_polls=True,              # 投票活動
            can_send_other_messages=True,      # 貼圖和GIF
            can_add_web_page_previews=True,    # 連結預覽
            
            # 群組管理權限（可根據需求調整）
            can_change_info=False,              # 禁止修改群組資訊
            can_invite_users=True,               # 允許邀請新用戶
            can_pin_messages=False,              # 禁止置頂消息
            can_manage_topics=False               # 禁止管理話題
        )
    except Exception as e:
        logger.error(f"完全解禁權限創建失敗: {e}")
        # 降級方案：只恢復基本發言
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
        # 使用完全解禁權限
        permissions = create_simple_unmute_permissions()
        
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
                    # 完全禁言（禁止所有功能）
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=user.id,
                        permissions=create_simple_mute_permissions(),
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
            # 完全解禁（恢復所有權限）
            permissions = create_simple_unmute_permissions()
            
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
            
        except Exception as e:
            logger.error(f"解除禁言失敗: {e}")
            await query.edit_message_text(f"❌ 解除禁言失敗: {str(e)[:100]}")
            
    except Exception as e:
        logger.error(f"驗證處理失敗: {e}")

# ================== 公投系統 ==================

def build_referendum_text(chat_id: int) -> str:
    """建立公投訊息文字"""
    ref = active_referendums.get(chat_id)
    if not ref:
        return "公投已結束"

    yes_count = len(ref["yes_votes"])
    no_count = len(ref["no_votes"])
    target = ref["current_target"]
    state = ref["state"]

    state_str = ""
    if state == "observation":
        leading_label = "✅ 支持" if ref["leading_option"] == "yes" else "❌ 反對"
        state_str = f"\n⏳ <b>追平觀察期（30 秒）</b> — 領先方：{leading_label}"

    round_num = (target - 3) // 2 + 1
    round_str = f"第 {round_num} 輪" if round_num == 1 else f"第 {round_num} 輪（延長）"

    return (
        f"🗳️ <b>公投：全員禁言 5 分鐘</b>\n"
        f"發起人：{ref['initiator_name']}\n"
        f"📊 {round_str}｜目標票數：<b>{target} 票</b>{state_str}\n\n"
        f"✅ 支持：<b>{yes_count}</b> 票\n"
        f"❌ 反對：<b>{no_count}</b> 票\n\n"
        f"每人限投一票，可隨時更換。"
    )

def build_referendum_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """建立公投按鈕"""
    ref = active_referendums.get(chat_id)
    yes_count = len(ref["yes_votes"]) if ref else 0
    no_count = len(ref["no_votes"]) if ref else 0
    keyboard = [[
        InlineKeyboardButton(f"✅ 支持 ({yes_count})", callback_data=f"ref_yes_{chat_id}"),
        InlineKeyboardButton(f"❌ 反對 ({no_count})", callback_data=f"ref_no_{chat_id}"),
    ]]
    return InlineKeyboardMarkup(keyboard)

async def update_referendum_message(context, chat_id: int, query=None):
    """更新公投訊息"""
    ref = active_referendums.get(chat_id)
    if not ref:
        return
    text = build_referendum_text(chat_id)
    keyboard = build_referendum_keyboard(chat_id)
    try:
        if query:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=ref["message_id"],
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.warning(f"更新公投訊息失敗: {e}")

async def observation_timer(context, chat_id: int):
    """30 秒追平觀察期計時器"""
    await asyncio.sleep(30)

    ref = active_referendums.get(chat_id)
    if not ref or ref["state"] != "observation":
        return

    yes_count = len(ref["yes_votes"])
    no_count = len(ref["no_votes"])
    target = ref["current_target"]
    leading = ref["leading_option"]
    trailing_count = no_count if leading == "yes" else yes_count

    if trailing_count >= target:
        # 追平了，進入下一輪（理論上應已被 callback 處理，這裡作為保底）
        await advance_to_next_round(context, chat_id)
    else:
        # 未追平，領先方勝出
        if leading == "yes":
            await execute_group_mute(context, chat_id)
        else:
            await end_referendum(context, chat_id, "❌ 反對方勝出，公投遭否決！")

async def advance_to_next_round(context, chat_id: int, query=None):
    """進入下一輪延長投票"""
    ref = active_referendums.get(chat_id)
    if not ref:
        return

    ref["current_target"] += 2
    ref["state"] = "voting"
    ref["leading_option"] = None
    new_target = ref["current_target"]

    text = build_referendum_text(chat_id)
    keyboard = build_referendum_keyboard(chat_id)
    notice = f"\n\n🔄 <b>雙方追平！進入延長投票，新目標：{new_target} 票</b>"

    try:
        if query:
            await query.edit_message_text(text + notice, reply_markup=keyboard, parse_mode="HTML")
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=ref["message_id"],
                text=text + notice,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.warning(f"更新延長投票訊息失敗: {e}")

async def execute_group_mute(context, chat_id: int):
    """執行公投通過：全員禁言 5 分鐘"""
    ref = active_referendums.pop(chat_id, None)

    try:
        mute_perms = create_simple_mute_permissions()
        await context.bot.set_chat_permissions(chat_id, mute_perms)

        result_text = (
            "✅ <b>公投通過！全員禁言 5 分鐘開始！</b>\n"
            "⏱️ 5 分鐘後自動解除禁言。"
        )
        try:
            if ref:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=ref["message_id"],
                    text=result_text,
                    parse_mode="HTML"
                )
        except Exception:
            await context.bot.send_message(chat_id, result_text, parse_mode="HTML")

        asyncio.create_task(delayed_group_unmute(context.bot, chat_id, 5))
        logger.info(f"🔇 全員禁言已執行: 群組 {chat_id}")

    except Exception as e:
        logger.error(f"全員禁言失敗: {e}")
        await context.bot.send_message(chat_id, f"❌ 執行禁言失敗: {e}")

async def delayed_group_unmute(bot, chat_id: int, minutes: int):
    """延遲解除全員禁言"""
    await asyncio.sleep(minutes * 60)
    try:
        permissions = create_simple_unmute_permissions()
        await bot.set_chat_permissions(chat_id, permissions)
        await bot.send_message(chat_id, "🔔 <b>全員禁言已解除！</b>", parse_mode="HTML")
        logger.info(f"✅ 全員禁言解除: 群組 {chat_id}")
    except Exception as e:
        logger.error(f"解除全員禁言失敗: {e}")

async def end_referendum(context, chat_id: int, message: str):
    """結束公投（否決）"""
    ref = active_referendums.pop(chat_id, None)
    try:
        if ref:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=ref["message_id"],
                text=f"🗳️ <b>公投結束</b>\n{message}",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.warning(f"結束公投訊息更新失敗: {e}")

async def check_referendum_state(context, chat_id: int, query=None):
    """每次投票後檢查公投狀態"""
    ref = active_referendums.get(chat_id)
    if not ref:
        return

    yes_count = len(ref["yes_votes"])
    no_count = len(ref["no_votes"])
    target = ref["current_target"]

    if ref["state"] == "voting":
        if yes_count >= target or no_count >= target:
            # 某方率先達標，進入觀察期
            leading = "yes" if yes_count >= target else "no"
            ref["state"] = "observation"
            ref["leading_option"] = leading
            await update_referendum_message(context, chat_id, query)

            # 取消舊計時器（如有）
            old_task = ref.get("observation_task")
            if old_task and not old_task.done():
                old_task.cancel()

            ref["observation_task"] = asyncio.create_task(
                observation_timer(context, chat_id)
            )
        else:
            await update_referendum_message(context, chat_id, query)

    elif ref["state"] == "observation":
        leading = ref["leading_option"]
        trailing_count = no_count if leading == "yes" else yes_count

        if trailing_count >= target:
            # 追平！取消計時器，進入下一輪
            old_task = ref.get("observation_task")
            if old_task and not old_task.done():
                old_task.cancel()
            await advance_to_next_round(context, chat_id, query)
        else:
            await update_referendum_message(context, chat_id, query)

async def referendum_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /vote 指令"""
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("❌ 此指令僅在群組中可用！")
        return

    if chat.id in active_referendums:
        await update.message.reply_text("⚠️ 目前已有進行中的公投，請等待結束後再發起！")
        return

    has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
    if not has_perms:
        await update.message.reply_text(f"❌ 權限不足，無法執行公投！\n{perm_msg}")
        return

    active_referendums[chat.id] = {
        "initiator_id": user.id,
        "initiator_name": user.mention_html(),
        "yes_votes": set(),
        "no_votes": set(),
        "current_target": 3,
        "state": "voting",
        "leading_option": None,
        "observation_task": None,
        "message_id": None,
    }

    text = build_referendum_text(chat.id)
    keyboard = build_referendum_keyboard(chat.id)

    msg = await context.bot.send_message(
        chat.id, text, reply_markup=keyboard, parse_mode="HTML"
    )
    active_referendums[chat.id]["message_id"] = msg.message_id
    logger.info(f"🗳️ 公投發起: 群組 {chat.id} 由用戶 {user.id}")

async def on_referendum_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理公投投票按鈕"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")  # ref_yes_CHATID or ref_no_CHATID
    if len(parts) != 3:
        return

    _, option, chat_id_str = parts
    chat_id = int(chat_id_str)
    voter_id = query.from_user.id

    if chat_id not in active_referendums:
        await query.answer("此公投已結束", show_alert=True)
        return

    ref = active_referendums[chat_id]

    # 更換票（先從兩邊移除再加入選擇方）
    ref["yes_votes"].discard(voter_id)
    ref["no_votes"].discard(voter_id)

    if option == "yes":
        ref["yes_votes"].add(voter_id)
        await query.answer("✅ 已投支持票")
    else:
        ref["no_votes"].add(voter_id)
        await query.answer("❌ 已投反對票")

    await check_referendum_state(context, chat_id, query)


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
/vote - 發起全員禁言公投
/list - 查看管理群組

📊 狀態:
群組數: {len(known_groups)}
待驗證: {len(pending_verifications)}

🔧 當前權限設定:
✅ 貼圖和 GIF
✅ 媒體文件
✅ 投票活動
✅ 連結預覽
✅ 邀請用戶
✅ 發送消息
"""
    
    await update.message.reply_text(response, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /help 指令"""
    await update.message.reply_text(
        "📖 幫助信息\n\n"
        "1. /start - 查看狀態\n"
        "2. /help - 查看詳細幫助\n"
        "3. /banme - 驚喜\n"
        "4. /vote - 發起全員禁言 5 分鐘公投\n"
        "5. /list - 管理員查看群組列表\n\n"
        "⚠️ 注意:\n"
        "- 機器人需要管理員權限\n"
        "- 開啟「限制成員」權限\n"
        "- 關閉「匿名管理員」\n\n"
        "✨ 完整權限支持:\n"
        "• 貼圖和 GIF\n"
        "• 媒體文件\n"
        "• 投票活動\n"
        "• 連結預覽\n"
        "• 邀請用戶\n"
        "• 發送消息",
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
        # 完全禁言（禁止所有功能）
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=create_simple_mute_permissions(),
        )
        
        await update.message.reply_text(
            f"wow {user.mention_html()} 恭喜你發現彩蛋啦",
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
    application.add_handler(CommandHandler("list", list_groups))
    application.add_handler(CommandHandler("vote", referendum_command))

    application.add_handler(CallbackQueryHandler(on_referendum_vote, pattern=r"^ref_"))
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
    print("\n🔧 權限設定: 完整模式")
    print("✅ 貼圖和 GIF")
    print("✅ 媒體文件")
    print("✅ 投票活動")
    print("✅ 連結預覽")
    print("✅ 邀請用戶")
    print("✅ 發送消息")
    print("❌ 群組管理權限（資訊、置頂、話題）")
    
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

import os
import re
import sys
import io
import shutil
import subprocess
import asyncio
import time
from typing import Optional, Dict, Tuple
import logging
import uuid
import random
from PIL import Image, ImageDraw, ImageFont
from ad_detector import detect_ad
from settings import (
    DEFAULT_FEATURES,
    FEATURE_LABELS,
    feature_enabled,
    get_group_features,
    set_group_feature,
)
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
BOT_VERSION = "v3.4.0-custom-proposal"

# 行政頻道（自訂提案結果公告 + 置頂）
ADMIN_GROUP_ID = -1003502034749
ADMIN_GROUP_LINK = "https://t.me/diacg_administration"

# 數據存儲
known_groups: Dict[int, Dict] = {}
pending_verifications: Dict[int, Dict] = {}
VERIFY_ATTEMPT_LIMIT = 3  # 圖片算術驗證碼最大嘗試次數，超過需管理員手動處理
user_welcomed: Dict[Tuple[int, int], bool] = {}
active_referendums: Dict[int, Dict] = {}        # chat_id -> 全員禁言公投狀態
active_proposals: Dict[int, Dict] = {}          # chat_id -> 自訂提案狀態
pending_proposal_setup: Dict[Tuple[int,int], Dict] = {}  # (chat_id, user_id) -> 待確認匿名設定
pending_sample_actions: Dict[Tuple[int, int], str] = {}  # (chat_id, user_id) -> add_ad/whitelist
consumed_sample_messages = set()  # (chat_id, message_id)，避免樣本輸入再進廣告偵測
pending_false_positive_samples: Dict[str, dict] = {}  # token -> {"text","chat_id","user_id"}
active_tests: set = set()  # (chat_id, user_id)，/test 後持續測試直到 /stop
pending_guard_kick: Dict[int, dict] = {}  # chat_id -> {"users": {user_id: name}, "selected": set(user_id,...)}

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
            for group in known_groups.values():
                group["features"] = get_group_features(group)
    except FileNotFoundError:
        known_groups = {}
    except Exception as e:
        logger.error(f"加載群組數據失敗: {e}")
        known_groups = {}


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """顯示目前群組功能開關。"""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    if chat.type == "private":
        await message.reply_text("❌ 此指令僅在群組中可用。")
        return
    if not await is_group_admin(context.bot, chat.id, update.effective_user.id):
        await message.reply_text("❌ 只有本群管理員可以查看群組設定。")
        return
    features = get_group_features(known_groups.get(chat.id, {}))
    lines = ["⚙️ <b>群組功能設定</b>"]
    lines.extend(
        f"{'✅' if enabled else '⛔'} <code>{name}</code>：{FEATURE_LABELS[name]}"
        for name, enabled in features.items()
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{'✅' if enabled else '⛔'} {name}",
            callback_data=f"feature_toggle:{name}",
        )]
        for name, enabled in features.items()
    ])
    await message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


async def feature_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理員設定單一功能：/feature <name> <on|off>。"""
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await update.message.reply_text("❌ 此指令僅在群組中可用。")
        return
    try:
        member = await chat.get_member(user.id)
        if member.status not in ["administrator", "creator"] and user.id != OWNER_ID:
            await update.message.reply_text("❌ 只有群組管理員才能修改設定。")
            return
    except Exception:
        await update.message.reply_text("❌ 無法確認你的管理員權限。")
        return
    if len(context.args) != 2:
        await update.message.reply_text(
            "用法：<code>/feature ad_detection off</code>\n"
            "可用名稱：" + ", ".join(DEFAULT_FEATURES), parse_mode="HTML"
        )
        return
    name, value = context.args[0].lower(), context.args[1].lower()
    if name not in DEFAULT_FEATURES or value not in {"on", "off", "true", "false"}:
        await update.message.reply_text("❌ 功能名稱或值無效，使用 /settings 查看可用名稱。")
        return
    known_groups.setdefault(chat.id, {"title": chat.title or str(chat.id), "status": "active"})
    set_group_feature(known_groups, chat.id, name, value in {"on", "true"})
    save_known_groups()
    await update.message.reply_text(
        f"✅ {FEATURE_LABELS[name]} 已{'啟用' if value in {'on', 'true'} else '停用'}。"
    )


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
    if not feature_enabled(known_groups.get(chat_id, {}), "welcome"):
        return
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


async def _delete_after(message, seconds: int):
    """延遲刪除訊息"""
    await asyncio.sleep(seconds)
    try:
        await message.delete()
    except Exception:
        pass


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

        # DEBUG：記錄所有成員狀態變化
        logger.info(f"📊 成員狀態變化: {user.full_name} | {old_status} → {new_status} | 群組: {chat.title}")
        
        # 成員離開
        if new_status in ["left", "kicked"] and old_status in ["member", "administrator", "restricted"]:
            if not feature_enabled(known_groups.get(chat.id, {}), "leave_notice"):
                return
            name = user.mention_html()
            await context.bot.send_message(
                chat.id,
                f"{name} 離開了我們，我們會想念他的 👋",
                parse_mode="HTML"
            )
            logger.info(f"👋 成員離開: {user.full_name} (ID: {user.id}) 離開 {chat.title}")
            return

        if old_status in ["left", "kicked"] and new_status == "member":
            logger.info(f"👤 新成員: {user.full_name} (ID: {user.id}) 加入 {chat.title}")

            # 🛡 防護模式：完全靜默，不發任何提示，直接關閉所有權限並記錄名單，關閉時再統一處理
            if known_groups.get(chat.id, {}).get("guard_mode", False):
                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=user.id,
                        permissions=create_simple_mute_permissions(),
                    )
                except Exception as e:
                    logger.error(f"防護模式禁言失敗 chat={chat.id} user={user.id}: {e}")
                known_groups[chat.id].setdefault("guard_joined", []).append({
                    "id": user.id,
                    "name": user.full_name or str(user.id),
                })
                save_known_groups()
                logger.info(f"🛡 防護模式：新成員 {user.id} 已靜默禁言並記錄（{chat.id}）")
                return

            # 🚨 鎖群模式：直接禁言，不歡迎、不簡介檢測、不發驗證按鈕，保持安靜
            if known_groups.get(chat.id, {}).get("lockdown", False):
                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=user.id,
                        permissions=create_simple_mute_permissions(),
                    )
                    logger.info(f"🚨 鎖群模式：新成員 {user.id} 已直接禁言（{chat.id}）")
                except Exception as e:
                    logger.error(f"鎖群模式禁言失敗 chat={chat.id} user={user.id}: {e}")
                return

            # 檢查用戶簡介
            bio = ""
            is_suspicious = False
            hard_block = False
            reasons = []
            if feature_enabled(known_groups.get(chat.id, {}), "profile_check"):
                try:
                    user_chat = await context.bot.get_chat(user.id)
                    bio = user_chat.bio or ""
                    logger.info(f"📝 用戶 {user.id} 簡介: {bio[:50]}{'...' if len(bio) > 50 else ''}")
                except Exception as e:
                    logger.warning(f"無法獲取用戶 {user.id} 簡介: {e}")

                # 檢查 @ 標籤
                if re.search(r"@\w+", bio, re.IGNORECASE):
                    is_suspicious = True
                    reasons.append("@標籤")

                # 檢查連結
                if re.search(r"https?://|t\.me/", bio, re.IGNORECASE):
                    is_suspicious = True
                    reasons.append("網址/連結")

                # 非中文名稱（純英文或其他非中文字元），群組情境下視為軟性可疑訊號
                display_name = user.full_name or ""
                if display_name.strip() and not re.search(r"[\u4e00-\u9fff]", display_name):
                    is_suspicious = True
                    reasons.append("非中文名稱")

                # 用戶名／暱稱／簡介直接對廣告模板庫掃描（L1 正則 + L2 TF-IDF 相似度）
                # 命中模板庫視為高置信度廣告帳號，標記 hard_block：不給自助驗證按鈕，只能由管理員手動解除
                profile_fields = (
                    ("用戶名", f"@{user.username}" if user.username else ""),
                    ("暱稱", user.full_name or ""),
                    ("簡介", bio),
                )
                for field_label, field_text in profile_fields:
                    if not field_text:
                        continue
                    hit, _score, hit_reason = detect_ad(field_text)
                    if hit:
                        is_suspicious = True
                        hard_block = True
                        reasons.append(f"{field_label}命中模板庫[{hit_reason}]")

            if hard_block:
                logger.warning(f"🚫 高置信度廣告帳號: {user.id}, 原因: {reasons}")

                has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
                if not has_perms:
                    await context.bot.send_message(
                        chat.id,
                        f"⚠️ 檢測到高置信度廣告帳號但權限不足\n{perm_msg}",
                        parse_mode="HTML"
                    )
                    return

                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=user.id,
                        permissions=create_simple_mute_permissions(),
                    )
                    await context.bot.send_message(
                        chat.id,
                        f"🚫 {user.mention_html()} 用戶名/暱稱/簡介直接命中廣告模板庫（{', '.join(reasons)}），"
                        f"已直接禁言，不提供自助驗證，需管理員手動確認後解除。",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"高置信度廣告帳號禁言失敗: {e}")
                return

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

                    captcha_img, answer = generate_math_captcha()
                    options = _generate_captcha_options(answer)

                    # 記錄待驗證信息
                    pending_verifications[user.id] = {
                        "chat_id": chat.id,
                        "user_name": user.mention_html(),
                        "reasons": reasons,
                        "timestamp": time.time(),
                        "needs_welcome": True,  # 標記需要歡迎
                        "captcha_answer": answer,
                        "attempts": 0,
                    }

                    keyboard = [[
                        InlineKeyboardButton(str(opt), callback_data=f"captcha_{user.id}_{opt}")
                        for opt in options
                    ]]

                    await context.bot.send_photo(
                        chat.id,
                        photo=captcha_img,
                        caption=f"⚠️ {user.mention_html()} 需要人機驗證（{', '.join(reasons)}）\n"
                                f"請點選圖片中算式的正確答案（{VERIFY_ATTEMPT_LIMIT} 次機會，30 分鐘內有效）",
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

# ================== 圖片算術驗證碼 ==================
def _load_captcha_font(size: int):
    """嘗試載入系統字型，找不到就退回 Pillow 內建字型。"""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def generate_math_captcha():
    """產生一題簡單算術驗證碼圖片。回傳 (圖片 BytesIO, 正確答案:int)。"""
    op = random.choice(["+", "-", "×"])
    if op == "+":
        a, b = random.randint(1, 20), random.randint(1, 20)
        answer = a + b
    elif op == "-":
        a, b = random.randint(1, 20), random.randint(1, 20)
        if a < b:
            a, b = b, a
        answer = a - b
    else:
        a, b = random.randint(2, 9), random.randint(2, 9)
        answer = a * b

    text = f"{a} {op} {b} = ?"
    width, height = 220, 90
    img = Image.new("RGB", (width, height), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)

    # 干擾線
    for _ in range(6):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        draw.line((x1, y1, x2, y2), fill=tuple(random.randint(160, 210) for _ in range(3)), width=1)

    # 干擾點
    for _ in range(100):
        x, y = random.randint(0, width), random.randint(0, height)
        draw.point((x, y), fill=tuple(random.randint(160, 210) for _ in range(3)))

    font = _load_captcha_font(34)
    x_cursor = 15
    for ch in text:
        y_offset = random.randint(-6, 6)
        color = tuple(random.randint(10, 90) for _ in range(3))
        draw.text((x_cursor, 25 + y_offset), ch, font=font, fill=color)
        x_cursor += 22 if ch != " " else 12

    buf = io.BytesIO()
    buf.name = "captcha.png"
    img.save(buf, "PNG")
    buf.seek(0)
    return buf, answer


def _generate_captcha_options(answer: int, count: int = 4) -> list:
    """產生含正確答案在內、隨機排序的選項清單。"""
    options = {answer}
    while len(options) < count:
        delta = random.choice([-6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6])
        candidate = answer + delta
        if candidate >= 0:
            options.add(candidate)
    options = list(options)
    random.shuffle(options)
    return options


async def on_captcha_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理圖片算術驗證碼的選項按鈕（captcha_{user_id}_{選項}）。"""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    try:
        parts = query.data.split("_")
        if len(parts) != 3:
            return
        user_id = int(parts[1])
        selected = int(parts[2])

        if user_id not in pending_verifications:
            await query.answer("驗證已過期或無效", show_alert=True)
            return

        verify_info = pending_verifications[user_id]
        chat_id = verify_info["chat_id"]

        if query.from_user.id != user_id:
            await query.answer("這不是你的驗證！", show_alert=True)
            return

        if time.time() - verify_info["timestamp"] > 1800:
            await query.edit_message_caption(caption="❌ 驗證已過期（超過30分鐘）", reply_markup=None)
            asyncio.create_task(_delete_after(query.message, 5))
            del pending_verifications[user_id]
            return

        if selected != verify_info.get("captcha_answer"):
            verify_info["attempts"] = verify_info.get("attempts", 0) + 1
            if verify_info["attempts"] >= VERIFY_ATTEMPT_LIMIT:
                del pending_verifications[user_id]
                await query.edit_message_caption(
                    caption=f"❌ 已達最大嘗試次數（{VERIFY_ATTEMPT_LIMIT}次），請聯繫管理員手動處理。",
                    reply_markup=None,
                )
                asyncio.create_task(_delete_after(query.message, 8))
                return

            # 答錯，重新出題，舊題目直接刪除避免洗版
            captcha_img, answer = generate_math_captcha()
            options = _generate_captcha_options(answer)
            verify_info["captcha_answer"] = answer
            remaining = VERIFY_ATTEMPT_LIMIT - verify_info["attempts"]

            keyboard = [[
                InlineKeyboardButton(str(opt), callback_data=f"captcha_{user_id}_{opt}")
                for opt in options
            ]]
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_photo(
                chat_id,
                photo=captcha_img,
                caption=f"❌ 答錯了，請見新題目（剩餘 {remaining} 次機會）",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # 答對，解除禁言
        try:
            permissions = create_simple_unmute_permissions()
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions,
            )
            del pending_verifications[user_id]

            if verify_info.get("needs_welcome", False):
                await send_welcome_message(
                    context.bot,
                    chat_id,
                    user_id,
                    query.from_user.mention_html(),
                    force_send=True
                )

            await query.edit_message_caption(
                caption=f"✅ {query.from_user.mention_html()} 驗證成功！已恢復所有權限。",
                parse_mode="HTML",
                reply_markup=None,
            )
            asyncio.create_task(_delete_after(query.message, 5))
        except Exception as e:
            logger.error(f"解除禁言失敗: {e}")
            await query.edit_message_caption(caption=f"❌ 解除禁言失敗: {str(e)[:100]}", reply_markup=None)

    except Exception as e:
        logger.error(f"圖片驗證碼處理失敗: {e}")


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

    if not feature_enabled(known_groups.get(chat.id, {}), "referendum"):
        await update.message.reply_text("❌ 此群組已停用全員禁言公投。")
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


# ================== 自訂提案系統 ==================
# 規則：
#   - 任何成員均可發起，每群同時只能有一個自訂提案
#   - 發起時可選擇是否匿名（匿名則隱藏發起人姓名）
#   - 通過條件：同意票數率先達到 10 票
#   - 即時否決條件：反對票數任何時刻超過同意票數（不等 = 超過才否決）
#   - 無延長輪次，結果確立後立即結束
#   - 無論通過或否決，均向行政頻道 ADMIN_GROUP_ID 發送公告並置頂
#   - 逾時：提案發起後 30 分鐘無人達標則自動否決（防死票）

PROPOSAL_TARGET = 10          # 通過所需同意票
PROPOSAL_TIMEOUT_MIN = 30     # 提案逾時分鐘數


def build_proposal_text(chat_id: int) -> str:
    """建立自訂提案訊息文字"""
    prop = active_proposals.get(chat_id)
    if not prop:
        return "提案已結束"

    yes_count = len(prop["yes_votes"])
    no_count  = len(prop["no_votes"])
    initiator = "（匿名）" if prop["anonymous"] else prop["initiator_name"]
    topic = prop["topic"]
    elapsed = int((time.time() - prop["started_at"]) / 60)
    remaining = max(0, PROPOSAL_TIMEOUT_MIN - elapsed)

    warning = ""
    if no_count > 0 and (yes_count - no_count) <= 5:
        gap = yes_count - no_count
        warning = f"\n⚠️ <b>注意：反對票距否決門檻還差 {max(0, 5 - (no_count - yes_count) if no_count > yes_count else 5 + gap)} 票！（反對超過同意 5 票即否決）</b>"

    return (
        f"📋 <b>提案投票</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📌 <b>提案內容：</b>{topic}\n"
        f"👤 <b>發起人：</b>{initiator}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"✅ 同意：<b>{yes_count}</b> 票　❌ 反對：<b>{no_count}</b> 票\n"
        f"🎯 通過門檻：<b>{PROPOSAL_TARGET} 票同意</b>\n"
        f"⏱️ 剩餘時間：約 <b>{remaining}</b> 分鐘{warning}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"每人限投一票，可隨時更換。\n"
        f"⚠️ 若反對票數超過同意票數 <b>5 票以上</b>，提案即時否決。"
    )


def build_proposal_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """建立自訂提案按鈕"""
    prop = active_proposals.get(chat_id)
    yes_count = len(prop["yes_votes"]) if prop else 0
    no_count  = len(prop["no_votes"])  if prop else 0
    keyboard = [[
        InlineKeyboardButton(f"✅ 同意 ({yes_count})", callback_data=f"prop_yes_{chat_id}"),
        InlineKeyboardButton(f"❌ 反對 ({no_count})",  callback_data=f"prop_no_{chat_id}"),
    ]]
    return InlineKeyboardMarkup(keyboard)


async def report_to_admin_group(bot, source_chat_title: str, source_chat_id: int,
                                 topic: str, initiator_name: str, anonymous: bool,
                                 yes_count: int, no_count: int, passed: bool, reason: str):
    """向行政頻道發送提案結果公告並置頂"""
    result_emoji = "✅ 通過" if passed else "❌ 否決"
    initiator_str = "（匿名）" if anonymous else initiator_name
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    text = (
        f"📢 <b>提案公告</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏠 <b>群組：</b>{source_chat_title}（<code>{source_chat_id}</code>）\n"
        f"📌 <b>提案：</b>{topic}\n"
        f"👤 <b>發起人：</b>{initiator_str}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🗳️ <b>結果：{result_emoji}</b>\n"
        f"✅ 同意：<b>{yes_count}</b> 票　❌ 反對：<b>{no_count}</b> 票\n"
        f"📝 <b>原因：</b>{reason}\n"
        f"🕐 <b>時間：</b>{ts}\n"
        f"━━━━━━━━━━━━━━━"
    )

    try:
        msg = await bot.send_message(ADMIN_GROUP_ID, text, parse_mode="HTML")
        try:
            await bot.pin_chat_message(
                chat_id=ADMIN_GROUP_ID,
                message_id=msg.message_id,
                disable_notification=False,
            )
            logger.info(f"📌 已置頂行政頻道公告 msg_id={msg.message_id}")
        except Exception as e:
            logger.warning(f"置頂失敗（可能缺少置頂權限）: {e}")
    except Exception as e:
        logger.error(f"發送行政頻道公告失敗: {e}")


async def proposal_timeout_task(context, chat_id: int):
    """提案逾時自動否決"""
    await asyncio.sleep(PROPOSAL_TIMEOUT_MIN * 60)

    prop = active_proposals.get(chat_id)
    if not prop:
        return  # 已結束

    yes_count = len(prop["yes_votes"])
    no_count  = len(prop["no_votes"])
    prop_copy = active_proposals.pop(chat_id, None)

    timeout_text = (
        f"🗳️ <b>提案結束（逾時）</b>\n"
        f"📌 <b>提案：</b>{prop['topic']}\n"
        f"❌ <b>結果：否決</b>（{PROPOSAL_TIMEOUT_MIN} 分鐘內未達 {PROPOSAL_TARGET} 票同意）\n"
        f"✅ 同意 {yes_count} 票　❌ 反對 {no_count} 票"
    )
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=prop["message_id"],
            text=timeout_text,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"更新逾時提案訊息失敗: {e}")

    source_title = known_groups.get(chat_id, {}).get("title", str(chat_id))
    await report_to_admin_group(
        context.bot, source_title, chat_id,
        prop["topic"], prop["initiator_name"], prop["anonymous"],
        yes_count, no_count, passed=False,
        reason=f"逾時 {PROPOSAL_TIMEOUT_MIN} 分鐘，未達通過門檻"
    )


async def check_proposal_state(context, chat_id: int, query=None):
    """每次投票後檢查提案狀態"""
    prop = active_proposals.get(chat_id)
    if not prop:
        return

    yes_count = len(prop["yes_votes"])
    no_count  = len(prop["no_votes"])

    # ── 即時否決：反對票超過同意票 5 票以上 ──
    if no_count >= yes_count + 5:
        task = prop.get("timeout_task")
        if task and not task.done():
            task.cancel()
        prop_data = active_proposals.pop(chat_id, None)

        reject_text = (
            f"🗳️ <b>提案結束</b>\n"
            f"📌 <b>提案：</b>{prop_data['topic']}\n"
            f"❌ <b>結果：否決</b>（反對票超過同意票 5 票以上）\n"
            f"✅ 同意 {yes_count} 票　❌ 反對 {no_count} 票"
        )
        try:
            if query:
                await query.edit_message_text(reject_text, parse_mode="HTML")
            else:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=prop_data["message_id"],
                    text=reject_text, parse_mode="HTML"
                )
        except Exception as e:
            logger.warning(f"更新否決訊息失敗: {e}")

        source_title = known_groups.get(chat_id, {}).get("title", str(chat_id))
        await report_to_admin_group(
            context.bot, source_title, chat_id,
            prop_data["topic"], prop_data["initiator_name"], prop_data["anonymous"],
            yes_count, no_count, passed=False,
            reason="反對票數超過同意票數 5 票以上"
        )
        return

    # ── 通過：同意票達 10 票 ──
    if yes_count >= PROPOSAL_TARGET:
        task = prop.get("timeout_task")
        if task and not task.done():
            task.cancel()
        prop_data = active_proposals.pop(chat_id, None)

        pass_text = (
            f"🗳️ <b>提案結束</b>\n"
            f"📌 <b>提案：</b>{prop_data['topic']}\n"
            f"✅ <b>結果：通過</b>（達到 {PROPOSAL_TARGET} 票同意）\n"
            f"✅ 同意 {yes_count} 票　❌ 反對 {no_count} 票"
        )
        try:
            if query:
                await query.edit_message_text(pass_text, parse_mode="HTML")
            else:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=prop_data["message_id"],
                    text=pass_text, parse_mode="HTML"
                )
        except Exception as e:
            logger.warning(f"更新通過訊息失敗: {e}")

        source_title = known_groups.get(chat_id, {}).get("title", str(chat_id))
        await report_to_admin_group(
            context.bot, source_title, chat_id,
            prop_data["topic"], prop_data["initiator_name"], prop_data["anonymous"],
            yes_count, no_count, passed=True,
            reason=f"同意票達到 {PROPOSAL_TARGET} 票門檻"
        )
        return

    # ── 尚未決定，更新票數顯示 ──
    text     = build_proposal_text(chat_id)
    keyboard = build_proposal_keyboard(chat_id)
    try:
        if query:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=prop["message_id"],
                text=text, reply_markup=keyboard, parse_mode="HTML"
            )
    except Exception as e:
        logger.warning(f"更新提案訊息失敗: {e}")


async def propose_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /propose <提案內容> 指令"""
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("❌ 此指令僅在群組中可用！")
        return

    if not feature_enabled(known_groups.get(chat.id, {}), "proposals"):
        await update.message.reply_text("❌ 此群組已停用自訂提案。")
        return

    if chat.id in active_proposals:
        await update.message.reply_text("⚠️ 目前已有進行中的提案，請等待結束後再發起！")
        return

    # 取得提案內容
    topic = " ".join(context.args).strip() if context.args else ""
    if not topic:
        await update.message.reply_text(
            "📋 <b>發起自訂提案</b>\n\n"
            "用法：<code>/propose 你的提案內容</code>\n\n"
            "例如：\n"
            "<code>/propose 希望每周五設為自由討論日</code>",
            parse_mode="HTML"
        )
        return

    if len(topic) > 200:
        await update.message.reply_text("❌ 提案內容過長，請控制在 200 字以內！")
        return

    # 暫存草稿，等待匿名選擇
    key = (chat.id, user.id)
    pending_proposal_setup[key] = {
        "topic": topic,
        "chat_id": chat.id,
        "chat_title": chat.title,
        "initiator_id": user.id,
        "initiator_name": user.mention_html(),
    }

    keyboard = [[
        InlineKeyboardButton("👤 公開（顯示我的名字）", callback_data=f"propsetup_public_{chat.id}_{user.id}"),
        InlineKeyboardButton("🕵️ 匿名（隱藏發起人）",   callback_data=f"propsetup_anon_{chat.id}_{user.id}"),
    ]]
    await update.message.reply_text(
        f"📋 <b>提案預覽</b>\n\n"
        f"<b>內容：</b>{topic}\n\n"
        f"請選擇是否匿名發起：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def on_proposal_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理匿名/公開選擇回調"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")  # propsetup_public/anon_CHATID_USERID
    if len(parts) != 4:
        return

    _, choice, chat_id_str, user_id_str = parts
    chat_id = int(chat_id_str)
    user_id = int(user_id_str)

    if query.from_user.id != user_id:
        await query.answer("這不是你的提案設定按鈕！", show_alert=True)
        return

    key = (chat_id, user_id)
    if key not in pending_proposal_setup:
        await query.edit_message_text("❌ 提案設定已過期，請重新使用 /propose 指令。")
        return

    draft = pending_proposal_setup.pop(key)

    if chat_id in active_proposals:
        await query.edit_message_text("⚠️ 其他人剛剛已發起提案，請等待結束後再試！")
        return

    anonymous = (choice == "anon")

    active_proposals[chat_id] = {
        "topic":          draft["topic"],
        "initiator_id":   draft["initiator_id"],
        "initiator_name": draft["initiator_name"],
        "anonymous":      anonymous,
        "yes_votes":      set(),
        "no_votes":       set(),
        "started_at":     time.time(),
        "message_id":     None,
        "timeout_task":   None,
    }

    # 刪除設定訊息，改發正式提案
    try:
        await query.delete_message()
    except Exception:
        pass

    text     = build_proposal_text(chat_id)
    keyboard = build_proposal_keyboard(chat_id)
    msg = await context.bot.send_message(
        chat_id, text, reply_markup=keyboard, parse_mode="HTML"
    )
    active_proposals[chat_id]["message_id"] = msg.message_id

    # 啟動逾時計時器
    active_proposals[chat_id]["timeout_task"] = asyncio.create_task(
        proposal_timeout_task(context, chat_id)
    )

    anon_label = "匿名" if anonymous else "公開"
    logger.info(f"📋 自訂提案發起 [{anon_label}]: 群組 {chat_id}，內容：{draft['topic'][:50]}")


async def on_proposal_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理提案投票按鈕"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")  # prop_yes_CHATID or prop_no_CHATID
    if len(parts) != 3:
        return

    _, option, chat_id_str = parts
    chat_id  = int(chat_id_str)
    voter_id = query.from_user.id

    if chat_id not in active_proposals:
        await query.answer("此提案已結束", show_alert=True)
        return

    prop = active_proposals[chat_id]

    # 發起人不可投票（防止自投）
    if voter_id == prop["initiator_id"] and not prop["anonymous"]:
        await query.answer("⚠️ 發起人不可為自己的提案投票！", show_alert=True)
        return

    # 更換票
    prop["yes_votes"].discard(voter_id)
    prop["no_votes"].discard(voter_id)

    if option == "yes":
        prop["yes_votes"].add(voter_id)
        await query.answer("✅ 已投同意票")
    else:
        prop["no_votes"].add(voter_id)
        await query.answer("❌ 已投反對票")

    await check_proposal_state(context, chat_id, query)


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
/propose <內容> - 發起自訂提案
/list - 查看管理群組
/ban - 管理員禁言用戶
/update - 更新機器人代碼並重啟
/updatead - 僅更新廣告模板（不重啟）
/addsample <文字> - 將文字加入動態廣告樣本庫（Owner；也可回覆訊息使用）
/whitelist <文字> - 將誤封訊息加入非廣告白樣本庫（Owner；也可回覆訊息使用）
/exportsamples - 匯出動態廣告樣本與白樣本 JSON（Owner）
/settings - 查看本群功能開關
/feature <名稱> <on|off> - 管理員修改功能開關

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
    
    message = update.effective_message
    await message.reply_text(response, parse_mode="Markdown", reply_markup=build_help_keyboard())


def build_help_keyboard() -> InlineKeyboardMarkup:
    """建立常用管理功能按鈕，避免管理員必須手動輸入指令。"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ 加入廣告樣本", callback_data="sample_add"),
            InlineKeyboardButton("🛡 加入非廣告白樣本", callback_data="sample_whitelist"),
        ],
        [InlineKeyboardButton("📦 匯出樣本庫", callback_data="sample_export")],
        [InlineKeyboardButton("🧹 整理廣告去重", callback_data="ads_cleanup")],
        [
            InlineKeyboardButton("⚙️ 群組設定", callback_data="menu_settings"),
            InlineKeyboardButton("📖 指令說明", callback_data="menu_help"),
        ],
    ])

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /help 指令"""
    message = update.effective_message
    if not message:
        return
    await message.reply_text(
        "📖 指令說明\n\n"
        "/start - 查看狀態\n"
        "/settings - 群組功能設定\n"
        "/feature <名稱> <on|off> - 開關功能\n"
        "/banme - 彩蛋禁言\n"
        "/ban - 管理員禁言\n"
        "/vote - 發起禁言公投\n"
        "/propose <內容> - 發起提案\n"
        "/addsample - 加入廣告樣本\n"
        "/whitelist - 加入非廣告樣本\n"
        "/exportsamples - 匯出樣本庫\n"
        "/cleanupads - 整理並去除廣告樣本重複項\n"
        "/test - 開始逐則測試（/stop 結束）\n"
        "/omg - 炸群應急鎖群（禁言所有新加入者，/stop 解除）\n"
        "/guard - 防護模式（靜默禁言新加入者並記錄名單，/stop 解除後可選擇踢出）\n"
        "/stop - 停止測試模式 / 解除鎖群或防護模式",
        parse_mode="HTML",
        reply_markup=build_help_keyboard(),
    )

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/test：開始持續測試，直到使用 /stop。"""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return
    active_tests.add((chat.id, user.id))
    await message.reply_text("🧪 已開始測試模式。請逐則傳送文字；輸入 /stop 結束。")


async def omg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/omg：炸群應急鎖群模式。開啟後，在收到 /stop 前，所有新加入成員一律先禁言、保持安靜。"""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return
    if chat.type not in ("group", "supergroup"):
        await message.reply_text("❌ 此指令僅在群組中可用！")
        return
    if not await is_group_admin(context.bot, chat.id, user.id):
        await message.reply_text("❌ 只有本群管理員可以啟用鎖群模式。")
        return

    has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
    if not has_perms:
        await message.reply_text(
            f"❌ 權限檢查失敗！\n{perm_msg}\n\n請確認機器人有「限制成員」與「刪除訊息」權限。",
            parse_mode="HTML",
        )
        return

    known_groups.setdefault(chat.id, {"title": chat.title or str(chat.id), "status": "active"})
    known_groups[chat.id]["title"] = chat.title or str(chat.id)
    known_groups[chat.id]["lockdown"] = True
    save_known_groups()

    logger.warning(f"🚨 鎖群模式已由 {user.id} 於群組 {chat.id} 啟動")
    await message.reply_text(
        "🚨 <b>鎖群模式已啟動</b>\n\n"
        "在收到 /stop 之前：\n"
        "• 所有新加入成員將直接禁言，不做簡介/廣告判斷\n"
        "• 不發歡迎訊息、不發驗證按鈕，保持安靜\n"
        "• 「OO加入了群組」系統訊息會被自動刪除\n\n"
        "確認情況解除後，請管理員執行 /stop 解鎖。",
        parse_mode="HTML",
    )


async def guard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/guard：防護模式。開啟後，在收到 /stop 前，所有新加入成員會被完全靜默地關閉所有權限
    （不發送任何提示訊息），並記錄名單；關閉時可選擇是否要把這段期間加入的人踢出。"""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return
    if chat.type not in ("group", "supergroup"):
        await message.reply_text("❌ 此指令僅在群組中可用！")
        return
    if not await is_group_admin(context.bot, chat.id, user.id):
        await message.reply_text("❌ 只有本群管理員可以啟用防護模式。")
        return

    has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
    if not has_perms:
        await message.reply_text(
            f"❌ 權限檢查失敗！\n{perm_msg}\n\n請確認機器人有「限制成員」權限（同時涵蓋禁言與踢出）。",
            parse_mode="HTML",
        )
        return

    known_groups.setdefault(chat.id, {"title": chat.title or str(chat.id), "status": "active"})
    known_groups[chat.id]["title"] = chat.title or str(chat.id)
    known_groups[chat.id]["guard_mode"] = True
    known_groups[chat.id]["guard_joined"] = []
    save_known_groups()

    logger.warning(f"🛡 防護模式已由 {user.id} 於群組 {chat.id} 啟動")
    await message.reply_text(
        "🛡 <b>防護模式已啟動</b>\n\n"
        "在收到 /stop 之前：\n"
        "• 所有新加入成員將被直接關閉所有權限\n"
        "• 完全靜默，不發送任何提示或驗證訊息\n"
        "• 名單會被記錄下來，關閉時可選擇要不要踢出\n\n"
        "確認情況解除後，請管理員執行 /stop。",
        parse_mode="HTML",
    )


def _build_guard_pick_keyboard(chat_id: int, info: dict) -> InlineKeyboardMarkup:
    rows = []
    for uid, name in info["users"].items():
        mark = "✅" if uid in info["selected"] else "☐"
        label = f"{mark} {name}"
        if len(label) > 60:
            label = label[:57] + "..."
        rows.append([InlineKeyboardButton(label, callback_data=f"guardsel_{chat_id}_{uid}")])
    rows.append([
        InlineKeyboardButton("👢 踢出已選中", callback_data=f"guardexec_selected_{chat_id}"),
        InlineKeyboardButton("👢 踢出未選中", callback_data=f"guardexec_unselected_{chat_id}"),
    ])
    return InlineKeyboardMarkup(rows)


async def _execute_guard_kick(bot, chat_id: int, user_ids: list) -> Tuple[int, int]:
    """踢出指定用戶（ban 後立即 unban，允許之後重新加入）。回傳 (成功數, 失敗數)。"""
    success, failed = 0, 0
    for uid in user_ids:
        try:
            await bot.ban_chat_member(chat_id, uid)
            await bot.unban_chat_member(chat_id, uid)
            success += 1
        except Exception as e:
            logger.error(f"防護模式踢出失敗 chat={chat_id} user={uid}: {e}")
            failed += 1
    return success, failed


async def on_guard_kick_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理防護模式關閉後「全部踢出／挑選踢出／不踢出」及挑選介面的按鈕。"""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    chat = query.message.chat if query.message else None
    if not chat or not await is_group_admin(context.bot, chat.id, query.from_user.id):
        await query.answer("只有本群管理員能操作", show_alert=True)
        return

    data = query.data

    if data.startswith("guardkick_all_"):
        chat_id = int(data.split("_")[2])
        info = pending_guard_kick.pop(chat_id, None)
        if not info:
            await query.edit_message_text("❌ 這份名單已過期或已處理。", reply_markup=None)
            return
        success, failed = await _execute_guard_kick(context.bot, chat_id, list(info["users"].keys()))
        text = f"👢 已踢出 {success} 人"
        if failed:
            text += f"，{failed} 人踢出失敗（可能已離群或權限不足）"
        await query.edit_message_text(text, reply_markup=None)
        return

    if data.startswith("guardkick_none_"):
        chat_id = int(data.split("_")[2])
        pending_guard_kick.pop(chat_id, None)
        await query.edit_message_text("🚫 已保留不踢出，這些成員維持禁言狀態，請自行手動處理。", reply_markup=None)
        return

    if data.startswith("guardkick_pick_"):
        chat_id = int(data.split("_")[2])
        info = pending_guard_kick.get(chat_id)
        if not info:
            await query.edit_message_text("❌ 這份名單已過期或已處理。", reply_markup=None)
            return
        await query.edit_message_text(
            f"🗂 挑選要踢出的成員（共 {len(info['users'])} 人，預設全選）\n"
            f"點名字可切換選取／取消，選好後點下方按鈕執行。",
            reply_markup=_build_guard_pick_keyboard(chat_id, info),
        )
        return

    if data.startswith("guardsel_"):
        _, chat_id_str, uid_str = data.split("_")
        chat_id, uid = int(chat_id_str), int(uid_str)
        info = pending_guard_kick.get(chat_id)
        if not info:
            await query.answer("這份名單已過期", show_alert=True)
            return
        if uid in info["selected"]:
            info["selected"].discard(uid)
        else:
            info["selected"].add(uid)
        await query.edit_message_reply_markup(reply_markup=_build_guard_pick_keyboard(chat_id, info))
        return

    if data.startswith("guardexec_selected_") or data.startswith("guardexec_unselected_"):
        mode_selected = data.startswith("guardexec_selected_")
        chat_id = int(data.rsplit("_", 1)[1])
        info = pending_guard_kick.pop(chat_id, None)
        if not info:
            await query.edit_message_text("❌ 這份名單已過期或已處理。", reply_markup=None)
            return
        all_ids = set(info["users"].keys())
        target_ids = info["selected"] if mode_selected else (all_ids - info["selected"])
        if not target_ids:
            await query.edit_message_text("ℹ️ 沒有選中任何人，未執行踢出。", reply_markup=None)
            return
        success, failed = await _execute_guard_kick(context.bot, chat_id, list(target_ids))
        text = f"👢 已踢出 {success} 人"
        if failed:
            text += f"，{failed} 人踢出失敗（可能已離群或權限不足）"
        await query.edit_message_text(text, reply_markup=None)
        return


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stop：停止目前使用者的持續測試模式；群組中若鎖群模式（/omg）或防護模式（/guard）啟動中，
    管理員可一併解除；防護模式解除時，若期間有新成員加入，會另外彈出處理選項。"""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return
    active_tests.discard((chat.id, user.id))

    group_info = known_groups.get(chat.id, {})
    lockdown_active = group_info.get("lockdown", False)
    guard_active = group_info.get("guard_mode", False)

    if chat.type not in ("group", "supergroup") or not (lockdown_active or guard_active):
        await message.reply_text("🛑 已停止測試模式。")
        return

    if not await is_group_admin(context.bot, chat.id, user.id):
        await message.reply_text("🛑 已停止測試模式。\n❌ 鎖群/防護模式仍在運作中，僅本群管理員可解除。")
        return

    lines = ["🛑 已停止測試模式。"]

    if lockdown_active:
        known_groups[chat.id]["lockdown"] = False
        logger.warning(f"🔓 鎖群模式已由 {user.id} 於群組 {chat.id} 解除")
        lines.append("🔓 鎖群模式已解除，新加入成員恢復正常入群檢測流程。")

    joined = []
    if guard_active:
        known_groups[chat.id]["guard_mode"] = False
        joined = known_groups[chat.id].get("guard_joined", [])
        known_groups[chat.id]["guard_joined"] = []
        logger.warning(f"🛡 防護模式已由 {user.id} 於群組 {chat.id} 解除，期間共 {len(joined)} 人加入")
        lines.append(f"🛡 防護模式已解除（期間共 {len(joined)} 人加入）。")

    save_known_groups()
    await message.reply_text("\n".join(lines))

    if joined:
        pending_guard_kick[chat.id] = {
            "users": {u["id"]: u["name"] for u in joined},
            "selected": set(u["id"] for u in joined),  # 預設全選
        }
        keyboard = [[
            InlineKeyboardButton("👢 全部踢出", callback_data=f"guardkick_all_{chat.id}"),
            InlineKeyboardButton("🗂 挑選踢出", callback_data=f"guardkick_pick_{chat.id}"),
            InlineKeyboardButton("🚫 不踢出", callback_data=f"guardkick_none_{chat.id}"),
        ]]
        await message.reply_text(
            f"防護模式期間加入的 {len(joined)} 人要怎麼處理？",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def test_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """測試模式下逐則分析文字，不執行刪除或禁言。"""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not message.text or not chat or not user:
        return
    if (chat.id, user.id) not in active_tests:
        return
    is_ad, confidence, reason = detect_ad(message.text)
    result = "✅ 會刪除並禁言" if is_ad else "✅ 不會刪除，會放行"
    await message.reply_text(
        f"🧪 測試結果：{result}\n"
        f"判定：{'廣告' if is_ad else '正常訊息'}\n"
        f"信心：{confidence:.0%}\n"
        f"原因：{reason}\n\n"
        f"（測試模式不會真的刪除或禁言）"
    )


async def banme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /banme 指令"""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type != "private" and not feature_enabled(known_groups.get(chat.id, {}), "banme"):
        await update.message.reply_text("❌ 此群組已停用 /banme。")
        return
    
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


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /update 指令：從 GitHub 拉取最新代碼並重啟機器人"""
    user = update.effective_user
    chat = update.effective_chat

    if user.id != OWNER_ID:
        await update.message.reply_text("❌ 僅管理員可用此指令！")
        return

    msg_wait = await update.message.reply_text("🔄 正在更新，請稍候...", parse_mode="HTML")

    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            capture_output=True, text=True, timeout=30,
            cwd=repo_dir,
        )
        output = result.stdout.strip()
        error = result.stderr.strip()

        # 刪除「請稍候」提示
        asyncio.create_task(_delete_after(msg_wait, 0))

        if result.returncode != 0:
            diag = (
                f"repo_dir={repo_dir}\n"
                f"os.getcwd()={os.getcwd()}\n"
                f"git={shutil.which('git')}\n"
                f"PATH={os.environ.get('PATH', '')}"
            )
            await update.message.reply_text(
                f"❌ 更新失敗\n\n stderr: {error}\n stdout: {output}\n\n🔍 診斷資訊：\n{diag}",
                parse_mode="HTML"
            )
            return

        if "Already up to date" in output:
            msg = await update.message.reply_text("✅ 已是最新版本，無需更新。")
            asyncio.create_task(_delete_after(msg, 20))
            return

        msg = await update.message.reply_text(
            f"✅ 更新成功！\n\n📤 {output}\n\n⏳ 機器人將在 3 秒後重啟...",
            parse_mode="HTML"
        )

        # 重啟前同步刪除用戶的 /update 指令、「請稍候」和結果訊息，避免重啟後遺留
        await asyncio.sleep(2)
        for m in [update.message, msg, msg_wait]:
            try:
                await m.delete()
            except Exception:
                pass

        # 再等1秒後重啟
        await asyncio.sleep(1)
        os.execv(sys.executable, sys.argv)

    except subprocess.TimeoutExpired:
        await update.message.reply_text("❌ 更新超時，請稍後再試。")
    except Exception as e:
        await update.message.reply_text(f"❌ 更新失敗：{e}", parse_mode="HTML")


async def updatead_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /updatead 指令：從 GitHub 拉取最新代碼並熱重載廣告模板（不重啟機器人）"""
    user = update.effective_user

    if user.id != OWNER_ID:
        await update.message.reply_text("❌ 僅管理員可用此指令！")
        return

    msg_wait = await update.message.reply_text("🔄 正在更新廣告模板，請稍候...", parse_mode="HTML")

    try:
        # 先 git pull 拉取最新代碼
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            capture_output=True, text=True, timeout=30,
            cwd=repo_dir,
        )
        output = result.stdout.strip()
        error = result.stderr.strip()

        # 刪除「請稍候」提示
        asyncio.create_task(_delete_after(msg_wait, 0))

        if result.returncode != 0:
            diag = (
                f"repo_dir={repo_dir}\n"
                f"os.getcwd()={os.getcwd()}\n"
                f"git={shutil.which('git')}\n"
                f"PATH={os.environ.get('PATH', '')}"
            )
            await update.message.reply_text(
                f"❌ git pull 失敗\n\n stderr: {error}\n stdout: {output}\n\n🔍 診斷資訊：\n{diag}",
                parse_mode="HTML"
            )
            return

        # 熱重載：先 reload ad_templates，再 reload ad_detector（會自動重建 TF-IDF 向量器）
        import importlib
        import ad_templates as _adt
        import ad_detector as _ad

        importlib.reload(_adt)
        importlib.reload(_ad)

        # 更新 detect_ad 的引用（main.py 頂層 from ad_detector import detect_ad）
        import main as _self
        # 直接替換 detect_ad 函數引用
        import sys
        sys.modules[__name__].detect_ad = _ad.detect_ad

        # 統計模板數量
        template_count = len(_adt.AD_TEMPLATES)

        msg = await update.message.reply_text(
            f"✅ 廣告模板更新成功！\n\n"
            f"📤 {output}\n"
            f"📊 當前模板數量：{template_count} 條\n"
            f"🔄 模板已熱重載，無需重啟。",
            parse_mode="HTML"
        )
        asyncio.create_task(_delete_after(msg, 20))
        logger.info(f"✅ 廣告模板已熱重載，共 {template_count} 條")

    except subprocess.TimeoutExpired:
        await update.message.reply_text("❌ 更新超時，請稍後再試。")
    except Exception as e:
        await update.message.reply_text(f"❌ 更新廣告模板失敗：{e}", parse_mode="HTML")


# ================== 動態樣本庫指令 ==================

def _reload_detector():
    """重建偵測器向量器，讓動態樣本即時生效。"""
    import importlib
    import ad_samples as _as
    import ad_detector as _ad
    importlib.reload(_as)
    importlib.reload(_ad)
    import sys
    sys.modules[__name__].detect_ad = _ad.detect_ad


def _extract_sample_text(update) -> str:
    """從指令取得樣本文字：優先取被回覆訊息，其次取指令後的參數。"""
    msg = update.effective_message
    if msg and msg.reply_to_message and msg.reply_to_message.text:
        return msg.reply_to_message.text.strip()
    # 取指令後文字
    if msg and msg.text:
        parts = msg.text.split(None, 1)
        if len(parts) == 2:
            return parts[1].strip()
    return ""


def _dedupe_ad_samples():
    """整理動態廣告樣本，並與官方模板庫做正規化去重。

    官方模板是基準；若動態樣本與官方模板在 NFKC/casefold/去空白符號後相同，
    保留官方版本並移除動態副本，避免匯入的樣本只和自己比較。
    """
    from ad_samples import load_ad_samples, save_ad_samples, normalize_key, official_template_keys

    official_keys = official_template_keys()
    samples = load_ad_samples()
    seen = set(official_keys)
    cleaned = []
    for sample in samples:
        normalized = normalize_key(sample)
        if normalized and normalized not in seen:
            seen.add(normalized)
            cleaned.append(sample.strip())
    removed = len(samples) - len(cleaned)
    save_ad_samples(cleaned)
    return len(cleaned), removed, len(official_keys)


async def cleanup_ads_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """整理廣告樣本庫，移除重複項目。"""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user:
        return
    if chat.type == "private" or not await is_group_admin(context.bot, chat.id, user.id):
        await message.reply_text("❌ 只有本群管理員可以整理廣告樣本。")
        return
    try:
        total, removed, official_total = _dedupe_ad_samples()
        _reload_detector()
        await message.reply_text(
            f"✅ 廣告樣本整理完成\n"
            f"📚 官方模板：{official_total} 條\n"
            f"📊 動態樣本保留：{total} 條\n"
            f"🗑 移除重複：{removed} 條"
        )
    except Exception as e:
        logger.exception("整理廣告樣本失敗")
        await message.reply_text(f"❌ 整理失敗：{e}")



async def addsample_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addsample：入庫，把回覆的訊息或指令後文字加入廣告樣本庫"""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("❌ 僅管理員可用此指令！")
        return

    from ad_samples import add_ad_sample, load_ad_samples
    text = _extract_sample_text(update)
    if not text:
        await update.message.reply_text(
            "❌ 用法：回覆一則廣告訊息並發送 /addsample，或 /addsample <文字>"
        )
        return

    added = add_ad_sample(text)
    if not added:
        await update.message.reply_text("ℹ️ 此樣本已存在於廣告樣本庫或原生模板庫（正規化去重），未重複加入。")
        return

    try:
        _reload_detector()
        total = len(load_ad_samples())
        preview = text if len(text) <= 60 else text[:60] + "…"
        await update.message.reply_text(
            f"✅ 已入庫廣告樣本並即時生效！\n\n"
            f"📝 內容：{preview}\n"
            f"📊 動態廣告樣本數：{total} 條"
        )
        logger.info(f"入庫廣告樣本，動態庫共 {total} 條")
    except Exception as e:
        await update.message.reply_text(f"⚠️ 已寫入樣本庫，但熱重載失敗：{e}")


async def whitelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/whitelist：誤封處理，把回覆的訊息或指令後文字加入白樣本（非廣告）"""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("❌ 僅管理員可用此指令！")
        return

    from ad_samples import add_whitelist_sample, load_whitelist_samples
    text = _extract_sample_text(update)
    if not text:
        await update.message.reply_text(
            "❌ 用法：回覆一則被誤判的訊息並發送 /whitelist，或 /whitelist <文字>"
        )
        return

    added = add_whitelist_sample(text)

    # 若是回覆某位用戶的訊息，順便嘗試恢復其發言權限（誤封解除）
    unmute_note = ""
    reply_msg = update.effective_message.reply_to_message if update.effective_message else None
    if reply_msg and reply_msg.from_user and not reply_msg.from_user.is_bot:
        try:
            await context.bot.restrict_chat_member(
                chat_id=update.effective_chat.id,
                user_id=reply_msg.from_user.id,
                permissions=create_simple_unmute_permissions(),
            )
            unmute_note = "\n🔓 已恢復該用戶發言權限。"
        except Exception as e:
            logger.error(f"/whitelist 解除禁言失敗: {e}")
            unmute_note = f"\n⚠️ 解除禁言失敗：{str(e)[:80]}"

    if not added:
        await update.message.reply_text(f"ℹ️ 此樣本已存在於白樣本庫，未重複加入。{unmute_note}")
        return

    try:
        _reload_detector()
        total = len(load_whitelist_samples())
        preview = text if len(text) <= 60 else text[:60] + "…"
        await update.message.reply_text(
            f"✅ 已加入白樣本（非廣告）並即時生效！\n\n"
            f"📝 內容：{preview}\n"
            f"📊 白樣本數：{total} 條\n"
            f"🛡 之後與此相似的訊息不會被誤封。{unmute_note}"
        )
        logger.info(f"加入白樣本，白樣本庫共 {total} 條")
    except Exception as e:
        await update.message.reply_text(f"⚠️ 已寫入白樣本庫，但熱重載失敗：{e}{unmute_note}")


async def exportsamples_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/exportsamples：提取匯出動態樣本庫（廣告樣本 + 白樣本）為檔案"""
    user = update.effective_user
    message = update.effective_message
    chat = update.effective_chat
    if not user or not message or not chat:
        return
    if chat.type == "private":
        await message.reply_text("❌ 此指令僅在群組中可用。")
        return
    if not await is_group_admin(context.bot, chat.id, user.id):
        await message.reply_text("❌ 只有本群管理員可以匯出樣本庫。")
        return

    import json
    import io
    from ad_samples import load_ad_samples, load_whitelist_samples

    ad_list = load_ad_samples()
    wl_list = load_whitelist_samples()

    payload = {
        "ad_samples": ad_list,
        "whitelist_samples": wl_list,
        "ad_count": len(ad_list),
        "whitelist_count": len(wl_list),
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    bio = io.BytesIO(data)
    bio.name = "samples_export.json"

    try:
        await message.reply_document(
            document=bio,
            filename="samples_export.json",
            caption=(
                f"📦 動態樣本庫匯出\n"
                f"廣告樣本：{len(ad_list)} 條\n"
                f"白樣本：{len(wl_list)} 條"
            ),
        )
        logger.info(f"匯出樣本庫：廣告{len(ad_list)}/白{len(wl_list)}")
    except Exception as e:
        # 傳檔失敗時退回純文字摘要
        await message.reply_text(
            f"📦 動態樣本庫\n廣告樣本：{len(ad_list)} 條\n白樣本：{len(wl_list)} 條\n\n"
            f"（傳檔失敗：{e}）"
        )




async def is_group_admin(bot, chat_id: int, user_id: int) -> bool:
    """確認使用者是該群組管理員；Owner 可跨群組管理樣本。"""
    if user_id == OWNER_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        logger.warning(f"樣本庫權限檢查失敗 chat={chat_id} user={user_id}: {e}")
        return False


async def on_sample_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理樣本庫按鈕；新增樣本時由下一則文字訊息提供內容。"""
    query = update.callback_query
    if not query:
        return
    user = query.from_user
    callback_chat_id = query.message.chat_id if query.message else None
    if callback_chat_id is None or not await is_group_admin(context.bot, callback_chat_id, user.id):
        await query.answer("只有本群管理員可以操作樣本庫", show_alert=True)
        return

    await query.answer()
    action = query.data
    if action.startswith("false_positive_whitelist:"):
        action_name, _, token = action.partition(":")
    else:
        action_name, token = action, ""
    chat_id = query.message.chat_id if query.message else user.id
    key = (chat_id, user.id)

    if action.startswith("feature_toggle:"):
        feature_name = action.split(":", 1)[1]
        if feature_name not in DEFAULT_FEATURES:
            await query.answer("無效的功能項目", show_alert=True)
            return
        set_group_feature(known_groups, chat_id, feature_name, not feature_enabled(
            known_groups.get(chat_id, {}), feature_name
        ))
        known_groups.setdefault(chat_id, {})["title"] = query.message.chat.title or str(chat_id)
        save_known_groups()
        enabled = feature_enabled(known_groups.get(chat_id, {}), feature_name)
        features = get_group_features(known_groups.get(chat_id, {}))
        lines = ["⚙️ <b>群組功能設定</b>"]
        lines.extend(
            f"{'✅' if value else '⛔'} <code>{name}</code>：{FEATURE_LABELS[name]}"
            for name, value in features.items()
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{'✅' if value else '⛔'} {name}",
                callback_data=f"feature_toggle:{name}",
            )]
            for name, value in features.items()
        ])
        await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)
        return

    if action_name == "ads_cleanup":
        await query.answer("正在整理廣告樣本…")
        await cleanup_ads_command(update, context)
        return
    if action_name == "sample_export":
        await exportsamples_command(update, context)
        return
    if action_name == "menu_settings":
        await settings_command(update, context)
        return
    if action_name == "menu_help":
        await help_command(update, context)
        return
    if action_name == "sample_add":
        pending_sample_actions[key] = "add_ad"
        await query.message.reply_text(
            "➕ 請直接傳送要加入的廣告樣本文字。\n"
            "（只會讀取你下一則文字訊息。）"
        )
    elif action_name == "sample_whitelist":
        pending_sample_actions[key] = "whitelist"
        await query.message.reply_text(
            "🛡 請直接傳送被誤封的訊息文字，加入非廣告白樣本庫。\n"
            "（只會讀取你下一則文字訊息。）"
        )
    elif action_name == "false_positive_whitelist":
        record = pending_false_positive_samples.pop(token, None)
        if not record:
            await query.answer("這則攔截通知已過期，請使用 /whitelist 回覆原訊息", show_alert=True)
            return
        text = record["text"]
        target_chat_id = record.get("chat_id", chat_id)
        target_user_id = record.get("user_id")

        from ad_samples import add_whitelist_sample, load_whitelist_samples
        added = add_whitelist_sample(text)

        # 恢復被誤封用戶的發言權限
        unmute_note = ""
        if target_user_id is not None:
            try:
                await context.bot.restrict_chat_member(
                    chat_id=target_chat_id,
                    user_id=target_user_id,
                    permissions=create_simple_unmute_permissions(),
                )
                unmute_note = "，已恢復該用戶發言權限"
            except Exception as e:
                logger.error(f"誤封解除禁言失敗 chat={target_chat_id} user={target_user_id}: {e}")
                unmute_note = f"，但解除禁言失敗：{str(e)[:80]}"

        if not added:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"ℹ️ 此訊息已在非廣告白樣本庫中{unmute_note}。")
            return
        try:
            _reload_detector()
            total = len(load_whitelist_samples())
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ 已將該則誤封訊息加入非廣告樣本庫，目前共 {total} 條{unmute_note}。")
        except Exception as e:
            await query.message.reply_text(f"⚠️ 已寫入非廣告樣本庫，但熱重載失敗：{e}{unmute_note}")

    elif action_name == "menu_settings":
        await settings_command(update, context)
    elif action_name == "menu_help":
        await help_command(update, context)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """統一文字訊息入口：先處理樣本輸入，再進行群組廣告偵測。"""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not message.text or not chat or not user:
        return
    if (chat.id, user.id) in active_tests:
        await test_message(update, context)
        return
    if (chat.id, user.id) in pending_sample_actions:
        await handle_sample_input(update, context)
        return
    if chat.type in ("group", "supergroup"):
        await handle_message_ad_check(update, context)


async def handle_sample_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收按鈕流程中管理員輸入的樣本文字。"""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not message.text or not user or not chat:
        return
    key = (chat.id, user.id)
    if not await is_group_admin(context.bot, chat.id, user.id):
        await message.reply_text("❌ 只有本群管理員可以輸入樣本。")
        pending_sample_actions.pop(key, None)
        return
    action = pending_sample_actions.pop(key, None)
    if not action:
        return
    consumed_sample_messages.add((chat.id, message.message_id))
    if user.id != OWNER_ID:
        await message.reply_text("❌ 僅 Owner 可以管理樣本庫。")
        return

    text = message.text.strip()
    if action == "add_ad":
        from ad_samples import add_ad_sample, load_ad_samples
        added = add_ad_sample(text)
        label = "廣告樣本"
        total = len(load_ad_samples())
    else:
        from ad_samples import add_whitelist_sample, load_whitelist_samples
        added = add_whitelist_sample(text)
        label = "非廣告白樣本"
        total = len(load_whitelist_samples())

    if not added:
        await message.reply_text(f"ℹ️ 此{label}已存在，沒有重複加入。")
        return
    try:
        _reload_detector()
        await message.reply_text(f"✅ 已加入{label}並即時生效！\n📊 目前共 {total} 條。")
    except Exception as e:
        await message.reply_text(f"⚠️ 已寫入樣本庫，但熱重載失敗：{e}")

async def handle_new_member_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """鎖群模式（/omg）下，刪除「OO加入了群組」系統訊息，保持安靜。"""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return
    if not known_groups.get(chat.id, {}).get("lockdown", False):
        return
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"鎖群模式刪除入群訊息失敗 chat={chat.id}: {e}")


async def get_all_admins(bot, chat_id: int) -> list:
    """取得群組所有管理員列表"""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        return [a.user for a in admins if not a.user.is_bot]
    except Exception as e:
        logger.error(f"取得管理員列表失敗: {e}")
        return []

async def handle_message_ad_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """偵測訊息是否為廣告，是則禁言並通知管理員"""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not user or not message.text:
        return
    if chat.type == "private":
        return
    if (chat.id, message.message_id) in consumed_sample_messages:
        consumed_sample_messages.discard((chat.id, message.message_id))
        return
    if not feature_enabled(known_groups.get(chat.id, {}), "ad_detection"):
        return

    # 管理員發的訊息不偵測
    try:
        member = await chat.get_member(user.id)
        if member.status in ["administrator", "creator"]:
            return
    except Exception:
        pass

    is_ad, confidence, reason = detect_ad(message.text)
    if not is_ad:
        return

    logger.info(f"廣告偵測: 用戶 {user.id} 在 {chat.id} | {reason} | 信心:{confidence:.2f}")

    # 禁言該用戶
    if feature_enabled(known_groups.get(chat.id, {}), "ad_mute"):
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions=create_simple_mute_permissions(),
            )
        except Exception as e:
            logger.error(f"廣告禁言失敗: {e}")

    # 刪除廣告訊息
    if feature_enabled(known_groups.get(chat.id, {}), "ad_delete"):
        try:
            await message.delete()
        except Exception:
            pass

    if not feature_enabled(known_groups.get(chat.id, {}), "ad_notify_admins"):
        return

    # 取得所有管理員並產生 @ 列表
    admins = await get_all_admins(context.bot, chat.id)
    admin_mentions = " ".join(
        f'<a href="tg://user?id={a.id}">{a.full_name}</a>' for a in admins
    )

    token = uuid.uuid4().hex
    pending_false_positive_samples[token] = {
        "text": message.text,
        "chat_id": chat.id,
        "user_id": user.id,
    }
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🛡 誤封：加入非廣告樣本",
            callback_data=f"false_positive_whitelist:{token}",
        )
    ]])

    notice = (
        f"🚨 <b>廣告攔截</b>\n"
        f"用戶：{user.mention_html()}\n"
        f"原因：{reason}\n"
        f"置信度：{confidence:.0%}\n\n"
        f"已自動禁言，請管理員確認：\n{admin_mentions}"
    )
    await context.bot.send_message(chat.id, notice, parse_mode="HTML", reply_markup=keyboard)


# ================== /ban 指令 ==================

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理員用 /ban：禁言目標用戶（回覆訊息或附帶 user_id）"""
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if chat.type == "private":
        await message.reply_text("❌ 此指令僅在群組中可用！")
        return

    if not feature_enabled(known_groups.get(chat.id, {}), "ban_command"):
        await message.reply_text("❌ 此群組已停用 /ban。")
        return

    # 確認發令者是管理員
    try:
        caller = await chat.get_member(user.id)
        if caller.status not in ["administrator", "creator"]:
            await message.reply_text("❌ 只有管理員才能使用此指令！")
            return
    except Exception:
        await message.reply_text("❌ 無法確認你的權限。")
        return

    # 取得目標用戶：優先回覆對象，其次 /ban <user_id>
    target_user = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
    elif context.args:
        try:
            target_id = int(context.args[0])
            target_chat = await context.bot.get_chat(target_id)
            class _FakeUser:
                def __init__(self, c):
                    self.id = c.id
                    self.full_name = c.full_name or str(c.id)
                def mention_html(self):
                    return f'<a href="tg://user?id={self.id}">{self.full_name}</a>'
            target_user = _FakeUser(target_chat)
        except Exception:
            await message.reply_text("❌ 無效的用戶 ID，或請直接回覆要禁言的訊息。")
            return
    else:
        await message.reply_text(
            "❌ 用法：\n"
            "• 回覆某人訊息後輸入 /ban\n"
            "• 或 /ban <user_id>"
        )
        return

    # 不能禁言管理員
    try:
        target_member = await chat.get_member(target_user.id)
        if target_member.status in ["administrator", "creator"]:
            await message.reply_text("❌ 無法禁言管理員！")
            return
    except Exception:
        pass

    # 執行禁言
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target_user.id,
            permissions=create_simple_mute_permissions(),
        )
    except Exception as e:
        await message.reply_text(f"❌ 禁言失敗：{e}")
        return

    mention = target_user.mention_html() if callable(target_user.mention_html) else target_user.mention_html
    msg = await message.reply_text(
        f"🔇 {mention} 已被禁言。",
        parse_mode="HTML"
    )
    asyncio.create_task(_delete_after(msg, 20))
    logger.info(f"/ban: 管理員 {user.id} 禁言用戶 {target_user.id} 於群組 {chat.id}")

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
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("feature", feature_command))
    application.add_handler(CommandHandler("vote", referendum_command))
    application.add_handler(CommandHandler("propose", propose_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("update", update_command))
    application.add_handler(CommandHandler("updatead", updatead_command))
    application.add_handler(CommandHandler("addsample", addsample_command))
    application.add_handler(CommandHandler("whitelist", whitelist_command))
    application.add_handler(CommandHandler("exportsamples", exportsamples_command))
    application.add_handler(CommandHandler("cleanupads", cleanup_ads_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("omg", omg_command))
    application.add_handler(CommandHandler("guard", guard_command))

    # 鎖群模式（/omg）：刪除「OO加入了群組」系統訊息
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        handle_new_member_service_message,
    ))

    # 按鈕操作：樣本庫、設定與說明
    application.add_handler(CallbackQueryHandler(
        on_sample_action,
        pattern=r"^(sample_add|sample_whitelist|sample_export|ads_cleanup|menu_settings|menu_help|feature_toggle:[a-z_]+|false_positive_whitelist:[0-9a-f]+)$",
    ))

    # 按鈕選擇新增樣本後，下一則文字直接作為樣本內容
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text_message,
    ), group=0)

    # 廣告偵測已由統一文字入口處理，避免樣本輸入被第二個 handler 漏掉或重複處理。

    application.add_handler(CallbackQueryHandler(on_proposal_setup,  pattern=r"^propsetup_"))
    application.add_handler(CallbackQueryHandler(on_proposal_vote,   pattern=r"^prop_"))
    application.add_handler(CallbackQueryHandler(on_referendum_vote, pattern=r"^ref_"))
    application.add_handler(CallbackQueryHandler(on_captcha_click, pattern=r"^captcha_"))
    application.add_handler(CallbackQueryHandler(on_guard_kick_click, pattern=r"^guard(kick|sel|exec)_"))
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

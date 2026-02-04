#!/bin/bash
echo "============== Telegram 隱形管理機器人安裝 =============="

# 1. 安裝 Python 3.12
if ! command -v python3.12 &> /dev/null; then
    echo "❌ 未檢測到 Python 3.12+，開始安裝..."
    apt-get update && apt-get install -y python3.12 python3.12-venv python3-pip
fi

# 2. 創建虛擬環境
echo "🐍 創建虛擬環境..."
python3.12 -m venv bot_env
source bot_env/bin/activate || { echo "❌ 虛擬環境激活失敗"; exit 1; }

# 3. 安裝依賴
echo "📦 安裝依賴包..."
pip install --upgrade pip
pip install python-telegram-bot==20.7 -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4. 設置 Token 和 Owner ID
read -p "請輸入你的 Telegram Bot Token：" BOT_TOKEN
read -p "請輸入你的 Telegram ID（在 @userinfobot 查詢）：" OWNER_ID

# 驗證輸入
if [[ -z "$BOT_TOKEN" ]]; then
    echo "❌ Token 不能為空！"
    exit 1
fi

if ! [[ "$OWNER_ID" =~ ^[0-9]+$ ]]; then
    echo "❌ OWNER_ID 必須是數字！"
    exit 1
fi

# 保存到環境變量
echo "export BOT_TOKEN=$BOT_TOKEN" >> ~/.bashrc
echo "export OWNER_ID=$OWNER_ID" >> ~/.bashrc
echo "export BOT_TOKEN=$BOT_TOKEN" >> bot_env/bin/activate
echo "export OWNER_ID=$OWNER_ID" >> bot_env/bin/activate

# 立即生效
export BOT_TOKEN=$BOT_TOKEN
export OWNER_ID=$OWNER_ID
source ~/.bashrc

echo "✅ BOT_TOKEN 設置完成！"
echo "✅ OWNER_ID 設置完成！"

# 5. 創建主程式
echo "📝 創建主程式..."
cat > main.py << 'EOF'
import os
import re
import asyncio
import time
import random
from typing import Dict
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

# ================== 處理機器人加入群組（靜默模式） ==================
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

# ================== 指令處理 ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /start 指令（僅管理員可用）"""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != "private":
        return
    
    if user.id != OWNER_ID:
        await update.message.reply_text(
            "🚫 此機器人不接受私聊\n"
            "如需使用功能，請在群組中使用",
            parse_mode="HTML"
        )
        return
    
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
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != "private":
        return
    
    if user.id != OWNER_ID:
        await update.message.reply_text(
            "🚫 此機器人不接受私聊",
            parse_mode="HTML"
        )
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
    
    has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
    if not has_perms:
        return
    
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=create_mute_permissions(),
        )
        
        responses = [
            f"🎉 {user.mention_html()} 發現了隱藏驚喜！獲得2分鐘安靜時間～",
            f"🤫 {user.mention_html()} 觸發了神秘機關！請享受2分鐘靜音體驗",
            f"🔇 {user.mention_html()} 成功解鎖「禁言成就」！冷卻時間：2分鐘",
            f"⏳ {user.mention_html()} 的發言技能正在冷卻中...（2分鐘）",
            f"🎁 {user.mention_html()} 打開了潘多拉魔盒！獲得2分鐘沉默 buff",
            f"✨ {user.mention_html()} 發現了彩蛋！獲得2分鐘禁言體驗券",
            f"🎪 {user.mention_html()} 進入了馬戲團靜音區！表演時間：2分鐘",
            f"🔒 {user.mention_html()} 觸發了沉默陷阱！解鎖時間：2分鐘後",
            f"🎰 {user.mention_html()} 中了沉默大獎！領獎時間：2分鐘",
            f"🚫 {user.mention_html()} 進入了禁言休息室！休息時間：2分鐘"
        ]
        
        response = random.choice(responses)
        
        await update.message.reply_text(
            response + "\n\n⏰ 時間到自動恢復，請耐心等待～",
            parse_mode="HTML"
        )
        
        asyncio.create_task(delayed_unmute(context.bot, chat.id, user.id, 2))
        
    except Exception as e:
        logger.error(f"/banme 失敗: {e}")

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理 /list 指令（僅管理員可用）"""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != "private":
        return
    
    if user.id != OWNER_ID:
        await update.message.reply_text(
            "🚫 此機器人不接受私聊",
            parse_mode="HTML"
        )
        return
    
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
    
    load_known_groups()
    
    application = Application.builder().token(bot_token).build()
    
    application.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("help", help_command, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("list", list_groups, filters=filters.ChatType.PRIVATE))
    
    application.add_handler(CommandHandler("banme", banme, filters=filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP))
    
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
    
    print(f"\n{'='*60}")
    print(f"🕶️ 隱形管理機器人 {BOT_VERSION}")
    print(f"👤 管理員 ID: {OWNER_ID}")
    print(f"📊 已記錄群組: {len(known_groups)} 個")
    print(f"🔧 運行模式: 隱形模式")
    print(f"📝 日誌文件: bot.log")
    print(f"{'='*60}")
    print("\n✅ 機器人正在靜默運行中...")
    
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
EOF

# 6. 創建啟動腳本
echo "🚀 創建啟動腳本..."
cat > start_bot.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source bot_env/bin/activate
echo "🕶️ 啟動隱形管理機器人..."
echo "📝 查看日誌: tail -f bot.log"
echo "🛑 停止機器人: Ctrl+C"
python main.py
EOF

chmod +x start_bot.sh

# 7. 關鍵配置提示
echo -e "\n⚠️  必須完成以下配置："
echo "1. 向 @BotFather 配置指令列表："
echo "   - 發送 /setcommands"
echo "   - 選擇你的機器人"
echo "   - 粘貼以下內容："
echo "     start - 管理員查看狀態（僅私聊）"
echo "     banme - 發現驚喜（僅群組）"
echo "     list - 管理員查看群組（僅私聊）"
echo "2. 群組權限設置："
echo "   - 將機器人設為管理員"
echo "   - 開啟「限制成員」權限"
echo "   - 關閉「匿名管理員」模式"

# 8. 運行提示
echo -e "\n============== 安裝完成！=============="
echo "🕶️ 隱形管理機器人已配置完成"
echo "👤 管理員 ID: $OWNER_ID"
echo ""
echo "🚀 啟動方式："
echo "   手動啟動: ./start_bot.sh"
echo ""
echo "🔧 配置驗證："
echo "   檢查環境變量: echo \$BOT_TOKEN"
echo "   檢查 OWNER_ID: echo \$OWNER_ID"
echo ""
echo "🎯 功能特性："
echo "   - 靜默加入群組（無歡迎消息）"
echo "   - 只接受管理員私聊"
echo "   - /banme 變成驚喜功能"
echo "   - 自動檢測可疑用戶"
echo ""
echo "📝 查看日誌：tail -f bot.log"
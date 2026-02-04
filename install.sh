#!/bin/bash
echo "============== Telegram 隱形管理機器人 自動安裝 =============="

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 函數：顯示進度
show_progress() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

show_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

show_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# 檢查是否為 root 用戶
if [ "$EUID" -ne 0 ]; then 
    show_warning "建議使用 root 用戶運行此腳本"
    read -p "是否繼續？(y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 1. 安裝 Python 3.12
show_progress "檢查 Python 3.12..."
if ! command -v python3.12 &> /dev/null; then
    show_progress "安裝 Python 3.12..."
    apt-get update && apt-get install -y python3.12 python3.12-venv python3-pip
    if [ $? -eq 0 ]; then
        show_success "Python 3.12 安裝完成"
    else
        show_error "Python 3.12 安裝失敗"
        exit 1
    fi
else
    show_success "Python 3.12 已安裝"
fi

# 2. 獲取安裝參數
show_progress "獲取安裝參數..."

# 檢查是否有命令行參數
if [ $# -ge 2 ]; then
    BOT_TOKEN="$1"
    OWNER_ID="$2"
    show_progress "使用命令行參數: Token=${BOT_TOKEN:0:10}..., OwnerID=$OWNER_ID"
else
    # 交互式輸入
    echo -e "\n${BLUE}=== 請輸入配置信息 ===${NC}"
    
    while true; do
        read -p "請輸入 Telegram Bot Token: " BOT_TOKEN
        if [[ -n "$BOT_TOKEN" ]]; then
            break
        else
            show_error "Token 不能為空"
        fi
    done
    
    while true; do
        read -p "請輸入你的 Telegram ID (在 @userinfobot 查詢): " OWNER_ID
        if [[ "$OWNER_ID" =~ ^[0-9]+$ ]]; then
            break
        else
            show_error "OWNER_ID 必須是數字"
        fi
    done
fi

# 3. 創建安裝目錄
INSTALL_DIR="/opt/telegram-admin-bot"
show_progress "創建安裝目錄: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# 4. 創建虛擬環境
show_progress "創建 Python 虛擬環境..."
python3.12 -m venv bot_env
if [ $? -ne 0 ]; then
    show_error "虛擬環境創建失敗"
    exit 1
fi

source bot_env/bin/activate

# 5. 安裝依賴
show_progress "安裝依賴包..."
pip install --upgrade pip
pip install python-telegram-bot==20.7 -i https://pypi.tuna.tsinghua.edu.cn/simple
if [ $? -eq 0 ]; then
    show_success "依賴安裝完成"
else
    show_error "依賴安裝失敗"
    exit 1
fi

# 6. 創建主程式
show_progress "創建主程式..."
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
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_VERSION = "v4.1.0-auto-background"

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

# ================== 處理新成員加入（簡單歡迎語） ==================
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
            
            try:
                await context.bot.send_message(
                    chat.id,
                    f"👋 歡迎 {user.mention_html()} 加入 {chat.title}，請觀看置頂內容",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"發送歡迎語失敗: {e}")
            
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

🔧 運行模式: 自動後台
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
        "- 靜默加入群組，不發送機器人歡迎消息\n"
        "- 新成員收到簡單歡迎語\n"
        "- 自動檢測可疑新成員\n"
        "- 不接受非管理員私聊\n"
        "- 自動後台運行\n\n"
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
    print(f"🔧 運行模式: 自動後台")
    print(f"📝 日誌文件: bot.log")
    print(f"{'='*60}")
    print("\n✅ 機器人正在後台靜默運行...")
    
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

show_success "主程式創建完成"

# 7. 創建環境變量文件
show_progress "創建環境變量配置文件..."
cat > /etc/profile.d/telegram-bot.sh << EOF
export BOT_TOKEN="$BOT_TOKEN"
export OWNER_ID="$OWNER_ID"
EOF

chmod +x /etc/profile.d/telegram-bot.sh

# 立即生效
export BOT_TOKEN="$BOT_TOKEN"
export OWNER_ID="$OWNER_ID"

# 8. 創建 systemd 服務（自動後台運行）
show_progress "創建 systemd 服務..."
cat > /etc/systemd/system/telegram-bot.service << EOF
[Unit]
Description=Telegram 隱形管理機器人
After=network.target
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="BOT_TOKEN=$BOT_TOKEN"
Environment="OWNER_ID=$OWNER_ID"
ExecStart=$INSTALL_DIR/bot_env/bin/python $INSTALL_DIR/main.py
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/bot_service.log
StandardError=append:$INSTALL_DIR/bot_error.log

# 安全設置
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# 9. 創建管理腳本
show_progress "創建管理腳本..."
cat > /usr/local/bin/telegram-bot << 'EOF'
#!/bin/bash
case "\$1" in
    start)
        systemctl start telegram-bot
        echo "✅ 啟動機器人"
        ;;
    stop)
        systemctl stop telegram-bot
        echo "🛑 停止機器人"
        ;;
    restart)
        systemctl restart telegram-bot
        echo "🔄 重啟機器人"
        ;;
    status)
        systemctl status telegram-bot
        ;;
    logs)
        tail -f /opt/telegram-admin-bot/bot.log
        ;;
    logs-service)
        tail -f /opt/telegram-admin-bot/bot_service.log
        ;;
    update)
        cd /opt/telegram-admin-bot
        source bot_env/bin/activate
        pip install --upgrade python-telegram-bot
        systemctl restart telegram-bot
        echo "📦 更新完成並重啟"
        ;;
    config)
        echo "🔧 當前配置:"
        echo "   Token: \${BOT_TOKEN:0:10}..."
        echo "   Owner ID: \$OWNER_ID"
        echo "   安裝目錄: /opt/telegram-admin-bot"
        ;;
    help|*)
        echo "📖 Telegram 隱形管理機器人 管理命令"
        echo "用法: telegram-bot {start|stop|restart|status|logs|logs-service|update|config|help}"
        echo ""
        echo "命令說明:"
        echo "  start     - 啟動機器人"
        echo "  stop      - 停止機器人"
        echo "  restart   - 重啟機器人"
        echo "  status    - 查看狀態"
        echo "  logs      - 查看應用日誌"
        echo "  logs-service - 查看服務日誌"
        echo "  update    - 更新依賴"
        echo "  config    - 查看配置"
        echo "  help      - 顯示幫助"
        ;;
esac
EOF

chmod +x /usr/local/bin/telegram-bot

# 10. 啟動服務
show_progress "啟動 systemd 服務..."
systemctl daemon-reload
systemctl enable telegram-bot
systemctl start telegram-bot

# 檢查服務狀態
sleep 3
if systemctl is-active --quiet telegram-bot; then
    show_success "機器人服務啟動成功"
else
    show_error "服務啟動失敗，檢查日誌: journalctl -u telegram-bot -f"
    exit 1
fi

# 11. 創建配置檢查腳本
show_progress "創建配置檢查腳本..."
cat > /opt/telegram-admin-bot/check_config.sh << 'EOF'
#!/bin/bash
echo "🔧 配置檢查"
echo "=========="
echo "安裝目錄: /opt/telegram-admin-bot"
echo "Python 版本: $(python3.12 --version 2>/dev/null || echo '未安裝')"
echo "虛擬環境: $(ls -d /opt/telegram-admin-bot/bot_env 2>/dev/null && echo '存在' || echo '不存在')"
echo ""
echo "環境變量:"
echo "  BOT_TOKEN: ${BOT_TOKEN:0:10}..."
echo "  OWNER_ID: $OWNER_ID"
echo ""
echo "服務狀態:"
systemctl status telegram-bot --no-pager -l
echo ""
echo "日誌文件:"
ls -la /opt/telegram-admin-bot/*.log 2>/dev/null || echo "無日誌文件"
EOF

chmod +x /opt/telegram-admin-bot/check_config.sh

# 12. 安裝完成
echo -e "\n${GREEN}============== 安裝完成！ ==============${NC}"
echo ""
echo "📋 安裝摘要:"
echo "   安裝目錄: $INSTALL_DIR"
echo "   Bot Token: ${BOT_TOKEN:0:10}..."
echo "   管理員 ID: $OWNER_ID"
echo "   服務名稱: telegram-bot"
echo ""
echo "🎯 功能特性:"
echo "   ✅ 靜默加入群組（機器人不發歡迎）"
echo "   ✅ 新成員歡迎語: '歡迎 username 加入 groupname，請觀看置頂內容'"
echo "   ✅ 自動後台運行"
echo "   ✅ 不接受非管理員私聊"
echo "   ✅ /banme 驚喜功能"
echo "   ✅ 自動檢測可疑用戶"
echo ""
echo "🚀 管理命令:"
echo "   telegram-bot start      # 啟動"
echo "   telegram-bot stop       # 停止"
echo "   telegram-bot restart    # 重啟"
echo "   telegram-bot status     # 狀態"
echo "   telegram-bot logs       # 查看日誌"
echo "   telegram-bot config     # 查看配置"
echo ""
echo "📝 重要日誌文件:"
echo "   $INSTALL_DIR/bot.log          # 應用日誌"
echo "   $INSTALL_DIR/bot_service.log  # 服務日誌"
echo "   $INSTALL_DIR/bot_error.log    # 錯誤日誌"
echo ""
echo "🔧 配置驗證:"
echo "   /opt/telegram-admin-bot/check_config.sh"
echo ""
echo "⚙️  快速安裝（未來）:"
echo "   ./install.sh '你的Token' '你的TelegramID'"
echo ""
echo "📌 必須完成:"
echo "   1. 在 @BotFather 設置 /setcommands"
echo "   2. 將機器人設為群組管理員"
echo "   3. 開啟「限制成員」權限"
echo ""
echo "🎉 機器人已自動在後台運行！"

# 顯示服務狀態
echo -e "\n${BLUE}=== 當前服務狀態 ===${NC}"
systemctl status telegram-bot --no-pager | head -20
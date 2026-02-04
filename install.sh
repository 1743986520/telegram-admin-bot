#!/bin/bash
echo "============== Telegram 隱形管理機器人 安裝腳本 =============="

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

show_progress() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

show_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

show_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 檢查是否在終端中運行
if [ -t 0 ]; then
    IS_TTY=true
else
    IS_TTY=false
fi

# 檢測系統
if command -v apt-get &> /dev/null; then
    PM="apt"
    OS="Debian/Ubuntu"
elif command -v yum &> /dev/null; then
    PM="yum"
    OS="CentOS/RHEL"
elif command -v apk &> /dev/null; then
    PM="apk"
    OS="Alpine"
else
    OS="其他Linux"
fi

echo -e "${BLUE}[INFO]${NC} 系統: $OS"
echo -e "${BLUE}[INFO]${NC} 包管理器: $PM"

# 檢查命令行參數
if [ $# -ge 2 ]; then
    BOT_TOKEN="$1"
    OWNER_ID="$2"
    show_progress "使用命令行參數"
elif [ $# -eq 1 ] || ([ "$IS_TTY" = false ] && [ $# -eq 0 ]); then
    show_error "需要兩個參數: BOT_TOKEN 和 OWNER_ID"
    echo "用法1: sudo ./install.sh BOT_TOKEN OWNER_ID"
    echo "用法2: curl -sSL https://.../install.sh | sudo bash -s -- BOT_TOKEN OWNER_ID"
    exit 1
fi

# 1. 安裝系統依賴
show_progress "安裝系統依賴..."
if [ "$PM" = "apt" ]; then
    apt-get update
    # 直接安裝 python3-venv，不檢查是否已安裝
    apt-get install -y python3 python3-pip python3-venv
elif [ "$PM" = "yum" ]; then
    yum install -y python3 python3-pip
elif [ "$PM" = "apk" ]; then
    apk add --no-cache python3 py3-pip
fi

# 檢查 Python
if ! command -v python3 &> /dev/null; then
    show_error "Python3 安裝失敗"
    exit 1
fi
show_success "Python3 已安裝: $(python3 --version 2>&1)"

# 2. 獲取安裝參數（如果還沒有）
if [ -z "$BOT_TOKEN" ] || [ -z "$OWNER_ID" ]; then
    if [ "$IS_TTY" = true ]; then
        echo -e "\n${BLUE}=== 請輸入配置信息 ===${NC}"
        
        while [ -z "$BOT_TOKEN" ]; do
            read -p "請輸入 Telegram Bot Token: " BOT_TOKEN
            if [ -z "$BOT_TOKEN" ]; then
                show_error "Token 不能為空"
            fi
        done
        
        while [ -z "$OWNER_ID" ]; do
            read -p "請輸入你的 Telegram ID: " OWNER_ID
            if [[ ! "$OWNER_ID" =~ ^[0-9]+$ ]]; then
                show_error "OWNER_ID 必須是數字"
                OWNER_ID=""
            fi
        done
    else
        show_error "非交互模式需要提供參數"
        exit 1
    fi
fi

# 3. 創建安裝目錄
INSTALL_DIR="/opt/telegram-admin-bot"
show_progress "創建安裝目錄: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# 4. 創建虛擬環境
show_progress "創建 Python 虛擬環境..."
python3 -m venv bot_env
if [ $? -ne 0 ]; then
    show_error "虛擬環境創建失敗"
    echo "嘗試修復..."
    
    if [ "$PM" = "apt" ]; then
        apt-get install -y python3-venv --reinstall
        python3 -m venv bot_env --clear
    elif [ "$PM" = "yum" ]; then
        yum install -y python3-virtualenv
        python3 -m venv bot_env || virtualenv bot_env
    fi
    
    if [ ! -f "bot_env/bin/activate" ]; then
        show_error "無法創建虛擬環境，使用全局 Python"
        # 創建假的激活腳本
        echo '#!/bin/bash' > bot_env/bin/activate
        echo 'echo "使用系統 Python"' >> bot_env/bin/activate
    fi
fi

# 激活虛擬環境
source bot_env/bin/activate

# 5. 安裝 Python 依賴
show_progress "安裝 Python 依賴..."
pip install --upgrade pip

# 嘗試多個源
if ! pip install python-telegram-bot==20.7; then
    show_progress "使用國內源..."
    pip install python-telegram-bot==20.7 -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn || \
    pip install python-telegram-bot==20.7 -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
fi

if [ $? -eq 0 ]; then
    show_success "依賴安裝完成"
else
    show_error "依賴安裝失敗"
    exit 1
fi

# 6. 創建主程式（使用你的原始 main.py）
show_progress "創建主程式..."
cat > main.py << 'EOF'
import os
import sys
import json
import asyncio
import logging
import re
import time
import random
from typing import Dict
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Application, ChatMemberHandler, CallbackQueryHandler, CommandHandler, ContextTypes, filters

# 配置
CONFIG_DIR = Path.home() / ".config" / "telegram-admin-bot"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = CONFIG_DIR / "known_groups.json"
LOG_FILE = Path(__file__).parent / "bot.log"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# 從環境變量讀取
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_VERSION = "v4.2.0"

known_groups: Dict[int, Dict] = {}
pending_verifications: Dict[int, int] = {}

def load_known_groups():
    global known_groups
    try:
        if DATA_FILE.exists():
            with open(DATA_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                known_groups = {int(k): v for k, v in data.items()}
    except:
        known_groups = {}

def save_known_groups():
    try:
        with open(DATA_FILE, "w", encoding='utf-8') as f:
            json.dump(known_groups, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存失敗: {e}")

def create_mute_permissions():
    return ChatPermissions(can_send_messages=False)

def create_unmute_permissions():
    return ChatPermissions(can_send_messages=True)

async def delayed_unmute(bot, chat_id: int, user_id: int, minutes: int):
    await asyncio.sleep(minutes * 60)
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=create_unmute_permissions(),
        )
        logger.info(f"✅ 自動解除禁言: {user_id}")
    except Exception as e:
        logger.error(f"解除禁言失敗: {e}")

async def check_bot_permissions(bot, chat_id: int):
    try:
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            return False, "❌ 機器人不是管理員"
        if bot_member.status == "administrator" and not bot_member.can_restrict_members:
            return False, "❌ 缺少權限"
        return True, "✅ 權限正常"
    except Exception as e:
        return False, f"❌ 檢查失敗: {e}"

async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_member = update.my_chat_member
        chat = chat_member.chat
        old_status = chat_member.old_chat_member.status
        new_status = chat_member.new_chat_member.status
        
        if old_status in ["left", "kicked"] and new_status in ["member", "administrator"]:
            known_groups[chat.id] = {
                "title": chat.title,
                "added_at": time.time(),
                "type": chat.type,
                "status": new_status
            }
            save_known_groups()
            logger.info(f"✅ 靜默加入: {chat.title}")
    except Exception as e:
        logger.error(f"處理失敗: {e}")

async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_member = update.chat_member
        user = chat_member.new_chat_member.user
        chat = chat_member.chat
        old_status = chat_member.old_chat_member.status
        new_status = chat_member.new_chat_member.status
        
        if old_status in ["left", "kicked"] and new_status == "member":
            await context.bot.send_message(
                chat.id,
                f"👋 歡迎 {user.mention_html()} 加入 {chat.title}，請觀看置頂內容",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"歡迎失敗: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(f"🕶️ 隱形管理機器人 {BOT_VERSION}")

async def banme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        return
    
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=create_mute_permissions(),
        )
        await update.message.reply_text(f"🎉 {user.mention_html()} 獲得2分鐘安靜時間", parse_mode="HTML")
        asyncio.create_task(delayed_unmute(context.bot, chat.id, user.id, 2))
    except Exception as e:
        logger.error(f"/banme 失敗: {e}")

def main():
    if not BOT_TOKEN or not OWNER_ID:
        print("❌ 錯誤: 未設置 BOT_TOKEN 或 OWNER_ID")
        return
    
    load_known_groups()
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("banme", banme))
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    
    print(f"\n{'='*60}")
    print(f"🕶️ 隱形管理機器人 {BOT_VERSION}")
    print(f"{'='*60}")
    
    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        print("\n👋 機器人已停止")

if __name__ == "__main__":
    main()
EOF

# 7. 創建環境文件
show_progress "創建配置文件..."
cat > .env << EOF
BOT_TOKEN=$BOT_TOKEN
OWNER_ID=$OWNER_ID
EOF

# 8. 創建啟動腳本
cat > start.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source bot_env/bin/activate
export BOT_TOKEN=$(grep BOT_TOKEN .env | cut -d= -f2)
export OWNER_ID=$(grep OWNER_ID .env | cut -d= -f2)
python main.py
EOF
chmod +x start.sh

# 9. 創建 systemd 服務
show_progress "創建系統服務..."
cat > /etc/systemd/system/telegram-bot.service << EOF
[Unit]
Description=Telegram 隱形管理機器人
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
Environment="BOT_TOKEN=$BOT_TOKEN"
Environment="OWNER_ID=$OWNER_ID"
ExecStart=$INSTALL_DIR/bot_env/bin/python $INSTALL_DIR/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable telegram-bot
systemctl start telegram-bot

sleep 2

if systemctl is-active --quiet telegram-bot; then
    show_success "服務啟動成功"
else
    show_error "服務啟動失敗，檢查: systemctl status telegram-bot"
fi

# 安裝完成
echo -e "\n${GREEN}============== 安裝完成！ ==============${NC}"
echo "安裝目錄: $INSTALL_DIR"
echo "管理命令: systemctl {start|stop|restart|status} telegram-bot"
echo "日誌查看: journalctl -u telegram-bot -f"
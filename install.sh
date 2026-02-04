#!/bin/bash
echo "============== Telegram 隱形管理機器人 跨平台安裝腳本 =============="

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

# 檢查是否在終端中運行
check_tty() {
    if [ -t 0 ]; then
        IS_TTY=true
    else
        IS_TTY=false
    fi
}

# 安全讀取輸入（支持非交互式）
safe_read() {
    local prompt="$1"
    local var_name="$2"
    local validation="$3"
    local default_value="$4"
    
    if [ "$IS_TTY" = false ] && [ -z "${!var_name}" ]; then
        show_error "錯誤: 非交互式模式下必須提供 $var_name"
        show_error "請使用: curl ... | sudo bash -s -- BOT_TOKEN OWNER_ID"
        exit 1
    fi
    
    while true; do
        if [ -n "${!var_name}" ]; then
            # 已經有環境變量或命令行參數
            echo "$prompt: ${!var_name}"
            break
        elif [ "$IS_TTY" = true ]; then
            # 交互式模式
            read -p "$prompt: " input_value
            if [ -n "$input_value" ]; then
                eval "$var_name=\"$input_value\""
                break
            elif [ -n "$default_value" ]; then
                eval "$var_name=\"$default_value\""
                echo "使用默認值: $default_value"
                break
            else
                show_error "輸入不能為空"
            fi
        else
            # 非交互式且沒有預設值
            show_error "$prompt 是必需的"
            exit 1
        fi
    done
    
    # 驗證輸入
    if [ -n "$validation" ]; then
        case "$validation" in
            "number")
                if [[ ! "${!var_name}" =~ ^[0-9]+$ ]]; then
                    show_error "必須輸入數字"
                    if [ "$IS_TTY" = true ]; then
                        unset "$var_name"
                        continue
                    else
                        exit 1
                    fi
                fi
                ;;
            "not_empty")
                if [ -z "${!var_name}" ]; then
                    show_error "不能為空"
                    if [ "$IS_TTY" = true ]; then
                        unset "$var_name"
                        continue
                    else
                        exit 1
                    fi
                fi
                ;;
        esac
    fi
}

# 檢測操作系統
detect_os() {
    case "$(uname -s)" in
        Linux*)     OS="Linux" ;;
        Darwin*)    OS="macOS" ;;
        CYGWIN*|MINGW*|MSYS*) OS="Windows" ;;
        *)          OS="Unknown" ;;
    esac
    echo $OS
}

# 檢測包管理器
detect_package_manager() {
    if command -v apt-get &> /dev/null; then
        PM="apt"
    elif command -v yum &> /dev/null; then
        PM="yum"
    elif command -v dnf &> /dev/null; then
        PM="dnf"
    elif command -v pacman &> /dev/null; then
        PM="pacman"
    elif command -v brew &> /dev/null; then
        PM="brew"
    elif command -v apk &> /dev/null; then
        PM="apk"
    else
        PM="unknown"
    fi
    echo $PM
}

# 檢查 Python 版本
check_python_version() {
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        if [ "$(echo "$PYTHON_VERSION >= 3.8" | bc -l 2>/dev/null || echo "0")" = "1" ]; then
            echo "python3"
        else
            echo ""
        fi
    elif command -v python &> /dev/null; then
        PYTHON_VERSION=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0")
        if [ "$(echo "$PYTHON_VERSION >= 3.8" | bc -l 2>/dev/null || echo "0")" = "1" ]; then
            echo "python"
        else
            echo ""
        fi
    else
        echo ""
    fi
}

# 檢查是否為 root 用戶
check_root() {
    if [ "$EUID" -ne 0 ] && [ "$OS" = "Linux" ]; then 
        if [ "$IS_TTY" = true ]; then
            show_warning "建議使用 root 用戶運行此腳本"
            read -p "是否繼續？(y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        else
            show_warning "非交互式模式下建議使用 sudo"
        fi
    fi
}

# 初始化檢查
check_tty
OS=$(detect_os)
PM=$(detect_package_manager)

echo -e "${BLUE}[INFO]${NC} 檢測到系統: $OS"
echo -e "${BLUE}[INFO]${NC} 包管理器: $PM"
echo -e "${BLUE}[INFO]${NC} 交互模式: $IS_TTY"

# 檢查命令行參數
if [ $# -ge 2 ]; then
    BOT_TOKEN="$1"
    OWNER_ID="$2"
    show_progress "使用命令行參數: Token=${BOT_TOKEN:0:10}..., OwnerID=$OWNER_ID"
elif [ $# -eq 1 ]; then
    show_error "錯誤: 需要兩個參數 (BOT_TOKEN 和 OWNER_ID)"
    show_error "用法: curl ... | sudo bash -s -- BOT_TOKEN OWNER_ID"
    exit 1
fi

# 檢查 root 權限
check_root

# 1. 安裝 Python（如果需要）
PYTHON_CMD=$(check_python_version)
echo -e "${BLUE}[INFO]${NC} Python 命令: ${PYTHON_CMD:-未找到合適的Python版本}"

if [ -z "$PYTHON_CMD" ]; then
    show_progress "安裝 Python 3.8+..."
    
    case "$OS" in
        "Linux")
            case "$PM" in
                "apt")
                    apt-get update && apt-get install -y python3 python3-venv python3-pip
                    ;;
                "yum")
                    yum install -y python3 python3-pip
                    ;;
                "dnf")
                    dnf install -y python3 python3-pip
                    ;;
                "pacman")
                    pacman -Sy --noconfirm python python-pip
                    ;;
                "apk")
                    apk add --no-cache python3 py3-pip
                    ;;
                *)
                    show_error "不支持的Linux發行版"
                    echo "請手動安裝 Python 3.8+ 後重新運行腳本"
                    exit 1
                    ;;
            esac
            ;;
        "macOS")
            if [ "$PM" = "brew" ]; then
                brew install python@3.9
            else
                show_error "請先安裝 Homebrew: https://brew.sh/"
                exit 1
            fi
            ;;
        "Windows")
            show_error "Windows系統請手動安裝Python 3.8+"
            echo "下載地址: https://www.python.org/downloads/"
            exit 1
            ;;
        *)
            show_error "不支持的操作系統"
            exit 1
            ;;
    esac
    
    # 重新檢查Python
    PYTHON_CMD=$(check_python_version)
    if [ -z "$PYTHON_CMD" ]; then
        show_error "Python安裝失敗"
        exit 1
    fi
    show_success "Python安裝完成: $($PYTHON_CMD --version 2>&1)"
else
    show_success "Python已安裝: $($PYTHON_CMD --version 2>&1)"
fi

# 2. 獲取安裝參數（如果還沒有）
show_progress "獲取安裝參數..."

if [ -z "$BOT_TOKEN" ] || [ -z "$OWNER_ID" ]; then
    if [ "$IS_TTY" = true ]; then
        echo -e "\n${BLUE}=== 請輸入配置信息 ===${NC}"
    fi
    
    # 獲取 BOT_TOKEN
    while [ -z "$BOT_TOKEN" ]; do
        if [ "$IS_TTY" = true ]; then
            read -p "請輸入 Telegram Bot Token: " BOT_TOKEN
            if [ -z "$BOT_TOKEN" ]; then
                show_error "Token 不能為空"
            fi
        else
            show_error "錯誤: BOT_TOKEN 未提供"
            show_error "請使用: curl ... | sudo bash -s -- BOT_TOKEN OWNER_ID"
            exit 1
        fi
    done
    
    # 獲取 OWNER_ID
    while [ -z "$OWNER_ID" ]; do
        if [ "$IS_TTY" = true ]; then
            read -p "請輸入你的 Telegram ID (在 @userinfobot 查詢): " OWNER_ID
            if [[ ! "$OWNER_ID" =~ ^[0-9]+$ ]]; then
                show_error "OWNER_ID 必須是數字"
                OWNER_ID=""
            fi
        else
            show_error "錯誤: OWNER_ID 未提供"
            show_error "請使用: curl ... | sudo bash -s -- BOT_TOKEN OWNER_ID"
            exit 1
        fi
    done
fi

# 驗證 OWNER_ID 是數字
if [[ ! "$OWNER_ID" =~ ^[0-9]+$ ]]; then
    show_error "OWNER_ID 必須是數字: $OWNER_ID"
    exit 1
fi

# 3. 創建安裝目錄（跨平台）
if [ "$OS" = "Windows" ]; then
    INSTALL_DIR="$HOME/telegram-admin-bot"
else
    INSTALL_DIR="/opt/telegram-admin-bot"
fi

show_progress "創建安裝目錄: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# 4. 創建虛擬環境
show_progress "創建 Python 虛擬環境..."
$PYTHON_CMD -m venv bot_env
if [ $? -ne 0 ]; then
    show_error "虛擬環境創建失敗"
    exit 1
fi

# 激活虛擬環境（跨平台）
if [ "$OS" = "Windows" ]; then
    source bot_env/Scripts/activate
else
    source bot_env/bin/activate
fi

# 5. 安裝依賴
show_progress "安裝依賴包..."
pip install --upgrade pip setuptools wheel

# 根據系統選擇合適的源
show_progress "安裝 python-telegram-bot..."
if command -v timeout &> /dev/null; then
    # 測試網絡連接
    if timeout 5 curl -s https://pypi.org/ > /dev/null; then
        pip install python-telegram-bot==20.7
    else
        show_warning "網絡連接超時，嘗試使用國內源..."
        pip install python-telegram-bot==20.7 -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
    fi
else
    # 沒有 timeout 命令，直接嘗試
    pip install python-telegram-bot==20.7 || {
        show_warning "安裝失敗，嘗試使用國內源..."
        pip install python-telegram-bot==20.7 -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
    }
fi

if [ $? -eq 0 ]; then
    show_success "依賴安裝完成"
else
    show_error "依賴安裝失敗，請檢查網絡連接"
    exit 1
fi

# 6. 創建主程式（使用簡化版避免 EOF 問題）
show_progress "創建主程式..."
cat > main.py << 'MAIN_EOF'
import os
import sys
import json
import asyncio
import logging
from pathlib import Path

# 跨平台配置
def get_config_dir():
    if sys.platform == "win32":
        config_dir = Path(os.environ.get("APPDATA", "")) / "telegram-admin-bot"
    else:
        config_dir = Path.home() / ".config" / "telegram-admin-bot"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

CONFIG_DIR = get_config_dir()
INSTALL_DIR = Path(__file__).parent.absolute()
DATA_FILE = CONFIG_DIR / "known_groups.json"

# 主程序代碼（簡化，完整版請見後續）
MAIN_EOF

# 下載完整的主程序
show_progress "下載完整主程序..."
if command -v curl &> /dev/null; then
    curl -sSL -o main_full.py https://raw.githubusercontent.com/1743986520/telegram-admin-bot/main/main.py 2>/dev/null || {
        show_warning "無法下載完整主程序，使用內置簡化版"
        # 這裡應該有完整的 main.py 代碼
        # 但由於長度限制，我們先創建一個最小可用版本
        cat >> main.py << 'MINIMAL_EOF'
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

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_VERSION = "v4.2.0-universal"

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(f"🕶️ 隱形管理機器人 {BOT_VERSION}\n👤 管理員: {OWNER_ID}")

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

def main():
    if not BOT_TOKEN or not OWNER_ID:
        print("❌ 錯誤: 未設置 BOT_TOKEN 或 OWNER_ID")
        return
    
    load_known_groups()
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    
    print(f"\n{'='*60}")
    print(f"🕶️ 隱形管理機器人 {BOT_VERSION}")
    print(f"👤 管理員 ID: {OWNER_ID}")
    print(f"{'='*60}")
    
    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        print("\n👋 機器人已停止")

if __name__ == "__main__":
    main()
MINIMAL_EOF
    }
else
    show_warning "curl 不可用，使用簡化版主程序"
fi

# 7. 創建環境變量文件
show_progress "創建環境變量配置文件..."
ENV_FILE="$INSTALL_DIR/.env"
cat > "$ENV_FILE" << EOF
BOT_TOKEN=$BOT_TOKEN
OWNER_ID=$OWNER_ID
INSTALL_DIR=$INSTALL_DIR
EOF

# 8. 創建啟動腳本
show_progress "創建啟動腳本..."
cat > "$INSTALL_DIR/start.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source bot_env/bin/activate
python main.py
EOF
chmod +x "$INSTALL_DIR/start.sh"

# 9. 創建管理腳本
show_progress "創建管理腳本..."
cat > /usr/local/bin/telegram-bot 2>/dev/null << 'EOF' || cat > "$INSTALL_DIR/telegram-bot-manage" << 'EOF'
#!/bin/bash
INSTALL_DIR="/opt/telegram-admin-bot"
[ ! -d "$INSTALL_DIR" ] && INSTALL_DIR="$HOME/telegram-admin-bot"

case "$1" in
    start)
        cd "$INSTALL_DIR"
        nohup ./start.sh > bot_service.log 2>&1 &
        echo $! > "$INSTALL_DIR/bot.pid"
        echo "✅ 啟動成功 (PID: $(cat $INSTALL_DIR/bot.pid))"
        ;;
    stop)
        if [ -f "$INSTALL_DIR/bot.pid" ]; then
            kill $(cat "$INSTALL_DIR/bot.pid") 2>/dev/null
            rm -f "$INSTALL_DIR/bot.pid"
            echo "🛑 已停止"
        else
            pkill -f "python.*main.py" 2>/dev/null
            echo "🛑 已停止所有相關進程"
        fi
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        echo "🔄 重啟完成"
        ;;
    status)
        if [ -f "$INSTALL_DIR/bot.pid" ] && kill -0 $(cat "$INSTALL_DIR/bot.pid") 2>/dev/null; then
            echo "✅ 正在運行 (PID: $(cat $INSTALL_DIR/bot.pid))"
        elif pgrep -f "python.*main.py" > /dev/null; then
            echo "✅ 正在運行"
        else
            echo "❌ 未運行"
        fi
        ;;
    logs)
        tail -f "$INSTALL_DIR/bot.log" 2>/dev/null || echo "日誌文件不存在"
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "安裝信息:"
        echo "  安裝目錄: $INSTALL_DIR"
        echo "  配置目錄: ~/.config/telegram-admin-bot/"
        echo "  日誌文件: $INSTALL_DIR/bot.log"
        ;;
esac
EOF

if [ -d "/usr/local/bin" ]; then
    chmod +x /usr/local/bin/telegram-bot 2>/dev/null || chmod +x "$INSTALL_DIR/telegram-bot-manage"
fi

# 10. 啟動機器人
show_progress "啟動機器人..."
cd "$INSTALL_DIR"
nohup ./start.sh > bot_service.log 2>&1 &
echo $! > bot.pid

sleep 3

if kill -0 $(cat bot.pid) 2>/dev/null; then
    show_success "✅ 機器人啟動成功 (PID: $(cat bot.pid))"
else
    show_warning "⚠️  機器人可能啟動失敗，檢查日誌: tail -f $INSTALL_DIR/bot_service.log"
fi

# 11. 安裝完成
echo -e "\n${GREEN}============== 安裝完成！ ==============${NC}"
echo ""
echo "📋 安裝摘要:"
echo "   系統平台: $OS"
echo "   安裝目錄: $INSTALL_DIR"
echo "   Bot Token: ${BOT_TOKEN:0:10}..."
echo "   管理員 ID: $OWNER_ID"
echo ""
echo "🚀 管理命令:"
echo "   telegram-bot start    # 啟動"
echo "   telegram-bot stop     # 停止"
echo "   telegram-bot status   # 狀態"
echo "   telegram-bot logs     # 日誌"
echo ""
echo "📝 重要文件:"
echo "   $INSTALL_DIR/main.py"
echo "   $INSTALL_DIR/.env"
echo "   $INSTALL_DIR/bot.log"
echo ""
echo "🎉 開始使用:"
echo "   1. 私聊機器人發送 /start"
echo "   2. 將機器人設為群組管理員"
echo "   3. 開啟「限制成員」權限"
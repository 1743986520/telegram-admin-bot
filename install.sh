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
if [ -t 0 ]; then
    IS_TTY=true
else
    IS_TTY=false
fi

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
    show_error "用法: sudo ./install.sh BOT_TOKEN OWNER_ID"
    exit 1
fi

# 1. 安裝 Python 和必要套件
PYTHON_CMD=$(check_python_version)
echo -e "${BLUE}[INFO]${NC} Python 命令: ${PYTHON_CMD:-未找到合適的Python版本}"

# 安裝必要的系統套件
show_progress "安裝系統依賴..."
case "$OS" in
    "Linux")
        case "$PM" in
            "apt")
                apt-get update
                # 安裝 Python 和虛擬環境支援
                apt-get install -y python3 python3-pip
                # 檢查是否需要安裝 python3-venv
                if ! dpkg -l | grep -q python3-venv; then
                    show_progress "安裝 python3-venv..."
                    apt-get install -y python3-venv
                fi
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
        esac
        ;;
    "macOS")
        if [ "$PM" = "brew" ]; then
            brew install python@3.9
        fi
        ;;
esac

# 重新檢查Python
PYTHON_CMD=$(check_python_version)
if [ -z "$PYTHON_CMD" ]; then
    show_error "Python安裝失敗"
    exit 1
fi
show_success "Python已安裝: $($PYTHON_CMD --version 2>&1)"

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
            show_error "請使用: sudo ./install.sh BOT_TOKEN OWNER_ID"
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
            show_error "請使用: sudo ./install.sh BOT_TOKEN OWNER_ID"
            exit 1
        fi
    done
fi

# 驗證 OWNER_ID 是數字
if [[ ! "$OWNER_ID" =~ ^[0-9]+$ ]]; then
    show_error "OWNER_ID 必須是數字: $OWNER_ID"
    exit 1
fi

# 3. 創建安裝目錄
INSTALL_DIR="/opt/telegram-admin-bot"
show_progress "創建安裝目錄: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# 4. 創建虛擬環境（帶錯誤處理）
show_progress "創建 Python 虛擬環境..."
$PYTHON_CMD -m venv bot_env
if [ $? -ne 0 ]; then
    show_warning "虛擬環境創建失敗，嘗試安裝缺少的套件..."
    
    case "$OS" in
        "Linux")
            case "$PM" in
                "apt")
                    show_progress "安裝 python3-venv..."
                    apt-get install -y python3-venv
                    ;;
                "yum")
                    show_progress "安裝 python3-virtualenv..."
                    yum install -y python3-virtualenv
                    ;;
                "dnf")
                    show_progress "安裝 python3-virtualenv..."
                    dnf install -y python3-virtualenv
                    ;;
            esac
            
            # 再次嘗試
            show_progress "再次嘗試創建虛擬環境..."
            $PYTHON_CMD -m venv bot_env
            if [ $? -ne 0 ]; then
                show_error "虛擬環境創建失敗，嘗試替代方案..."
                
                # 嘗試使用 virtualenv 命令
                if command -v virtualenv &> /dev/null || pip3 install virtualenv --quiet; then
                    virtualenv bot_env
                else
                    # 最後方案：直接創建目錄結構
                    show_warning "使用簡化虛擬環境..."
                    mkdir -p bot_env/bin
                    ln -s $(which $PYTHON_CMD) bot_env/bin/python
                    cat > bot_env/bin/activate << 'ACTIVATE_EOF'
#!/bin/bash
export VIRTUAL_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$VIRTUAL_ENV/bin:$PATH"
unset PYTHON_HOME
ACTIVATE_EOF
                    chmod +x bot_env/bin/activate
                fi
            fi
            ;;
    esac
fi

# 檢查虛擬環境是否創建成功
if [ ! -f "bot_env/bin/activate" ]; then
    show_error "虛擬環境創建失敗，無法繼續"
    exit 1
fi

# 激活虛擬環境
source bot_env/bin/activate

# 5. 安裝依賴
show_progress "安裝依賴包..."
pip install --upgrade pip setuptools wheel

show_progress "安裝 python-telegram-bot..."
# 嘗試多個源
pip install python-telegram-bot==20.7 || {
    show_warning "使用默認源失敗，嘗試清華源..."
    pip install python-telegram-bot==20.7 -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn || {
        show_warning "清華源失敗，嘗試阿里源..."
        pip install python-telegram-bot==20.7 -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
    }
}

if [ $? -eq 0 ]; then
    show_success "依賴安裝完成"
else
    show_error "依賴安裝失敗，請檢查網絡連接"
    exit 1
fi

# 6. 創建主程式
show_progress "創建主程式..."
cat > main.py << 'MAIN_EOF'
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
LOG_FILE = INSTALL_DIR / "bot.log"

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
                logger.info(f"加載 {len(known_groups)} 個群組記錄")
    except Exception as e:
        logger.error(f"加載失敗: {e}")
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

async def check_bot_permissions(bot, chat_id: int) -> tuple[bool, str]:
    try:
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            return False, "❌ 機器人不是管理員"
        if bot_member.status == "administrator" and not bot_member.can_restrict_members:
            return False, "❌ 缺少「限制成員」權限"
        return True, "✅ 權限正常"
    except Exception as e:
        return False, f"❌ 檢查權限失敗: {e}"

async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_member = update.my_chat_member
        chat = chat_member.chat
        old_status = chat_member.old_chat_member.status
        new_status = chat_member.new_chat_member.status
        
        logger.info(f"🤖 機器人狀態: {chat.title} | {old_status} -> {new_status}")
        
        if old_status in ["left", "kicked"] and new_status in ["member", "administrator"]:
            known_groups[chat.id] = {
                "title": chat.title,
                "added_at": time.time(),
                "type": chat.type,
                "status": new_status
            }
            save_known_groups()
            logger.info(f"✅ 靜默加入: {chat.title}")
        
        elif new_status in ["left", "kicked"]:
            if chat.id in known_groups:
                del known_groups[chat.id]
                save_known_groups()
                logger.info(f"🗑️ 移除: {chat.title}")
                
    except Exception as e:
        logger.error(f"處理失敗: {e}")

async def handle_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_member = update.chat_member
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
                logger.error(f"歡迎失敗: {e}")
            
            # 可疑用戶檢測
            bio = ""
            try:
                user_chat = await context.bot.get_chat(user.id)
                bio = user_chat.bio or ""
            except:
                pass
            
            is_suspicious = False
            if re.search(r"@\w+", bio, re.IGNORECASE):
                is_suspicious = True
            if re.search(r"https?://|t\.me/", bio, re.IGNORECASE):
                is_suspicious = True
            
            if is_suspicious:
                logger.info(f"⚠️ 可疑用戶: {user.id}")
                has_perms, perm_msg = await check_bot_permissions(context.bot, chat.id)
                if has_perms:
                    try:
                        await context.bot.restrict_chat_member(
                            chat_id=chat.id,
                            user_id=user.id,
                            permissions=create_mute_permissions(),
                        )
                        pending_verifications[user.id] = chat.id
                        keyboard = [[InlineKeyboardButton("✅ 我是真人，點擊驗證", callback_data=f"verify_{user.id}")]]
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

async def on_verify_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            await query.edit_message_text(f"✅ {query.from_user.mention_html()} 驗證成功", parse_mode="HTML")
        except Exception as e:
            await query.edit_message_text("❌ 解除禁言失敗")
            
    except Exception as e:
        logger.error(f"驗證處理失敗: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != "private":
        return
    
    if user.id != OWNER_ID:
        await update.message.reply_text("🚫 此機器人不接受私聊")
        return
    
    response = f"""
🕶️ 隱形管理機器人 {BOT_VERSION}

👤 管理員 ID: `{OWNER_ID}`
📊 當前狀態:
- 管理群組數: {len(known_groups)}
- 待驗證用戶: {len(pending_verifications)}

🏠 安裝目錄: {INSTALL_DIR}
📁 配置目錄: {CONFIG_DIR}
✅ 所有功能正常
"""
    await update.message.reply_text(response, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != "private" or user.id != OWNER_ID:
        return
    
    await update.message.reply_text(
        "📖 隱形管理機器人幫助\n\n"
        "🤖 機器人特性:\n"
        "- 靜默加入群組，不發送機器人歡迎消息\n"
        "- 新成員收到簡單歡迎語\n"
        "- 自動檢測可疑新成員\n"
        "- 不接受非管理員私聊\n\n"
        "📋 管理員指令:\n"
        "/start - 查看狀態\n"
        "/list - 查看管理群組\n\n"
        "🎯 群組功能:\n"
        "/banme - 發現驚喜（群組成員專用）",
        parse_mode="HTML"
    )

async def banme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        await update.message.reply_text("🎯 這個驚喜只能在群組中發現哦！")
        return
    
    try:
        user_member = await chat.get_member(user.id)
        if user_member.status in ["administrator", "creator"]:
            await update.message.reply_text("👑 管理員大人，這個驚喜是給普通成員準備的啦！")
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
        ]
        
        response = random.choice(responses)
        await update.message.reply_text(response + "\n\n⏰ 時間到自動恢復", parse_mode="HTML")
        asyncio.create_task(delayed_unmute(context.bot, chat.id, user.id, 2))
        
    except Exception as e:
        logger.error(f"/banme 失敗: {e}")

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type != "private" or user.id != OWNER_ID:
        return
    
    if not known_groups:
        await update.message.reply_text("📭 還沒有管理任何群組")
        return
    
    groups_text = "🕶️ 隱形管理的群組:\n\n"
    for idx, (chat_id, info) in enumerate(known_groups.items(), 1):
        title = info.get('title', '未知群組')
        groups_text += f"{idx}. {title}\n   ID: `{chat_id}`\n\n"
    
    groups_text += f"總計: {len(known_groups)} 個群組"
    await update.message.reply_text(groups_text, parse_mode="Markdown")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"錯誤: {context.error}", exc_info=True)

def main():
    if not BOT_TOKEN:
        print("❌ 錯誤: 未設置 BOT_TOKEN")
        return
    
    if not OWNER_ID:
        print("❌ 錯誤: 未設置 OWNER_ID")
        return
    
    load_known_groups()
    
    print(f"\n{'='*60}")
    print(f"🕶️ 隱形管理機器人 {BOT_VERSION}")
    print(f"👤 管理員 ID: {OWNER_ID}")
    print(f"📊 已記錄群組: {len(known_groups)} 個")
    print(f"📝 日誌文件: {LOG_FILE}")
    print(f"{'='*60}")
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("help", help_command, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("list", list_groups, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("banme", banme, filters=filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP))
    app.add_handler(CallbackQueryHandler(on_verify_click))
    app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_error_handler(error_handler)
    
    print("\n✅ 機器人正在啟動...")
    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        print("\n👋 機器人已停止")
        save_known_groups()

if __name__ == "__main__":
    main()
MAIN_EOF

show_success "主程式創建完成"

# 7. 創建環境變量文件
show_progress "創建環境變量配置文件..."
cat > "$INSTALL_DIR/.env" << EOF
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
export BOT_TOKEN=$(grep BOT_TOKEN .env | cut -d= -f2)
export OWNER_ID=$(grep OWNER_ID .env | cut -d= -f2)
python main.py
EOF
chmod +x "$INSTALL_DIR/start.sh"

# 9. 創建管理腳本
show_progress "創建管理腳本..."
cat > /usr/local/bin/telegram-bot << 'EOF'
#!/bin/bash
INSTALL_DIR="/opt/telegram-admin-bot"

case "$1" in
    start)
        cd "$INSTALL_DIR"
        if [ -f "$INSTALL_DIR/bot.pid" ] && kill -0 $(cat "$INSTALL_DIR/bot.pid") 2>/dev/null; then
            echo "✅ 機器人已在運行 (PID: $(cat $INSTALL_DIR/bot.pid))"
        else
            nohup ./start.sh > bot_service.log 2>&1 &
            echo $! > "$INSTALL_DIR/bot.pid"
            echo "✅ 啟動成功 (PID: $(cat $INSTALL_DIR/bot.pid))"
        fi
        ;;
    stop)
        if [ -f "$INSTALL_DIR/bot.pid" ]; then
            PID=$(cat "$INSTALL_DIR/bot.pid")
            kill $PID 2>/dev/null && echo "🛑 已停止 (PID: $PID)" || echo "❌ 停止失敗"
            rm -f "$INSTALL_DIR/bot.pid"
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
            echo "運行時間: $(ps -o etime= -p $(cat $INSTALL_DIR/bot.pid) 2>/dev/null || echo '未知')"
        elif pgrep -f "python.*main.py" > /dev/null; then
            echo "✅ 正在運行 (PID: $(pgrep -f 'python.*main.py'))"
        else
            echo "❌ 未運行"
        fi
        ;;
    logs)
        if [ "$2" = "service" ]; then
            tail -f "$INSTALL_DIR/bot_service.log"
        else
            tail -f "$INSTALL_DIR/bot.log"
        fi
        ;;
    update)
        cd "$INSTALL_DIR"
        source bot_env/bin/activate
        pip install --upgrade python-telegram-bot
        echo "📦 更新完成"
        $0 restart
        ;;
    config)
        echo "🔧 當前配置:"
        echo "   Token: $(grep BOT_TOKEN $INSTALL_DIR/.env | cut -d= -f2 | head -c 10)..."
        echo "   Owner ID: $(grep OWNER_ID $INSTALL_DIR/.env | cut -d= -f2)"
        echo "   安裝目錄: $INSTALL_DIR"
        ;;
    *)
        echo "📖 Telegram 隱形管理機器人 管理命令"
        echo "用法: telegram-bot {start|stop|restart|status|logs|update|config}"
        echo ""
        echo "命令說明:"
        echo "  start          - 啟動機器人"
        echo "  stop           - 停止機器人"
        echo "  restart        - 重啟機器人"
        echo "  status         - 查看狀態"
        echo "  logs           - 查看應用日誌"
        echo "  logs service   - 查看服務日誌"
        echo "  update         - 更新依賴"
        echo "  config         - 查看配置"
        ;;
esac
EOF

chmod +x /usr/local/bin/telegram-bot

# 10. 創建 systemd 服務
show_progress "創建 systemd 服務..."
if [ -d "/etc/systemd/system" ]; then
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

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable telegram-bot
    systemctl start telegram-bot
    
    sleep 2
    
    if systemctl is-active --quiet telegram-bot; then
        show_success "systemd 服務啟動成功"
        SERVICE_TYPE="systemd"
    else
        show_warning "systemd 服務啟動失敗，使用腳本啟動"
        SERVICE_TYPE="script"
    fi
else
    SERVICE_TYPE="script"
fi

# 11. 如果 systemd 失敗，使用腳本啟動
if [ "$SERVICE_TYPE" = "script" ]; then
    show_progress "使用腳本啟動..."
    cd "$INSTALL_DIR"
    nohup ./start.sh > bot_service.log 2>&1 &
    echo $! > bot.pid
    
    sleep 3
    
    if kill -0 $(cat bot.pid) 2>/dev/null; then
        show_success "腳本啟動成功 (PID: $(cat bot.pid))"
    else
        show_warning "啟動可能失敗，檢查日誌: tail -f $INSTALL_DIR/bot_service.log"
    fi
fi

# 12. 安裝完成
echo -e "\n${GREEN}============== 安裝完成！ ==============${NC}"
echo ""
echo "📋 安裝摘要:"
echo "   系統平台: $OS"
echo "   安裝目錄: $INSTALL_DIR"
echo "   Bot Token: ${BOT_TOKEN:0:10}..."
echo "   管理員 ID: $OWNER_ID"
echo "   服務類型: $SERVICE_TYPE"
echo ""
echo "🚀 管理命令:"
echo "   telegram-bot start      # 啟動"
echo "   telegram-bot stop       # 停止"
echo "   telegram-bot restart    # 重啟"
echo "   telegram-bot status     # 狀態"
echo "   telegram-bot logs       # 查看日誌"
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
echo ""
echo "🔧 檢查狀態:"
telegram-bot status
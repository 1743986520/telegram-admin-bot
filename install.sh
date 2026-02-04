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
if [ "$EUID" -ne 0 ] && [ "$(detect_os)" = "Linux" ]; then 
    show_warning "建議使用 root 用戶運行此腳本"
    read -p "是否繼續？(y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

OS=$(detect_os)
PM=$(detect_package_manager)
PYTHON_CMD=$(check_python_version)

echo -e "${BLUE}[INFO]${NC} 檢測到系統: $OS"
echo -e "${BLUE}[INFO]${NC} 包管理器: $PM"
echo -e "${BLUE}[INFO]${NC} Python 命令: ${PYTHON_CMD:-未找到合適的Python版本}"

# 1. 安裝 Python（如果需要）
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
if [ "$OS" = "Linux" ] && [ "$PM" = "apt" ]; then
    # 中國大陸使用清華源
    pip install python-telegram-bot==20.7 -i https://pypi.tuna.tsinghua.edu.cn/simple
else
    # 其他地區使用默認源
    pip install python-telegram-bot==20.7
fi

if [ $? -eq 0 ]; then
    show_success "依賴安裝完成"
else
    show_error "依賴安裝失敗，嘗試使用備用源..."
    pip install python-telegram-bot==20.7
    if [ $? -ne 0 ]; then
        show_error "依賴安裝失敗，請檢查網絡連接"
        exit 1
    fi
fi

# 6. 創建主程式
show_progress "創建主程式..."
cat > main.py << 'EOF'
import os
import re
import asyncio
import time
import random
import json
import sys
from typing import Dict
import logging
from pathlib import Path
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

# ================== 跨平台配置 ==================
def get_config_dir():
    """獲取配置目錄（跨平台）"""
    if sys.platform == "win32":
        config_dir = Path(os.environ.get("APPDATA", "")) / "telegram-admin-bot"
    else:
        config_dir = Path.home() / ".config" / "telegram-admin-bot"
    
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

def get_install_dir():
    """獲取安裝目錄"""
    install_dir = Path(__file__).parent.absolute()
    return install_dir

# ================== 基本設定 ==================
CONFIG_DIR = get_config_dir()
INSTALL_DIR = get_install_dir()
DATA_FILE = CONFIG_DIR / "known_groups.json"
LOG_FILE = INSTALL_DIR / "bot.log"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ],
)
logger = logging.getLogger(__name__)

# === 從環境變量讀取配置 ===
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_VERSION = "v4.2.0-universal"

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
        with open(DATA_FILE, "w", encoding='utf-8') as f:
            json.dump(known_groups, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存群組數據失敗: {e}")

def load_known_groups():
    """從文件加載群組數據"""
    global known_groups
    try:
        if DATA_FILE.exists():
            with open(DATA_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                known_groups = {int(k): v for k, v in data.items()}
                logger.info(f"加載 {len(known_groups)} 個群組記錄")
        else:
            known_groups = {}
            logger.info("無歷史群組記錄")
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

🏠 安裝目錄: {INSTALL_DIR}
📁 配置目錄: {CONFIG_DIR}
🔧 運行平台: {sys.platform}
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
        f"📖 隱形管理機器人幫助 {BOT_VERSION}\n\n"
        "🤖 機器人特性:\n"
        "- 靜默加入群組，不發送機器人歡迎消息\n"
        "- 新成員收到簡單歡迎語\n"
        "- 自動檢測可疑新成員\n"
        "- 不接受非管理員私聊\n"
        "- 跨平台支持\n\n"
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
        print("或者在啟動時設置環境變量")
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
    
    # 顯示系統信息
    print(f"\n{'='*60}")
    print(f"🕶️ 隱形管理機器人 {BOT_VERSION}")
    print(f"🏠 安裝目錄: {INSTALL_DIR}")
    print(f"📁 配置目錄: {CONFIG_DIR}")
    print(f"🖥️  運行平台: {sys.platform}")
    print(f"🐍 Python 版本: {sys.version.split()[0]}")
    print(f"{'='*60}")
    
    load_known_groups()
    
    print(f"👤 管理員 ID: {OWNER_ID}")
    print(f"📊 已記錄群組: {len(known_groups)} 個")
    print(f"📝 日誌文件: {LOG_FILE}")
    print(f"{'='*60}")
    print("\n✅ 機器人正在啟動...")
    
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
        save_known_groups()
    except Exception as e:
        print(f"❌ 啟動失敗: {e}")
        save_known_groups()

if __name__ == "__main__":
    main()
EOF

show_success "主程式創建完成"

# 7. 創建環境變量文件（跨平台）
show_progress "創建環境變量配置文件..."
if [ "$OS" = "Windows" ]; then
    ENV_FILE="$INSTALL_DIR/.env"
else
    ENV_FILE="$INSTALL_DIR/.env"
    
    # 也創建系統級環境變量（Linux/macOS）
    cat > /etc/profile.d/telegram-bot.sh 2>/dev/null << EOF || true
export BOT_TOKEN="$BOT_TOKEN"
export OWNER_ID="$OWNER_ID"
EOF
    chmod +x /etc/profile.d/telegram-bot.sh 2>/dev/null || true
fi

cat > "$ENV_FILE" << EOF
BOT_TOKEN=$BOT_TOKEN
OWNER_ID=$OWNER_ID
INSTALL_DIR=$INSTALL_DIR
EOF

show_success "環境變量文件創建: $ENV_FILE"

# 立即生效
export BOT_TOKEN="$BOT_TOKEN"
export OWNER_ID="$OWNER_ID"

# 8. 創建服務管理（跨平台）
show_progress "創建服務管理..."

if [ "$OS" = "Linux" ]; then
    # Linux: systemd 服務
    cat > /etc/systemd/system/telegram-bot.service << EOF
[Unit]
Description=Telegram 隱形管理機器人
After=network.target
Wants=network.target

[Service]
Type=simple
User=$(whoami)
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
    systemctl enable telegram-bot 2>/dev/null || true
    
elif [ "$OS" = "macOS" ]; then
    # macOS: launchd 服務
    PLIST_FILE="$HOME/Library/LaunchAgents/telegram.bot.plist"
    cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>telegram.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/bot_env/bin/python</string>
        <string>$INSTALL_DIR/main.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>BOT_TOKEN</key>
        <string>$BOT_TOKEN</string>
        <key>OWNER_ID</key>
        <string>$OWNER_ID</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$INSTALL_DIR/bot_service.log</string>
    <key>StandardErrorPath</key>
    <string>$INSTALL_DIR/bot_error.log</string>
</dict>
</plist>
EOF
    launchctl load "$PLIST_FILE" 2>/dev/null || true
    
elif [ "$OS" = "Windows" ]; then
    # Windows: 創建啟動腳本
    cat > "$INSTALL_DIR/start.bat" << EOF
@echo off
chcp 65001 > nul
echo Telegram 隱形管理機器人
echo ==========================
set BOT_TOKEN=$BOT_TOKEN
set OWNER_ID=$OWNER_ID
call %~dp0bot_env\Scripts\activate.bat
python main.py
pause
EOF

    cat > "$INSTALL_DIR/start-service.vbs" << 'VBS'
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Run "cmd /c start.bat", 0, False
VBS
fi

# 9. 創建管理腳本（跨平台）
show_progress "創建管理腳本..."
if [ "$OS" = "Windows" ]; then
    # Windows 批處理
    cat > "$INSTALL_DIR/manage.bat" << EOF
@echo off
chcp 65001 > nul
echo Telegram 隱形管理機器人 管理工具
echo =================================

if "%1"=="" goto help

if "%1"=="start" (
    echo 啟動機器人...
    start "" "%~dp0start-service.vbs"
    echo ✅ 機器人已啟動（後台運行）
    goto end
)

if "%1"=="stop" (
    echo 🛑 停止機器人...
    echo Windows 系統請手動結束 Python 進程
    echo 或在任務管理器中結束 python.exe
    goto end
)

if "%1"=="restart" (
    echo 🔄 重啟機器人...
    echo 請先停止再啟動
    goto end
)

if "%1"=="status" (
    echo 🔧 當前狀態:
    echo   安裝目錄: %~dp0
    echo   Token: ${BOT_TOKEN:0:10}...
    echo   Owner ID: %OWNER_ID%
    echo.
    tasklist | findstr python.exe && echo ✅ 機器人正在運行 || echo ❌ 機器人未運行
    goto end
)

if "%1"=="logs" (
    if exist "%~dp0bot.log" (
        type "%~dp0bot.log"
    ) else (
        echo 無日誌文件
    )
    goto end
)

if "%1"=="update" (
    echo 📦 更新依賴...
    call %~dp0bot_env\Scripts\activate.bat
    pip install --upgrade python-telegram-bot
    echo ✅ 更新完成
    goto end
)

if "%1"=="config" (
    echo 🔧 當前配置:
    echo   安裝目錄: %~dp0
    echo   Token: ${BOT_TOKEN:0:10}...
    echo   Owner ID: %OWNER_ID%
    goto end
)

:help
echo 📖 Telegram 隱形管理機器人 管理命令
echo.
echo 用法: manage.bat {start^|stop^|restart^|status^|logs^|update^|config^|help}
echo.
echo 命令說明:
echo   start     - 啟動機器人（後台）
echo   stop      - 停止機器人
echo   restart   - 重啟機器人
echo   status    - 查看狀態
echo   logs      - 查看日誌
echo   update    - 更新依賴
echo   config    - 查看配置
echo   help      - 顯示幫助

:end
pause
EOF

else
    # Linux/macOS shell 腳本
    cat > /usr/local/bin/telegram-bot 2>/dev/null << 'EOF' || cat > "$INSTALL_DIR/telegram-bot.sh" << 'EOF'
#!/bin/bash
case "$1" in
    start)
        if command -v systemctl &> /dev/null && systemctl list-units --full -all | grep -q telegram-bot; then
            systemctl start telegram-bot
            echo "✅ 啟動機器人 (systemd)"
        elif [ "$(uname)" = "Darwin" ] && [ -f "$HOME/Library/LaunchAgents/telegram.bot.plist" ]; then
            launchctl load "$HOME/Library/LaunchAgents/telegram.bot.plist"
            echo "✅ 啟動機器人 (launchd)"
        else
            cd /opt/telegram-admin-bot 2>/dev/null || cd "$HOME/telegram-admin-bot" 2>/dev/null || cd "$(dirname "$0")/.."
            nohup ./bot_env/bin/python main.py > bot_service.log 2> bot_error.log &
            echo $! > bot.pid
            echo "✅ 啟動機器人 (nohup)"
        fi
        ;;
    stop)
        if command -v systemctl &> /dev/null && systemctl list-units --full -all | grep -q telegram-bot; then
            systemctl stop telegram-bot
            echo "🛑 停止機器人 (systemd)"
        elif [ "$(uname)" = "Darwin" ] && [ -f "$HOME/Library/LaunchAgents/telegram.bot.plist" ]; then
            launchctl unload "$HOME/Library/LaunchAgents/telegram.bot.plist"
            echo "🛑 停止機器人 (launchd)"
        else
            cd /opt/telegram-admin-bot 2>/dev/null || cd "$HOME/telegram-admin-bot" 2>/dev/null || cd "$(dirname "$0")/.."
            if [ -f bot.pid ]; then
                kill $(cat bot.pid) 2>/dev/null && rm bot.pid
                echo "🛑 停止機器人 (pid)"
            else
                pkill -f "python.*main.py" 2>/dev/null
                echo "🛑 停止機器人 (pkill)"
            fi
        fi
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        echo "🔄 重啟機器人"
        ;;
    status)
        if command -v systemctl &> /dev/null && systemctl list-units --full -all | grep -q telegram-bot; then
            systemctl status telegram-bot --no-pager -l
        elif [ "$(uname)" = "Darwin" ] && [ -f "$HOME/Library/LaunchAgents/telegram.bot.plist" ]; then
            launchctl list | grep telegram.bot
        else
            cd /opt/telegram-admin-bot 2>/dev/null || cd "$HOME/telegram-admin-bot" 2>/dev/null || cd "$(dirname "$0")/.."
            if pgrep -f "python.*main.py" > /dev/null; then
                echo "✅ 機器人正在運行"
                ps aux | grep "python.*main.py" | grep -v grep
            else
                echo "❌ 機器人未運行"
            fi
        fi
        ;;
    logs)
        cd /opt/telegram-admin-bot 2>/dev/null || cd "$HOME/telegram-admin-bot" 2>/dev/null || cd "$(dirname "$0")/.."
        if [ -f bot.log ]; then
            tail -f bot.log
        else
            echo "無日誌文件"
        fi
        ;;
    logs-service)
        cd /opt/telegram-admin-bot 2>/dev/null || cd "$HOME/telegram-admin-bot" 2>/dev/null || cd "$(dirname "$0")/.."
        if [ -f bot_service.log ]; then
            tail -f bot_service.log
        else
            echo "無服務日誌文件"
        fi
        ;;
    update)
        cd /opt/telegram-admin-bot 2>/dev/null || cd "$HOME/telegram-admin-bot" 2>/dev/null || cd "$(dirname "$0")/.."
        source bot_env/bin/activate 2>/dev/null || . bot_env/bin/activate
        pip install --upgrade python-telegram-bot
        echo "📦 更新完成"
        $0 restart
        ;;
    config)
        echo "🔧 當前配置:"
        echo "   Token: ${BOT_TOKEN:0:10}..."
        echo "   Owner ID: $OWNER_ID"
        if [ -d "/opt/telegram-admin-bot" ]; then
            echo "   安裝目錄: /opt/telegram-admin-bot"
        elif [ -d "$HOME/telegram-admin-bot" ]; then
            echo "   安裝目錄: $HOME/telegram-admin-bot"
        else
            echo "   安裝目錄: $(pwd)"
        fi
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

    if [ -d "/usr/local/bin" ]; then
        chmod +x /usr/local/bin/telegram-bot 2>/dev/null || true
    else
        chmod +x "$INSTALL_DIR/telegram-bot.sh"
    fi
fi

# 10. 創建配置檢查腳本
show_progress "創建配置檢查腳本..."
cat > "$INSTALL_DIR/check_config.sh" << EOF
#!/bin/bash
echo "🔧 配置檢查"
echo "=========="
echo "系統: $(uname -s)"
echo "安裝目錄: $INSTALL_DIR"
echo "Python 版本: $($PYTHON_CMD --version 2>&1)"
echo "虛擬環境: $(ls -d $INSTALL_DIR/bot_env 2>/dev/null && echo '存在' || echo '不存在')"
echo ""
echo "環境變量:"
echo "  BOT_TOKEN: ${BOT_TOKEN:0:10}..."
echo "  OWNER_ID: $OWNER_ID"
echo ""
echo "服務狀態:"
if [ "$OS" = "Linux" ] && command -v systemctl &> /dev/null; then
    systemctl status telegram-bot --no-pager -l 2>/dev/null || echo "systemd 服務未安裝"
elif [ "$OS" = "macOS" ]; then
    launchctl list | grep -i telegram 2>/dev/null || echo "launchd 服務未安裝"
else
    pgrep -f "python.*main.py" > /dev/null && echo "✅ 機器人正在運行" || echo "❌ 機器人未運行"
fi
echo ""
echo "日誌文件:"
ls -la $INSTALL_DIR/*.log 2>/dev/null || echo "無日誌文件"
EOF

chmod +x "$INSTALL_DIR/check_config.sh"

# 11. 啟動服務
show_progress "啟動機器人..."
if [ "$OS" = "Linux" ] && command -v systemctl &> /dev/null; then
    systemctl start telegram-bot 2>/dev/null || true
elif [ "$OS" = "macOS" ]; then
    launchctl load "$HOME/Library/LaunchAgents/telegram.bot.plist" 2>/dev/null || true
else
    # 手動啟動
    cd "$INSTALL_DIR"
    if [ "$OS" = "Windows" ]; then
        start "" "start-service.vbs"
    else
        nohup ./bot_env/bin/python main.py > bot_service.log 2> bot_error.log &
        echo $! > bot.pid
    fi
fi

# 檢查服務狀態
sleep 3
show_progress "檢查運行狀態..."
if [ "$OS" = "Windows" ]; then
    tasklist | findstr python.exe > /dev/null && RUNNING=true || RUNNING=false
else
    pgrep -f "python.*main.py" > /dev/null && RUNNING=true || RUNNING=false
fi

if $RUNNING; then
    show_success "機器人啟動成功"
else
    show_warning "機器人可能未啟動，請檢查日誌"
fi

# 12. 安裝完成
echo -e "\n${GREEN}============== 安裝完成！ ==============${NC}"
echo ""
echo "📋 安裝摘要:"
echo "   系統平台: $OS"
echo "   安裝目錄: $INSTALL_DIR"
echo "   Bot Token: ${BOT_TOKEN:0:10}..."
echo "   管理員 ID: $OWNER_ID"
echo "   Python: $($PYTHON_CMD --version 2>&1)"
echo ""
echo "🎯 功能特性:"
echo "   ✅ 跨平台支持 (Linux/macOS/Windows)"
echo "   ✅ Python 3.8+ 自動檢測"
echo "   ✅ 靜默加入群組（機器人不發歡迎）"
echo "   ✅ 新成員歡迎語"
echo "   ✅ 自動後台運行"
echo "   ✅ 不接受非管理員私聊"
echo "   ✅ /banme 驚喜功能"
echo "   ✅ 自動檢測可疑用戶"
echo ""
echo "🚀 管理命令:"
if [ "$OS" = "Windows" ]; then
    echo "   $INSTALL_DIR/manage.bat start      # 啟動"
    echo "   $INSTALL_DIR/manage.bat stop       # 停止"
    echo "   $INSTALL_DIR/manage.bat status     # 狀態"
    echo "   或直接運行 start.bat"
else
    if [ -f "/usr/local/bin/telegram-bot" ]; then
        echo "   telegram-bot start      # 啟動"
        echo "   telegram-bot stop       # 停止"
        echo "   telegram-bot restart    # 重啟"
        echo "   telegram-bot status     # 狀態"
    else
        echo "   $INSTALL_DIR/telegram-bot.sh start      # 啟動"
        echo "   $INSTALL_DIR/telegram-bot.sh stop       # 停止"
        echo "   $INSTALL_DIR/telegram-bot.sh status     # 狀態"
    fi
fi
echo ""
echo "📝 重要文件:"
echo "   $INSTALL_DIR/main.py            # 主程式"
echo "   $INSTALL_DIR/.env               # 環境變量"
echo "   $INSTALL_DIR/bot.log            # 應用日誌"
echo "   $INSTALL_DIR/bot_service.log    # 服務日誌"
echo "   $INSTALL_DIR/check_config.sh    # 配置檢查"
echo ""
echo "📌 必須完成:"
echo "   1. 在 @BotFather 設置 /setcommands"
echo "   2. 將機器人設為群組管理員"
echo "   3. 開啟「限制成員」權限"
echo ""
echo "🎉 機器人已安裝完成！"
echo ""
echo "💡 快速測試:"
echo "   1. 私聊機器人發送 /start"
echo "   2. 將機器人加入群組"
echo "   3. 邀請新成員測試歡迎語"

if [ "$OS" = "Windows" ]; then
    echo ""
    echo "⚠️  Windows 用戶注意:"
    echo "   1. 請確保已安裝 Python 3.8+"
    echo "   2. 可能需要管理員權限運行腳本"
    echo "   3. 防火牆可能阻止連接"
fi
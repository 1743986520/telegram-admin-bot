#!/bin/bash
echo "============== Telegram Admin Bot 一鍵安裝 =============="

# 1. 檢查 Python 環境
if ! command -v python3.12 &> /dev/null; then
    echo "❌ 未檢測到 Python 3.12+，開始安裝..."
    sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip
fi

# 2. 創建虛擬環境
echo "🐍 創建虛擬環境..."
python3.12 -m venv bot_env
source bot_env/bin/activate || {
    echo "❌ 虛擬環境激活失敗"
    exit 1
}

# 3. 安裝依賴
echo "📦 安裝依賴包..."
pip install --upgrade pip
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4. 設置 Bot Token（從 @BotFather 獲取）
read -p "請輸入你的 Telegram Bot Token：" BOT_TOKEN
echo "export BOT_TOKEN=$BOT_TOKEN" >> ~/.bashrc
source ~/.bashrc
echo "✅ 環境變量設置完成！"

# 5. 配置管理員 ID（修改 main.py 中的 OWNER_ID）
echo "⚠️  請記得修改 main.py 中的 OWNER_ID 為你的 Telegram ID（用於 /list 指令授權）"

echo "============== 安裝完成！=============="
echo "運行命令：source bot_env/bin/activate && python main.py"

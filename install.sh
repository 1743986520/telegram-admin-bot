#!/bin/bash
echo "============== Telegram Admin Bot 修復版安裝 =============="

# 1. 檢查並安裝 Python 3.12
if ! command -v python3.12 &> /dev/null; then
    echo "❌ 未檢測到 Python 3.12+，開始安裝..."
    sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip
fi

# 2. 創建並激活虛擬環境
echo "🐍 創建虛擬環境..."
python3.12 -m venv bot_env
source bot_env/bin/activate || {
    echo "❌ 虛擬環境激活失敗"
    exit 1
}

# 3. 安裝依賴（鎖定版本）
echo "📦 安裝依賴包..."
pip install --upgrade pip
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4. 設置 Bot Token（永久生效）
read -p "請輸入你的 Telegram Bot Token：" BOT_TOKEN
echo "export BOT_TOKEN=$BOT_TOKEN" >> ~/.bashrc
echo "export BOT_TOKEN=$BOT_TOKEN" >> bot_env/bin/activate  # 虛擬環境中也生效
source ~/.bashrc
echo "✅ BOT_TOKEN 設置完成！"

# 5. 提示管理員 ID 配置
echo -e "\n⚠️  重要配置："
echo "1. 打開 main.py，將 OWNER_ID = 7807347685 替換為你的 Telegram ID（通過 @userinfobot 查詢）"
echo "2. 將機器人加入群組，並授予「管理員」權限（必須開啟：限制成員、發送消息、編輯消息）"

# 6. 測試運行提示
echo -e "\n============== 安裝完成！=============="
echo "📝 運行步驟："
echo "1. 激活虛擬環境：source bot_env/bin/activate"
echo "2. 啟動機器人：python main.py"
echo "3. 後臺運行：nohup python main.py > bot.log 2>&1 &"
echo "4. 查看日誌：tail -f bot.log"

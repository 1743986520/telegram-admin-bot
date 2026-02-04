#!/bin/bash
echo "============== Telegram Admin Bot 修復版安裝 =============="

# 1. 安裝 Python 3.12
if ! command -v python3.12 &> /dev/null; then
    echo "❌ 未檢測到 Python 3.12+，開始安裝..."
    sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip
fi

# 2. 創建虛擬環境
echo "🐍 創建虛擬環境..."
python3.12 -m venv bot_env
source bot_env/bin/activate || { echo "❌ 虛擬環境激活失敗"; exit 1; }

# 3. 安裝依賴
echo "📦 安裝依賴包..."
pip install --upgrade pip
pip install python-telegram-bot==22.0 -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4. 設置 Token
read -p "請輸入你的 Telegram Bot Token：" BOT_TOKEN
echo "export BOT_TOKEN=$BOT_TOKEN" >> ~/.bashrc
echo "export BOT_TOKEN=$BOT_TOKEN" >> bot_env/bin/activate
source ~/.bashrc
echo "✅ BOT_TOKEN 設置完成！"

# 5. 下載修復版代碼
echo "📥 下載修復版代碼..."
curl -s https://raw.githubusercontent.com/your-repo/main.py -o main.py

# 6. 配置提示
echo -e "\n⚠️  重要配置步驟："
echo "1. 修改 OWNER_ID："
echo "   - 編輯 main.py，將 OWNER_ID = 7807347685 替換為你的 Telegram ID"
echo "2. 設置 BotFather 指令："
echo "   - 向 @BotFather 發送 /setcommands"
echo "   - 選擇你的機器人"
echo "   - 粘貼以下內容："
echo "     start - 查看機器人狀態"
echo "     banme - 群組內自願禁言2分鐘"
echo "     list - 私聊查詢管理群組"
echo "3. 群組權限："
echo "   - 將機器人設為管理員"
echo "   - 開啟「限制成員」權限"
echo "   - 關閉「匿名管理員」"

# 7. 啟動測試
echo -e "\n============== 安裝完成！=============="
echo "啟動步驟："
echo "1. source bot_env/bin/activate"
echo "2. python main.py"
echo "3. 查看日誌：tail -f bot.log"
echo "4. 將機器人加入群組測試"
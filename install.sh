#!/bin/bash
echo "============== Telegram 靜默管理機器人安裝 =============="

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
pip install python-telegram-bot==20.7 -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4. 設置 Token 和 管理員 ID
read -p "請輸入你的 Telegram Bot Token：" BOT_TOKEN
read -p "請輸入你的 Telegram 管理員 ID (從 @userinfobot 獲取)：" OWNER_ID

# 保存到環境變量
echo "export BOT_TOKEN=$BOT_TOKEN" >> ~/.bashrc
echo "export OWNER_ID=$OWNER_ID" >> ~/.bashrc
echo "export BOT_TOKEN=$BOT_TOKEN" >> bot_env/bin/activate
echo "export OWNER_ID=$OWNER_ID" >> bot_env/bin/activate

# 立即生效
export BOT_TOKEN=$BOT_TOKEN
export OWNER_ID=$OWNER_ID

echo "✅ Token 和 管理員ID 設置完成！"

# 5. 下載主程序
echo "📥 下載主程序..."
cat > main.py << 'EOF'
[在這裡貼上上面的完整main.py代碼]
EOF

echo "✅ 主程序下載完成！"

# 6. 配置提示（靜默模式）
echo -e "\n⚠️  配置提示（靜默模式）:"
echo "1. 向 @BotFather 設置指令列表:"
echo "   /setcommands → 選擇機器人 → 粘貼:"
echo "   start - 查看狀態（僅管理員）"
echo "   banme - 群組小驚喜 🎁"
echo "   list - 查看群組（僅管理員）"
echo ""
echo "2. 群組權限設置:"
echo "   - 將機器人設為管理員"
echo "   - 開啟「限制成員」權限"
echo "   - 關閉「匿名管理員」"
echo ""
echo "3. 靜默模式特點:"
echo "   ✅ 進群不自我介紹"
echo "   ✅ 不接受非管理員私聊"
echo "   ✅ Banme改為小驚喜"
echo "   ✅ 正常用戶不發歡迎消息"

# 7. 運行提示
echo -e "\n============== 安裝完成！=============="
echo "📱 功能特點:"
echo "• 靜默加入群組，不發自我介紹"
echo "• 僅管理員可私聊機器人"
echo "• /banme 改為小驚喜模式"
echo "• 自動檢測可疑用戶"
echo ""
echo "🚀 啟動步驟:"
echo "1. 激活環境: source bot_env/bin/activate"
echo "2. 啟動機器人: python main.py"
echo "3. 查看日誌: tail -f bot.log"
echo ""
echo "🔧 管理員指令:"
echo "• 私聊 /start - 查看狀態"
echo "• 私聊 /list - 查看群組"
echo "• 群組 /banme - 小驚喜"
echo ""
echo "🛡️ 自動功能:"
echo "• 可疑用戶自動禁言+驗證"
echo "• 驗證成功自動解除"
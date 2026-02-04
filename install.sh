#!/bin/bash
echo "============== Telegram 隱形管理機器人安裝 =============="

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

# 5. 下載主程式
echo "📥 下載主程式..."
cat > main.py << 'EOF'
[將上面的完整 main.py 代碼貼在這裡]
EOF

# 6. 關鍵配置提示
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
echo "3. 機器人特性："
echo "   - 靜默加入群組，不發歡迎消息"
echo "   - 不接受非管理員私聊"
echo "   - /banme 變成驚喜功能"

# 7. 創建啟動腳本
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

# 8. 創建 systemd 服務（可選）
read -p "是否創建 systemd 服務？(y/N): " CREATE_SERVICE
if [[ "$CREATE_SERVICE" =~ ^[Yy]$ ]]; then
    echo "📦 創建 systemd 服務..."
    sudo cat > /etc/systemd/system/telegram-bot.service << EOF
[Unit]
Description=Telegram 隱形管理機器人
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
Environment="BOT_TOKEN=$BOT_TOKEN"
Environment="OWNER_ID=$OWNER_ID"
ExecStart=$(pwd)/bot_env/bin/python $(pwd)/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable telegram-bot.service
    echo "✅ systemd 服務已創建！"
    echo "📋 管理命令："
    echo "   sudo systemctl start telegram-bot    # 啟動"
    echo "   sudo systemctl stop telegram-bot     # 停止"
    echo "   sudo systemctl status telegram-bot   # 狀態"
    echo "   sudo journalctl -u telegram-bot -f   # 查看日誌"
fi

# 9. 運行提示
echo -e "\n============== 安裝完成！=============="
echo "🕶️ 隱形管理機器人已配置完成"
echo "👤 管理員 ID: $OWNER_ID"
echo ""
echo "🚀 啟動方式："
echo "1. 手動啟動: ./start_bot.sh"
if [[ "$CREATE_SERVICE" =~ ^[Yy]$ ]]; then
    echo "2. 服務啟動: sudo systemctl start telegram-bot"
fi
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
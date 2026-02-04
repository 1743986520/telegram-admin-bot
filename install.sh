#!/bin/bash
echo "============== Telegram 隱形管理機器人安裝 =============="

# 1. 安裝 Python 3.12
if ! command -v python3.12 &> /dev/null; then
    echo "❌ 未檢測到 Python 3.12+，開始安裝..."
    apt-get update && apt-get install -y python3.12 python3.12-venv python3-pip
fi

# 2. 安裝 screen（用於後台運行）
if ! command -v screen &> /dev/null; then
    echo "📦 安裝 screen 用於後台運行..."
    apt-get install -y screen
fi

# 3. 創建虛擬環境
echo "🐍 創建虛擬環境..."
python3.12 -m venv bot_env
source bot_env/bin/activate || { echo "❌ 虛擬環境激活失敗"; exit 1; }

# 4. 安裝依賴
echo "📦 安裝依賴包..."
pip install --upgrade pip
pip install python-telegram-bot==20.7 -i https://pypi.tuna.tsinghua.edu.cn/simple

# 5. 設置 Token 和 Owner ID
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

# 6. 創建主程式
echo "📝 創建主程式..."
cat > main.py << 'EOF'
[將上面的 main.py 完整代碼貼在這裡]
EOF

# 7. 創建後台運行管理腳本
echo "🚀 創建後台運行管理腳本..."

# 啟動腳本（前台）
cat > start_bot.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source bot_env/bin/activate
echo "🕶️ 啟動隱形管理機器人..."
echo "📝 查看日誌: tail -f bot.log"
echo "🛑 停止機器人: Ctrl+C"
python main.py
EOF

# 後台啟動腳本
cat > start_background.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"

# 停止已存在的進程
./stop_bot.sh >/dev/null 2>&1
sleep 2

# 檢查是否已在運行
if screen -list | grep -q "telegram-bot"; then
    echo "❌ 機器人已在 screen 會話中運行"
    echo "📋 查看會話: screen -ls"
    echo "🔗 連接會話: screen -r telegram-bot"
    exit 1
fi

# 在 screen 會話中後台啟動
echo "🚀 在 screen 會話中啟動機器人..."
screen -dmS telegram-bot bash -c 'cd /root/telegram-admin-bot && source bot_env/bin/activate && python main.py'

sleep 3

# 檢查是否啟動成功
if screen -list | grep -q "telegram-bot"; then
    echo "✅ 機器人啟動成功！"
    echo "📊 會話名稱: telegram-bot"
    echo "📋 查看會話列表: screen -ls"
    echo "🔗 連接會話: screen -r telegram-bot"
    echo "📝 查看日誌: tail -f bot.log"
    echo ""
    echo "💡 管理命令:"
    echo "   查看狀態: ./status_bot.sh"
    echo "   停止機器人: ./stop_bot.sh"
    echo "   重新啟動: ./restart_bot.sh"
else
    echo "❌ 機器人啟動失敗！"
    echo "🔍 檢查日誌: tail -n 20 bot.log"
fi
EOF

# 停止腳本
cat > stop_bot.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
echo "🛑 停止隱形管理機器人..."

# 停止 screen 會話
if screen -list | grep -q "telegram-bot"; then
    echo "📊 找到 screen 會話: telegram-bot"
    screen -S telegram-bot -X quit
    sleep 2
fi

# 檢查是否還有其他進程
if pgrep -f "python main.py" > /dev/null; then
    echo "⚠️  還有殘留進程，強制停止..."
    pkill -9 -f "python main.py"
fi

# 確認停止
if screen -list | grep -q "telegram-bot"; then
    echo "❌ 停止 screen 會話失敗"
    exit 1
elif pgrep -f "python main.py" > /dev/null; then
    echo "❌ 停止進程失敗"
    exit 1
else
    echo "✅ 機器人已停止"
fi
EOF

# 狀態檢查腳本
cat > status_bot.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
echo "📊 機器人狀態檢查..."

# 檢查 screen 會話
if screen -list | grep -q "telegram-bot"; then
    echo "✅ 機器人正在 screen 會話中運行"
    echo "📋 會話信息:"
    screen -ls | grep telegram-bot
    
    # 檢查日誌文件
    if [ -f "bot.log" ]; then
        echo -e "\n📝 最近日誌 (最後10行):"
        tail -n 10 bot.log
    else
        echo -e "\n⚠️  日誌文件不存在"
    fi
    
    # 檢查進程
    if pgrep -f "python main.py" > /dev/null; then
        echo -e "\n⚡ 運行進程:"
        ps aux | grep "python main.py" | grep -v grep
    fi
else
    echo "❌ 機器人未在 screen 會話中運行"
    
    # 檢查是否有其他進程
    if pgrep -f "python main.py" > /dev/null; then
        echo "⚠️  發現未在 screen 中的機器人進程"
        ps aux | grep "python main.py" | grep -v grep
    else
        echo "💤 機器人完全停止狀態"
        
        # 檢查日誌
        if [ -f "bot.log" ]; then
            echo -e "\n🔍 上次運行日誌 (最後5行):"
            tail -n 5 bot.log
        fi
    fi
fi

# 檢查群組記錄
if [ -f "known_groups.json" ]; then
    group_count=$(python3 -c "import json; data=json.load(open('known_groups.json')); print(len(data))" 2>/dev/null || echo "0")
    echo -e "\n📊 已記錄群組數: $group_count"
else
    echo -e "\n📊 已記錄群組數: 0"
fi
EOF

# 重啟腳本
cat > restart_bot.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
echo "🔄 重新啟動機器人..."
./stop_bot.sh
sleep 2
./start_background.sh
EOF

# 設置執行權限
chmod +x start_bot.sh start_background.sh stop_bot.sh status_bot.sh restart_bot.sh

# 8. 創建自動啟動腳本（可選）
echo "🤔 是否設置開機自動啟動？"
read -p "輸入 y 設置開機啟動，其他跳過: " SET_AUTO_START

if [[ "$SET_AUTO_START" == "y" || "$SET_AUTO_START" == "Y" ]]; then
    echo "⚙️  創建開機啟動腳本..."
    
    # 創建 systemd 服務文件
    if [ -d "/etc/systemd/system" ]; then
        cat > /etc/systemd/system/telegram-bot.service << EOF
[Unit]
Description=Telegram 隱形管理機器人
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$(pwd)
Environment="BOT_TOKEN=$BOT_TOKEN"
Environment="OWNER_ID=$OWNER_ID"
ExecStart=$(pwd)/bot_env/bin/python $(pwd)/main.py
Restart=always
RestartSec=10
StandardOutput=append:$(pwd)/bot_service.log
StandardError=append:$(pwd)/bot_error.log

[Install]
WantedBy=multi-user.target
EOF
        
        systemctl daemon-reload
        systemctl enable telegram-bot.service
        
        echo "✅ systemd 服務已創建並啟用"
        echo "📋 systemd 命令:"
        echo "   systemctl start telegram-bot    # 啟動"
        echo "   systemctl stop telegram-bot     # 停止"
        echo "   systemctl status telegram-bot   # 狀態"
        echo "   journalctl -u telegram-bot -f   # 查看日誌"
    else
        # 如果沒有 systemd，創建 rc.local 啟動
        echo "⚠️  沒有 systemd，創建 rc.local 啟動"
        
        # 檢查 rc.local 是否存在
        if [ -f "/etc/rc.local" ]; then
            # 在 rc.local 中添加啟動命令
            START_CMD="cd $(pwd) && ./start_background.sh"
            if ! grep -q "$START_CMD" /etc/rc.local; then
                sed -i "/^exit 0/i $START_CMD &" /etc/rc.local
                echo "✅ 已添加到 rc.local"
            fi
        else
            echo "❌ 找不到 rc.local，跳過開機啟動設置"
        fi
    fi
fi

# 9. 關鍵配置提示
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

# 10. 運行提示
echo -e "\n============== 安裝完成！=============="
echo "🕶️ 隱形管理機器人已配置完成"
echo "👤 管理員 ID: $OWNER_ID"
echo ""
echo "🚀 啟動方式："
echo "   前台啟動: ./start_bot.sh"
echo "   後台啟動: ./start_background.sh   ← 推薦！"
echo ""
echo "🔧 管理命令："
echo "   查看狀態: ./status_bot.sh"
echo "   停止機器人: ./stop_bot.sh"
echo "   重新啟動: ./restart_bot.sh"
echo "   連接會話: screen -r telegram-bot"
echo "   分離會話: Ctrl+A, D"
echo ""
echo "🎯 功能特性："
echo "   - 機器人靜默加入群組（不發歡迎消息）"
echo "   - 新成員加入發送: 歡迎xxx加入，請觀看置頂內容"
echo "   - 只接受管理員私聊"
echo "   - /banme 變成驚喜功能"
echo "   - 自動檢測可疑用戶"
echo ""
echo "📝 查看日誌："
echo "   機器人日誌: tail -f bot.log"
echo "   後台輸出: tail -f ~/telegram-admin-bot/bot_output.log"
echo ""
echo "💡 小貼士："
echo "   1. 使用 ./start_background.sh 啟動後可以關閉終端"
echo "   2. 使用 screen -r telegram-bot 重新連接查看"
echo "   3. 使用 Ctrl+A, D 分離會話回到終端"
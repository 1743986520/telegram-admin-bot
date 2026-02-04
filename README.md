# Telegram Admin Bot 🤖
一個用於 Telegram 群組管理的機器人，支持自動驗證可疑進群用戶、禁言/解除禁言、群組查詢等功能，基於 `python-telegram-bot` 開發。

## 功能特點
- 🚫 自動檢測可疑進群用戶（簡介包含 @ 標籤/網址），自動禁言並觸發真人驗證
- 🔇 支持用戶自願禁言（`/banme` 指令，2 分鐘後自動解除）
- 📋 管理員專用指令：查詢機器人管理的所有群組（`/list` 指令）
- ⚡ 穩定的權限控制（符合 Telegram API 規範）
- 🛡️ 完善的異常處理（超時控制、錯誤日誌）

## 環境要求
- Python 3.12+
- Linux/Mac 操作系統（腳本基於 Linux 編寫）

## 快速安裝（Linux 環境）
### 1. 克隆倉庫
```bash
git clone https://github.com/1743986520/telegram-admin-bot.git
cd telegram-admin-bot

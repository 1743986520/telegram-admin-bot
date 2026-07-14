# Telegram Admin Bot 🤖

一個用於 Telegram 群組管理的機器人，支持廣告自動攔截、成員管理、投票提案等功能，基於 `python-telegram-bot` 開發。

## 功能特點

- 🚫 **本地廣告攔截**：正則規則 + TF-IDF 語義相似度 + 廣告模板庫，自動禁言並通知管理員
- 🧠 **動態廣告樣本庫**：可用 `/addsample` 將新廣告加入樣本庫，立即重建偵測器
- 🛡️ **誤封白樣本庫**：可用 `/whitelist` 將誤判訊息加入非廣告樣本，協助降低相似度誤封
- 📦 **樣本庫提取**：可用 `/exportsamples` 匯出廣告樣本與白樣本 JSON
- 🔍 **帳號畫像偵測**：結合用戶名格式與簡介關鍵詞，識別廣告帳號
- 🔇 **禁言指令**：`/ban` 管理員專用，回覆訊息或指定 ID 即可禁言
- 👋 **成員離開通知**：成員退群自動發送告別訊息
- 🗳️ **投票提案系統**：`/propose` 發起提案，群組民主決策
- 📋 **群組查詢**：`/list` 查詢 Bot 管理的所有群組
- 🛡️ **完善異常處理**：超時控制、錯誤日誌、零誤封設計

## 廣告攔截架構

```
訊息
 │
 ├─ L1 正則規則（<0.1ms）
 │   └─ 命中 → 禁言 + 通知管理員
 │
 ├─ L2 TF-IDF 語義相似度（~3ms）
 │   └─ 相似度 > 0.28 → 禁言 + 通知管理員
 │
 └─ 帳號畫像（用戶名 + 簡介）
     └─ 兩項同時可疑 → 禁言 + 通知管理員
```

**偵測類別（11 大類 240+ 範本）：**

| 類別 | 說明 |
|------|------|
| A | 高收益招募（一天幾萬、提豪車） |
| B | 兼職詐騙（刷單、抖音養號、充電寶投放） |
| C | 洗錢 / 非法收款（USDT搬磚、微信代收） |
| D | 假鈔 / 違禁品（高仿鈔、VCC虛擬卡） |
| E | TG推廣 / 廣告代發 |
| F | 博彩 / 幣圈（紅單、合約喊單） |
| G | 色情 / 性服務 |
| H | 上門服務 / 便民引流（吉隆坡、東南亞） |
| I | NFT / 數位資產 |
| J | 遠程控制 / 監控工具 |
| K | 模糊引流 / 其他 |

## 環境要求

- Python 3.12+
- Linux/Mac 操作系統

## 快速安裝（Linux 環境）

### 1. 克隆倉庫

```bash
git clone https://github.com/1743986520/telegram-admin-bot.git
cd telegram-admin-bot
```

### 2. 執行安裝腳本

```bash
chmod +x install.sh
./install.sh
```

### 3. 配置 Token

```bash
cp .env.example .env
nano .env  # 填入 BOT_TOKEN
```

### 4. 啟動

```bash
python main.py
```

## 指令列表

| 指令 | 權限 | 說明 |
|------|------|------|
| `/ban` | 管理員 | 禁言用戶（回覆訊息或 `/ban <user_id>`） |
| `/banme` | 所有人 | 自願禁言 2 分鐘 |
| `/propose` | 管理員 | 發起群組投票提案 |
| `/list` | 管理員 | 查詢 Bot 管理的群組 |
| `/settings` | 群組管理員 | 查看本群功能開關 |
| `/feature <名稱> <on\|off>` | 群組管理員 | 修改本群功能開關 |
| `/addsample` | Bot Owner | 回覆廣告訊息加入動態廣告樣本庫 |
| `/whitelist` | Bot Owner | 回覆誤封訊息加入非廣告白樣本庫 |
| `/exportsamples` | Bot Owner | 匯出動態廣告樣本與白樣本 JSON |

## 新增廣告範本

在 `ad_templates.py` 的對應類別加入新範本：

```python
# G. 色情 / 性服務類
"新範本內容",
```

修改後重啟 Bot 即時生效，無需其他操作。

## 群組功能開關

設定會持久化到 `known_groups.json`，舊群組未記錄的項目預設為啟用。可用名稱如下：

- `welcome`：入群歡迎
- `leave_notice`：離群通知
- `profile_check`：入群簡介檢測
- `ad_detection`：訊息廣告檢測
- `ad_delete`：廣告自動刪除
- `ad_mute`：廣告自動禁言
- `ad_notify_admins`：廣告通知管理員
- `referendum`：`/vote` 全員禁言公投
- `proposals`：`/propose` 自訂提案
- `banme`：`/banme` 彩蛋禁言
- `ban_command`：`/ban` 管理員禁言

例如：`/feature ad_notify_admins off`。廣告偵測、刪除、禁言與通知是獨立開關，可按群組需求分開調整。

## 文件結構

```
telegram-admin-bot/
├── main.py           # 主程式、指令與事件處理
├── ad_detector.py    # 廣告偵測核心（L1 + L2 + 帳號畫像）
├── ad_templates.py   # 基礎廣告模板庫（11 大類）
├── ad_samples.py     # 動態廣告／白樣本庫讀寫
├── custom_ad_samples.json  # 執行時產生，勿提交
├── whitelist_samples.json   # 執行時產生，勿提交
├── requirements.txt  # 依賴套件
├── install.sh        # 安裝腳本
└── runtime.txt       # Python 版本聲明
```

## 部署平台

支持 [Zeabur](https://zeabur.com) 一鍵部署，已內含 `zeabur.json` 配置。

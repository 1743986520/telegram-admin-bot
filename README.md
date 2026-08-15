# Telegram Admin Bot

> 面向 Telegram 群組的本地反廣告與應急管理機器人。  
> 目前核心由 **文字正規化 + 166 條 L1 規則 + 269 條 L2 廣告模板 + 動態樣本庫 + 帳號畫像聯合判定** 組成，並提供圖片驗證碼、防護模式、群組功能開關、投票與管理工具。

## 專案現在能做什麼

這個專案已經不只是「關鍵詞封廣告」。目前會從訊息內容、帳號名稱、`@username`、Telegram 簡介，以及短時間重複發送行為一起判斷，並針對容易誤判的中性話術加入額外保護。

### 廣告偵測

- **L1 正則規則引擎**：目前 166 條規則，處理高置信度話術、組合關鍵詞與常見規避寫法。
- **L2 TF-IDF 相似度**：以 269 條內建廣告模板與動態廣告樣本建立雙字元 n-gram 向量器。
- **自適應相似度門檻**：短訊息、一般訊息、長訊息採不同策略，降低共享字元造成的誤判。
- **品牌／付款詞語境保護**：例如 OpenAI、GPT、Claude、Telegram、微信、支付寶等詞本身不會直接當成廣告，必須搭配推廣、代收、售賣等語境。
- **白樣本救援**：被判定與廣告模板相似時，會再與非廣告白樣本比較，降低已知誤判再次出現的機率。
- **中性話術 + 帳號畫像聯合判斷**：像「一起搞錢」「有興趣的來」這種單獨看不應直接封鎖的內容，只有在發送者的名稱／用戶名／簡介同時呈現廣告訊號時才升級判定。
- **重複洗版偵測**：同一群組中，正規化後相同且長度至少 8 字的內容，在 10 分鐘內出現 3 次會被視為洗版嫌疑。
- **媒體訊息支援**：文字、圖片/影片/文件 caption、聯絡人分享，以及重複圖片/影片/文件都能進入統一檢測流程。

### 帳號畫像與入群驗證

- 新成員加入時可檢查 **用戶名、暱稱、簡介**。
- 帳號畫像直接命中廣告模板時，可視為高置信度廣告帳號並直接限制權限。
- 只有軟性可疑訊號時，可要求完成 **網頁 6 位數圖片驗證碼 + Cloudflare Turnstile**；若未配置 Web 驗證環境變數，會安全回退到 Telegram 圖片算術驗證碼。
- 驗證碼提供 4 個答案、最多 3 次機會，並有自動過期與訊息清理機制。
- 已加入成員若修改名稱，`rename_recheck` 可重新檢查帳號畫像。
- `profile_hit_report` 可獨立控制簡介命中的通報行為。

### 防護模式

遇到炸群或大量新帳號湧入時，管理員可使用：

```text
/guard
```

或別名：

```text
/omg
```

開啟後，在 `/stop` 前：

- 新加入者會被直接限制所有權限；
- 不發送歡迎或驗證提示；
- 自動刪除「某某加入了群組」系統訊息；
- 記錄防護期間加入的成員；
- `/stop` 後可選擇全部踢出、挑選踢出或全部保留。

這個模式和一般入群驗證分離，適合臨時應急。

## 偵測流程

```text
Telegram 訊息 / caption / 帳號畫像
               │
               ▼
        clean_text 正規化
               │
     ┌─────────┴─────────┐
     ▼                   ▼
L1 正則規則          L2 TF-IDF 相似度
166 條規則           269 模板 + 動態樣本
     │                   │
     └─────────┬─────────┘
               ▼
       品牌語境 / 白樣本保護
               │
       ┌───────┴────────┐
       ▼                ▼
   高置信命中       邊界 / 中性內容
       │                │
       │          查發送者帳號畫像
       │                │
       └───────┬────────┘
               ▼
      刪除 / 禁言 / 管理員通知
```

若文字本身沒有命中，還會再檢查 **10 分鐘內是否重複洗版**；管理員訊息則不走一般廣告攔截。

## 文字正規化

`ad_detector.clean_text()` 會先處理常見繞過方式，例如：

- Unicode 零寬字元與 `Cf` 類控制字元；
- NFKC 全形／半形正規化；
- 字元間插入 `+ · • / \\ - .` 等拆字混淆；
- 常見同音、形近字與縮寫混淆；
- 數字中的 `o/O` 替代；
- 再交由規則與相似度層處理。

因此偵測使用的是「清洗後的文字」，不是只拿原文做關鍵詞搜尋。

## 動態樣本庫

不必每次修改程式碼才能補案例。

### 加入廣告樣本

Bot Owner 回覆一則廣告：

```text
/addsample
```

或：

```text
/addsample <廣告文字>
```

樣本會做正規化去重，加入後立即重建偵測器，不需要重啟 Bot。

### 加入非廣告白樣本

Bot Owner 回覆誤封訊息：

```text
/whitelist
```

也可以直接附文字。若是回覆某位使用者的訊息，Bot 會順便嘗試恢復該使用者的發言權限。

廣告攔截通知上同樣提供「誤封：加入非廣告樣本」按鈕，方便管理員處理 false positive。

### 管理樣本

```text
/samples
/samples wl
```

可查看動態廣告樣本或白樣本，並直接用按鈕刪除。列表超過 30 條時只顯示前 30 條，可透過 `/exportsamples` 取得完整 JSON。

```text
/cleanupads
```

會將動態廣告樣本與官方模板做正規化去重，再熱重載偵測器。

## 指令

| 指令 | 權限 / 場景 | 功能 |
|---|---|---|
| `/start` | 所有人 | 顯示 Bot 狀態與常用入口 |
| `/help` | 所有人 | 顯示完整指令說明 |
| `/settings` | 群組管理員 | 查看本群功能開關，可直接用按鈕切換 |
| `/feature <name> <on\|off>` | 群組管理員 | 修改單一群組功能 |
| `/ban` | 群組管理員 | 回覆訊息或指定 ID 禁言成員 |
| `/banme` | 非管理員成員 | 自願禁言 2 分鐘 |
| `/test` | 所有人 | 開啟個人測試模式，不真的刪除/禁言 |
| `/stop` | 視目前模式 | 結束測試；或由群管理員解除防護模式 |
| `/guard` / `/omg` | 群組管理員 | 開啟靜默防護模式 |
| `/vote` | 群組管理員 | 發起全員禁言公投 |
| `/propose <內容>` | 群組管理員 | 發起自訂提案 |
| `/list` | Bot Owner，私聊 | 查看 Bot 記錄的群組 |
| `/addsample` | Bot Owner | 加入動態廣告樣本 |
| `/whitelist` | Bot Owner | 加入非廣告白樣本，回覆使用時可嘗試解除誤封 |
| `/samples [wl]` | Bot Owner | 查看、刪除廣告樣本或白樣本 |
| `/exportsamples` | 本群管理員 | 匯出動態廣告樣本與白樣本 JSON |
| `/cleanupads` | 本群管理員 | 去除動態廣告樣本中的重複項 |
| `/updatead` | Bot Owner | `git pull` 後熱重載廣告模板，不重啟 Bot |
| `/update` | Bot Owner | `git pull` 更新整個專案並重啟程序 |

## 群組功能開關

目前 `settings.py` 共有 14 個可獨立控制的功能：

| 名稱 | 說明 |
|---|---|
| `welcome` | 入群歡迎 |
| `leave_notice` | 離群通知 |
| `profile_check` | 入群帳號畫像檢測 |
| `ad_detection` | 訊息廣告檢測 |
| `ad_delete` | 廣告自動刪除 |
| `ad_mute` | 廣告自動禁言 |
| `ad_notify_admins` | 廣告命中後通知管理員 |
| `referendum` | 全員禁言公投 |
| `proposals` | 自訂提案 |
| `banme` | `/banme` 彩蛋禁言 |
| `ban_command` | `/ban` 管理員禁言 |
| `join_captcha` | 入群圖片驗證碼 |
| `profile_hit_report` | 帳號簡介命中通報 |
| `rename_recheck` | 成員改名後重新檢測 |

例如：

```text
/feature ad_notify_admins off
/feature rename_recheck on
```

設定會保存到 `known_groups.json`。防護模式狀態也保存在群組資料中，但不透過 `/feature` 控制。

## 安裝

### 環境

- Python 3.12+
- Linux（安裝腳本以 Debian / Ubuntu 類環境為主）
- `python-telegram-bot >= 22`
- NumPy
- scikit-learn
- Pillow

圖片驗證碼會優先使用系統中的 DejaVu / Liberation 字型；沒有時會退回 Pillow 可用字型。

### 自動安裝

```bash
git clone https://github.com/1743986520/telegram-admin-bot.git
cd telegram-admin-bot
chmod +x install.sh
./install.sh
```

安裝腳本會要求 Bot Token 與 Owner Telegram ID，建立 Python 3.12 環境並配置服務。

### 手動啟動

```bash
export BOT_TOKEN="你的 Bot Token"
python main.py
```

### 網頁驗證與 Cloudflare Turnstile

要啟用網頁驗證，需讓 Bot 所在服務公開一個 HTTPS 網址，並設定：

```bash
export WEB_VERIFY_BASE_URL="https://bot.example.com"
export WEB_VERIFY_PORT="8080"
export CF_TURNSTILE_SITE_KEY="你的 Site Key"
export CF_TURNSTILE_SECRET_KEY="你的 Secret Key"
python main.py
```

`CF_TURNSTILE_SECRET_KEY` 只放在部署平台的 Secret/環境變數，不能提交到 Git。網頁驗證連結為一次性、5 分鐘有效；後端會同時檢查圖片數字答案與 Turnstile token，成功後才解除 Telegram 禁言。部署平台需要把 `WEB_VERIFY_PORT` 對外轉發到 HTTPS 網域；若任一必要變數缺少，Bot 會回退到 Telegram 內建圖片驗證流程。

若使用虛擬環境：

```bash
venv/bin/pip install -r requirements.txt
BOT_TOKEN="你的 Bot Token" venv/bin/python main.py
```

> `git pull` 本身不會安裝新增的 Python 套件。如果 `requirements.txt` 有變化，更新後請重新執行 `pip install -r requirements.txt`。

## 專案結構

```text
telegram-admin-bot/
├── main.py                 # Telegram 事件、指令、驗證、防護、投票與廣告處理
├── ad_detector.py          # clean_text、L1 規則、L2 TF-IDF、品牌語境與白樣本保護
├── ad_templates.py         # 269 條內建廣告模板
├── ad_samples.py           # 動態廣告/白樣本讀寫與去重
├── settings.py             # 14 個群組功能開關
├── tests/
│   └── test_settings.py    # 設定模組測試
├── index.html              # GitHub Pages / 專案展示頁
├── install.sh              # Linux 安裝腳本
├── requirements.txt        # Python 依賴
├── runtime.txt             # Python runtime 聲明
├── CNAME                   # 自訂網域設定
├── known_groups.json       # 執行期產生：群組與功能狀態
├── custom_ad_samples.json  # 執行期產生：動態廣告樣本
└── whitelist_samples.json  # 執行期產生：非廣告白樣本
```

最後三個 JSON 屬於執行期資料，正常情況下不應提交到公開倉庫。

## 設計原則

這個 Bot 的方向不是「看到可疑詞就封」，而是盡量分開 **高置信度訊號** 與 **需要上下文的中性訊號**：

1. 明確廣告模式由 L1 快速攔截；
2. 改寫型廣告交給 L2 模板相似度；
3. 品牌詞、付款詞、短訊息加入額外保護；
4. 中性話術只有配合帳號畫像才升級；
5. 已知誤判透過白樣本持續修正；
6. 炸群場景交給獨立的 `/guard` 應急模式，而不是硬塞進一般偵測流程。

## 已知限制

- TF-IDF 是本地統計相似度模型，不是真正理解語意的 LLM；模板品質仍會直接影響判定。
- 純圖片內容目前不做 OCR；無 caption 的圖片/影片/文件主要能參與重複洗版識別。
- Telegram Bot API 能取得的使用者資料有限，帳號畫像仍以可取得的名稱、username、bio 為主。
- `/guard` 的挑選踢出名單尚未分頁，大量成員時操作會變長。
- 動態樣本是本機 JSON 資料，部署到無持久磁碟的平台時應額外處理資料持久化。

## License / 使用提醒

部署前請自行確認 Telegram Bot 權限、資料保存方式以及所在地區的法律與社群規範。對自動禁言與刪除策略，建議先在測試群使用 `/test` 和群組功能開關確認效果，再套用到正式群組。

# 🩺 PadPilot 疑難排解與常見問答 (Troubleshooting & FAQ)

本手冊收錄 PadPilot 在 macOS 環境下常見的狀態警告、硬體辨識問題、連線異常及其解決方案。

---

## 目錄 (Table of Contents)

- [1. FileVault 與無頭冷開機限制 (`#filevault`)](#filevault)
- [2. Sidecar 使用者登入會話先決條件 (`#sidecar-session`)](#sidecar-session)
- [3. BetterDisplay 權限與 CLI 介面 (`#betterdisplay`)](#betterdisplay)
- [4. 開機虛擬/佔位螢幕 (Generic Display) 處理 (`#generic-display`)](#generic-display)
- [5. 連線瞬斷、重試與冷卻保護期 (`#cooldown`)](#cooldown)
- [6. 登入自啟動 LaunchAgent 問題 (`#autostart`)](#autostart)
- [7. 如何收集除錯日誌回報問題 (`#logs`)](#logs)

---

<a id="filevault"></a>
## 1. FileVault 與無頭冷開機限制

> [!WARNING]
> **重要物理限制：PadPilot 無法讓 iPad 成為 FileVault / Pre-login 畫面。**

### 現象
Mac mini 冷開機（重開機或關機後開機）時，iPad 螢幕一片漆黑，完全沒有出現 macOS 登入畫面。

### 原因
- macOS 的 **FileVault** 是開機全磁碟加密機制。在使用者輸入密碼解鎖磁碟之前，系統處於「Pre-boot 階段」，此時：
  1. 作業系統核心尚未完全載入。
  2. 使用者帳號與背景守護行程（LaunchAgent）尚未啟動。
  3. Apple 的無線/有線 Sidecar 驅動程式與輔助背景程序尚未就緒。
- 因此，任何軟體層級的 Sidecar 工具都**不可能**在 FileVault 解鎖前驅動 iPad。

### 解決方法
若您欲實現「Mac mini 不接任何螢幕、出門只帶 iPad，一開機就能直接用」的極致 Headless 情境：
1. **關閉 FileVault 全磁碟加密**（系統設定 -> 隱私權與安全性 -> FileVault -> 關閉）。
2. **開啟 macOS 自動登入**（系統設定 -> 使用者與群組 -> 自動登入 -> 選擇您的帳號）。
3. 這樣 Mac mini 開機時便會自動跳過登入鎖定畫面進入桌面，PadPilot daemon 隨即啟動並在數秒內將 iPad 轉為主顯示器。
4. *(安全折衷方案)*：若堅持開啟 FileVault，初次開機需盲打帳號密碼解鎖，或在外接實體螢幕/隨身便攜螢幕下輸入密碼進入系統後，再拔除螢幕轉由 iPad 接管。

---

<a id="sidecar-session"></a>
## 2. Sidecar 使用者登入會話先決條件

### 現象
PadPilot 顯示已偵測到 USB iPad，但發起 Sidecar 連線時持續逾時或失敗。

### 檢查清單
1. **相同 Apple Account**：Mac 與 iPad 必須登入完全相同的 Apple 帳號（Apple ID）。
2. **雙重認證 (Two-Factor Authentication)**：兩部設備均需開啟 Apple ID 雙重認證。
3. **信任此電腦**：首次以 USB 傳輸線插上 iPad 時，iPad 螢幕會跳出「信任這部電腦？」，務必點擊「信任」並輸入 iPad 解鎖密碼。
4. **無線通訊開啟**：即使透過 USB-C 實體線連接，macOS 與 iPad 雙方的 **Wi-Fi 與藍牙亦必須保持開啟狀態**（此為 Apple 原生 Sidecar 底層握手協定的硬性要求）。

---

<a id="betterdisplay"></a>
## 3. BetterDisplay 權限與 CLI 介面

### 現象
GUI 診斷卡片顯示「BetterDisplay 控制介面：未啟用」或「找不到 betterdisplaycli」。

### 原因
PadPilot 透過 BetterDisplay 命令列介面（CLI）進行底層顯示器角色設定與虛擬螢幕管理。若 BetterDisplay 未開啟 CLI 或權限不足，系統將無法調度顯示器。

### 解決方法
1. 開啟 **BetterDisplay.app**。
2. 進入 BetterDisplay「偏好設定 (Settings)」-> 側邊欄切換至「整合 / 進階 (Integration / CLI)」。
3. 確保 **「Enable Command Line Interface (CLI)」** 已勾選。
4. 在終端機測試執行：
   ```bash
   betterdisplaycli get -identifiers
   ```
   若能正常印出顯示器清單 JSON，即代表 CLI 運作正常。
5. 若 macOS 系統設定彈出「輔助使用 (Accessibility)」或「螢幕錄製 (Screen Recording)」權限要求，請核對實際提出要求的 App（例如 BetterDisplay）及系統提示，不要一律授權 Terminal 或其他 App。原生選單本身只讀快照並呼叫 CLI。

---

<a id="generic-display"></a>
## 4. 開機虛擬/佔位螢幕 (Generic Display) 處理

### 現象
無接實體螢幕開機時，PadPilot 偵測到名為 `Generic Display` 或 `Generic` 的裝置，導致系統誤以為有實體螢幕而暫停連線 iPad。

### 原因
部分 Mac 機型在未接螢幕開機時，GPU 會產生極簡的佔位 framebuffer 裝置。

### 解決方法
- PadPilot 內建**精確佔位過濾邏輯**，已將已知之佔位名稱排除在實體螢幕外。
- 若您的實體螢幕剛好名稱也包含 Generic，可透過 CLI 查看 EDID 與識別碼：
  ```bash
  ./bin/padpilot-cli status --json
  ```
- 亦可在設定中將特定裝置名稱加入 `ignore_list`。

---

<a id="cooldown"></a>
## 5. 連線瞬斷、重試與冷卻保護期

### 現象
Menu Bar 圖示亮起 `⚠️`，狀態顯示「冷卻保護期 (Cooldown 30s)」。

### 原因
PadPilot 內建**保護性退避機制**：
- 當 Sidecar 連線發起後連續失敗達 3 次（每次間隔 3 秒），為防範持續狂暴連線導致 macOS WindowServer 或 BetterDisplay 當機，系統會自動進入 30 秒的 Cooldown 鎖定。

### 恢復方式
1. 檢查 iPad 是否處於睡眠鎖定狀態（點亮 iPad 螢幕）。
2. 檢查傳輸線是否接觸不良。
3. 若確認硬體已正常，可直接於 Menu Bar 點選「重新連線」，或執行：
   ```bash
   ./bin/padpilot-cli action reset
   ```
   即可立刻清除重試計數與冷卻狀態。

---

<a id="autostart"></a>
## 6. 登入自啟動 LaunchAgent 問題

### 現象
重開機後，Menu Bar 沒有出現 PadPilot 圖示，背景服務未執行。

### 解決方法
1. 檢查 LaunchAgent 是否已載入：
   ```bash
   launchctl list | grep padpilot
   ```
2. 若未載入，透過 CLI 重新啟用自啟：
   ```bash
   ./bin/padpilot-cli autostart enable
   ```
3. 確認 plist 檔案已正產生成於：
   `~/Library/LaunchAgents/com.padpilot.daemon.plist`

---

<a id="logs"></a>
## 7. 如何收集除錯日誌回報問題

若上述指引仍無法排除您的問題，歡迎在 GitHub 提交 Issue，並附上日誌資訊：

```bash
# 即時查看日誌
./bin/padpilot-cli open-log

# 或查看日誌檔案
cat ~/Library/Logs/PadPilot/daemon.log | tail -n 50
cat ~/Library/Logs/PadPilot/launchd.stderr.log
```
*在提交日誌至公開平台前，請自行檢視並遮蔽任何個人敏感路徑或資訊。*

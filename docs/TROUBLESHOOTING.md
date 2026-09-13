# 🩺 PadPilot 疑難排解與常見問答 (Troubleshooting & FAQ)

**繁體中文** | [English](TROUBLESHOOTING.en.md) | [日本語](TROUBLESHOOTING.ja.md) · [文件索引](README.md)

發行版的 Gatekeeper 警告、Python 切換／遺失復原，以及原始碼版移轉方式，請先參閱[已編譯版本安裝說明](INSTALLATION.md)。BetterDisplay App 必須安裝並執行，獨立 CLI 可省略。

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
- [8. 預檢、私人路徑或啟動握手失敗 (`#safe-startup`)](#safe-startup)

---

<a id="filevault"></a>
## 1. FileVault 與無頭冷開機限制

> [!WARNING]
> **重要物理限制：PadPilot 無法讓 iPad 成為 FileVault / Pre-login 畫面。**

### 現象
Mac mini 冷開機（重開機或關機後開機）時，iPad 螢幕一片漆黑，完全沒有出現 macOS 登入畫面。

### 原因
PadPilot 的 LaunchAgent 在使用者登入後啟動，依賴登入工作階段中的 Sidecar。FileVault 解鎖與登入前畫面不在 PadPilot 的支援範圍；開啟登入啟動不會改變這個限制。

### 解決方法
1. 保留可用的實體螢幕完成解鎖與登入，再確認 Sidecar 能手動連線。
2. 登入後執行 `./bin/padpilot-cli status`，確認服務有回應，再測試 iPad 接管。
3. 無頭使用前，先驗證自己的冷開機與救援流程；不同硬體組合仍為待驗證。

**安裝不要求關閉 FileVault 或開啟自動登入。** 這些設定會影響資料與帳號安全，也不能保證 Sidecar 在數秒內連線；不要為通過檢查而降低系統安全性。

這兩項診斷用於評估開機後自動連接螢幕的條件：macOS 自動登入啟用為綠色「通過」、停用為紅色「不通過」；FileVault 未開啟為通過、已開啟為不通過。尚未檢查或無法確認時顯示橘色。這些檢查僅讀取狀態，不會修改設定或讀取密碼；通過也不保證 Sidecar 必定連線。

---

<a id="sidecar-session"></a>
## 2. Sidecar 使用者登入會話先決條件

### 現象
PadPilot 顯示已偵測到 USB iPad，但發起 Sidecar 連線時持續逾時或失敗。

### 檢查清單
1. **相同 Apple Account**：Mac 與 iPad 必須登入完全相同的 Apple 帳號（Apple ID）。
2. **雙重認證 (Two-Factor Authentication)**：兩部設備均需開啟 Apple ID 雙重認證。
3. **信任此電腦**：首次以 USB 傳輸線插上 iPad 時，iPad 螢幕會跳出「信任這部電腦？」，務必點擊「信任」並輸入 iPad 解鎖密碼。
4. **無線條件**：無線 Sidecar 需要 Wi-Fi、藍牙及 Handoff；USB 連線請確認資料線與信任設定。完整相容性及連線條件以 [Apple Sidecar 說明](https://support.apple.com/en-us/102597)為準。

---

<a id="betterdisplay"></a>
## 3. BetterDisplay 權限與 CLI 介面

### 現象
GUI 診斷卡片顯示「BetterDisplay 控制介面：未啟用」或「找不到 betterdisplaycli」。

### 原因
PadPilot 透過 BetterDisplay 命令列介面（CLI）進行底層顯示器角色設定與虛擬螢幕管理。若 BetterDisplay 未開啟 CLI 或權限不足，系統將無法調度顯示器。

### 解決方法
1. 開啟 **BetterDisplay.app**。
2. 依已安裝版本的 [BetterDisplay CLI 說明](https://github.com/waydabber/BetterDisplay/wiki/Integration-features,-CLI)確認控制介面可用；設定名稱與位置可能因版本而異。
3. 確認具備所需 Pro 授權或有效試用，並確認 PadPilot 使用正確的 CLI 路徑。
4. 在終端機測試執行：
   ```bash
   betterdisplaycli get -identifiers
   ```
   確認指令成功且能讀到預期裝置。CLI 有回應不代表 Sidecar 配對與實際顯示已通過驗收。
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
- 若您的實體螢幕剛好也叫 `Generic` 或 `Generic Display`，請保留狀態並另行收集 EDID／識別資料供排查：
  ```bash
  ./bin/padpilot-cli status --json
  ```
- 不應把真正的實體螢幕加入忽略清單；請回報其識別資料，避免擴大名稱排除範圍。

---

<a id="cooldown"></a>
## 5. 連線瞬斷、重試與冷卻保護期

### 現象
Menu Bar 圖示亮起 `⚠️`，顯示自動重試已暫停；前 30 秒仍有冷卻保護。

### 原因
PadPilot 內建**保護性退避機制**：
- 當 Sidecar 連線連續失敗達 3 次（每次間隔 3 秒），通知一次並停止自動重試，保留實體或虛擬備援。30 秒冷卻結束後仍維持暫停，不會因 iPad 關閉但仍留在 Sidecar 清單而持續連線、累積警告。USB 插拔及喚醒與自動偵測 iPad 可繼續開啟。

### 恢復方式
1. 檢查 iPad 是否處於睡眠鎖定狀態（點亮 iPad 螢幕）。
2. 檢查傳輸線是否接觸不良。目標 iPad 的 USB 或 Sidecar 可用狀態重新由無變有後，待剩餘冷卻結束會恢復有限次數的嘗試。若只是點亮螢幕、沒有重新偵測到裝置，請選「重新連線」。一般 USB 喚醒、重新整理或接回實體螢幕不會解除暫停。
3. 若確認硬體已正常，需要清除暫時覆寫與冷卻時可執行：
   ```bash
   ./bin/padpilot-cli action reset
   ```
   背景服務會重新評估；需要手動連線時再選「重新連線」。送出成功不等於連線完成。

---

<a id="autostart"></a>
## 6. 登入自啟動 LaunchAgent 問題

### 現象
重開機後，Menu Bar 沒有出現 PadPilot 圖示，背景服務未執行。

### 解決方法
1. 檢查 LaunchAgent 是否已載入：
   ```bash
   ./bin/padpilot-cli autostart status
   ./bin/padpilot-cli status
   ```
2. 若未載入，透過 CLI 重新啟用自啟：
   ```bash
   ./bin/padpilot-cli autostart enable
   ```
3. 本版的 plist 位於 `PadPilot.app/Contents/Library/LaunchAgents/com.padpilot.daemon.plist`，不會建立 `~/Library/LaunchAgents` 下的檔案。若狀態為 `requiresApproval`，請到「系統設定 → 一般 → 登入項目」允許 PadPilot 背景執行。測試用舊版外部 LaunchAgent 必須自行停止並清除；本版不做遷移。

---

<a id="logs"></a>
## 7. 如何收集除錯日誌回報問題

若上述指引仍無法排除您的問題，請整理重現步驟與日誌；目前 GitHub 倉庫為私人，僅有存取權限的帳號可提交 Issue：

```bash
# 即時查看日誌
./bin/padpilot-cli open-log

# 或查看日誌檔案
tail -n 50 ~/Library/Logs/PadPilot/padpilot.log
cat ~/Library/Logs/PadPilot/launchd.stderr.log
```
*在提交日誌至公開平台前，請自行檢視並遮蔽任何個人敏感路徑或資訊。*

<a id="safe-startup"></a>
## 8. 預檢、私人路徑或啟動握手失敗

- `FAIL: BetterDisplay CLI`：App 已安裝不等於 CLI 可用。確認 BetterDisplay 的 CLI 功能與已儲存的執行檔路徑，再執行 `./scripts/install.sh --check`。不要把 help 成功當成授權或實機驗收通過。
- 設定視窗無法開啟：更新原始碼後請重新執行 `./scripts/install.sh`，建置與目前版本相符的 App。
- `Refusing unsafe state directory/file`：先停止操作，檢查訊息指定路徑的所有者、符號連結與硬連結。不要對 `/tmp` 或他人目錄遞迴改權限、刪除或強制接管。確認是自己的舊資料後先備份，再由擁有者整理；應用程式會拒絕不可信路徑。
- `Login service belongs to another ...`：同名 App／服務來自另一個 checkout。請回到原專案路徑使用其解除安裝器，不要直接終止所有包含 padpilot 的程序。
- `Daemon handshake failed`：代表沒有確認此專案的服務正常回應，不能算安裝成功。查看 `~/Library/Logs/PadPilot/launchd.stderr.log` 與 `padpilot.log`，排除路徑、權限或 BetterDisplay 問題後重試。若附帶 `Rollback incomplete`，舊設定或執行狀態也尚未確認恢復，先保留紀錄，不要反覆安裝。

新的 IPC 日誌只保留命令名稱；舊日誌、診斷狀態與實際錯誤仍可能包含裝置資訊。分享前遮蔽序號、UUID、帳號及個人路徑。

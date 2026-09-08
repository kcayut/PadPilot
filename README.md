# 📱 PadPilot

**Mac mini M4 + iPad 自動螢幕系統 (Display State Manager)**

PadPilot 是一套專為 Mac mini M4 與透過 USB-C 連接的 iPad 所設計的智慧顯示器管理系統。系統以「**實體螢幕優先、手動操作絕對優先、狀態全透明、Headless 備援長期保留**」為核心原則，在無實體螢幕時自動將指定 iPad 轉為主要顯示器；而在接有實體螢幕時保持安靜不干涉，並透過 macOS Menu Bar 提供直覺、即時的手動控制介面。

---

## 🌟 核心特性

- **自動情境接管**：
  - **外出 / Headless 模式**：Mac mini 未連接任何實體螢幕時，偵測到指定的 USB iPad 或已配對的 Sidecar 目標後，自動建立 Sidecar 連線並將 iPad 設為主要顯示器（Main Display）。
  - **桌機日常模式**：接有 HDMI / DP / USB-C 實體螢幕時，自動化保持靜默，不擅自啟動 Sidecar，iPad 維持一般平板狀態。
- **手動操作絕對優先 (User Override)**：
  - 使用者隨時可從 Menu Bar 選擇「Use iPad as Secondary」或「Use iPad as Main」。
  - 導入 **Topology Generation（拓撲世代碼）** 機制：手動決策會綁定當前硬體世代，只要硬體連接未發生實質改變，自動化絕不推翻使用者的決定；實體螢幕 ID 或 USB iPad 的連接狀態改變後會失效並重新評估；有實體螢幕時，已連線的 iPad 若斷線，也會清除 iPad 主／副螢幕覆寫。
- **單飛行狀態轉換鎖 (Single-Flight Transition Lock)**：
  - 防止 USB 插入、螢幕喚醒、定時輪詢併發觸發多次 Sidecar 連線，保障連線不發生 Race Condition。
- **連線防抖與冷卻保護**：
  - **Debounce 防抖**：實體螢幕瞬斷或切換輸入源時，啟動 4 秒防抖計時，未滿前不動作；下一次偵測到螢幕恢復時取消切換；4 秒是最短等待，實際反應時間受輪詢間隔影響。
  - **重試與冷卻**：Sidecar 連線失敗自動重試最多 3 次（間隔 3 秒）；若全數失敗則進入 30 秒冷卻保護期（Cooldown），避免連線風暴，並以系統通知發出警報。
- **三組獨立 iPad 識別碼**：
  - 解耦 `sidecar_uuid`（BetterDisplay/Sidecar 識別碼）、`usb_serial`（IOKit USB 樹硬體序號）、`device_name`（顯示名稱），杜絕同一 Apple ID 下多台 iPad 誤判。
- **Headless Fallback 虛擬螢幕**：
  - 整合 BetterDisplay 虛擬螢幕（預設 `PadPilotVirtual`），啟動時進行 **Capability Probing** 動態探測。無實體螢幕且 Sidecar 異常時，虛擬螢幕提供穩定的 Framebuffer 供 Screen Sharing / VNC / SSH 救援。
- **狀態刷新 + 開機暖機與 30 秒 Watchdog**：
  - 啟動時最多暖機 30 秒，每輪等待 2 秒再評估；之後每輪等待 30 秒。硬體查詢耗時另計，目前沒有原生插拔／睡眠／喚醒事件監聽。
  - 狀態輸出時呼叫 `open -g "swiftbar://refreshplugin?plugin=padpilot.30s.py"` 更新 Menu Bar。
  - SwiftBar 外掛純讀取由背景 Daemon 原子寫入的 `status.json`（讀取耗時 < 5ms），杜絕高頻 `system_profiler` 輪詢，CPU 佔用率近乎 0.0%。

---

## 🏛️ 系統架構

```
                   ┌───────────────────────────────────┐
                   │    SwiftBar Menu Bar Plugin       │
                   │ (動態圖示 / 狀態 / Reason / Actions)  │
                   └─────────────────▲─────────────────┘
                                     │ 事件主動觸發: swiftbar://refreshplugin
                                     │ 狀態讀取: atomic status.json
                                     ▼
                   ┌───────────────────────────────────┐
                   │   padpilotd (Display State Mgr)   │
                   │  - observe() -> ActualState       │
                   │  - policy()  -> DesiredState      │
                   │  - Single-flight Transition Lock  │
                   │  - Topology Generation Tracking   │
                   └──────┬──────────────────────┬─────┘
                          │                      │
       硬體偵測 + Watchdog│                      │ 控制命令 (動態 Capability Probing)
                          ▼                      ▼
      ┌───────────────────────────┐   ┌───────────────────────────┐
      │  CoreGraphics (ctypes)    │   │     BetterDisplay CLI     │
      │  IOKit USB (ioreg)        │   │  - Sidecar Connect/Disc   │
      │  Sleep / Wake 監聽        │   │  - Set Main Display       │
      │  30s Watchdog 輪詢        │   │  - PadPilotVirtual Check  │
      └───────────────────────────┘   └───────────────────────────┘
```

---

## 🧭 三種工作模式

| 模式 | 行為說明 |
| :--- | :--- |
| **Automatic**<br>*(預設日常)* | 有實體螢幕時不自動干預；無實體螢幕且配對 USB iPad 或 Sidecar 目標可用時，自動連線並將 iPad 設為主螢幕。 |
| **Manual Only**<br>*(完全手動)* | 自動化暫停，不主動連線、斷開或切換主螢幕。使用者仍可透過 Menu Bar 手動點選任何動作。 |
| **Prefer iPad**<br>*(偏好 iPad)* | 即使連接實體螢幕，依然偏好將 iPad 連線並設為主要顯示器；失敗時仍遵守重試與冷卻策略並優雅 Fallback。 |

---

## 📊 Menu Bar UI 狀態展示

外觀會隨系統狀態動態呈現對應圖示：
- `🖥️`：實體螢幕使用中
- `📱`：iPad Sidecar 使用中
- `◻️`：Virtual Display / Headless 備援狀態
- `⚠️`：錯誤、連線中斷或處於冷卻保護期
- `⏸️`：Manual Only 暫停狀態

```text
🖥️ PadPilot
───────────────────────────────
Status
Physical Display:     ROG PG279Q (2560x1440)
USB iPad:             Connected (Cayut iPad)
Sidecar:              Disconnected
Current Main:         ROG PG279Q
Virtual Fallback:     Configured
───────────────────────────────
Desired vs Actual
Desired State:        PHYSICAL
Actual State:         ✓ Satisfied
───────────────────────────────
Reason
Physical display detected (ROG PG279Q).
Automatic Sidecar not required.
───────────────────────────────
Mode
✓ Automatic
  Manual Only
  Prefer iPad
───────────────────────────────
Actions
Use iPad as Secondary
Use iPad as Main
Disconnect iPad
Reconnect Sidecar
───────────────────────────────
Refresh Display State
Reset Display Automation
Open BetterDisplay
Preferences...
Open Log
```

---

## 🛠️ 快速安裝與設定

### 1. 執行安裝引導腳本
PadPilot 提供友善且非侵入式的安裝腳本，會自動探測 BetterDisplay 與 SwiftBar，並提示是否由 Homebrew 安裝：

```bash
cd /Users/smallmac/work/PadPilot
./scripts/install.sh
```
*(或帶 `--yes` 自動確認相依性安裝)*

### 2. 配對您的 iPad
將 iPad 透過 USB-C 連接線插入 Mac mini，確保兩台設備登入相同 Apple Account，然後執行配對精靈：

```bash
./bin/padpilot-cli pair --interactive
```
配對完成後，iPad 的 `name`、`sidecar_uuid` 與 `usb_serial` 將安全記錄於：
`~/Library/Application Support/PadPilot/config.json`。

### 3. 開啟 SwiftBar
```bash
open -a SwiftBar
```
Menu Bar 即會顯示 PadPilot 動態圖示與控制選單！

---

## ⌨️ CLI 命令列使用手冊

PadPilot 提供強大的 `padpilot-cli` 工具，可直接透過終端機檢查狀態或進行腳本整合：

```bash
# 查看當前狀態 (圖形化文字輸出)
padpilot-cli status

# 輸出機器可讀的 JSON 狀態快照
padpilot-cli status --json

# 切換工作模式
padpilot-cli set-mode automatic
padpilot-cli set-mode manual_only
padpilot-cli set-mode prefer_ipad

# 觸發手動操作 (即時生效並刷新 Menu Bar)
padpilot-cli action use_ipad_secondary  # 將 iPad 作為副螢幕
padpilot-cli action use_ipad_main       # 將 iPad 設為主要顯示器
padpilot-cli action disconnect_ipad     # 斷開 Sidecar
padpilot-cli action reconnect_sidecar   # 重新連線 Sidecar
padpilot-cli action refresh             # 立即重新掃描拓撲
padpilot-cli action reset               # 清除暫時覆寫、重試計數與冷卻狀態

# 啟動與停止背景守護行程
padpilot-cli stop                      # 停止 daemon
padpilot-cli start                     # 重新啟動 daemon

# 開機登入自動執行管理 (可從 Menu Bar 直接切換，或使用 CLI)
padpilot-cli autostart status          # 查看登入啟動狀態 (Enabled / Disabled)
padpilot-cli autostart enable          # 設定登入時自動執行 Daemon
padpilot-cli autostart disable         # 設定登入時不執行 Daemon (維持當前 session 運作)
padpilot-cli autostart toggle          # 切換登入自動執行開關

# 查看目前設定檔
padpilot-cli prefs

# 開啟即時日誌
padpilot-cli open-log
```

---

## 🧪 單元測試覆蓋

測試涵蓋偵測、狀態切換、LaunchAgent 與開機／控制衝突的回歸案例。模擬測試不能取代拔線冷開機驗收：

```bash
python3 -m unittest discover -s tests -v
```

1. **Scenario 1 (桌機日常)**：實體螢幕 + USB iPad -> `is_satisfied` 為真，Sidecar 不啟動。
2. **Scenario 2 (外出 Headless)**：無實體螢幕 + USB iPad -> 觸發 Sidecar 連線並將 iPad 設為主螢幕。
3. **Scenario 3 (手動覆寫保護)**：使用者手動選 `Secondary` -> 綁定 Generation，自動化絕不推翻。
4. **Scenario 4 (實體螢幕拔除)**：螢幕拔除使 Generation 改變 -> Override 自然失效，自動切回 iPad Main。
5. **Scenario 5 (完全 Headless 備援)**：無螢幕無 iPad -> Fallback 啟動 Virtual Display。
6. **Scenario 6 (Sidecar 重試與冷卻)**：連線失敗連續重試 3 次，第 3 次失敗進入 30 秒 Cooldown，發出警告通知。
7. **Scenario 7 (評估)**：模擬喚醒後的評估，若狀態已滿足則不無故重連；目前實作由輪詢發現恢復後狀態。
8. **Scenario 8 (螢幕瞬斷防抖)**：實體螢幕斷開 1 秒 -> 4 秒 Debounce 生效，螢幕恢復後取消計時。
9. **Scenario 9 (無線 Sidecar 尊重)**：未插 USB 但手動開啟無線 Sidecar -> 自動化不中斷連線、不強求 USB。
10. **Scenario 10 (零冗餘操作驗證 DO NOTHING)**：狀態已滿足時，連線與設定主螢幕呼叫次數嚴格為 0。

---

## 🗑️ 安全解除安裝

PadPilot 預設卸載時**保留**您的設定檔、日誌、BetterDisplay、SwiftBar 與虛擬螢幕：

```bash
./scripts/uninstall.sh
```

若欲徹底刪除所有設定檔與日誌：
```bash
./scripts/uninstall.sh --purge
```


## 2026-09-09 無頭開機修正

`Generic Display`／`Generic` 精確名稱按此 Mac 已觀察到的佔位螢幕處理，不算實體螢幕；沒有採用「所有 vendor=0 都排除」的廣泛規則。若真實螢幕也使用這兩個名稱，需先確認其 EDID 再調整辨識。

- `Disconnect iPad` 會建立本次硬體拓撲的斷線覆寫，避免 Automatic／Prefer iPad 立即連回。切換模式、Reset、重新連線或拓撲改變後可恢復。
- Automatic、Prefer iPad 與手動主／副螢幕覆寫共用連線冷卻；無頭連線前會接上已配置的虛擬備援，iPad 成為主螢幕後仍保留備援連線，避免移除顯示器造成拓撲變動。
- 手動命令與自動切換依序執行。命令逾時表示結果尚未確認，不能當成背景程式已停止，也不會刪除通訊 socket。

檢查結果、限制與實機驗收步驟見 [修復與邏輯檢查紀錄](docs/2026-09-09-boot-review.md)。

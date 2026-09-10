# 🏛️ PadPilot 系統架構與設計原理 (System Architecture)

PadPilot 是一套專為無頭 Mac mini + iPad 打造的確定性顯示器狀態管理引擎（Deterministic Display State Manager）。

---

## 🧭 核心設計原則

1. **實體螢幕優先 (Physical Display First)**：只要連接 HDMI / DP / USB-C 實體螢幕，系統即刻將主畫面交還給實體螢幕，自動化保持靜默，不擅自干預。
2. **手動操作絕對優先 (Manual Override Absolute Priority)**：使用者的主觀操作（例如指定「將 iPad 作為副螢幕」）至高無上，自動化絕不隨意推翻。
3. **狀態全透明 (Observability)**：背景決策與當前硬體現況原子化寫入快照，原生選單與 GUI 只讀取快照，杜絕重度硬體輪詢。
4. **極限容錯與自癒 (Fault Tolerance & Self-Healing)**：任何硬體連線失敗均有防抖（Debounce）、重試限制（Retry Limit）與冷卻退避（Cooldown），避免連線風暴或 WindowServer 當機。

---

## 🏛️ 整體架構圖

```text
Swift / AppKit PadPilot.app
  ├─ menu-json → core/menu.py → config.json + atomic status.json + daemon liveness
  └─ CLI argument arrays → padpilot-cli → Unix socket → padpilotd
                                                       ├─ Detector / IOKit / CoreGraphics
                                                       └─ StateEngine → BetterDisplay CLI
Tk settings GUI ─────────────→ shared CLI/config transactions
```

選單每秒檢查快照檔案是否改變；有變動或距上次讀取達 5 秒才呼叫 `menu-json`，不在選單讀取路徑掃描硬體。CLI 子程序不阻塞 AppKit 主執行緒；選單展開時不重建，關閉後呈現最新內容。動作採參數陣列與白名單，不把裝置名稱組成 shell 指令。登入由既有 LaunchAgent 啟動 Python 服務，再開啟原生 App；鎖檔避免多個選單實例。停止服務保留選單，只有「結束」才停服務並關閉選單。

---

## 🧩 核心技術機制

### 1. 拓撲世代碼 (Topology Generation Tracking)
- **問題**：使用者手動從 Menu Bar 選擇「Use iPad as Secondary」後，如果背景輪詢發現「現在沒有實體螢幕」，會不會下一秒又把 iPad 強制切成 Main？
- **解法**：PadPilot 將每次手動覆寫綁定到當前的硬體世代（Generation）。只要實體螢幕 ID 清單與 USB iPad 連線狀態沒有發生實質改變，世代碼保持不變，覆寫永遠生效。只有當使用者拔掉線材、插上新螢幕或硬體拓撲改變時，世代碼推進，手動覆寫自動優雅失效並重新評估。

### 2. 單飛行狀態轉換鎖 (Single-Flight Transition Lock)
- **問題**：插上 USB 傳輸線時，USB 偵測、螢幕喚醒事件與定時 30 秒輪詢可能在同一瞬間併發觸發。
- **解法**：狀態機擁有專屬轉換鎖，同一時間只允許一個狀態轉換處於「In Flight」狀態，其餘重複事件被合流（Coalescing）或忽略，徹底杜絕 Sidecar 握手競爭。

### 3. 螢幕瞬斷防抖與冷卻保護 (Debounce & Cooldown)
- **4 秒瞬斷防抖 (Debounce)**：許多外接螢幕切換訊號源或休眠喚醒時會短暫掉訊 1~2 秒。PadPilot 在偵測到實體螢幕消失時，會啟動 4 秒防抖計時器；若螢幕在倒數結束前恢復，立即取消轉移動作，避免 iPad 被不必要地喚起。
- **重試上限與 30 秒冷卻 (Cooldown)**：Sidecar 連線發起後若連續 3 次失敗，系統立刻進入 30 秒 Cooldown，並在 Menu Bar 發出警告圖示，防止連續高頻發起連線導致 macOS WindowServer 崩潰。

### 4. 虛擬螢幕備援 (Headless Virtual Display Fallback)
- 當無實體螢幕且指定的 iPad 無法連線時，系統自動啟動 BetterDisplay 虛擬顯示器（預設 `PadPilotVirtual`），提供穩定的 Framebuffer 讓 macOS 正常運算圖形，並供 Screen Sharing / VNC / SSH 進行應急救援。

### 5. 原子狀態快照 (Atomic Snapshot Architecture)
- 背景守護行程將觀測到的實際狀態、預期狀態與決策原因寫入暫存檔，並透過 `os.replace` 原子替換至 `~/Library/Application Support/PadPilot/runtime/status.json`。
- `core/menu.py` 與 GUI 讀取快照；設定版本不一致或資料過期時停用相應控制並保留未知狀態。選單主動「重新整理」才會透過 CLI 要求背景服務更新硬體狀態。

## USB 事件與暫時目標

`core/usb_events.py` 使用 ctypes 註冊 IOKit `IOUSBHostDevice` 的 first-match／terminated 通知；回呼耗盡並釋放 iterator 內物件後只設定喚醒事件。背景服務以同一個等待迴圈處理事件、暖機探索與 Watchdog，仍呼叫既有 `StateEngine.evaluate`，不在原生回呼執行 BetterDisplay 命令。停止時移除 RunLoop source、釋放 iterator 與 notification port；註冊失敗保留 Watchdog 並輸出診斷。

`usb_event_wakeup` 預設 true，`auto_detect_ipad` 預設 true，均經既有設定交易儲存與即時套用。兩個開關位於預設收合的「進階選項」，點擊後展開；已儲存的停用值仍會保留。設定交易與狀態轉換共用評估鎖，避免切換途中換掉目標設定。

啟用自動偵測時，偵測器優先沿用具有 Sidecar UUID 的指定配對，不要求 USB 在場，也不因候選暫時消失而更換身份；未指定有效配對時才以 USB 唯一候選推定。選取結果放入 `ActualState.resolved_ipad`；連線、中斷、重新連線與主螢幕切換共用該目標。USB 序號與 Sidecar UUID 納入拓撲簽章，換裝置後既有覆寫失效。推定不寫入 Config 或配對清單；不完整查詢及歧義不允許發起 iPad 連線。已存 USB／Sidecar 對應優先；無對應時以唯一候選推定，無法證明兩種識別屬於同一裝置。GUI／選單列呈現本次目標，指定配對卡片可直接控制，送出前重新確認設定目標；其他配對需先設為控制目標。

原生通知 API 核對來源：[Apple IOServiceAddMatchingNotification](https://developer.apple.com/documentation/iokit/1514362-ioserviceaddmatchingnotification) 與本機 macOS SDK `IOKitLib.h`。即時的是通知與喚醒，Sidecar 完成連線仍受探索、既有操作、重試與防抖影響。

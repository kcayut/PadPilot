# 🏛️ PadPilot 系統架構與設計原理 (System Architecture)

**繁體中文** | [English](ARCHITECTURE.en.md) | [日本語](ARCHITECTURE.ja.md) · [文件索引](README.md)

PadPilot 是一套專為無頭 Mac mini + iPad 打造的確定性顯示器狀態管理引擎（Deterministic Display State Manager）。

---

## 🧭 核心設計原則

1. **實體螢幕優先 (Physical Display First)**：自動模式且沒有有效手動覆寫時，優先使用實體螢幕，不主動建立 Sidecar。其他模式依各自策略評估，不保證立即完成切換。
2. **手動操作優先 (Manual Override Priority)**：例如「將 iPad 作為副螢幕」會在目前硬體拓撲內優先；切換模式、重設或拓撲改變後重新評估。
3. **狀態全透明 (Observability)**：背景決策與當前硬體現況原子化寫入快照，原生選單與 GUI 只讀取快照，杜絕重度硬體輪詢。
4. **失敗復原 (Failure Recovery)**：防抖、重試限制與冷卻降低反覆連線的風險；不保證第三方服務永不失敗。

---

## 🏛️ 整體架構圖

```text
Swift / AppKit + SwiftUI PadPilot.app
  ├─ SwiftUI settings → shared CLI/config transactions
  ├─ menu-json → core/menu.py → config.json + atomic status.json + daemon liveness
  └─ CLI argument arrays → padpilot-cli → Unix socket → padpilotd
                                                       ├─ Detector / IOKit / CoreGraphics
                                                       └─ StateEngine → BetterDisplay CLI
```

選單每秒檢查快照檔案是否改變；有變動或距上次讀取達 5 秒才呼叫 `menu-json`，不在選單讀取路徑掃描硬體。CLI 子程序不阻塞 AppKit 主執行緒；選單展開時不重建，關閉後呈現最新內容。動作採參數陣列與白名單，不把裝置名稱組成 shell 指令。登入由 `SMAppService.agent` 管理 App 內的 LaunchAgent，透過相對路徑啟動原生入口，並以子程序執行選定的 Python；不建立外部啟動 plist。Python 正常結束不重啟，異常退出由 launchd 重啟。原生服務持續監看 App 搬移事件，拖入垃圾桶時解除登入註冊並結束。之後開啟原生 App；鎖檔避免多個選單實例。停止顯示自動化會保留選單，「結束」會另外關閉選單；已啟用的登入服務仍保留移除監看。

---

## 🧩 核心技術機制

### 1. 拓撲世代碼 (Topology Generation Tracking)
- **問題**：使用者手動從 Menu Bar 選擇「Use iPad as Secondary」後，如果背景輪詢發現「現在沒有實體螢幕」，會不會下一秒又把 iPad 強制切成 Main？
- **解法**：PadPilot 將手動覆寫綁定到硬體世代（Generation），一般評估不任意推翻。拓撲改變、模式切換或重設會使覆寫失效；有實體螢幕時，iPad 連線消失也可能清除其主／副螢幕覆寫。
- **單次要求**：全域快速鍵，以及僅手動模式中的主／副螢幕連線要求，只維持一輪；結束後移除要求，保留已完成的連線。僅手動模式不會因後續斷線或裝置重新出現而自行重連。

### 2. 單飛行狀態轉換鎖 (Single-Flight Transition Lock)
- **問題**：插上 USB 傳輸線時，USB 偵測、螢幕喚醒事件與定時 30 秒輪詢可能在同一瞬間併發觸發。
- **解法**：狀態機以共用鎖序列化評估與設定交易；重複喚醒合併處理，避免 PadPilot 自身同時發起狀態轉換。其他應用程式仍可能同時控制顯示器。

### 3. 螢幕瞬斷防抖與冷卻保護 (Debounce & Cooldown)
- **4 秒瞬斷防抖 (Debounce)**：許多外接螢幕切換訊號源或休眠喚醒時會短暫掉訊 1~2 秒。PadPilot 在偵測到實體螢幕消失時，會啟動 4 秒防抖計時器；若螢幕在倒數結束前恢復，立即取消轉移動作，避免 iPad 被不必要地喚起。
- **重試上限與 30 秒冷卻 (Cooldown)**：Sidecar 連線最多嘗試 3 次，間隔 3 秒；耗盡後通知一次並保留備援。30 秒冷卻結束也不會自動重開重試；需觀察到目標 iPad 的 USB／Sidecar 可用狀態由無變有，或由使用者手動重連／重設。查詢錯誤、一般 USB 喚醒與實體螢幕插拔不會解除暫停。

### 4. 虛擬螢幕備援 (Headless Virtual Display Fallback)
- 無實體螢幕時，使用已配置的 BetterDisplay 虛擬顯示器（預設 `PadPilotVirtual`）維持桌面備援；iPad 接管後也保留。Screen Sharing／VNC 或 SSH 必須事先自行設定，PadPilot 不啟用遠端存取；SSH 本身不依賴虛擬顯示器。

### 5. 原子狀態快照 (Atomic Snapshot Architecture)
- 背景守護行程將觀測到的實際狀態、預期狀態與決策原因寫入暫存檔，並透過 `os.replace` 原子替換至 `~/Library/Application Support/PadPilot/runtime/status.json`。
- `core/menu.py` 與 GUI 讀取快照；設定版本不一致或資料過期時停用相應控制並保留未知狀態。選單主動「重新整理」才會透過 CLI 要求背景服務更新硬體狀態。

## USB 事件與暫時目標

`core/usb_events.py` 使用 ctypes 註冊 IOKit `IOUSBHostDevice` 的 first-match／terminated 通知；回呼耗盡並釋放 iterator 內物件後只設定喚醒事件。背景服務以同一個等待迴圈處理事件、暖機探索與 Watchdog，仍呼叫既有 `StateEngine.evaluate`，不在原生回呼執行 BetterDisplay 命令。停止時移除 RunLoop source、釋放 iterator 與 notification port；註冊失敗保留 Watchdog 並輸出診斷。

`usb_event_wakeup` 預設 true，`auto_detect_ipad` 預設 true，均經既有設定交易儲存與即時套用。兩個開關位於預設收合的「進階選項」，點擊後展開；已儲存的停用值仍會保留。設定交易與狀態轉換共用評估鎖，避免切換途中換掉目標設定。

啟用自動偵測時，偵測器優先沿用具有 Sidecar UUID 的指定配對，不要求 USB 在場，也不因候選暫時消失而更換身份；未指定有效配對時才以 USB 唯一候選推定。選取結果放入 `ActualState.resolved_ipad`；連線、中斷、重新連線與主螢幕切換共用該目標。USB 序號與 Sidecar UUID 納入拓撲簽章，換裝置後既有覆寫失效。推定不寫入 Config 或配對清單；不完整查詢及歧義不允許發起 iPad 連線。已存 USB／Sidecar 對應優先；無對應時以唯一候選推定，無法證明兩種識別屬於同一裝置。GUI／選單列呈現本次目標，指定配對卡片可直接控制，送出前重新確認設定目標；其他配對需先設為控制目標。

原生通知 API 核對來源：[Apple IOServiceAddMatchingNotification](https://developer.apple.com/documentation/iokit/1514362-ioserviceaddmatchingnotification) 與本機 macOS SDK `IOKitLib.h`。即時的是通知與喚醒，Sidecar 完成連線仍受探索、既有操作、重試與防抖影響。

## 設定一致性與未知狀態

主設定／狀態檔與 `/tmp/PadPilot` 備援共用最後寫入時間的選擇規則，讀取前驗證路徑所有者與檔案型態。設定解析失敗會拒絕啟動，不自動套用預設值；GUI 停用儲存並保留原檔。GUI 設定交易送出 `expected_revision`，名稱草稿保留開始編輯時的版本，衝突時需重新檢視後再儲存。

偵測器只在執行期間保留已確認的 Sidecar session UUID／display UUID 對應；探索清單消失時仍使用該對應，目標改變或連線確認關閉時清除。`ActualState.sidecar_display_id` 供主螢幕選擇與滿足條件共用。已連線但無法確認顯示身分時標示未知並保留目前畫面；同輪 identifiers 查詢後來成功也不會抹除先前失敗。

## 全域連線快速鍵

在「設定與配對 → 運作與偏好 → 全域快速鍵」點選按鍵欄，直接按下組合，再按「儲存快速鍵」啟用；至少包含 Control 或 Command。支援字母、數字、常用符號、方向／導覽鍵及 F1–F20；Esc 或切換視窗可取消錄製。錄製期間暫停原有全域快速鍵，取消後恢復。初次不會自動佔用組合，可自行設定或停用。使用直接連到 Mac 的鍵盤，Mac 須已登入並解鎖，鎖定畫面時無法使用全域快速鍵。PadPilot 選單列程式與背景服務須持續執行；不必開著設定視窗或接實體螢幕。

- 手動模式平時只接受快速鍵或選單的明確操作；可另行勾選「開機無螢幕時自動連線 iPad」。每次開機後首次啟動服務，最多偵測 3 輪，每輪 30 秒（合計最多 90 秒），沿用約 2 秒的掃描間隔；三輪都找不到目標便停止開機連線流程。無實體螢幕且有可識別的 iPad 目標時發起一輪要求。已有實體螢幕、使用者已操作、設定停用或逾時即取消；同次開機重新啟動 App／服務不會重試。須啟用登入自動啟動才能隨登入執行，登入前不會連線。
- 新安裝預設手動模式，並勾選開機連線；更新保留原本模式。設定與選單列均先列手動，再列自動。
- 自動模式保留原有自動連線；快速鍵額外發起一輪有上限的連線要求。
- 手動模式的一輪要求完成、失敗或取消後即結束；後續斷線、USB 插拔或 iPad 重新出現不會自行連線。
- 每輪沿用最多 3 次與現有間隔；長按與進行中的重複要求不會增加重試次數。完成後重新按下可再發起一輪。
- 沒有實體螢幕時使用 iPad 主螢幕，有實體螢幕時使用副螢幕；偏好 iPad 模式仍以 iPad 為主。已連線且畫面上線時不重新斷接或改變角色。
- 快速鍵設定走既有設定版本檢查與 CLI／IPC；修改快速鍵不觸發裝置掃描或連線。註冊衝突會提示改選，不用失敗對話框。底層 Sidecar 自行產生的失敗警告仍不保證消失。

只用 macOS 原生快捷鍵註冊，不需安裝套件或開啟鍵盤監聽的輔助使用權限。儲存的按鍵以鍵盤實體位置辨識，切換輸入法不改變組合。

目前無法事先確認 iPad 是否能成功連線 Sidecar；設定的自動模式下方另行提示：裝置無法連線時，自動嘗試可能頻繁觸發 macOS 警告視窗。可用裝置清單與 USB 偵測都不是連線成功保證。
